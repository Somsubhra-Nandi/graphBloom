"""Run a system over a question file; write results/<run_name>/<split>.jsonl and summary.json.

  .venv/bin/python scripts/evaluate.py --system static_graph --split heldout --run-name iter0_static_graph
  .venv/bin/python scripts/evaluate.py --system bm25  --split feedback --run-name iter0_bm25

Systems: static_graph (the iteration-0 shallow graph, never changed) and bm25 (BM25 top-5 chunks, no graph; named bm25).
Both use the same answer prompt and model. Everything runs in the smoke phase. Resumable: question ids already in
the results file are skipped, and a BudgetExceeded stops the run cleanly with the rows written so far.

Leakage rule: only the `answer` field of a question file is read, and only to score. Evidence and supporting facts
(present in feedback.jsonl, absent from heldout.jsonl) are never touched here.
"""
import argparse
import json
import sys
import threading
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import config, llm  # noqa: E402
from src.metrics import bootstrap_ci, exact_match, f1_score  # noqa: E402

# Hops along the entity chain, taken from the question type so that no gold evidence is needed (held-out files
# carry none): comparison looks up one attribute per entity; the others take a relation step first.
HOPS_BY_TYPE = {"comparison": 1, "bridge_comparison": 2, "compositional": 2, "inference": 2}
PHASE = "smoke"


def make_system(name):
    if name == "static_graph":
        from src.query import QueryEngine

        eng = QueryEngine(phase=PHASE)
        return lambda q: eng.answer(q)
    if name == "bm25":
        from src.query import answer_from_prompt, build_answer_prompt
        from src.bm25 import BM25Retriever

        ret = BM25Retriever()

        def run(q):
            chunks = ret.top_k(q, config.ANSWER_MAX_CHUNKS)
            ans, why = answer_from_prompt(build_answer_prompt(q, [], [], chunks), PHASE)
            return {"question": q, "chunks": [{"title": c["title"], "score": c["score"]} for c in chunks], "answer": ans, "reasoning": why, "run_params": config.run_params()}

        return run
    raise SystemExit(f"unknown system {name}")


def agg(rows):
    n = len(rows)
    if not n:
        return {"n": 0}
    ems, f1s = [r["em"] for r in rows], [r["f1"] for r in rows]
    return {"n": n, "em": round(sum(ems) / n, 4), "em_ci95": bootstrap_ci(ems), "f1": round(sum(f1s) / n, 4), "f1_ci95": bootstrap_ci(f1s)}  # 1,000 resamples, seed 42


def summarize(rows):
    by_type, by_hops = defaultdict(list), defaultdict(list)
    for r in rows:
        by_type[r["type"]].append(r)
        by_hops[str(HOPS_BY_TYPE[r["type"]])].append(r)
    return {"overall": agg(rows), "by_type": {k: agg(v) for k, v in sorted(by_type.items())}, "by_hops": {k: agg(v) for k, v in sorted(by_hops.items())}}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--system", required=True, choices=["static_graph", "bm25"])
    ap.add_argument("--split", required=True, choices=["feedback", "heldout"])
    ap.add_argument("--run-name", required=True)
    ap.add_argument("--limit", type=int)
    ap.add_argument("--workers", type=int, default=config.LLM_WORKERS)
    ap.add_argument("--use-reserve", action="store_true", help="allow spending the $1 reserve")
    args = ap.parse_args()
    llm.set_use_reserve(args.use_reserve)

    qs = [json.loads(l) for l in open(config.SPLIT_DIR / f"{args.split}.jsonl")]
    if args.limit:
        qs = qs[: args.limit]
    out_dir = config.ROOT / "results" / args.run_name
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{args.split}.jsonl"
    done = {}
    if out_path.exists():
        for l in open(out_path):
            r = json.loads(l)
            done[r["id"]] = r
    todo = [q for q in qs if q["_id"] not in done]
    print(f"{args.system} on {args.split}: {len(qs)} questions, {len(done)} already done, {len(todo)} to run")

    system = make_system(args.system)
    stop = threading.Event()

    def work(q):
        if stop.is_set():
            return q, None, "skipped"
        try:
            return q, system(q["question"]), None
        except llm.BudgetExceeded as e:
            stop.set()
            return q, None, f"BudgetExceeded: {e}"

    err = None
    with ThreadPoolExecutor(args.workers) as ex, open(out_path, "a") as f:
        for q, trace, e in ex.map(work, todo):
            if e:
                err = err or (e if e != "skipped" else None)
                continue
            pred = trace.get("answer", "")
            row = {"id": q["_id"], "type": q["type"], "question": q["question"], "prediction": pred, "gold": q["answer"],
                   "em": exact_match(pred, q["answer"]), "f1": round(f1_score(pred, q["answer"]), 4), "trace": trace}
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            f.flush()
            done[q["_id"]] = row

    rows = [done[q["_id"]] for q in qs if q["_id"] in done]
    st = llm.run_stats()
    sp = out_dir / "summary.json"
    summary = json.loads(sp.read_text()) if sp.exists() else {"run_name": args.run_name, "system": args.system, "splits": {}}
    prev = summary["splits"].get(args.split, {}).get("cost_usd", 0.0)
    prev_calls = summary["splits"].get(args.split, {}).get("llm_calls", 0)
    summary["run_params"] = config.run_params()
    summary["splits"][args.split] = {
        **summarize(rows),
        "complete": len(rows) == len(qs),
        "questions": f"{len(rows)}/{len(qs)}",
        "cost_usd": round(prev + st["cost"], 6),  # accumulates across resumed invocations
        "llm_calls": prev_calls + st["calls"],
        "tokens_this_invocation": {"input": st["input_tokens"], "output": st["output_tokens"]},
    }
    sp.write_text(json.dumps(summary, indent=1))
    s = summary["splits"][args.split]
    o = s["overall"]
    print(f"\n{args.run_name} / {args.split}: {s['questions']} questions  EM {o.get('em')} {o.get('em_ci95')}  F1 {o.get('f1')} {o.get('f1_ci95')}  cost ${s['cost_usd']:.4f}")
    for k, v in s["by_type"].items():
        print(f"   {k:20s} n={v['n']:3d} EM {v['em']:.3f} {v['em_ci95']}  F1 {v['f1']:.3f} {v['f1_ci95']}")
    if err:
        print("STOPPED:", err)
        sys.exit(2)
    llm.log_stats(f"eval:{args.run_name}:{args.split}")


if __name__ == "__main__":
    main()
