"""Mutation nodes: provenance for every change the learning loop makes. Read from HydraDB or from an export."""
import json
import re


def parse_relation(kind, reason):
    if kind == "schema_growth":
        m = re.search(r"added '([^']+)'", reason or "")
        return m.group(1) if m else ""
    return (reason or "").split(" from chunk")[0]


def from_graph(g):
    rows = g.read("MATCH (n:Mutation) RETURN n.id AS id, n.iter AS iteration, n.kind AS kind, n.reason AS reason, n.question_id AS question_id")
    for r in rows:
        r["relation"] = parse_relation(r["kind"], r["reason"])
    return sorted(rows, key=lambda r: r["id"])


def export(g, path):
    rows = from_graph(g)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
    return len(rows)
