"""HydraDB graph layer.

Constraints from the v0.4.0 smoke test (see PLAN.md, "Smoke test findings"):
- every write is an UNWIND batch, and `write(query, rows)` is the only place write Cypher is run;
- node ids are non-negative integers from a persisted counter;
- name and alias lookup is a Python dict persisted to data/state/index.json;
- IS NULL / IN / CONTAINS are unavailable, so every property is always written with a default.
"""
import json
import os
import re
import unicodedata

from neo4j import GraphDatabase

from src import config

BATCH = 500
_PUNCT = re.compile(r"[^\w\s]", re.UNICODE)
_PAREN = re.compile(r"\s*\([^)]*\)\s*$")
_WRITE_WORDS = re.compile(r"\b(MERGE|CREATE|SET|DELETE|REMOVE)\b", re.I)


_TRANSLIT = str.maketrans({"ł": "l", "đ": "d", "ø": "o", "ı": "i", "ß": "ss", "æ": "ae", "œ": "oe", "þ": "th", "ð": "d"})


def normalize(name):
    """casefold, drop accents, strip punctuation, collapse whitespace. Used only for lookup."""
    s = unicodedata.normalize("NFKD", name.casefold().translate(_TRANSLIT))
    s = "".join(c for c in s if not unicodedata.combining(c))
    return " ".join(_PUNCT.sub(" ", s).split())


def strip_qualifier(name):
    """'Polish-Russian War (film)' -> 'Polish-Russian War'."""
    return _PAREN.sub("", name).strip()


class Index:
    """Persisted dicts: normalized name/alias -> id, id -> display name, plus the id counter."""

    def __init__(self, path=config.INDEX_PATH):
        self.path = path
        self.d = {
            "next_id": 1, "names": {}, "aliases": {}, "ambiguous": [], "display": {}, "chunks": {}, "mention_rid": {},
            "titles": {}, "titles_done": False, "reltypes": {}, "pending": {},
        }
        if path.exists():
            self.d.update(json.loads(path.read_text()))

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.d, ensure_ascii=False, separators=(",", ":")))
        os.replace(tmp, self.path)

    def new_id(self):
        i = self.d["next_id"]
        self.d["next_id"] += 1
        return i

    def resolve(self, name):
        """Return the entity id for a name or alias, or None. Tries the full name, then without a qualifier."""
        for cand in (name, strip_qualifier(name)):
            n = normalize(cand)
            if n in self.d["names"]:
                return self.d["names"][n]
            if n in self.d["aliases"]:
                return self.d["aliases"][n]
        return None

    def add_alias(self, entity_id, alias):
        n = normalize(alias)
        if n and n not in self.d["names"] and n not in self.d["aliases"] and n not in self.d["ambiguous"]:
            self.d["aliases"][n] = entity_id
            return True
        return False

    def _qualifier_alias(self, entity_id, name):
        """Register `name` minus a '(film)'-style qualifier as an alias. If another entity already owns that
        alias it is ambiguous ('John Smith (actor)' vs '(footballer)'), so nobody gets it: a wrong link is worse
        than a new entity."""
        s = normalize(strip_qualifier(name))
        if not s or s == normalize(name) or s in self.d["names"] or s in self.d["ambiguous"]:
            return
        owner = self.d["aliases"].get(s)
        if owner is None:
            self.d["aliases"][s] = entity_id
        elif owner != entity_id:
            del self.d["aliases"][s]
            self.d["ambiguous"].append(s)

    def add_title(self, title):
        """Create (or find, by exact normalized name) the entity for a paragraph title. Titles are distinct
        pages, so they never merge through a qualifier-stripped match. Returns the entity id."""
        n = normalize(title)
        if n in self.d["names"]:
            return self.d["names"][n]
        self.d["aliases"].pop(n, None)  # a real title outranks an earlier qualifier-stripped alias
        i = self.new_id()
        self.d["names"][n] = i
        self.d["display"][str(i)] = title
        self.d["pending"][str(i)] = {"id": i, "name": title}
        self._qualifier_alias(i, title)
        return i

    def entity_for(self, name):
        """Resolve `name` or allocate a new entity (staged as pending until flushed). Returns (id, is_new)."""
        found = self.resolve(name)
        if found is not None:
            self.add_alias(found, name)  # keep the other spelling resolvable
            return found, False
        i = self.new_id()
        self.d["names"][normalize(name)] = i
        self.d["display"][str(i)] = name
        self._qualifier_alias(i, name)
        self.d["pending"][str(i)] = {"id": i, "name": name}
        return i, True


