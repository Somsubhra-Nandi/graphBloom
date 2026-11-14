"""HydraDB smoke test for the Cypher features PLAN.md relies on.

Run: .venv/bin/python scripts/smoke_test.py
Needs the node from scripts/start_hydradb.sh. Exits non-zero if a required check fails.
Uses ids >= 9_000_000 so it can be rerun and cleans up after itself.
"""
import os
import sys

from neo4j import GraphDatabase

URI = os.environ.get("HYDRA_URI", "neo4j://127.0.0.1:7687")
TOKEN = os.environ.get("HYDRA_TOKEN", "local-development-token-32-bytes")

BASE = 9_000_000
A, B, C, D = BASE + 1, BASE + 2, BASE + 3, BASE + 4
R_AB, R_AC, R_AD = BASE + 11, BASE + 12, BASE + 13

results = []


def check(name, fn, required=True):
    try:
        detail = fn()
        results.append((name, True, detail or "", required))
        print(f"PASS  {name}" + (f"  [{detail}]" if detail else ""))
    except Exception as e:  # noqa: BLE001 - report any failure, keep going
        msg = str(e).replace("\n", " ")[:200]
        results.append((name, False, msg, required))
        print(f"{'FAIL' if required else 'WARN'}  {name}  -> {msg}")


def main():
    driver = GraphDatabase.driver(URI, auth=("neo4j", TOKEN))
    s = driver.session()

    def run(q, **p):
        return [r.data() for r in s.run(q, **p)]

    def cleanup():
        for q in (
            "UNWIND $v AS row MATCH (n {id: row.vertex}) DETACH DELETE n",
        ):
            try:
                run(q, v=[{"vertex": i} for i in (A, B, C, D, R_AB, R_AC, R_AD)])
            except Exception:
                pass

    cleanup()

    check("connect over Bolt", lambda: driver.verify_connectivity())

    def t_merge():
        up = "UNWIND $rows AS row MERGE (n {id: row.vertex}) SET n:Entity, n.name = row.name"
        run(up, rows=[{"vertex": A, "name": "alpha"}])
        run(up, rows=[{"vertex": A, "name": "alpha2"}])  # idempotent
        rows = run("MATCH (n:Entity {id: $id}) RETURN n.name AS name", id=A)
        assert rows == [{"name": "alpha2"}], rows
        return "UNWIND MERGE by id then SET, idempotent"

    check("MERGE + SET node (via UNWIND)", t_merge)

    def t_standalone_merge():
        run("MERGE (n {id: $id}) SET n.name = $name", id=A, name="x")

    check("standalone MERGE ... SET (no UNWIND)", t_standalone_merge, required=False)

    def t_unwind_nodes():
        rows = [{"vertex": i, "name": f"n{i}"} for i in (B, C, D)]
        run("UNWIND $rows AS row MERGE (n {id: row.vertex}) SET n:Entity, n.name = row.name", rows=rows)
        got = run("MATCH (n:Entity) WHERE n.id >= $lo AND n.id <= $hi RETURN n.id AS id ORDER BY id", lo=A, hi=D)
        assert [g["id"] for g in got] == [A, B, C, D], got
        return "4 nodes after batch"

    check("UNWIND batch node upsert", t_unwind_nodes)

    def t_unwind_edges():
        rows = [
            {"s": A, "d": B, "rid": R_AB, "type": "spouse", "conf": 0.9},
            {"s": A, "d": C, "rid": R_AC, "type": "director", "conf": 0.5},
            {"s": A, "d": D, "rid": R_AD, "type": "born_in", "conf": 0.7},
        ]
        run(
            "UNWIND $rows AS row MATCH (s:Entity {id: row.s}), (d:Entity {id: row.d}) "
            "MERGE (s)-[r:REL {id: row.rid}]->(d) SET r.type = row.type, r.confidence = row.conf",
            rows=rows,
        )
        got = run("MATCH (a:Entity {id: $a})-[r:REL]->(b) RETURN b.id AS id, r.type AS type", a=A)
        assert len(got) == 3, got
        return "3 REL edges with properties"

    check("UNWIND batch edge MERGE + SET props", t_unwind_edges)

    def t_set_rel():
        run("MATCH (a {id: $a})-[r:REL]->(b {id: $b}) SET r.confidence = 0.1, r.weight = 2.5", a=A, b=B)
        got = run("MATCH (a {id: $a})-[r:REL]->(b {id: $b}) RETURN r.confidence AS c, r.weight AS w", a=A, b=B)
        assert got == [{"c": 0.1, "w": 2.5}], got
        return "SET on relationship property"

    check("SET relationship property", t_set_rel)

    def t_order_limit():
        got = run(
            "MATCH (a:Entity {id: $a})-[r:REL]->(b) RETURN b.id AS id, r.confidence AS c ORDER BY c DESC LIMIT 2",
            a=A,
        )
        assert [g["id"] for g in got] == [D, C], got  # 0.7, 0.5 (B was lowered to 0.1)
        return "ORDER BY alias DESC LIMIT"

    check("ORDER BY alias + LIMIT", t_order_limit)

    def t_no_computed_order():
        # PLAN.md orders by RelType.weight * REL.confidence. Probe whether that works.
        run(
            "MATCH (a:Entity {id: $a})-[r:REL]->(b) RETURN b.id AS id, r.weight * r.confidence AS s ORDER BY s DESC",
            a=A,
        )
        return "computed ORDER BY works"

    check("computed score expression in RETURN/ORDER BY", t_no_computed_order, required=False)

    def t_prop_filter():
        got = run("MATCH (a:Entity {id: $a})-[r:REL]->(b) WHERE r.type = $t RETURN b.id AS id", a=A, t="born_in")
        assert [g["id"] for g in got] == [D], got
        return "WHERE on rel property"

    check("WHERE on relationship property", t_prop_filter)

    def t_name_lookup():
        got = run("MATCH (n:Entity {name: $n}) RETURN n.id AS id", n="n%d" % C)
        assert [g["id"] for g in got] == [C], got
        return "lookup by name property"

    check("MATCH by non-id property (name index)", t_name_lookup)

    def t_list_prop():
        run("MATCH (n:Entity {id: $id}) SET n.aliases = $al", id=A, al=["a1", "a2"])
        return run("MATCH (n:Entity {id: $id}) RETURN n.aliases AS al", id=A)[0]["al"] and "list property stored"

    check("list-valued property (aliases)", t_list_prop, required=False)

    def t_varlen():
        got = run("MATCH (a {id: $a})-[:REL*1..2]->(b) RETURN b.id AS id", a=A)
        assert len(got) >= 3, got
        return "bounded *1..2"

    check("variable-length path *1..2", t_varlen, required=False)

    def t_collect_count():
        got = run("MATCH (a {id: $a})-[r:REL]->(b) RETURN count(*) AS n", a=A)
        assert got == [{"n": 3}], got
        return "count(*)"

    check("count(*) aggregate", t_collect_count)

    cleanup()
    left = run("MATCH (n:Entity) WHERE n.id >= $lo RETURN count(*) AS n", lo=BASE)
    check("cleanup removed test nodes", lambda: None if left == [{"n": 0}] or left == [] else 1 / 0)

    s.close()
    driver.close()

    failed = [r for r in results if not r[1] and r[3]]
    warned = [r for r in results if not r[1] and not r[3]]
    print(f"\n{len(results) - len(failed) - len(warned)} passed, {len(failed)} failed, {len(warned)} optional unsupported")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
