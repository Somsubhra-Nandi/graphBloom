"""Load test: 50 concurrent queries while a repair-style write batch is running. Reports p50 / p95 latency.

  .venv/bin/python scripts/load_test.py
Queries are the first 50 held-out questions through the full pipeline (planner, beam, attributes, answer) with the
LLM replaced by cache lookups, so the numbers are the graph path's latency and cost no money; a cache miss is
counted as an error. The writer thread writes batches of throwaway nodes and edges (ids from 9,500,000) in the
same shape as the repair writes, and everything it wrote is deleted at the end.
"""
import json
import statistics
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from src import config, llm  # noqa: E402
from src.graph import Graph  # noqa: E402
from src.query import QueryEngine  # noqa: E402
from src.schema import ActiveSchema  # noqa: E402
import learn  # noqa: E402

CONCURRENCY, ROUNDS, BASE = 50, 15, 9_500_000


def cache_only():
    def call(model, prompt, system="", schema=None, max_tokens=1024, temperature=0.0, *, phase):
        hit, res = llm.cache_lookup(model, prompt, system, schema, max_tokens, temperature)
        if not hit:
            raise RuntimeError("cache miss")
        return res

    llm.call = call


def pct(xs, p):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(p / 100 * (len(xs) - 1))))]


def stats(lat):
    return {"n": len(lat), "p50_ms": round(pct(lat, 50) * 1000), "p95_ms": round(pct(lat, 95) * 1000), "max_ms": round(max(lat) * 1000), "mean_ms": round(statistics.mean(lat) * 1000)}


def run_round(eng, qs):
    lat, errs = [], 0

    def one(q):
        t = time.perf_counter()
        try:
            eng.answer(q["question"])
            return time.perf_counter() - t, False
        except Exception:  # noqa: BLE001
            return time.perf_counter() - t, True

    with ThreadPoolExecutor(CONCURRENCY) as ex:
        for d, e in ex.map(one, qs):
            lat.append(d)
            errs += e
    return lat, errs


def main():
    cache_only()
    schema = ActiveSchema.load(config.RUNS_DIR / "learned" / "schema.json")
    g, writer_g = Graph(schema=schema), Graph(schema=schema)  # every Graph() is built before any test node exists
    eng = QueryEngine(g, phase="learning", schema=schema)
    qs = learn.load_heldout()[:CONCURRENCY]
    eng.answer(qs[0]["question"])  # warm up connections
    print(f"{CONCURRENCY} concurrent queries x {ROUNDS} rounds; schema has {len(schema.names())} relations")

    base, base_err = [], 0
    for _ in range(ROUNDS):
        lat, e = run_round(eng, qs)
        base += lat
        base_err += e

    stop, wlat, written = threading.Event(), [], {"nodes": 0, "edges": 0}
    nid = [BASE]

    def writer():
        while not stop.is_set():
            ids = list(range(nid[0], nid[0] + 200))
            nid[0] += 200
            t = time.perf_counter()
            writer_g.write("MERGE (n {id: row.id}) SET n:Entity, n.name = row.name", [{"id": i, "name": f"loadtest {i}"} for i in ids])
            wlat.append(time.perf_counter() - t)
            t = time.perf_counter()
            writer_g.write_rel_edges([{"rid": i + 5_000_000, "s": i, "d": ids[(k + 1) % len(ids)], "type": "loadtest", "confidence": 0.9, "src_chunk": 0, "created_iter": 0} for k, i in enumerate(ids)])
            wlat.append(time.perf_counter() - t)
            written["nodes"] += 200
            written["edges"] += 200

    th = threading.Thread(target=writer)
    th.start()
    time.sleep(1)
    t0 = time.perf_counter()
    during, during_err = [], 0
    for _ in range(ROUNDS):
        lat, e = run_round(eng, qs)
        during += lat
        during_err += e
    elapsed = time.perf_counter() - t0
    stop.set()
    th.join()

    # pure graph reads under writes would need another writer run; the pipeline numbers above include them.
    writer_g.delete_nodes(list(range(BASE, nid[0])))
    left = writer_g.read("MATCH (n:Entity) WHERE n.id >= 9500000 RETURN count(*) AS n")[0]["n"]
    res = {
        "concurrent_queries": CONCURRENCY, "rounds": ROUNDS, "llm": "cache lookups only (no spend)",
        "baseline_no_writes": {**stats(base), "errors": base_err},
        "with_concurrent_repair_writes": {**stats(during), "errors": during_err},
        "writer": {"nodes_written": written["nodes"], "edges_written": written["edges"], "seconds": round(elapsed, 1),
                   "write_batch_p50_ms": round(pct(wlat, 50) * 1000), "write_batch_p95_ms": round(pct(wlat, 95) * 1000), "batch_size": 200},
        "test_nodes_left_after_cleanup": left,
    }
    (config.ROOT / "results" / "load_test.json").write_text(json.dumps(res, indent=1))
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
