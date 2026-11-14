"""Open-vocabulary baseline: the planner's vocabulary is the seed schema plus the whole candidate pool from the start,
query-time extraction is on with the same budget as the learned policy, and there is no feedback and no learning.
Held-out only, one pass. Run on the iteration-0 graph (scripts/snapshot.py restore iter0).

  .venv/bin/python scripts/open_vocab.py --estimate
  .venv/bin/python scripts/open_vocab.py                 # stops if spend in this run would pass --max-usd (default 0.80)
Note the pool is built from the gold relations of the feedback questions, so this baseline assumes someone already
knows which relations are worth looking for; it is an upper-bound-style comparison, not a deployable system.
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
from src.query import QueryEngine, plan_prompt  # noqa: E402
from src.schema import ActiveSchema  # noqa: E402
import learn  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--estimate", action="store_true")
    ap.add_argument("--max-usd", type=float, default=0.80)
    ap.add_argument("--workers", type=int, default=config.LLM_WORKERS)
    args = ap.parse_args()
    pool = learn.candidate_pool(load_feedback())
    schema = ActiveSchema()
    for rel, info in pool.items():
        schema.add(rel, info["literal"], 0)
    qs = learn.load_heldout()
    unit = json.loads((config.ROOT / "results" / "unit_costs.json").read_text())

    if args.estimate:
        plan = sum(llm.estimate_cost(config.EXTRACT_MODEL, "You plan how to answer a multi-hop question over a knowledge graph of Wikipedia entities.", plan_prompt(q["question"], schema.names()), learn.__dict__["QueryEngine"].__init__ and __import__("src.query", fromlist=["PLAN_SCHEMA"]).PLAN_SCHEMA, config.PLAN_MAX_TOKENS, "learning") for q in qs)
        ext = len(qs) * config.QUERY_EXTRACT_BUDGET * unit["extraction_usd_per_call"]
        ans = len(qs) * unit["answer_usd_per_query"] * 1.2
        total = plan + ext + ans
        print(f"vocabulary: {len(schema.names())} relations (8 seed + {len(pool)} pool)")
        print(f"upper-bound estimate: planner ${plan:.3f} (all {len(qs)} prompts are new) + extraction ${ext:.3f} (2 calls for every query) + answers ${ans:.3f} = ${total:.3f}")
        print("OK, under the limit" if total <= args.max_usd else f"EXCEEDS ${args.max_usd}: stop")
        sys.exit(0 if total <= args.max_usd else 3)

    g = Graph(schema=schema)
    for prop in schema.literal_props():
        g.add_literal_prop(prop)  # defaults for the date relations that are new to the graph
    eng = QueryEngine(g, phase="learning", schema=schema)
    extractor = QueryTimeExtractor(g, schema, 0)
    start = llm.total_spent()

    def system(q):
        if llm.total_spent() - start > args.max_usd:
            raise llm.BudgetExceeded(f"open-vocabulary run passed its ${args.max_usd} limit")
        return eng.answer(q["question"], extractor, q["_id"])

    out = config.ROOT / "results" / "open_vocab"
    rows, err = run_questions(qs, system, out / "heldout.jsonl", args.workers)
    s = summarize(rows)
    s.update(questions=f"{len(rows)}/87", cost_usd=round(llm.total_spent() - start, 5),
             query_extraction_calls=sum(len(r["trace"].get("query_extraction", [])) for r in rows),
             queries_with_events=sum(1 for r in rows if r["trace"].get("events")),
             queries_with_extraction=sum(1 for r in rows if r["trace"].get("query_extraction")))
    (out / "summary.json").write_text(json.dumps({"run_name": "open_vocab", "system": "open_vocab", "vocabulary": schema.names(), "pool": pool,
                                                   "splits": {"heldout": s}, "run_params": config.run_params()}, indent=1))
    o = s["overall"]
    print(f"open vocabulary: {s['questions']}  EM {o['em']} {o['em_ci95']}  F1 {o['f1']} {o['f1_ci95']}  extraction calls {s['query_extraction_calls']}  cost ${s['cost_usd']}")
    for k, v in s["by_type"].items():
        print(f"   {k:18s} n={v['n']:2d} EM {v['em']:.3f} {v['em_ci95']}")
    if err:
        print("STOPPED:", err)
    llm.log_stats("open_vocab")


if __name__ == "__main__":
    main()
