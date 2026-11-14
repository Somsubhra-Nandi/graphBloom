"""Query pipeline: plan -> resolve seeds -> weighted beam traversal -> answer, with a JSON trace.

Cypher cannot order by a computed expression, so each hop fetches candidate edges with
`ORDER BY r.confidence DESC LIMIT 200` and Python scores them as RelType.weight x REL.confidence.
The extraction budget is not implemented yet: when a branch of the planned chain dead-ends, the trace records it.
"""
from src import config, llm
from src.graph import Graph, normalize

PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "seeds": {"type": "array", "items": {"type": "string"}, "description": "entity names the question starts from"},
        "question_type": {"type": "string", "enum": config.QUESTION_TYPES},
        "relation_chain": {"type": "array", "items": {"type": "string"}, "description": "relations to follow, in order, at most 3"},
    },
    "required": ["seeds", "question_type", "relation_chain"],
}
PLAN_SYSTEM = "You plan how to answer a multi-hop question over a knowledge graph of Wikipedia entities."
ANSWER_SCHEMA = {
    "type": "object",
    "properties": {"reasoning": {"type": "string", "description": "one sentence"}, "answer": {"type": "string"}},
    "required": ["reasoning", "answer"],
}

# Relations whose value is a date stored as an attribute on the entity, not an edge.
LITERAL_RELATIONS = {normalize(r) for r, (p, _) in config.SEED_RELATIONS.items() if p}


def is_literal_step(rel):
    n = normalize(rel)
    return n in LITERAL_RELATIONS or n.startswith("date of ") or n.endswith(" date")


def plan_prompt(question):
    return (
        f"Question: {question}\n\n"
        "Return:\n"
        "- seeds: the named entities the question starts from (one for a lookup chain, two for a comparison). Use the names as written in the question.\n"
        "- question_type: comparison (compare an attribute of two entities), inference (a relation chain such as grandparent via father or mother), "
        "compositional (an attribute of an entity reached through another relation, e.g. the mother of the director of a film), "
        "bridge_comparison (compare an attribute of entities reached through a bridge, e.g. which film's director was born earlier).\n"
        "- relation_chain: the relations to follow from the seed(s), in order, at most 3. The graph stores exactly these relation names: "
        + ", ".join(config.SEED_RELATIONS)
        + ". When a step is one of them, write it exactly as listed. For any other step use a short lowercase relation name of your own "
        "(for example father, mother, spouse, place of death, date of death). For comparison questions give the attribute being compared."
    )


def build_answer_prompt(question, path_lines, attr_lines, chunks):
    """Shared by every system (static graph, vector only, and later runs) so answers are comparable."""
    return (
        f"Question: {question}\n\nGraph paths:\n" + ("\n".join(path_lines) or "(none)")
        + "\n\nEntity attributes:\n" + ("\n".join(attr_lines) or "(none)")
        + "\n\nSource paragraphs:\n" + ("\n".join(f"[{c['title']}] {c['text']}" for c in chunks) or "(none)")
        + "\n\n" + config.ANSWER_INSTRUCTION
    )


def answer_from_prompt(prompt, phase):
    out = llm.call(config.ANSWER_MODEL, prompt, system=config.ANSWER_SYSTEM, schema=ANSWER_SCHEMA, max_tokens=config.ANSWER_MAX_TOKENS, phase=phase) or {}
    return out.get("answer", ""), out.get("reasoning", "")


