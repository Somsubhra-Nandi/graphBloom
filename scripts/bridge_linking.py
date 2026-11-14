"""Bridge-entity linking rate on the 150 feedback questions (gold evidence is legal here: feedback only).

A bridge entity is the object of one gold triple and the subject of another. For each one we check whether
the graph has a REL edge from the gold subject to the bridge entity's title node.
  .venv/bin/python scripts/bridge_linking.py
"""
import json
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import config  # noqa: E402
from src.graph import Graph, normalize  # noqa: E402


def bridges(evidences):
    """[(subject_triple, bridge_name)]: triples whose object is the subject of another triple."""
    subj = {normalize(s) for s, _, _ in evidences}
    return [(t, t[2]) for t in evidences if normalize(t[2]) in subj]


def main():
    g = Graph()
    ix = g.index
    titles = ix.d["titles"]
    fb = [json.loads(l) for l in open(config.SPLIT_DIR / "feedback.jsonl")]
    seed_rels = set(config.SEED_RELATIONS)
    rows = []
    for q in fb:
        for (s, rel, o), b in bridges(q["evidences"]):
            sid, bid = ix.resolve(s), ix.resolve(b)
            if sid is None:
                cause, ok = "subject not in graph", False
            elif bid is None:
                cause, ok = "bridge has no entity", False
            elif str(bid) not in titles:
                cause, ok = "bridge entity is not a title node", False
            else:
                e = g.read("MATCH (a:Entity {id: $a})-[r:REL]->(b:Entity {id: $b}) RETURN r.type AS t", a=sid, b=bid)
                ok = bool(e)
                cause = "linked" if ok else ("no edge (relation held back from schema)" if rel not in seed_rels else "no edge (relation in schema, not extracted)")
            rows.append({"qid": q["_id"], "type": q["type"], "question": q["question"], "subject": s, "relation": rel, "bridge": b, "ok": ok, "cause": cause, "in_schema": rel in seed_rels})

    def rate(rs):
        return f"{sum(r['ok'] for r in rs)}/{len(rs)} = {sum(r['ok'] for r in rs) / max(1, len(rs)):.1%}"

    print(f"bridge links to check: {len(rows)} (in {len({r['qid'] for r in rows})} of {len(fb)} questions)")
    print("OVERALL:", rate(rows))
    print("by question type:")
    for t in config.QUESTION_TYPES:
        rs = [r for r in rows if r["type"] == t]
        print(f"  {t:20s} {rate(rs) if rs else 'no bridges'}")
    ins = [r for r in rows if r["in_schema"]]
    print(f"only links whose relation is in the seed schema: {rate(ins)}")
    for t in config.QUESTION_TYPES:
        rs = [r for r in ins if r["type"] == t]
        if rs:
            print(f"  {t:20s} {rate(rs)}")
    print("causes:", dict(Counter(r["cause"] for r in rows)))
    print("by gold relation:", {k: rate(v) for k, v in sorted(((k, [r for r in rows if r["relation"] == k]) for k in {r["relation"] for r in rows}), key=lambda kv: -len(kv[1]))})
    fails = [r for r in rows if not r["ok"]]
    print("\n10 failure examples (random, seed 42):")
    for r in random.Random(42).sample(fails, min(10, len(fails))):
        print(f"  [{r['type']}] ({r['subject']}) -[{r['relation']}]-> ({r['bridge']})  => {r['cause']}")
    print("\nfailures among in-schema relations (up to 10):")
    for r in [r for r in fails if r["in_schema"]][:10]:
        print(f"  [{r['type']}] ({r['subject']}) -[{r['relation']}]-> ({r['bridge']})  => {r['cause']}")
    Path("data/state/bridge_linking.json").write_text(json.dumps(rows, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