class Graph:
    def __init__(self, index=None):
        self.driver = GraphDatabase.driver(config.HYDRA_URI, auth=("neo4j", config.HYDRA_TOKEN))
        self.index = index or Index()
        self._reconcile_counter()

    def close(self):
        self.driver.close()

    # ---- the only write path -------------------------------------------------
    def write(self, query, rows):
        """Run `UNWIND $rows AS row <query>` in batches. `query` is the body after the UNWIND."""
        if not rows:
            return
        if not re.match(r"\s*(MERGE|MATCH|CREATE)\b", query):
            raise ValueError("write body must start with MERGE, MATCH or CREATE")
        with self.driver.session() as s:
            for i in range(0, len(rows), BATCH):
                s.run("UNWIND $rows AS row " + query, rows=rows[i : i + BATCH]).consume()

    def read(self, query, **params):
        if _WRITE_WORDS.search(query):
            raise ValueError("read() cannot run write Cypher; use write()")
        with self.driver.session() as s:
            return [r.data() for r in s.run(query, **params)]

    # ---- counter safety ------------------------------------------------------
    def _reconcile_counter(self):
        """If the index file is behind the graph (crash, lost file), never reuse an id that exists."""
        top = 0
        for label in ("Entity", "Chunk", "RelType", "Mutation"):  # a node-only MATCH needs a label
            rows = self.read(f"MATCH (n:{label}) RETURN n.id AS id ORDER BY id DESC LIMIT 1")
            if rows and rows[0]["id"] is not None:
                top = max(top, rows[0]["id"])
        if top >= self.index.d["next_id"]:
            self.index.d["next_id"] = top + 1

    # ---- typed write helpers (all go through write()) ------------------------
    def flush_entities(self):
        """Write entities staged by Index.entity_for. Each carries every property with its default."""
        pending = list(self.index.d["pending"].values())
        if not pending:
            return
        cols = [c for p in config.LITERAL_PROPS for c in (p, f"{p}_norm", f"{p}_approx")]
        props = "".join(f", n.{c} = row.{c}" for c in cols)
        rows = []
        for e in pending:
            row = {"id": e["id"], "name": e["name"], "aliases": "", "type": ""}
            row.update({c: (False if c.endswith("_approx") else "") for c in cols})
            rows.append(row)
        self.write("MERGE (n {id: row.id}) SET n:Entity, n.name = row.name, n.aliases = row.aliases, n.type = row.type" + props, rows)
        self.index.d["pending"] = {}
        self.index.save()

    def write_literals(self, prop, rows):
        """rows: {id, value, norm, approx}. Sets a date attribute on existing entities: the raw string, its
        normalized form (src/literals.py) in `<prop>_norm`, and `<prop>_approx` for 'c. 1732'."""
        if prop not in config.LITERAL_PROPS:
            raise ValueError(prop)
        self.write(
            f"MERGE (n {{id: row.id}}) SET n:Entity, n.{prop} = row.value, n.{prop}_norm = row.norm, n.{prop}_approx = row.approx", rows
        )

    def write_aliases(self, rows):
        """rows: {id, aliases}. `aliases` is the '|'-joined alias string kept on the entity for display."""
        self.write("MERGE (n {id: row.id}) SET n:Entity, n.aliases = row.aliases", rows)

    def load_edges(self):
        """Every REL edge as {s, d, t, c, chunk, it}. An edge's own id cannot be projected in a read."""
        return self.read(
            "MATCH (a:Entity)-[r:REL]->(b:Entity) RETURN a.id AS s, b.id AS d, r.type AS t, r.confidence AS c, r.src_chunk AS chunk, r.created_iter AS it"
        )

    def commit_edges(self, old, new):
        """Make the graph's REL edges equal `new`, given `old` (what load_edges returned). A delete can only
        target an endpoint pair (all REL edges between two nodes), so every pair whose edges differ is deleted
        and its desired edges are written again with fresh ids. Returns (pairs rewritten, edges written)."""
        def by_pair(edges):
            out = {}
            for e in edges:
                out.setdefault((e["s"], e["d"]), []).append((e["t"], e["c"], e["chunk"], e["it"]))
            return {k: sorted(v, key=str) for k, v in out.items()}

        o, n = by_pair(old), by_pair(new)
        changed = [k for k in set(o) | set(n) if o.get(k) != n.get(k)]
        self.write("MATCH (a {id: row.s})-[r:REL]->(b {id: row.d}) DELETE r", [{"s": s, "d": d} for s, d in changed if (s, d) in o])
        rows = [
            {"rid": self.index.new_id(), "s": s, "d": d, "type": t, "confidence": c, "src_chunk": ch, "created_iter": it}
            for s, d in changed
            for t, c, ch, it in n.get((s, d), [])
        ]
        self.index.save()
        self.write_rel_edges(rows)
        return len(changed), len(rows)

    def delete_nodes(self, ids):
        self.write("MATCH (n {id: row.id}) DETACH DELETE n", [{"id": i} for i in ids])

    def write_chunks(self, rows):
        self.write("MERGE (n {id: row.id}) SET n:Chunk, n.title = row.title, n.text = row.text", rows)

    def write_mentions(self, rows):
        self.write("MATCH (c:Chunk {id: row.c}), (e:Entity {id: row.e}) MERGE (c)-[r:MENTIONS {id: row.rid}]->(e) SET r.chunk = row.c", rows)

    def write_rel_edges(self, rows):
        """rows: {rid, s, d, type, confidence, src_chunk, created_iter}."""
        self.write(
            "MATCH (s:Entity {id: row.s}), (d:Entity {id: row.d}) MERGE (s)-[r:REL {id: row.rid}]->(d) "
            "SET r.type = row.type, r.confidence = row.confidence, r.src_chunk = row.src_chunk, r.created_iter = row.created_iter",
            rows,
        )

    def write_extracted(self, rows):
        """rows: {rid, c, t, rel_type}. Marks relation `rel_type` as attempted on chunk c."""
        self.write("MATCH (c:Chunk {id: row.c}), (t:RelType {id: row.t}) MERGE (c)-[r:EXTRACTED {id: row.rid}]->(t) SET r.rel_type = row.rel_type, r.chunk = row.c", rows)

    def write_reltypes(self, rows):
        self.write("MERGE (n {id: row.id}) SET n:RelType, n.name = row.name, n.qtype = row.qtype, n.weight = row.weight, n.blame_count = row.blame_count", rows)

    def clear_chunk(self, chunk_id):
        """Delete what a previous, partial extraction of this chunk wrote, so a retry never duplicates edges.
        UNWIND deletes only accept a relationship-property filter, so each edge type carries its chunk id."""
        row = [{"c": chunk_id}]
        self.write("MATCH ()-[r:REL {src_chunk: row.c}]->() DELETE r", row)
        self.write("MATCH ()-[r:EXTRACTED {chunk: row.c}]->() DELETE r", row)

    # ---- schema --------------------------------------------------------------
    def init_reltypes(self):
        """One RelType per (question type, relation) with weight 1.0, plus one anchor per relation for EXTRACTED."""
        rows = []
        for rel in config.SEED_RELATIONS:
            for qt in config.QUESTION_TYPES + [config.ANCHOR_QTYPE]:
                key = f"{qt}|{rel}"
                if key not in self.index.d["reltypes"]:
                    i = self.index.new_id()
                    self.index.d["reltypes"][key] = i
                    rows.append({"id": i, "name": rel, "qtype": qt, "weight": 1.0, "blame_count": 0})
        self.index.save()
        self.write_reltypes(rows)
        return len(rows)