class QueryEngine:
    def __init__(self, graph=None, phase="smoke"):
        self.phase = phase
        self.g = graph or Graph()
        self.weights = {}
        self.load_weights()
        self._chunk_cache = {}

    def load_weights(self):
        """RelType weights into a Python dict once; the learning loop writes them back at the end of an iteration."""
        rows = self.g.read("MATCH (n:RelType) RETURN n.qtype AS qtype, n.name AS name, n.weight AS weight")
        self.weights = {(r["qtype"], r["name"]): r["weight"] for r in rows}

    def weight(self, qtype, rel):
        return self.weights.get((qtype, rel), 1.0)

    # ---- traversal -----------------------------------------------------------
    def fetch_edges(self, node_ids):
        """Out-edges of each frontier node, highest confidence first. A list-of-maps parameter is accepted
        only by write batches, so reads take one call per frontier node (at most BEAM_K per seed per hop)."""
        out = {}
        for i in node_ids:
            out[i] = self.g.read(
                "MATCH (a:Entity {id: $id})-[r:REL]->(b:Entity) "
                "RETURN b.id AS bid, b.name AS bname, r.type AS type, r.confidence AS conf, r.src_chunk AS chunk "
                "ORDER BY conf DESC LIMIT %d" % config.FETCH_LIMIT,
                id=i,
            )
        return out

    def beam(self, seed_ids, qtype, chain):
        """Weighted beam over the edge steps of the planned chain. Literal steps (a date held as an attribute)
        are not traversed. A dead end is recorded only for a path that has followed the planned chain so far
        and has no edge of the next planned relation; leaves and literal steps do not count."""
        steps = [normalize(c) for c in chain if not is_literal_step(c)][: config.MAX_HOPS]
        terminal, dead_ends, final = [], [], []
        for sid, sname in seed_ids:
            frontier = [{"nodes": [(sid, sname)], "edges": [], "score": 1.0}]
            for h, expected in enumerate(steps):
                edges = self.fetch_edges(sorted({p["nodes"][-1][0] for p in frontier}))
                cand = []
                for p in frontier:
                    last = p["nodes"][-1]
                    visited = {n[0] for n in p["nodes"]}
                    ext = [e for e in edges.get(last[0], []) if e["bid"] not in visited]
                    on_chain = [normalize(e["type"]) for e in p["edges"]] == steps[:h]
                    if on_chain and not any(normalize(e["type"]) == expected for e in ext):
                        dead_ends.append({"hop": h, "entity_id": last[0], "entity": last[1], "expected_relation": expected})
                    if not ext:
                        if p["edges"]:
                            terminal.append(p)
                        continue
                    for e in ext:
                        boost = config.CHAIN_BOOST if normalize(e["type"]) == expected else 1.0
                        score = p["score"] * self.weight(qtype, e["type"]) * e["conf"] * boost
                        cand.append(
                            {
                                "nodes": p["nodes"] + [(e["bid"], e["bname"])],
                                "edges": p["edges"] + [{"type": e["type"], "confidence": e["conf"], "chunk": e["chunk"]}],
                                "score": score,
                            }
                        )
                frontier = sorted(cand, key=lambda p: -p["score"])[: config.BEAM_K]
                if not frontier:
                    break
            final += frontier
        allp = final + terminal
        allp.sort(key=lambda p: (-p["score"], [n[0] for n in p["nodes"]]))  # stable order for a stable answer prompt
        return allp, dead_ends

    # ---- context for the answer ---------------------------------------------
    def attributes(self, entity_ids):
        """Date attributes per entity: raw text, ISO form, approximate flag."""
        cols = ", ".join(f"n.{p} AS {p}, n.{p}_norm AS {p}_norm, n.{p}_approx AS {p}_approx" for p in config.LITERAL_PROPS)
        out = {}
        for i in entity_ids:
            rows = self.g.read(f"MATCH (n:Entity {{id: $id}}) RETURN {cols}", id=i)
            row, attrs = (rows[0] if rows else {}), {}
            for p in config.LITERAL_PROPS:
                if row.get(p):
                    attrs[p] = {"raw": row[p], "iso": row.get(f"{p}_norm") or "", "approx": bool(row.get(f"{p}_approx"))}
            if attrs:
                out[i] = attrs
        return out

    @staticmethod
    def attr_text(a):
        s = f"{a['raw']}"
        if a["iso"]:
            s += f" [ISO {a['iso']}{', approximate' if a['approx'] else ''}]"
        return s

    def chunk(self, chunk_id):
        if chunk_id not in self._chunk_cache:
            rows = self.g.read("MATCH (c:Chunk {id: $id}) RETURN c.title AS title, c.text AS text", id=chunk_id)
            self._chunk_cache[chunk_id] = rows[0] if rows else {"title": "", "text": ""}
        return self._chunk_cache[chunk_id]

    # ---- the pipeline --------------------------------------------------------
    def answer(self, question):
        plan = llm.call(config.EXTRACT_MODEL, plan_prompt(question), system=PLAN_SYSTEM, schema=PLAN_SCHEMA, max_tokens=config.PLAN_MAX_TOKENS, phase=self.phase)
        qtype, chain = plan["question_type"], plan["relation_chain"][: config.MAX_HOPS]
        resolved, unresolved = [], []
        for name in plan["seeds"]:
            i = self.g.index.resolve(name)
            (resolved if i is not None else unresolved).append((i, name) if i is not None else name)
        seeds = [(i, self.g.index.d["display"].get(str(i), n)) for i, n in resolved]

        trace = {"question": question, "plan": plan, "seeds": [{"name": n, "id": i} for i, n in seeds], "unresolved_seeds": unresolved}
        if not seeds:
            trace.update(paths=[], dead_ends=[], chunks=[], attributes={}, answer="", note="no seed resolved", run_params=config.run_params())
            return trace

        paths, dead_ends = self.beam(seeds, qtype, chain)
        ent_ids = sorted({n[0] for p in paths for n in p["nodes"]} | {i for i, _ in seeds})
        attrs = self.attributes(ent_ids)
        chunk_ids = []  # in path-score order, first appearance, at most ANSWER_MAX_CHUNKS
        for p in paths:
            for e in p["edges"]:
                if e["chunk"] not in chunk_ids:
                    chunk_ids.append(e["chunk"])
        chunk_ids = chunk_ids[: config.ANSWER_MAX_CHUNKS]
        chunks = {c: self.chunk(c) for c in chunk_ids}

        lines = []
        for p in paths:
            hops = "".join(f" -[{e['type']}]-> {n[1]}" for e, n in zip(p["edges"], p["nodes"][1:]))
            lines.append(f"- {p['nodes'][0][1]}{hops}")
        attr_lines = [
            f"- {self.g.index.d['display'].get(str(i), i)}: " + ", ".join(f"{k.replace('_', ' ')} = {self.attr_text(v)}" for k, v in sorted(a.items()))
            for i, a in sorted(attrs.items())
        ]
        prompt = build_answer_prompt(question, lines, attr_lines, list(chunks.values()))
        answer, reasoning = answer_from_prompt(prompt, self.phase)
        trace.update(
            paths=[{"nodes": [{"id": i, "name": n} for i, n in p["nodes"]], "edges": p["edges"], "score": round(p["score"], 4)} for p in paths],
            dead_ends=dead_ends,
            chunks=[{"id": c, "title": v["title"]} for c, v in chunks.items()],
            attributes={str(k): v for k, v in attrs.items()},
            answer=answer,
            reasoning=reasoning,
            run_params=config.run_params(),
        )
        return trace
