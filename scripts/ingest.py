"""Shallow ingest: chunks, title entities, and LLM extraction of the 8 seed relations only.

  .venv/bin/python scripts/ingest.py --limit 20     # trial: 20 chunks, prints the extraction output
  .venv/bin/python scripts/ingest.py --all          # the rest of the corpus
Resumable: chunks listed in data/state/ingested.json are skipped. Chunks are processed in a seeded
shuffled order (seed 42) so a trial run is a spread of the corpus, not the first 20 titles.
"""
import argparse
import json
import os
import random
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import config, llm  # noqa: E402
from src.graph import Graph, normalize, strip_qualifier  # noqa: E402
from src.literals import normalize_literal  # noqa: E402

EXTRACTIONS_PATH = config.STATE_DIR / "extractions.jsonl"
OUTPUT_TOKENS_GUESS = 150
CORPUS_SAMPLE = []  # filled in main(): chunks used to calibrate the estimate

SCHEMA = {
    "type": "object",
    "properties": {
        "triples": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "subject": {"type": "string"},
                    "relation": {"type": "string", "enum": list(config.SEED_RELATIONS)},
                    "object": {"type": "string"},
                    "confidence": {"type": "number", "description": "0 to 1: how clearly the text states this fact"},
                },
                "required": ["subject", "relation", "object", "confidence"],
            },
        }
    },
    "required": ["triples"],
}

SYSTEM = "You extract facts from one Wikipedia paragraph into (subject, relation, object) triples. Use only the listed relations and only facts the text states."


def build_prompt(chunk):
    rels = "\n".join(
        f"- {r}: {d}" + (" (the object is a date, written as in the text)" if p else "")
        for r, (p, d) in config.SEED_RELATIONS.items()
    )
    return (
        f"Relations:\n{rels}\n\n"
        "Rules:\n"
        "- The subject and object are names as written in the text; resolve pronouns to the full name. "
        f"The paragraph is about \"{chunk['title']}\".\n"
        "- Extract only facts explicitly stated in the text; never infer from names or titles.\n"
        "- When a fact is about the paragraph's main subject, write the title exactly as the subject.\n"
        "- If a fact is not stated, leave the triple out; never write UNKNOWN or a placeholder. Return an empty list if there are none.\n"
        "- One triple per fact. Do not invent relations or facts.\n\n"
        f"Title: {chunk['title']}\nText: {chunk['text']}"
    )


def extract(chunk, max_tokens=config.EXTRACT_MAX_TOKENS):
    out = llm.call(config.EXTRACT_MODEL, build_prompt(chunk), system=SYSTEM, schema=SCHEMA, max_tokens=max_tokens, phase="ingest")
    return (out or {}).get("triples", [])  # a truncated or missing tool call counts as no triples


def request(chunk):
    return {"custom_id": f"c{abs(hash(chunk['title'])) % 10**12}", "prompt": build_prompt(chunk), "system": SYSTEM, "schema": SCHEMA, "max_tokens": config.EXTRACT_MAX_TOKENS}


def chunk_usage(chunk):
    return llm.cached_usage(config.EXTRACT_MODEL, build_prompt(chunk), system=SYSTEM, schema=SCHEMA, max_tokens=config.EXTRACT_MAX_TOKENS)


def batch_extract(chunks, size=2000):
    """Extract through the Message Batches API (50% price). Results land in the call cache, so the ingest loop
    that follows reads them at no cost."""
    for i in range(0, len(chunks), size):
        part = chunks[i : i + size]
        reqs = [dict(request(c), custom_id=f"r{j}") for j, c in enumerate(part)]
        bid, n = llm.submit_batch(reqs, "ingest")
        if not bid:
            continue
        print(f"  batch {bid}: {n} requests submitted, waiting...", flush=True)
        _, status = llm.collect_batch(bid, reqs, "ingest")
        print("  batch result:", status, flush=True)


