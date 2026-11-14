"""Show normalize_literal on 20 date strings sampled (seed 42) from gold evidences in feedback.jsonl, plus edge cases."""
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from inspect_dataset import is_date  # noqa: E402
from src.literals import normalize_literal  # noqa: E402

dates = sorted({o for l in open("data/split/feedback.jsonl") for _, _, o in json.loads(l)["evidences"] if is_date(o)})
print(f"{len(dates)} distinct gold date strings in feedback.jsonl; sampling 20 (seed 42)")
for d in random.Random(42).sample(dates, 20):
    r = normalize_literal(d)
    print(f"  {d!r:24} -> {r['norm']!r:14} approx={r['approx']}")
bad = [d for d in dates if not normalize_literal(d)["norm"]]
print(f"gold dates that fail to normalize: {len(bad)} / {len(dates)}", bad[:5])
print("edge cases:")
for d in ["c. 1732", "circa 1250", "ca. 1180", "1732?", "1st May 1900", "May 1st, 1900", "March 1921", "44 BC", "31 February 1900", "1182–1226", "<UNKNOWN>", "1971-12-22"]:
    r = normalize_literal(d)
    print(f"  {d!r:24} -> {r['norm']!r:14} approx={r['approx']}")
