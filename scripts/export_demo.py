"""Write the data files the demo site reads, into demo/public/data/.
Needs the HydraDB container running with the learned_iter5 snapshot restored (the script checks).
  .venv/bin/python scripts/export_demo.py
"""
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import config, snapshot  # noqa: E402
from src.graph import Graph  # noqa: E402
from src.mutations import from_graph  # noqa: E402

R = config.ROOT / "results"
OUT = config.ROOT / "demo" / "public" / "data"
OUT.mkdir(parents=True, exist_ok=True)


def dump(name, obj):
    (OUT / name).write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")))
    print(f"{name}: {(OUT / name).stat().st_size / 1024:.0f} KB")


def jl(path):
    return [json.loads(x) for x in open(path)]


# node type from the relations a node takes part in (the graph stores no type; ingest left it empty)
SRC_TYPE = {"director": "film", "country of origin": "film", "performer": "film", "composer": "film"}
DST_TYPE = {"director": "person", "performer": "person", "composer": "person", "father": "person", "mother": "person",
            "spouse": "person", "place of birth": "place", "place of death": "place", "country": "place",
            "country of origin": "place", "country of citizenship": "place", "award received": "award",
            "educated at": "school", "employer": "organisation"}
PERSON_SRC = {"place of birth", "place of death", "country of citizenship", "father", "mother", "spouse",
              "award received", "educated at", "employer"}


def node_type(rels_out, rels_in):
    if rels_out & set(SRC_TYPE):
        return "film"
    if rels_out & PERSON_SRC:
        return "person"
    for r in ("father", "mother", "spouse", "director", "performer", "composer"):
        if r in rels_in:
            return "person"
    for r in rels_in:
        if r in DST_TYPE:
            return DST_TYPE[r]
    return "other"


live = snapshot.get_live()
if live.get("snapshot") != "learned_iter5":
    sys.exit(f"live graph is {live}, expected learned_iter5; run snapshot.restore_snapshot('learned_iter5')")

g = Graph()
ents = g.read("MATCH (n:Entity) RETURN n.id AS id, n.name AS name")
edges = g.load_edges()
mut = from_graph(g)
g.close()

out_r, in_r, node_it = {}, {}, {}
for e in edges:
    out_r.setdefault(e["s"], set()).add(e["t"])
    in_r.setdefault(e["d"], set()).add(e["t"])
    for n in (e["s"], e["d"]):
        node_it[n] = min(node_it.get(n, 99), e["it"] or 0)
deg = Counter()
for e in edges:
    deg[e["s"]] += 1
    deg[e["d"]] += 1
nodes = [{"id": n["id"], "name": n["name"], "type": node_type(out_r.get(n["id"], set()), in_r.get(n["id"], set())),
          "created_iter": node_it.get(n["id"], 0), "degree": deg[n["id"]]} for n in ents]
by_id = {n["id"]: n for n in nodes}
elist = [{"source": e["s"], "target": e["d"], "type": e["t"], "created_iter": e["it"] or 0} for e in edges]
edge_it = {(e["source"], e["target"], e["type"]): e["created_iter"] for e in elist}
dump("graph.json", {"nodes": nodes, "links": elist,
                    "counts": {"entities": len(nodes), "edges": len(elist), "isolated": sum(1 for n in nodes if not n["degree"]),
                               "edges_by_iter": dict(sorted(Counter(e["created_iter"] for e in elist).items()))}})

# ---- curve ----
c = json.loads((R / "curve.json").read_text())
runs = {"learned": "Learned", "random": "Random (seed 42)", "random_s7": "Random (seed 7)"}
curve = {"metric": "exact match on 87 held-out questions", "n_questions": c["n_questions"], "iterations": [0, 1, 2, 3, 4, 5],
         "series": [{"key": k, "label": lab, "em": c["runs"][k]["em"], "ci95": c["runs"][k]["em_ci95"],
                     "cost_usd": c["runs"][k].get("cost_total_usd")} for k, lab in runs.items()],
         "baselines": [{"key": k, "label": v["label"], "em": v["em"], "ci95": v["em_ci95"]} for k, v in c["baselines"].items()]}
dump("curve.json", curve)

# ---- mutations ----
dump("mutations.json", [{"iteration": m["iteration"], "kind": m["kind"], "relation": m["relation"], "reason": m["reason"],
                         "question_id": m["question_id"]} for m in mut])


# ---- stories ----
def chain_path(trace):
    """The path that follows the planned relation chain furthest; returns (nodes, edge types)."""
    chain = trace["plan"]["relation_chain"]
    best = ([], [])
    for p in trace["paths"]:
        ts = [e["type"] for e in p["edges"]]
        k = 0
        while k < min(len(ts), len(chain)) and ts[k] == chain[k]:
            k += 1
        if k and (k, p["score"]) > (len(best[1]), 0) and k >= len(best[1]):
            best = (p["nodes"][: k + 1], ts[:k])
    return best