def estimate(chunks, batch=False):
    """Tokens and USD for these chunks. Uses the observed tokens-per-character and output tokens per chunk
    from any chunks already extracted; falls back to a guess."""
    seen = [(c, chunk_usage(c)) for c in CORPUS_SAMPLE if chunk_usage(c)]
    chars = lambda c: len(SYSTEM) + len(build_prompt(c))
    if seen:
        per_char = sum(u[0] for _, u in seen) / sum(chars(c) for c, _ in seen)
        out_per = sum(u[1] for _, u in seen) / len(seen)
    else:
        per_char, out_per = 0.25, OUTPUT_TOKENS_GUESS
    in_tok = sum(chars(c) for c in chunks) * per_char
    out_tok = out_per * len(chunks)
    return in_tok, out_tok, llm.price(config.EXTRACT_MODEL, in_tok, out_tok, batch=batch)


MIN_CONFIDENCE = 0.6  # the extractor sometimes emits placeholder triples at confidence 0.0
PLACEHOLDERS = {"", "unknown", "n a", "na", "none", "null", "unspecified", "not stated", "not specified"}


def usable(t):
    """False for placeholders such as object '<UNKNOWN>' or confidence 0.0."""
    from src.graph import normalize

    if float(t.get("confidence", 0) or 0) < MIN_CONFIDENCE:
        return False
    return normalize(t.get("subject") or "") not in PLACEHOLDERS and normalize(t.get("object") or "") not in PLACEHOLDERS


def ingest_titles(g, corpus):
    """Phase A, no LLM: every paragraph becomes a Chunk, its title becomes the main Entity, and a MENTIONS edge
    links them. All titles exist before any extracted object is resolved, so objects can link to them."""
    ix = g.index
    if ix.d["titles_done"]:
        return 0
    chunks, mentions = [], []
    for c in corpus:
        title = c["title"]
        if title not in ix.d["chunks"]:
            ix.d["chunks"][title] = ix.new_id()
            ix.d["mention_rid"][title] = ix.new_id()
        eid = ix.add_title(title)
        ix.d["titles"][str(eid)] = ix.d["chunks"][title]
        chunks.append({"id": ix.d["chunks"][title], "title": title, "text": c["text"]})
        mentions.append({"rid": ix.d["mention_rid"][title], "c": ix.d["chunks"][title], "e": eid})
    ix.save()  # ids and names reach disk before any graph write, so a crash never reuses an id
    g.flush_entities()
    g.write_chunks(chunks)
    g.write_mentions(mentions)
    ix.d["titles_done"] = True
    ix.save()
    return len(chunks)


def is_main_subject(subject, title):
    """True when an extracted subject is the paragraph's own title ('Adolf Frederick' for
    'Adolf Frederick, King of Sweden'), so its edges attach to the title entity, not a duplicate."""
    forms = {normalize(title), normalize(strip_qualifier(title)), normalize(title.split(",")[0])}
    return normalize(subject) in forms


def ingest_chunk(g, chunk, triples):
    """Phase B: write one chunk's extracted facts. Entity-valued objects link to existing entities
    (exact name or alias, then qualifier-stripped) before a new entity is created."""
    ix = g.index
    chunk_id = ix.d["chunks"][chunk["title"]]
    main_id = ix.resolve(chunk["title"])

    edges, literals, seen = [], {}, set()
    for t in filter(usable, triples):
        rel = t.get("relation")
        subj, obj = (t.get("subject") or "").strip(), (t.get("object") or "").strip()
        if rel not in config.SEED_RELATIONS or not subj or not obj:
            continue
        s_id = main_id if is_main_subject(subj, chunk["title"]) else ix.entity_for(subj)[0]
        prop = config.SEED_RELATIONS[rel][0]
        conf = max(0.0, min(1.0, float(t.get("confidence", 0.5))))
        if prop:  # literal object: an attribute on the subject, never a node. First listed value wins:
            # the extractor sometimes files a death date under 'date of birth' after the birth date.
            literals.setdefault((s_id, prop), (obj, conf))
            continue
        d_id, _ = ix.entity_for(obj)
        if (s_id, d_id, rel) in seen:
            continue
        seen.add((s_id, d_id, rel))
        edges.append({"rid": ix.new_id(), "s": s_id, "d": d_id, "type": rel, "confidence": conf, "src_chunk": chunk_id, "created_iter": 0})

    extracted = [
        {"rid": ix.new_id(), "c": chunk_id, "t": ix.d["reltypes"][f"{config.ANCHOR_QTYPE}|{rel}"], "rel_type": rel}
        for rel in config.SEED_RELATIONS
    ]
    ix.save()

    g.flush_entities()
    g.clear_chunk(chunk_id)  # a retried chunk never duplicates its edges
    g.write_rel_edges(edges)
    for prop in config.LITERAL_PROPS:
        rows = []
        for (s, p), (v, _) in literals.items():
            if p == prop:
                n = normalize_literal(v)
                rows.append({"id": s, "value": v, "norm": n["norm"], "approx": n["approx"]})
        g.write_literals(prop, rows)
    g.write_extracted(extracted)
    return {"edges": len(edges), "literals": len(literals)}


