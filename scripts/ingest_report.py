"""Post-ingest report: graph counts, linking rate, 10 random REL edges with source sentences, failed links.

  .venv/bin/python scripts/ingest_report.py
Linking rate = share of REL object entities that are title entities (an entity created from a paragraph title).
"""
import random
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import config  # noqa: E402
from src.graph import Graph, normalize  # noqa: E402


def sentence_for(text, obj):
    sents = re.split(r"(?<=[.!?])\s+", text)
    o = normalize(obj)
    for s in sents:
        if o and o in normalize(s):
            return s
    return text[:300] + ("..." if len(text) > 300 else "")


def main():
    g = Graph()
    ix = g.index
    titles = ix.d["titles"]
    ents = g.read("MATCH (n:Entity) RETURN count(*) AS n")[0]["n"]
    chunks = g.read("MATCH (n:Chunk) RETURN count(*) AS n")[0]["n"]
    edges = g.read("MATCH (a:Entity)-[r:REL]->(b:Entity) RETURN a.name AS a, b.id AS bid, b.name AS b, r.type AS t, r.confidence AS c, r.src_chunk AS chunk")
    lit = {p: g.read(f"MATCH (n:Entity) WHERE n.{p} <> '' RETURN count(*) AS n")[0]["n"] for p in config.LITERAL_PROPS}
    norm_ok = {p: g.read(f"MATCH (n:Entity) WHERE n.{p}_norm <> '' RETURN count(*) AS n")[0]["n"] for p in config.LITERAL_PROPS}
    print(f"entities {ents} (title entities {len(titles)}, created from extraction {ents - len(titles)})")
    print(f"chunks {chunks}")
    print(f"REL edges {len(edges)}  by type: {dict(Counter(e['t'] for e in edges).most_common())}")
    print(f"literals (entities with a value): {lit}; normalized to ISO: {norm_ok}; total literal values {sum(lit.values())}")

    linked = [e for e in edges if str(e["bid"]) in titles]
    objs = {e["bid"]: e["b"] for e in edges}
    linked_objs = {b for b in objs if str(b) in titles}
    print(f"\nlinking rate: {len(linked)}/{len(edges)} edges = {len(linked) / max(1, len(edges)):.1%};"
          f" distinct objects {len(linked_objs)}/{len(objs)} = {len(linked_objs) / max(1, len(objs)):.1%}")
    print("  by relation (edge level):")
    for t in config.SEED_RELATIONS:
        es = [e for e in edges if e["t"] == t]
        if es:
            print(f"    {t:24s} {sum(str(e['bid']) in titles for e in es):5d}/{len(es):5d} = {sum(str(e['bid']) in titles for e in es) / len(es):.0%}")

    rng = random.Random(42)
    print("\n== 10 random REL edges with their source sentence ==")
    for e in rng.sample(edges, min(10, len(edges))):
        row = g.read("MATCH (c:Chunk {id: $id}) RETURN c.title AS title, c.text AS text", id=e["chunk"])[0]
        print(f"\n({e['a']}) -[{e['t']}, conf {e['c']}]-> ({e['b']})   [chunk: {row['title']}]")
        print("   ", sentence_for(row["text"], e["b"]))

    fail = [e for e in edges if str(e["bid"]) not in titles]
    print(f"\n== objects that did not link ({len(fail)} edges) ==")
    print("  most frequent:", Counter(e["b"] for e in fail).most_common(15))
    tnames = {normalize(ix.d["display"][k]): ix.d["display"][k] for k in titles}
    print("  random sample, with any title that contains the object's name:")
    for e in rng.sample(fail, min(15, len(fail))):
        o = normalize(e["b"])
        near = [v for k, v in tnames.items() if o and (k.startswith(o + " ") or k.endswith(" " + o))][:2]
        print(f"    [{e['t']}] {e['b']!r}   possible titles: {near}")


if __name__ == "__main__":
    main()
