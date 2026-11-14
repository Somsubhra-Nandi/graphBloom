"""Inspect the 2WikiMultihopQA dev split: fields, types, evidence coverage, relations, answers.

Run: .venv/bin/python scripts/inspect_dataset.py
"""
import json
import re
import sys
from collections import Counter
from pathlib import Path

DEV = Path("data/raw/dev.json")

MONTHS = "january february march april may june july august september october november december".split()
DATE_RE = re.compile(
    r"^(\d{1,2}\s+(%s)\s+\d{3,4}|(%s)\s+\d{1,2},?\s+\d{3,4}|(%s)\s+\d{3,4}|\d{3,4}-\d{2}-\d{2}|\d{3,4})$"
    % ("|".join(MONTHS), "|".join(MONTHS), "|".join(MONTHS)),
    re.I,
)
NUM_RE = re.compile(r"^[+-]?\d+([.,]\d+)?$")


def is_date(s):
    return bool(DATE_RE.match(s.strip()))


def is_number(s):
    return bool(NUM_RE.match(s.strip())) and not is_date(s)


def is_literal(s):
    return is_date(s) or is_number(s) or s.strip().lower() in {"yes", "no"}


def answer_type(rec):
    a = rec["answer"].strip()
    if a.lower() in {"yes", "no"}:
        return "yes/no"
    if is_date(a):
        return "date"
    titles = {t.lower() for t, _ in rec["context"]}
    ents = {x.lower() for s, _, o in rec["evidences"] for x in (s, o) if not is_literal(x)}
    if a.lower() in ents or a.lower() in titles:
        return "entity"
    return "other"


def main():
    if not DEV.exists():
        sys.exit(f"missing {DEV}; see PLAN.md / data download step")
    data = json.load(open(DEV))
    print(f"records: {len(data)}\n")

    print("== fields of one record (full) ==")
    print(json.dumps(data[0], indent=1, ensure_ascii=False))

    print("\n== counts by question type ==")
    types = Counter(r["type"] for r in data)
    for t, n in types.most_common():
        print(f"  {t:20s} {n}")

    print("\n== evidence triples present ==")
    missing = [r for r in data if not r.get("evidences")]
    print(f"  records with evidences: {len(data) - len(missing)} / {len(data)}  (missing: {len(missing)})")
    sf_missing = sum(1 for r in data if not r.get("supporting_facts"))
    print(f"  records with supporting_facts: {len(data) - sf_missing} / {len(data)}")
    lens = Counter(len(r["evidences"]) for r in data)
    print("  triples per record:", dict(sorted(lens.items())))
    seen = set()
    for r in data:
        if r["type"] not in seen:
            seen.add(r["type"])
            print(f"  example [{r['type']}] {r['question']!r} -> {r['answer']!r}")
            for tr in r["evidences"]:
                print("     ", tr)

    print("\n== literal share of evidence objects ==")
    objs = [o for r in data for _, _, o in r["evidences"]]
    kinds = Counter("date" if is_date(o) else "number" if is_number(o) else "yes/no" if o.lower() in {"yes", "no"} else "entity" for o in objs)
    for k, n in kinds.most_common():
        print(f"  {k:8s} {n:7d}  {n / len(objs):.1%}")
    lit = sum(n for k, n in kinds.items() if k != "entity")
    print(f"  literal total: {lit} / {len(objs)} = {lit / len(objs):.1%}")
    print("  by question type (literal share):")
    for t in types:
        os_ = [o for r in data if r["type"] == t for _, _, o in r["evidences"]]
        print(f"    {t:20s} {sum(is_literal(o) for o in os_) / len(os_):.1%}")

    print("\n== distinct evidence relations (top 25) ==")
    rels = Counter(rel for r in data for _, rel, _ in r["evidences"])
    print(f"  distinct relations: {len(rels)}")
    for rel, n in rels.most_common(25):
        print(f"  {rel:35s} {n}")
    print("\n  top relations by question type:")
    for t in types:
        c = Counter(rel for r in data if r["type"] == t for _, rel, _ in r["evidences"])
        print(f"    {t}: " + ", ".join(f"{k} ({v})" for k, v in c.most_common(8)))

    print("\n== answer types ==")
    at = Counter(answer_type(r) for r in data)
    for k, n in at.most_common():
        print(f"  {k:8s} {n:6d}  {n / len(data):.1%}")
    print("  by question type:")
    for t in types:
        c = Counter(answer_type(r) for r in data if r["type"] == t)
        print(f"    {t:20s} {dict(c)}")
    print("  samples of 'other':")
    for r in [r for r in data if answer_type(r) == "other"][:5]:
        print(f"    {r['answer']!r}  <- {r['question']!r}")


if __name__ == "__main__":
    main()