def main():
    ap = argparse.ArgumentParser()
    grp = ap.add_mutually_exclusive_group(required=True)
    grp.add_argument("--batch-test", type=int, metavar="N", help="send N chunks (after the first 20) through the Batches API; cached, not ingested")
    grp.add_argument("--limit", type=int, help="ingest this many not-yet-ingested chunks")
    grp.add_argument("--all", action="store_true", help="ingest every remaining chunk")
    ap.add_argument("--estimate-only", action="store_true")
    ap.add_argument("--no-batch", action="store_true", help="with --all, use normal calls instead of the Batches API")
    ap.add_argument("--use-reserve", action="store_true", help="allow spending the $1 reserve")
    args = ap.parse_args()

    corpus = [json.loads(l) for l in open(config.SPLIT_DIR / "corpus.jsonl")]
    random.Random(42).shuffle(corpus)
    llm.set_use_reserve(args.use_reserve)
    CORPUS_SAMPLE[:] = corpus[:40]
    if args.batch_test:
        reqs = [dict(request(c), custom_id=f"t{j}") for j, c in enumerate(corpus[20 : 20 + args.batch_test])]
        pend = llm.pending_batches()
        if pend:  # an earlier run submitted a batch and never collected it: collect that one, do not submit again
            bid, n = next(iter(pend)), next(iter(pend.values()))["n"]
            print(f"resuming pending batch {bid} ({n} requests)", flush=True)
        else:
            bid, n = llm.submit_batch(reqs, "ingest")
            print(f"batch {bid}: {n} requests submitted (cached requests are skipped)", flush=True)
        if bid:
            _, status = llm.collect_batch(bid, reqs, "ingest")
            print("batch result:", status)
        llm.log_stats("batch-test")
        return
    done = set(json.loads(config.INGESTED_PATH.read_text())) if config.INGESTED_PATH.exists() else set()
    todo = [c for c in corpus if c["title"] not in done]
    batch = todo if args.all else todo[: args.limit]

    for label, cs, b in (("this run, normal calls", batch, False), ("all remaining, normal calls", todo, False), ("all remaining, Batches API", todo, True)):
        i, o, usd = estimate(cs, batch=b)
        print(f"estimate ({label}): {len(cs)} chunks, ~{i:,.0f} input + ~{o:,.0f} output tokens, ~${usd:.2f}")
    print(f"already ingested: {len(done)} / {len(corpus)}")
    if args.estimate_only or not batch:
        return

    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("ANTHROPIC_API_KEY is not set (put it in .env)")
    if args.all and not args.no_batch:
        batch_extract(batch)
    g = Graph()
    made = g.init_reltypes()
    if made:
        print(f"created {made} RelType nodes")
    n_titles = ingest_titles(g, corpus)
    if n_titles:
        print(f"wrote {n_titles} chunks and title entities")

    EXTRACTIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
    totals = {"edges": 0, "literals": 0}
    with ThreadPoolExecutor(config.LLM_WORKERS) as ex, open(EXTRACTIONS_PATH, "a") as log:
        for n, (chunk, triples) in enumerate(zip(batch, ex.map(extract, batch)), 1):
            res = ingest_chunk(g, chunk, triples)
            for k in totals:
                totals[k] += res[k]
            done.add(chunk["title"])
            config.INGESTED_PATH.write_text(json.dumps(sorted(done)))
            log.write(json.dumps({"title": chunk["title"], "triples": triples}, ensure_ascii=False) + "\n")
            log.flush()
            if n % 50 == 0 or n == len(batch):
                print(f"  {n}/{len(batch)} chunks, {totals['edges']} edges, {totals['literals']} literals")
    llm.log_stats("ingest")
    g.close()


if __name__ == "__main__":
    main()
