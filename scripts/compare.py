"""Paired bootstrap comparison of two runs on the same held-out questions.

  .venv/bin/python scripts/compare.py results/learned/iter5/heldout.jsonl results/random/iter5/heldout.jsonl
Reports, for EM and F1, the mean per-question difference (first minus second), its 95% CI from 10,000 paired
resamples (seed 42), and the share of resamples where the difference is <= 0 (a one-sided p-value-like number).
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.metrics import paired_bootstrap  # noqa: E402


def load(path):
    return {r["id"]: r for r in map(json.loads, open(path))}


def compare(path_a, path_b):
    a, b = load(path_a), load(path_b)
    ids = sorted(set(a) & set(b))
    if len(ids) != len(a) or len(ids) != len(b):
        print(f"warning: only {len(ids)} questions in common ({len(a)} vs {len(b)})", file=sys.stderr)
    return {m: paired_bootstrap([a[i][m] - b[i][m] for i in ids]) for m in ("em", "f1")}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("a")
    ap.add_argument("b")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    res = compare(args.a, args.b)
    if args.json:
        print(json.dumps(res, indent=1))
        return
    print(f"{args.a}  minus  {args.b}")
    for m, r in res.items():
        print(f"  {m.upper():3s} n={r['n']}  mean diff {r['mean_diff']:+.4f}  95% CI [{r['ci95'][0]:+.4f}, {r['ci95'][1]:+.4f}]  share of resamples <= 0: {r['share_le_0']:.4f}")


if __name__ == "__main__":
    main()
