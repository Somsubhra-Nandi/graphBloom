"""The learning loop. One policy per run, always starting from the same iteration-0 graph snapshot.

  .venv/bin/python scripts/learn.py --policy learned --until 1      # iteration 0 and 1 (dry run)
  .venv/bin/python scripts/learn.py --policy learned --until 5      # resumes where it stopped
  .venv/bin/python scripts/learn.py --policy random  --until 5      # needs the learned run's per-iteration counts

What is learned is the active schema: the relations the planner may use and the system extracts.
  iteration 0   the 8 seed relations; feedback is answered and diagnosed, held-out is scored
  iteration k   grow the schema, (learned only) repair-extract the feedback gaps, score held-out with query-time
                extraction, then diagnose feedback (re-answered only at iterations 0, 2 and 5)
Learned adds the top relations by blame_count (summed over question types, at most 2 per iteration, blame >= 2).
Random adds the same number of relations the learned policy added that iteration, drawn uniformly from the candidate
pool (relations in the gold evidence of the feedback questions, minus the active schema; seed 42). Random runs on
held-out only. Everything else (query-time extraction budget, CHAIN_BOOST, k, prompts) is identical.
"""
import argparse
import json
import random
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import config, extract as X, llm, snapshot  # noqa: E402
from src.extract import QueryTimeExtractor  # noqa: E402
from src.classifier import Diagnoser, load_feedback, summarize as summarize_diag  # noqa: E402
from src.evaluation import run_questions, summarize  # noqa: E402
from src.graph import Graph, normalize  # noqa: E402
from src.literals import normalize_literal  # noqa: E402
from src.mutations import export as export_mutations  # noqa: E402
from src.query import QueryEngine  # noqa: E402
from src.schema import ActiveSchema  # noqa: E402


def load_heldout():
    return [json.loads(l) for l in open(config.SPLIT_DIR / "heldout.jsonl")]  # question, answer, type only: no evidence


# ---------------------------------------------------------------- candidate pool and blame
def candidate_pool(feedback):
    """Relations in the gold evidence of the feedback questions, minus the seed schema. Feedback only."""
    seeds = {normalize(r) for r in config.SEED_RELATIONS}
    count, literal = Counter(), Counter()
    for q in feedback:
        for _, rel, o in q["evidences"]:
            if normalize(rel) in seeds:
                continue
            count[rel] += 1
            literal[rel] += bool(normalize_literal(o)["norm"])
    return {rel: {"count": n, "literal": literal[rel] * 2 > n} for rel, n in count.most_common()}


def load_reltypes(g):
    rows = g.read("MATCH (n:RelType) RETURN n.id AS id, n.qtype AS qtype, n.name AS name, n.weight AS weight, n.blame_count AS blame")
    return {(r["qtype"], r["name"]): r for r in rows}


def apply_blame(g, rt, diag_rows):
    """blame_count on RelType(question type, relation) = the number of current extraction gaps for that pair,
    recomputed from this iteration's diagnosis (not accumulated). New pairs are created. Returns pairs changed."""
    counts = Counter((r["type"], rel) for r in diag_rows for rel in r["missing_relations"])
    for key in counts:
        if key not in rt:
            i = g.index.new_id()
            g.index.d["reltypes"][f"{key[0]}|{key[1]}"] = i
            rt[key] = {"id": i, "qtype": key[0], "name": key[1], "weight": 1.0, "blame": -1}  # -1 forces the first write
    dirty = []
    for key, v in rt.items():
        new = counts.get(key, 0)
        if v["blame"] != new:
            v["blame"] = new
            dirty.append(key)
    g.index.save()
    g.write_reltypes([{"id": rt[k]["id"], "name": k[1], "qtype": k[0], "weight": rt[k]["weight"], "blame_count": rt[k]["blame"]} for k in sorted(dirty)])
    return len(dirty)


def choose_learned(rt, schema, pool):
    totals = Counter()
    for (_, name), v in rt.items():
        totals[name] += v["blame"]
    cands = [(n, b) for n, b in totals.items() if b >= config.LEARN_MIN_BLAME and schema.canonical(n) is None and n in pool]
    cands.sort(key=lambda x: (-x[1], x[0]))
    return [{"relation": n, "reason": f"blame_count {b} (summed over question types)"} for n, b in cands[: config.LEARN_MAX_NEW_RELATIONS]]


def choose_random(k, schema, pool, it, seed):
    avail = sorted(r for r in pool if schema.canonical(r) is None)
    rng = random.Random(f"{seed}-{it}")  # one draw per iteration, seeded
    return [{"relation": r, "reason": f"uniform random draw of {k} from a pool of {len(avail)}"} for r in rng.sample(avail, min(k, len(avail)))]


