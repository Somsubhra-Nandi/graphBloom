"""One-off code-side fixes after the full ingest (no full re-extraction).

Order: re-extract the truncated chunks, performer cleanup, confidence >= 0.6 (edges and literals), demonym merge.
  .venv/bin/python scripts/cleanup_fixes.py
Every graph change goes through Graph.write(); counts are printed per step.
"""
import json
import random
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import ingest  # noqa: E402
from src import config, llm  # noqa: E402
from src.countries import _GROUPS, canonical_country  # noqa: E402
from src.graph import Graph, normalize  # noqa: E402

MIN_CONF = 0.6
REEXTRACT_TOKENS = 1200


def counts(g):
    return {
        "entities": g.read("MATCH (n:Entity) RETURN count(*) AS n")[0]["n"],
        "REL edges": g.read("MATCH (a:Entity)-[r:REL]->(b:Entity) RETURN count(*) AS n")[0]["n"],
    }


def step5_reextract(g, corpus):
    trunc = [c for c in corpus if (ingest.chunk_usage(c) or [0, 0])[1] >= config.EXTRACT_MAX_TOKENS]
    print(f"[5] truncated chunks (output hit {config.EXTRACT_MAX_TOKENS} tokens): {len(trunc)}")
    before = llm.spend_summary()
    with ThreadPoolExecutor(config.LLM_WORKERS) as ex:
        results = list(ex.map(lambda c: ingest.extract(c, REEXTRACT_TOKENS), trunc))
    with open(ingest.EXTRACTIONS_PATH, "a") as log:
        for c, tr in zip(trunc, results):
            ingest.ingest_chunk(g, c, tr)  # clears the chunk's old edges first
            log.write(json.dumps({"title": c["title"], "triples": tr, "reextract": True}, ensure_ascii=False) + "\n")
    print(f"    triples before: {sum(len(json.loads(l)['triples']) for l in open(ingest.EXTRACTIONS_PATH) if json.loads(l).get('reextract') is None and json.loads(l)['title'] in {c['title'] for c in trunc})}"
          f" -> after: {sum(len(r) for r in results)}")
    print("   ", llm.spend_summary())


def step2_performer(g):
    old = g.load_edges()
    directors = {e["s"] for e in old if e["t"] == "director"}
    drop = [e for e in old if e["t"] == "performer" and e["s"] in directors]
    new = [e for e in old if not (e["t"] == "performer" and e["s"] in directors)]
    perf = sum(e["t"] == "performer" for e in old)
    pairs, written = g.commit_edges(old, new)
    print(f"[2] performer edges: {perf} before; removed {len(drop)} (subject also has a director edge); {perf - len(drop)} remain  ({pairs} pairs rewritten)")


def step3_confidence(g):
    old = g.load_edges()
    new = [e for e in old if e["c"] >= MIN_CONF]
    low = [e for e in old if e["c"] < MIN_CONF]
    g.commit_edges(old, new)
    print(f"[3] edges below {MIN_CONF} removed: {len(low)}  by type: {dict(Counter(e['t'] for e in low))}")

    # Literals do not store a confidence, so recompute them from the extraction log with the new threshold,
    # replaying ingest's rules (usable at >= 0.6, first listed value per chunk, later chunks overwrite).
    latest = {}
    for l in open(ingest.EXTRACTIONS_PATH):
        d = json.loads(l)
        latest.pop(d["title"], None)
        latest[d["title"]] = d["triples"]
    new = {}
    ix = g.index
    for title, triples in latest.items():
        mine = {}
        for t in filter(ingest.usable, triples):
            rel = t.get("relation")
            prop = config.SEED_RELATIONS.get(rel, (None,))[0]
            subj, obj = (t.get("subject") or "").strip(), (t.get("object") or "").strip()
            if not prop or not subj or not obj:
                continue
            sid = ix.resolve(title) if ingest.is_main_subject(subj, title) else ix.resolve(subj)
            if sid is not None:
                mine.setdefault((sid, prop), obj)
        new.update(mine)
    removed, changed = [], []
    for prop in config.LITERAL_PROPS:
        for r in g.read(f"MATCH (n:Entity) WHERE n.{prop} <> '' RETURN n.id AS id, n.{prop} AS v"):
            n = new.get((r["id"], prop))
            if n is None:
                removed.append((prop, r["id"]))
            elif n != r["v"]:
                changed.append((prop, r["id"], n))
    from src.literals import normalize_literal

    for prop in config.LITERAL_PROPS:
        rows = [{"id": i, "value": "", "norm": "", "approx": False} for p, i in removed if p == prop]
        for p, i, v in changed:
            if p == prop:
                nl = normalize_literal(v)
                rows.append({"id": i, "value": v, "norm": nl["norm"], "approx": nl["approx"]})
        g.write_literals(prop, rows)
    print(f"    literals below {MIN_CONF} cleared: {len(removed)}; replaced by a later >= {MIN_CONF} value: {len(changed)}")


