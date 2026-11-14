"""Unit costs from the response cache, on the live learned_iter5 graph (no spend): planner and answer dollars per
held-out query at the final schema, and dollars per targeted extraction call. Writes results/unit_costs.json."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from src import config, extract as X, llm  # noqa: E402
from src.graph import Graph  # noqa: E402
from src.query import QueryEngine  # noqa: E402
from src.schema import ActiveSchema  # noqa: E402
import learn  # noqa: E402

acc = {"planner": [0.0, 0], "answer": [0.0, 0]}


def cache_only(model, prompt, system="", schema=None, max_tokens=1024, temperature=0.0, *, phase):
    hit, res = llm.cache_lookup(model, prompt, system, schema, max_tokens, temperature)
    if not hit:
        raise RuntimeError("cache miss")
    kind = "planner" if "seeds" in schema["properties"] else "answer"
    acc[kind][0] += llm.price(model, *llm.cached_usage(model, prompt, system, schema, max_tokens, temperature))
    acc[kind][1] += 1
    return res


llm.call = cache_only
schema = ActiveSchema.load(config.RUNS_DIR / "learned" / "schema.json")
g = Graph(schema=schema)
eng = QueryEngine(g, phase="learning", schema=schema)
qs = learn.load_heldout()
for q in qs:
    eng.answer(q["question"])
# extraction calls made by the learned run at query time
costs, n = 0.0, 0
for k in range(1, 6):
    for l in open(config.ROOT / "results" / "learned" / f"iter{k}" / "heldout.jsonl"):
        for qe in json.loads(l)["trace"].get("query_extraction", []):
            cid = g.index.d["chunks"][qe["chunk"]]
            row = g.read("MATCH (c:Chunk {id: $id}) RETURN c.title AS title, c.text AS text", id=cid)[0]
            ch = {"id": cid, **row}
            u = llm.cached_usage(config.EXTRACT_MODEL, X.build_prompt(ch, [qe["relation"]], schema), X.SYSTEM, X.schema_json([qe["relation"]]), config.EXTRACT_MAX_TOKENS)
            if u:
                costs += llm.price(config.EXTRACT_MODEL, *u)
                n += 1
res = {"planner_usd_per_query": round(acc["planner"][0] / acc["planner"][1], 6), "answer_usd_per_query": round(acc["answer"][0] / acc["answer"][1], 6),
       "extraction_usd_per_call": round(costs / n, 6), "extraction_calls_priced": n, "queries": len(qs),
       "note": "planner and answer from the learned run's final-iteration cached usage; extraction from the learned run's query-time calls"}
(config.ROOT / "results" / "unit_costs.json").write_text(json.dumps(res, indent=1))
print(json.dumps(res, indent=1))