# ---------------------------------------------------------------- repairs
def grow(g, schema, added, it, pool):
    muts = []
    for a in added:
        rel = a["relation"]
        prop = schema.add(rel, pool[rel]["literal"], it)
        if prop:
            g.add_literal_prop(prop)
        g.ensure_reltypes(rel)
        muts.append({"id": g.index.new_id(), "iter": it, "kind": "schema_growth", "question_id": "", "reason": f"added '{rel}' ({'date' if prop else 'entity'}-valued): {a['reason']}"})
    schema.history.append({"iteration": it, "relations": [a["relation"] for a in added]})
    g.index.save()
    g.write_mutations(muts)


def repair_extraction(g, schema, diag_rows, it):
    """Feedback repairs: for each gap whose relation is now in the active schema, extract that relation from the
    gold subject's own chunks (skipping chunks that already have an EXTRACTED edge for it). Batched."""
    d = Diagnoser(g, schema)
    pairs = {}
    for row in diag_rows:
        for m in row["missing"]:
            rel = schema.canonical(m["relation"])
            sid = d.resolve(m["triple"][0]) if rel else None
            if sid is None:
                continue
            for ch in X.chunks_of_entity(g, sid):
                if (ch["id"], rel) not in pairs and not X.is_extracted(g, ch["id"], rel):
                    pairs[(ch["id"], rel)] = (ch, row["id"])
    items = list(pairs.values())
    keys = list(pairs)
    reqs = [X.request(ch, [rel], schema, f"r{j}") for j, ((_, rel), (ch, _)) in enumerate(zip(keys, items))]
    before = llm.total_spent()
    status = None
    pend = {b: v for b, v in llm.pending_batches().items() if v["phase"] == "learning"}
    if pend:
        bid = next(iter(pend))
        print(f"  resuming pending batch {bid}", flush=True)
    else:
        bid, _ = llm.submit_batch(reqs, "learning") if reqs else (None, 0)
    if bid:
        _, status = llm.collect_batch(bid, reqs, "learning")
    edges = lits = calls = 0
    for (cid, rel), (ch, qid) in zip(keys, items):
        res = X.extract_and_apply(g, ch, rel, schema, it, qid, "repair_extraction", "learning")
        if res is not None:
            calls += 1
            edges, lits = edges + res[0], lits + res[1]
    return {"chunks_extracted": calls, "edges_added": edges, "date_values_added": lits, "requests": len(reqs), "batch": status, "cost_usd": round(llm.total_spent() - before, 5)}


# ---------------------------------------------------------------- evaluation
def eval_heldout(g, schema, it, run_dir, workers):
    eng = QueryEngine(g, phase="learning", schema=schema)
    extractor = QueryTimeExtractor(g, schema, it)
    before = llm.total_spent()
    rows, err = run_questions(load_heldout(), lambda q: eng.answer(q["question"], extractor, q["_id"]), run_dir / f"iter{it}" / "heldout.jsonl", workers)
    s = summarize(rows)
    s["query_extraction_calls"] = sum(len(r["trace"].get("query_extraction", [])) for r in rows)
    s["queries_with_events"] = sum(1 for r in rows if r["trace"].get("events"))
    s["cost_usd"] = round(llm.total_spent() - before, 5)
    s["questions"] = f"{len(rows)}/87"
    return s, err


