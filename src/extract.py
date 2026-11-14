"""Targeted extraction: pull chosen relations out of specific chunks, for repairs (feedback) and at query time.

One call = one chunk, the requested relation(s). The same prompt, confidence threshold (0.6) and placeholder
filter as the shallow ingest. Writes REL edges, date attributes, EXTRACTED edges and a Mutation node.
All graph writes happen under LOCK because the index (id counter, name dict) is not thread-safe.
"""
import threading

from src import config, llm
from src.graph import normalize, strip_qualifier
from src.literals import normalize_literal

LOCK = threading.Lock()
MIN_CONFIDENCE = 0.6
PLACEHOLDERS = {"", "unknown", "n a", "na", "none", "null", "unspecified", "not stated", "not specified"}
SYSTEM = "You extract facts from one Wikipedia paragraph into (subject, relation, object) triples. Use only the listed relations and only facts the text states."


def schema_json(relations):
    return {
        "type": "object",
        "properties": {
            "triples": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "subject": {"type": "string"},
                        "relation": {"type": "string", "enum": list(relations)},
                        "object": {"type": "string"},
                        "confidence": {"type": "number", "description": "0 to 1: how clearly the text states this fact"},
                    },
                    "required": ["subject", "relation", "object", "confidence"],
                },
            }
        },
        "required": ["triples"],
    }


def build_prompt(chunk, relations, schema):
    rels = "\n".join(f"- {r}: {schema.relations[r]['desc']}" for r in relations)
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


def request(chunk, relations, schema, custom_id):
    return {"custom_id": custom_id, "prompt": build_prompt(chunk, relations, schema), "system": SYSTEM,
            "schema": schema_json(relations), "max_tokens": config.EXTRACT_MAX_TOKENS}


def extract(chunk, relations, schema, phase):
    out = llm.call(config.EXTRACT_MODEL, build_prompt(chunk, relations, schema), system=SYSTEM, schema=schema_json(relations),
                   max_tokens=config.EXTRACT_MAX_TOKENS, phase=phase)
    return (out or {}).get("triples", [])


def usable(t):
    if float(t.get("confidence", 0) or 0) < MIN_CONFIDENCE:
        return False
    return normalize(t.get("subject") or "") not in PLACEHOLDERS and normalize(t.get("object") or "") not in PLACEHOLDERS


def is_main_subject(subject, title):
    forms = {normalize(title), normalize(strip_qualifier(title)), normalize(title.split(",")[0])}
    return normalize(subject) in forms


def chunks_of_entity(g, entity_id):
    """The entity's own paragraph(s): chunks with a MENTIONS edge to it."""
    return g.read("MATCH (c:Chunk)-[r:MENTIONS]->(e:Entity {id: $id}) RETURN c.id AS id, c.title AS title, c.text AS text", id=entity_id)


def is_extracted(g, chunk_id, relation):
    return g.read("MATCH (c:Chunk {id: $c})-[r:EXTRACTED {rel_type: $rt}]->(t:RelType) RETURN count(*) AS n", c=chunk_id, rt=relation)[0]["n"] > 0


def apply(g, chunk, relations, triples, schema, iteration, question_id, kind):
    """Write extracted triples for `relations` from `chunk`. Caller holds LOCK. Returns (edges, literals)."""
    ix = g.index
    edges, literals, seen = [], {}, set()
    main_id = ix.resolve(chunk["title"])
    for t in filter(usable, triples):
        rel = schema.canonical(t.get("relation") or "")
        subj, obj = (t.get("subject") or "").strip(), (t.get("object") or "").strip()
        if rel not in relations or not subj or not obj:
            continue
        s_id = main_id if is_main_subject(subj, chunk["title"]) else ix.entity_for(subj)[0]
        prop = schema.relations[rel]["prop"]
        conf = max(0.0, min(1.0, float(t.get("confidence", 0.5))))
        if prop:
            literals.setdefault((s_id, prop), obj)  # first listed value wins
            continue
        d_id, _ = ix.entity_for(obj)
        if (s_id, d_id, rel) in seen:
            continue
        seen.add((s_id, d_id, rel))
        edges.append({"rid": ix.new_id(), "s": s_id, "d": d_id, "type": rel, "confidence": conf, "src_chunk": chunk["id"], "created_iter": iteration})
    for rel in relations:
        g.ensure_reltypes(rel)
    extracted = [{"rid": ix.new_id(), "c": chunk["id"], "t": ix.d["reltypes"][f"{config.ANCHOR_QTYPE}|{rel}"], "rel_type": rel} for rel in relations]
    mut = {"id": ix.new_id(), "iter": iteration, "kind": kind, "question_id": question_id or "",
           "reason": f"{', '.join(relations)} from chunk '{chunk['title']}': {len(edges)} edges, {len(literals)} date values"}
    ix.save()

    g.flush_entities()
    g.write_rel_edges(edges)
    n_lit = 0
    for prop in {p for (_, p) in literals}:
        rows = []
        for (s, p), v in literals.items():
            if p != prop:
                continue
            cur = g.read(f"MATCH (n:Entity {{id: $id}}) RETURN n.{prop} AS v", id=s)
            if cur and cur[0]["v"]:
                continue  # never overwrite a value that is already there
            nl = normalize_literal(v)
            rows.append({"id": s, "value": v, "norm": nl["norm"], "approx": nl["approx"]})
        g.write_literals(prop, rows)
        n_lit += len(rows)
    g.write_extracted(extracted)
    g.write_mutations([mut])
    return len(edges), n_lit


def extract_and_apply(g, chunk, relation, schema, iteration, question_id, kind, phase):
    """Skip if the relation was already extracted from this chunk; otherwise one call and one write."""
    with LOCK:
        if is_extracted(g, chunk["id"], relation):
            return None
        triples = extract(chunk, [relation], schema, phase)
        return apply(g, chunk, [relation], triples, schema, iteration, question_id, kind)


class QueryTimeExtractor:
    """At most `budget` targeted extraction calls per query, on the entity's own chunks, for the relation the
    planner asked for, which must be in the active schema. Skips chunks that already have an EXTRACTED edge."""

    def __init__(self, g, schema, iteration, budget=config.QUERY_EXTRACT_BUDGET, phase="learning"):
        self.g, self.schema, self.iteration, self.budget, self.phase = g, schema, iteration, budget, phase

    def __call__(self, events, question_id):
        performed, left = [], self.budget
        for ev in events:
            rel = self.schema.canonical(ev["relation"])
            if rel is None or left <= 0:
                continue
            for ch in chunks_of_entity(self.g, ev["entity_id"]):
                if left <= 0:
                    break
                res = extract_and_apply(self.g, ch, rel, self.schema, self.iteration, question_id, "query_extraction", self.phase)
                if res is not None:  # a call was made
                    left -= 1
                    performed.append({"chunk": ch["title"], "relation": rel, "edges": res[0], "literals": res[1]})
        return performed
