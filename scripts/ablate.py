"""Ablations of the learning loop, on held-out only (feedback is not re-run).

  A1  growth only: replay the learned run's schema sequence (from results/learned/state.json) with query-time
      extraction OFF. The graph stays the iteration-0 graph, so only the planner's vocabulary changes.
  A2  query-time extraction only: the static 8-relation schema with query-time extraction ON.
Held-out at iterations 1, 3 and 5. Run on the iteration-0 snapshot; results go to results/ablations/<A>/iter<k>/.

  .venv/bin/python scripts/ablate.py --ablation A1 --estimate     # cost estimate from the cache, no calls
  .venv/bin/python scripts/ablate.py --ablation A1
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from src import config, llm  # noqa: E402
from src.classifier import load_feedback  # noqa: E402
from src.evaluation import run_questions, summarize  # noqa: E402
from src.extract import QueryTimeExtractor  # noqa: E402
from src.graph import Graph  # noqa: E402
from src.query import QueryEngine  # noqa: E402
from src.schema import ActiveSchema  # noqa: E402
import learn  # noqa: E402

ITERATIONS = (1, 3, 5)


def schema_at(k, added, pool):
    s = ActiveSchema()
    for it in range(1, k + 1):
        for rel in added.get(str(it), []):
            s.add(rel, pool[rel]["literal"], it)
    return s


def install_estimator(counter):
    """Replace llm.call with a cache-only version that counts misses and returns harmless stubs."""
    real = llm.call

    def fake(model, prompt, system="", schema=None, max_tokens=1024, temperature=0.0, *, phase):
        hit, res = llm.cache_lookup(model, prompt, system, schema, max_tokens, temperature)
        if hit:
            counter["hits"] += 1
            return res
        kind = "planner" if schema and "seeds" in schema["properties"] else "answer" if schema and "reasoning" in schema["properties"] else "extraction"
        counter[kind] += 1
        counter["usd"] += llm.estimate_cost(model, system, prompt, schema, max_tokens, phase)
        if kind == "planner":
            return {"seeds": [], "question_type": "comparison", "relation_chain": []}
        return {"reasoning": "", "answer": ""} if kind == "answer" else {"triples": []}

    llm.call = fake
    return real


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ablation", required=True, choices=["A1", "A2"])
    ap.add_argument("--estimate", action="store_true")
    ap.add_argument("--workers", type=int, default=config.LLM_WORKERS)
    args = ap.parse_args()
    added = json.loads((config.ROOT / "results" / "learned" / "state.json").read_text())["added"]
    pool = learn.candidate_pool(load_feedback())
    out_root = config.ROOT / "results" / "ablations" / args.ablation
    counter = {"hits": 0, "planner": 0, "answer": 0, "extraction": 0, "usd": 0.0}
    if args.estimate:
        install_estimator(counter)
        out_root = Path("/tmp/_ablate_estimate") / args.ablation
    summ = {}
    for k in ITERATIONS:
        schema = schema_at(k, added, pool) if args.ablation == "A1" else ActiveSchema()
        g = Graph(schema=schema)
        eng = QueryEngine(g, phase="learning", schema=schema)
        extractor = QueryTimeExtractor(g, schema, k) if args.ablation == "A2" else None
        before = llm.total_spent()
        rows, err = run_questions(learn.load_heldout(), lambda q: eng.answer(q["question"], extractor, q["_id"]), out_root / f"iter{k}" / "heldout.jsonl", args.workers)
        s = summarize(rows)
        s.update(questions=f"{len(rows)}/87", cost_usd=round(llm.total_spent() - before, 5), active_schema=schema.names(),
                 query_extraction_calls=sum(len(r["trace"].get("query_extraction", [])) for r in rows))
        summ[str(k)] = s
        o = s["overall"]
        print(f"{args.ablation} iteration {k}: schema +{len(schema.names()) - 8} relations  held-out EM {o['em']} {o['em_ci95']}  F1 {o['f1']}  extraction calls {s['query_extraction_calls']}  cost ${s['cost_usd']}")
        g.close()
        if err:
            print("STOPPED:", err)
            break
    if args.estimate:
        print(f"ESTIMATE {args.ablation}: cache hits {counter['hits']}, misses planner {counter['planner']} answer {counter['answer']} extraction {counter['extraction']}  ->  ${counter['usd']:.4f}")
        return
    (out_root / "summary.json").write_text(json.dumps({"ablation": args.ablation, "iterations": summ, "run_params": config.run_params()}, indent=1))
    llm.log_stats(f"ablate:{args.ablation}")


if __name__ == "__main__":
    main()
