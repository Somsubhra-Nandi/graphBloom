"""Failure classifier for the feedback questions. It reads gold evidence, so it works on feedback only and
never opens heldout.jsonl.

Classes, in precedence order:
  entity_gap      a seed the planner named does not resolve to a node
  extraction_gap  a gold triple has no matching edge or date attribute in the graph
  ranking_gap     every gold triple is in the graph but not on the beam's retrieved paths
  reasoning_gap   the evidence was retrieved and the answer is still wrong (only when the question was re-answered)
Other labels: correct (answered, exact match), evidence_present (graph-only iterations, evidence is in the graph).

Triples are matched by endpoints, not by relation name: a gold (subject, relation, object) is present when the graph
has any REL edge between the two entities (objects resolve through the name/alias index and the demonym map), or,
for a date object, when the subject's attribute for that relation has the same normalized (ISO) value.
"""
from collections import Counter, defaultdict

from src import config
from src.countries import canonical_country
from src.literals import normalize_literal

FEEDBACK_PATH = config.SPLIT_DIR / "feedback.jsonl"  # the only question file this module reads


def load_feedback():
    return [__import__("json").loads(l) for l in open(FEEDBACK_PATH)]


class Diagnoser:
    def __init__(self, g, schema):
        self.g, self.schema = g, schema

    def resolve(self, name):
        i = self.g.index.resolve(name)
        if i is None:
            canon = canonical_country(name)
            i = self.g.index.resolve(canon) if canon else None
        return i

    def triple_status(self, s, rel, o):
        """(present, why_missing). `rel` is the gold relation name."""
        sid = self.resolve(s)
        if sid is None:
            return False, "subject_unresolved"
        gold_norm = normalize_literal(o)["norm"]
        if gold_norm:  # a date object
            prop = self.schema.prop_of(rel)
            if not prop:
                return False, "relation_not_in_schema"
            row = self.g.read(f"MATCH (n:Entity {{id: $id}}) RETURN n.{prop}_norm AS v", id=sid)
            return (True, None) if row and row[0]["v"] == gold_norm else (False, "date_missing")
        oid = self.resolve(o)
        if oid is None:
            return False, "object_unresolved"
        edge = self.g.read("MATCH (a:Entity {id: $a})-[r:REL]->(b:Entity {id: $b}) RETURN count(*) AS n", a=sid, b=oid)
        return (True, None) if edge[0]["n"] else (False, "no_edge")

    def covered_by_paths(self, s, o, paths, seed_ids):
        sid = self.resolve(s)
        if normalize_literal(o)["norm"]:  # a date: the subject entity just has to be on a retrieved path
            return sid in seed_ids or any(sid == n["id"] for p in paths for n in p["nodes"])
        oid = self.resolve(o)
        return any((a["id"], b["id"]) == (sid, oid) for p in paths for a, b in zip(p["nodes"], p["nodes"][1:]))

    def diagnose(self, q, trace=None, answered=False, em=None):
        """trace: a QueryEngine trace (answered iterations) or None for graph-only iterations."""
        assert "evidences" in q, "diagnosis needs gold evidence, which only feedback questions carry"
        gold = [tuple(t) for t in q["evidences"]]
        missing = []
        for s, rel, o in gold:
            ok, why = self.triple_status(s, rel, o)
            if not ok:
                missing.append({"triple": [s, rel, o], "relation": rel, "why": why})
        row = {"id": q["_id"], "type": q["type"], "answered": answered, "em": em, "missing": missing,
               "missing_relations": sorted({m["relation"] for m in missing})}
        if trace is not None and trace.get("unresolved_seeds"):
            cls = "entity_gap"
        elif trace is None:
            firsts = {s for s, _, _ in gold} - {o for _, _, o in gold}  # gold subjects that are not another triple's object
            cls = "entity_gap" if any(self.resolve(s) is None for s in firsts) else None
        else:
            cls = None
        if cls is None and missing:
            cls = "extraction_gap"
        if cls is None:
            if trace is not None:
                seed_ids = {s["id"] for s in trace["seeds"]}
                covered = all(self.covered_by_paths(s, o, trace["paths"], seed_ids) for s, _, o in gold)
                row["covered"] = covered
                cls = "ranking_gap" if not covered else None
            if cls is None:
                cls = "evidence_present" if not answered else ("correct" if em == 1 else "reasoning_gap")
        if answered and em == 1:
            row["gap_if_wrong"] = cls  # kept for information; a correct answer is not a failure
            cls = "correct"
        row["class"] = cls
        return row


def summarize(rows):
    """Counts of each class, overall and by question type."""
    by_type = defaultdict(Counter)
    for r in rows:
        by_type[r["type"]][r["class"]] += 1
    return {"overall": dict(Counter(r["class"] for r in rows)), "by_type": {k: dict(v) for k, v in sorted(by_type.items())},
            "questions_with_missing_gold_triples": sum(1 for r in rows if r["missing"]),
            "missing_relations": dict(Counter(m for r in rows for m in r["missing_relations"]).most_common())}