def eval_feedback(g, schema, it, run_dir, workers):
    fb = load_feedback()
    eng = QueryEngine(g, phase="learning", schema=schema)
    answered = it in config.FEEDBACK_ANSWER_ITERATIONS
    before = llm.total_spent()
    em, err, fsum = {}, None, None
    if answered:
        rows, err = run_questions(fb, lambda q: eng.answer(q["question"]), run_dir / f"iter{it}" / "feedback.jsonl", workers)
        traces = {r["id"]: r["trace"] for r in rows}
        em = {r["id"]: r["em"] for r in rows}
        fsum = summarize(rows)
    else:
        with ThreadPoolExecutor(workers) as ex:
            traces = dict(zip([q["_id"] for q in fb], ex.map(lambda q: eng.trace_from_state(eng.retrieve(q["question"])), fb)))
    d = Diagnoser(g, schema)
    diag = [d.diagnose(q, traces.get(q["_id"]), answered, em.get(q["_id"])) for q in fb if q["_id"] in traces]
    path = run_dir / f"iter{it}" / "diagnosis.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in diag))
    return diag, fsum, round(llm.total_spent() - before, 5), err


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--policy", required=True, choices=["learned", "random"])
    ap.add_argument("--until", type=int, default=config.LEARN_ITERATIONS, help="last iteration to run")
    ap.add_argument("--fresh", action="store_true", help="restore the iteration-0 snapshot and start over")
    ap.add_argument("--seed", type=int, default=config.LEARN_SEED, help="random policy seed")
    ap.add_argument("--run-name", help="results directory name (default: the policy name)")
    ap.add_argument("--workers", type=int, default=config.LLM_WORKERS)
    ap.add_argument("--use-reserve", action="store_true")
    args = ap.parse_args()
    llm.set_use_reserve(args.use_reserve)
    run = args.run_name or args.policy
    run_dir = config.ROOT / "results" / run
    state_path = run_dir / "state.json"
    sch_path = config.RUNS_DIR / run / "schema.json"
    live_path = config.STATE_DIR / "live_graph.json"

    feedback = load_feedback()
    pool = candidate_pool(feedback)

    if args.fresh or not state_path.exists():
        if not snapshot.SNAP.exists():
            g0 = Graph()
            assert g0.read("MATCH (n:Mutation) RETURN count(*) AS n")[0]["n"] == 0, "live graph already has mutations; refusing to snapshot it as iteration 0"
            g0.close()
            print("snapshot of the iteration-0 graph:", snapshot.make_snapshot())
        else:
            print("restored iteration-0 snapshot:", snapshot.restore_snapshot())
        run_dir.mkdir(parents=True, exist_ok=True)
        for f in run_dir.glob("iter*"):
            import shutil
            shutil.rmtree(f)
        if sch_path.exists():
            sch_path.unlink()
        state = {"policy": args.policy, "seed": args.seed, "next_iteration": 0, "growth_applied": -1, "added": {}, "iterations": {}, "pool": pool}
        snapshot.set_live(run=run, base_snapshot="iter0", snapshot="iter0", iteration=-1)
    else:
        state = json.loads(state_path.read_text())
        live = json.loads(live_path.read_text()).get("run") if live_path.exists() else None
        if live != run:
            sys.exit(f"the live graph belongs to run '{live}', not '{run}'. Use --fresh to restore the snapshot and start '{run}' over.")

    schema = ActiveSchema.load(sch_path)
    g = Graph(schema=schema)
    rt = load_reltypes(g)
    learned_counts = None
    if args.policy == "random":
        lp = config.ROOT / "results" / "learned" / "state.json"
        if not lp.exists():
            sys.exit("run the learned policy first: random needs its per-iteration counts")
        learned_counts = {int(k): len(v) for k, v in json.loads(lp.read_text())["added"].items()}

    for it in range(state["next_iteration"], args.until + 1):
        t0, spent0 = time.time(), llm.total_spent()
        info = {"iteration": it}
        print(f"\n=== {run} iteration {it} ===", flush=True)
        if it >= 1 and state["growth_applied"] < it:
            if args.policy == "learned":
                added = choose_learned(rt, schema, pool)
            else:
                if it not in learned_counts:
                    print(f"learned has not reached iteration {it} yet; stopping")
                    break
                added = choose_random(learned_counts[it], schema, pool, it, args.seed)
            grow(g, schema, added, it, pool)
            schema.save(sch_path)
            state["added"][str(it)] = [a["relation"] for a in added]
            state["growth_applied"] = it
            state_path.parent.mkdir(parents=True, exist_ok=True)
            state_path.write_text(json.dumps(state, indent=1))
            print("  schema grew by:", [(a["relation"], a["reason"]) for a in added])
            if args.policy == "learned":
                prev = [json.loads(l) for l in open(run_dir / f"iter{it - 1}" / "diagnosis.jsonl")]
                info["repair_extraction"] = repair_extraction(g, schema, prev, it)
                print("  repair extraction:", info["repair_extraction"])
        info["active_schema"] = schema.names()
        info["added"] = state["added"].get(str(it), [])

        hs, err = eval_heldout(g, schema, it, run_dir, args.workers)
        info["heldout"] = hs
        o = hs["overall"]
        print(f"  held-out: {hs['questions']} EM {o.get('em')} {o.get('em_ci95')} F1 {o.get('f1')}  query-time extraction calls {hs['query_extraction_calls']}  cost ${hs['cost_usd']}")
        if err:
            print("STOPPED:", err)
            break
        if args.policy == "learned":
            diag, fsum, fcost, err = eval_feedback(g, schema, it, run_dir, args.workers)
            info["feedback"] = {"summary": fsum, "diagnosis": summarize_diag(diag), "cost_usd": fcost, "answered": it in config.FEEDBACK_ANSWER_ITERATIONS}
            if err:
                print("STOPPED:", err)
                break
            rt = load_reltypes(g)
            info["blame_pairs_updated"] = apply_blame(g, rt, diag)
            print(f"  feedback ({'answered' if info['feedback']['answered'] else 'graph-only'}): diagnosis {info['feedback']['diagnosis']['overall']}  cost ${fcost}")
        info["cost_usd"] = round(llm.total_spent() - spent0, 5)
        info["seconds"] = round(time.time() - t0)
        (run_dir / f"iter{it}" / "summary.json").write_text(json.dumps(info, indent=1))
        state["iterations"][str(it)] = {"heldout_em": o.get("em"), "heldout_f1": o.get("f1"), "cost_usd": info["cost_usd"]}
        state["next_iteration"] = it + 1
        state_path.write_text(json.dumps(state, indent=1))
        export_mutations(g, run_dir / "mutations.jsonl")
        snapshot.set_live(run=run, iteration=it, snapshot=None)  # the live graph has moved on from any restored snapshot  # a snapshot restore wipes the graph's Mutation nodes
        print(f"  iteration cost ${info['cost_usd']}")
    llm.log_stats(f"learn:{run}")
    g.close()


if __name__ == "__main__":
    main()
