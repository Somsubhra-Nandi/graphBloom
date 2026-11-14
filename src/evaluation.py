"""Shared evaluation helpers: run a system over questions, score, and summarize with bootstrap CIs."""
import json
import threading
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

from src import llm
from src.metrics import bootstrap_ci, exact_match, f1_score

# Hops along the entity chain, taken from the question type so no gold evidence is needed (held-out files carry none).
HOPS_BY_TYPE = {"comparison": 1, "bridge_comparison": 2, "compositional": 2, "inference": 2}


def agg(rows):
    n = len(rows)
    if not n:
        return {"n": 0}
    ems, f1s = [r["em"] for r in rows], [r["f1"] for r in rows]
    return {"n": n, "em": round(sum(ems) / n, 4), "em_ci95": bootstrap_ci(ems), "f1": round(sum(f1s) / n, 4), "f1_ci95": bootstrap_ci(f1s)}


def summarize(rows):
    by_type, by_hops = defaultdict(list), defaultdict(list)
    for r in rows:
        by_type[r["type"]].append(r)
        by_hops[str(HOPS_BY_TYPE[r["type"]])].append(r)
    return {"overall": agg(rows), "by_type": {k: agg(v) for k, v in sorted(by_type.items())}, "by_hops": {k: agg(v) for k, v in sorted(by_hops.items())}}


def run_questions(qs, system, out_path, workers):
    """Run `system(question_record) -> trace` over `qs`, appending scored rows to out_path (resumable).
    Returns (rows in question order, error string or None)."""
    done = {}
    if out_path.exists():
        for l in open(out_path):
            r = json.loads(l)
            done[r["id"]] = r
    todo = [q for q in qs if q["_id"] not in done]
    stop, err = threading.Event(), None

    def work(q):
        if stop.is_set():
            return q, None, "skipped"
        try:
            return q, system(q), None
        except llm.BudgetExceeded as e:
            stop.set()
            return q, None, f"BudgetExceeded: {e}"

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(workers) as ex, open(out_path, "a") as f:
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
    return [done[q["_id"]] for q in qs if q["_id"] in done], err
