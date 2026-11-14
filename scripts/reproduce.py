"""Reproducibility checks. Everything here is offline and free.

  .venv/bin/python scripts/reproduce.py
Needs the learned_iter5 graph to be the live graph (scripts/snapshot.py restore learned_iter5) for check 4.
"""
import hashlib
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from src import config, llm  # noqa: E402
from src.curve import build_curve  # noqa: E402
from src.metrics import exact_match, f1_score, paired_bootstrap  # noqa: E402

R = config.ROOT / "results"
checks = []


def check(name, ok, detail=""):
    checks.append({"check": name, "pass": bool(ok), "detail": detail})
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()[:16]


# 1. the split regenerates byte-for-byte from seed 42
import make_split  # noqa: E402

orig = {f: sha(config.SPLIT_DIR / f) for f in ("feedback.jsonl", "heldout.jsonl", "corpus.jsonl")}
with tempfile.TemporaryDirectory() as d:
    make_split.OUT = Path(d)
    sys.stdout = open("/dev/null", "w")
    make_split.main()
    sys.stdout = sys.__stdout__
    again = {f: sha(Path(d) / f) for f in orig}
check("split files regenerate identically from seed 42", orig == again, json.dumps(orig))

# 2. every stored score recomputes from the stored prediction and gold; summaries recompute from the rows
bad, files = 0, 0
for p in sorted(R.glob("**/heldout.jsonl")) + sorted(R.glob("**/feedback.jsonl")):
    rows = [json.loads(l) for l in open(p)]
    files += 1
    for r in rows:
        if r["em"] != exact_match(r["prediction"], r["gold"]) or abs(r["f1"] - round(f1_score(r["prediction"], r["gold"]), 4)) > 1e-9:
            bad += 1
check("stored EM/F1 recompute from prediction and gold", bad == 0, f"{files} result files, {bad} mismatches")
mism = 0
for run in ("learned", "random", "random_s7"):
    for k in range(6):
        rows = [json.loads(l) for l in open(R / run / f"iter{k}" / "heldout.jsonl")]
        s = json.loads((R / run / f"iter{k}" / "summary.json").read_text())["heldout"]["overall"]
        mism += abs(sum(r["em"] for r in rows) / len(rows) - s["em"]) > 1e-3
check("per-iteration summaries match their rows (3 runs x 6 iterations)", mism == 0, f"{mism} mismatches")

# 3. curve.json and comparisons.json recompute
cur = json.loads((R / "curve.json").read_text())
new = build_curve()
cur.pop("updated"), new.pop("updated")
check("results/curve.json equals build_curve()", cur == new)
from compare import compare  # noqa: E402

stored = json.loads((R / "comparisons.json").read_text())
ok = all(compare(R / a, R / b) == stored[k] for k, (a, b) in {
    "learned_iter5_vs_random_iter5": ("learned/iter5/heldout.jsonl", "random/iter5/heldout.jsonl"),
    "learned_iter5_vs_static_graph": ("learned/iter5/heldout.jsonl", "iter0_static_graph/heldout.jsonl")}.items())
check("paired bootstrap comparisons recompute (seed 42, 10,000 resamples)", ok)

# 4. the saved learned graph plus the response cache reproduce the iteration-5 predictions
live = json.loads((config.STATE_DIR / "live_graph.json").read_text())
if live.get("snapshot") == "learned_iter5":
    from src.graph import Graph
    from src.query import QueryEngine
    from src.schema import ActiveSchema
    import learn

    def cache_only(model, prompt, system="", schema=None, max_tokens=1024, temperature=0.0, *, phase):
        hit, res = llm.cache_lookup(model, prompt, system, schema, max_tokens, temperature)
        if not hit:
            raise RuntimeError("cache miss")
        return res

    llm.call = cache_only
    schema = ActiveSchema.load(config.RUNS_DIR / "learned" / "schema.json")
    eng = QueryEngine(Graph(schema=schema), phase="learning", schema=schema)
    stored_rows = {r["id"]: r for r in map(json.loads, open(R / "learned/iter5/heldout.jsonl"))}
    diff = miss = 0
    for q in learn.load_heldout():
        try:
            diff += eng.answer(q["question"])["answer"] != stored_rows[q["_id"]]["prediction"]
        except RuntimeError:
            miss += 1
    check("learned_iter5 graph + cache reproduce the iteration-5 predictions", diff == 0 and miss == 0, f"{diff} differing, {miss} cache misses, 0 spend")
else:
    check("learned_iter5 graph + cache reproduce the iteration-5 predictions", False, "live graph is not learned_iter5; restore it and rerun")

# 5. identical run parameters across systems, and no label leakage
params = set()
for p in ["learned", "random", "random_s7", "iter0_static_graph"]:
    f = sorted(R.glob(f"{p}/iter*/heldout.jsonl")) or [R / p / "heldout.jsonl"]
    for fp in f:
        for l in open(fp):
            rp = json.loads(l)["trace"].get("run_params")
            if rp:
                params.add(json.dumps(rp, sort_keys=True))
check("run_params identical in every held-out trace (learned, random, static)", len(params) == 1, f"{len(params)} distinct")
ho_keys = set().union(*[json.loads(l).keys() for l in open(config.SPLIT_DIR / "heldout.jsonl")])
check("heldout.jsonl carries no evidence or supporting facts", ho_keys <= {"_id", "type", "question", "answer"}, str(sorted(ho_keys)))
src = (config.ROOT / "src" / "classifier.py").read_text()
check("classifier never opens heldout.jsonl", "heldout" not in src.replace("never opens heldout.jsonl", "").replace("not heldout", ""), "feedback.jsonl is its only question file")

# 6. the budget ledger adds up
led = json.loads((config.STATE_DIR / "spend.json").read_text())
check("spend ledger: phases sum to the total and stay under budget", abs(sum(led["by_phase"].values()) - led["total"]) < 1e-3 and led["total"] < config.BUDGET_TOTAL_USD and led["by_phase"].get("reserve", 0) == 0, f"total ${led['total']:.4f}, reserve $0")

(R / "reproducibility.json").write_text(json.dumps(checks, indent=1))
print(f"\n{sum(c['pass'] for c in checks)}/{len(checks)} checks passed")
sys.exit(0 if all(c["pass"] for c in checks) else 1)