def step4_demonyms(g):
    ix = g.index
    before = counts(g)
    ents = g.read("MATCH (n:Entity) RETURN n.id AS id, n.name AS name")
    groups = {}
    for e in ents:
        c = canonical_country(e["name"])
        if c:
            groups.setdefault(c, []).append(e)
    remap, aliases_of, skipped_titles = {}, {}, []
    for canon, members in sorted(groups.items()):
        existing = [m for m in members if m["name"] == canon]
        if existing:
            sid = existing[0]["id"]
        else:
            sid, _ = ix.entity_for(canon)
            g.flush_entities()
        for v in members:
            if v["id"] == sid:
                continue
            if str(v["id"]) in ix.d["titles"]:
                skipped_titles.append(v["name"])  # a title node is a real page; never merged away
                continue
            remap[v["id"]] = sid
            aliases_of.setdefault(sid, []).append(v["name"])
            ix.d["names"].pop(normalize(v["name"]), None)
            ix.d["display"].pop(str(v["id"]), None)
            for k, o in list(ix.d["aliases"].items()):
                if o == v["id"]:
                    ix.d["aliases"][k] = sid
            ix.d["aliases"][normalize(v["name"])] = sid
        for name in _GROUPS.get(canon, []):  # every known variant resolves to the canonical entity from now on
            n = normalize(name)
            if n not in ix.d["names"] and n not in ix.d["aliases"]:
                ix.d["aliases"][n] = sid
    ix.save()

    old = g.load_edges()
    new, seen, repointed, dups = [], set(), 0, 0
    for e in old:
        s, d = remap.get(e["s"], e["s"]), remap.get(e["d"], e["d"])
        if (s, d) != (e["s"], e["d"]):
            repointed += 1
        key = (s, d, e["t"])
        if s == d or (key in seen and (s, d) != (e["s"], e["d"])):
            dups += 1  # a repointed edge that duplicates an existing (subject, relation, country) edge
            continue
        seen.add(key)
        new.append(dict(e, s=s, d=d))
    g.commit_edges(old, new)
    g.delete_nodes(list(remap))
    for sid, names in aliases_of.items():
        cur = g.read("MATCH (n:Entity {id: $id}) RETURN n.aliases AS a", id=sid)
        have = [a for a in (cur[0]["a"] if cur else "").split("|") if a]
        g.write_aliases([{"id": sid, "aliases": "|".join(sorted(set(have + names)))}])
    after = counts(g)
    print(f"[4] demonyms: {len(groups)} canonical countries matched; {len(remap)} variant entities merged away; {repointed} edges repointed; {dups} duplicate edges dropped")
    if skipped_titles:
        print("    variants left alone because they are title nodes:", skipped_titles)
    print(f"    before: {before}   after: {after}")


def main():
    llm.set_use_reserve(False)
    g = Graph()
    corpus = [json.loads(l) for l in open(config.SPLIT_DIR / "corpus.jsonl")]
    print("start:", counts(g))
    if "--skip-reextract" not in sys.argv:
        step5_reextract(g, corpus)
        print("after re-extract:", counts(g))
    if "--only-reextract" in sys.argv:
        return
    step2_performer(g)
    step3_confidence(g)
    step4_demonyms(g)
    final = counts(g)
    perf = g.read("MATCH (a:Entity)-[r:REL]->(b:Entity) WHERE r.type = 'performer' RETURN count(*) AS n")[0]["n"]
    print("final:", final, "| performer edges remaining:", perf)
    print("by type:", dict(Counter(r["t"] for r in g.read("MATCH (a:Entity)-[r:REL]->(b:Entity) RETURN r.type AS t"))))


if __name__ == "__main__":
    main()