h0 = {r["id"]: r for r in jl(R / "learned/iter0/heldout.jsonl")}
h5 = {r["id"]: r for r in jl(R / "learned/iter5/heldout.jsonl")}
cands = []
for qid, a in h0.items():
    b = h5[qid]
    if not (a["em"] == 0 and a["f1"] < 0.4 and b["em"] == 1 and a["trace"]["dead_ends"]):  # iteration 0 clearly wrong
        continue
    nodes, types = chain_path(b["trace"])
    if len(types) < len(b["trace"]["plan"]["relation_chain"]) or any(n["id"] not in by_id for n in nodes):
        continue
    its = [edge_it.get((nodes[i]["id"], nodes[i + 1]["id"], t), 0) for i, t in enumerate(types)]
    if not any(its):
        continue
    cands.append((qid, nodes, types, its))
print(f"{len(cands)} fixed questions with a dead end and a new edge on the final path")
chosen, seen_rel, spare = [], set(), []
cands.sort(key=lambda c: (-len(c[2]), c[0]))
for qid, nodes, types, its in cands:
    fix = types[[i for i, x in enumerate(its) if x][0]]
    if "burial" in h0[qid]["question"]:  # the plan used place of death for a burial question; not a clean story
        continue
    if fix in seen_rel:
        spare.append((qid, nodes, types, its, fix))
        continue
    seen_rel.add(fix)
    chosen.append((qid, nodes, types, its, fix))
chosen = (chosen + spare)[:3]
stories = []
for qid, nodes, types, its, fix in chosen:
    a, b = h0[qid], h5[qid]
    de = a["trace"]["dead_ends"][0]
    n0, t0 = chain_path(a["trace"])
    # what iteration 0 managed: the chain path up to the dead end, then stops
    walked = [{"id": x["id"], "name": x["name"]} for x in n0[: de["hop"] + 1]] or [{"id": de["entity_id"], "name": de["entity"]}]
    stories.append({
        "id": qid, "type": a["type"], "question": a["question"], "gold": a["gold"],
        "plan": b["trace"]["plan"]["relation_chain"],
        "before": {"answer": a["prediction"], "walked": walked, "walked_edges": t0[: de["hop"]],
                   "dead_end": {"id": de["entity_id"], "name": de["entity"], "missing_relation": de["expected_relation"]}},
        "after": {"answer": b["prediction"], "nodes": [{"id": x["id"], "name": x["name"]} for x in nodes],
                  "edges": [{"type": t, "created_iter": it} for t, it in zip(types, its)]},
        "fixed_by": fix, "fixed_iter": min(i for i in its if i)})
dump("stories.json", stories)
for s in stories:
    print(s["question"], "|", s["gold"], "| fixed by", s["fixed_by"], "iter", s["fixed_iter"], "|", s["before"]["dead_end"])

# ---- metrics ----
projection = json.loads((R / "cost_projection.json").read_text())
lt = json.loads((R / "load_test_2min.json").read_text())
cc = json.loads((R / "cost_comparison.json").read_text())
rep = json.loads((R / "unit_costs.json").read_text()) if (R / "unit_costs.json").exists() else {}
per = cc["per_1000_future_queries"]
dump("metrics.json", {
    "load_test": {"concurrent_queries": lt["concurrent_queries"], "duration_s": lt["writer"]["seconds"],
                  "quiet": lt["baseline_no_writes"], "busy": lt["with_concurrent_repair_writes"], "writer": lt["writer"],
                  "windows": lt["per_30s_windows"][:4], "note": "The model is replaced by cached answers, so these times are the graph path only."},
    "cost": {"per_1000_queries": [{"key": k, "label": lab, "one_time_usd": per[k]["one_time_usd"],
                                   "recurring_usd": per[k]["recurring_usd_per_1000_queries"],
                                   "total_usd": per[k]["total_usd_for_1000_queries"], "parts": per[k]["recurring_parts_usd_per_1000"],
                                   "em": per[k]["final_held_out_em"]}
                                  for k, lab in [("learned", "Learned"), ("random", "Random (seed 42)"),
                                                 ("random_s7", "Random (seed 7)"), ("open_vocab", "Open vocabulary")]],
             "learning_total_usd": cc["total_cost_usd"]["learned"], "match_iteration": cc["iterations_to_match"]["random"]["first_learned_iteration_with_em_at_least_that"],
             "note": per["note"]},
    "projection": projection,
})
