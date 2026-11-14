"""Run N feedback questions end to end and print question, predicted answer, gold answer and path.

  .venv/bin/python scripts/smoke_query.py --n 10
Feedback questions only: gold answers and evidence are legal to read here. Held-out questions are never loaded.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import config, llm  # noqa: E402
from src.query import QueryEngine  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=10)
    ap.add_argument("--out", default="data/state/smoke_query.json")
    ap.add_argument("--use-reserve", action="store_true", help="allow spending the $1 reserve")
    args = ap.parse_args()
    qs = [json.loads(l) for l in open(config.SPLIT_DIR / "feedback.jsonl")][: args.n]
    llm.set_use_reserve(args.use_reserve)
    eng = QueryEngine(phase="smoke")
    traces = []
    for q in qs:
        t = eng.answer(q["question"])
        t["gold"], t["type"] = q["answer"], q["type"]
        traces.append(t)
        print(f"\nQ [{q['type']}]: {q['question']}")
        print(f"  planner: type={t['plan']['question_type']} chain={t['plan']['relation_chain']}")
        print(f"  seeds: {t['plan']['seeds']}  resolved ids: {[(s['name'], s['id']) for s in t['seeds']]}  unresolved: {t['unresolved_seeds']}")
        for p in t["paths"][:3]:
            print("  path:", p["nodes"][0]["name"] + "".join(f" -[{e['type']}]-> {n['name']}" for e, n in zip(p["edges"], p["nodes"][1:])), f"(score {p['score']})")
        if not t["paths"]:
            print("  path: (none)")
        if t["attributes"]:
            print("  attrs:", t["attributes"])
        print(f"  predicted: {t['answer']!r}    gold: {q['answer']!r}    beam dead-ended: {'yes ' + str([(d['entity'], d['expected_relation']) for d in t['dead_ends']]) if t['dead_ends'] else 'no'}")
    Path(args.out).write_text(json.dumps({"run_params": config.run_params(), "traces": traces}, indent=1, ensure_ascii=False))
    llm.log_stats("smoke_query")


if __name__ == "__main__":
    main()
