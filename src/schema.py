"""The active schema: the relations the system currently extracts and the planner may use.

It starts as the 8 seed relations and grows during learning. Entity-valued relations become REL edges; date-valued
relations become attributes on the subject entity (a raw property, `<prop>_norm`, and `<prop>_approx`).
"""
import json
from pathlib import Path

from src import config
from src.graph import normalize


class ActiveSchema:
    def __init__(self, relations=None, history=None):
        # relation name -> {"prop": attribute name or None, "desc": text used in extraction prompts}
        self.relations = relations or {r: {"prop": p, "desc": d} for r, (p, d) in config.SEED_RELATIONS.items()}
        self.history = history or []  # [{"iteration": k, "relations": [...], "policy_reason": ...}]

    def names(self):
        return list(self.relations)

    def __contains__(self, rel):
        return self.canonical(rel) is not None

    def canonical(self, rel):
        """The schema's spelling of a relation name (case/punctuation-insensitive), or None."""
        n = normalize(rel)
        for r in self.relations:
            if normalize(r) == n:
                return r
        return None

    def literal_props(self):
        return sorted(v["prop"] for v in self.relations.values() if v["prop"])

    def prop_of(self, rel):
        c = self.canonical(rel)
        return self.relations[c]["prop"] if c else None

    def is_literal(self, rel):
        """A planned step that reads an attribute instead of following an edge."""
        c = self.canonical(rel)
        if c:
            return bool(self.relations[c]["prop"])
        n = normalize(rel)
        return n.startswith("date of ") or n.endswith(" date")  # a date-like relation not (yet) in the schema

    def add(self, rel, literal, iteration):
        prop = rel.replace(" ", "_") if literal else None
        desc = (
            f"the {rel} of the subject: a date, written as in the text" if literal
            else f"the subject's {rel}: the object is the entity that is the {rel} of the subject"
        )
        self.relations[rel] = {"prop": prop, "desc": desc}
        return prop

    def to_json(self):
        return {"relations": self.relations, "history": self.history}

    @classmethod
    def load(cls, path):
        path = Path(path)
        if path.exists():
            d = json.loads(path.read_text())
            return cls(d["relations"], d["history"])
        return cls()

    def save(self, path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_json(), indent=1))
