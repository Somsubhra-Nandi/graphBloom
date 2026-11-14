"""Load test: 50 concurrent queries while a repair-style write batch is running. Reports p50 / p95 latency.

  .venv/bin/python scripts/load_test.py              # short version: 15 rounds per phase
  .venv/bin/python scripts/load_test.py --minutes 2  # writer loops batches for the full duration (created_iter=999)
Queries are the first 50 held-out questions through the full pipeline (planner, beam, attributes, answer) with the
LLM replaced by cache lookups, so the numbers are the graph path's latency and cost no money; a cache miss is
counted as an error. The writer thread writes batches of throwaway nodes and edges (ids from 9,500,000) in the
same shape as the repair writes, and everything it wrote is deleted at the end.
"""
import argparse
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
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=float, help="continuous mode: the writer runs for this long while queries loop")
    args = ap.parse_args()
    cache_only()
    schema = ActiveSchema.load(config.RUNS_DIR / "learned" / "schema.json")
    g, writer_g = Graph(schema=schema), Graph(schema=schema)  # every Graph() is built before any test node exists
    eng = QueryEngine(g, phase="learning", schema=schema)
    qs = learn.load_heldout()[:CONCURRENCY]
    eng.answer(qs[0]["question"])  # warm up connections
    print(f"{CONCURRENCY} concurrent queries; schema has {len(schema.names())} relations", flush=True)

    base, base_err = [], 0
    for _ in range(ROUNDS):
        lat, e = run_round(eng, qs)
        base += lat
        base_err += e

    stop, wlat, written = threading.Event(), [], {"nodes": 0, "edges": 0}
    nid, rid = [BASE], [50_000_000]
    wtimes = []  # (seconds since writer start, batch latency)

    def writer():
        t0 = time.perf_counter()
        while not stop.is_set():
            ids = list(range(nid[0], nid[0] + 200))
            nid[0] += 200
            t = time.perf_counter()
            writer_g.write("MERGE (n {id: row.id}) SET n:Entity, n.name = row.name", [{"id": i, "name": f"loadtest {i}"} for i in ids])
            d1 = time.perf_counter() - t
            t = time.perf_counter()
            rows = []
            for k, i in enumerate(ids):
                rid[0] += 1
                rows.append({"rid": rid[0], "s": i, "d": ids[(k + 1) % len(ids)], "type": "loadtest", "confidence": 0.9, "src_chunk": 0, "created_iter": 999})
            writer_g.write_rel_edges(rows)
            d2 = time.perf_counter() - t
            wlat.extend([d1, d2])
            wtimes.append((time.perf_counter() - t0, d1 + d2))
            written["nodes"] += 200
            written["edges"] += 200

    th = threading.Thread(target=writer)
    th.start()
    time.sleep(1)
    t0 = time.perf_counter()
    during, during_err, windows, stamps = [], 0, [], []
    deadline = t0 + args.minutes * 60 if args.minutes else None
    n_rounds = 0
    while True:
        lat, e = run_round(eng, qs)
        now = time.perf_counter() - t0
        during += lat
        stamps += [now] * len(lat)
        during_err += e
        n_rounds += 1
        if (deadline is None and n_rounds >= ROUNDS) or (deadline is not None and time.perf_counter() >= deadline):
            break
    elapsed = time.perf_counter() - t0
    stop.set()
    th.join()

    span = 30.0
    for w in range(int(elapsed // span) + 1):
        lat_w = [d for d, s in zip(during, stamps) if w * span <= s < (w + 1) * span]
        wb = [b for s, b in wtimes if w * span <= s < (w + 1) * span]
        if lat_w:
            windows.append({"seconds": f"{int(w * span)}-{int((w + 1) * span)}", "queries": len(lat_w), "read_p50_ms": round(pct(lat_w, 50) * 1000), "read_p95_ms": round(pct(lat_w, 95) * 1000),
                            "write_batches": len(wb), "write_batch_p50_ms": round(pct(wb, 50) * 1000) if wb else None})

    t1 = time.perf_counter()
    writer_g.delete_nodes(list(range(BASE, nid[0])))  # DETACH DELETE: the created_iter=999 edges go with their nodes
    cleanup_s = round(time.perf_counter() - t1, 1)
    left_nodes = writer_g.read("MATCH (n:Entity) WHERE n.id >= 9500000 RETURN count(*) AS n")[0]["n"]
    left_edges = writer_g.read("MATCH (a:Entity)-[r:REL]->(b:Entity) WHERE r.created_iter = 999 RETURN count(*) AS n")[0]["n"]
    res = {
        "mode": f"continuous writer for {args.minutes} min" if args.minutes else f"{ROUNDS} rounds",
        "concurrent_queries": CONCURRENCY, "llm": "cache lookups only (no spend)",
        "baseline_no_writes": {**stats(base), "errors": base_err},
        "with_concurrent_repair_writes": {**stats(during), "errors": during_err, "rounds": n_rounds},
        "writer": {"nodes_written": written["nodes"], "edges_written": written["edges"], "seconds": round(elapsed, 1), "batch_size": 200,
                   "nodes_per_second": round(written["nodes"] / elapsed), "write_batch_p50_ms": round(pct(wlat, 50) * 1000), "write_batch_p95_ms": round(pct(wlat, 95) * 1000), "write_batch_max_ms": round(max(wlat) * 1000)},
        "per_30s_windows": windows,
        "cleanup": {"seconds": cleanup_s, "test_nodes_left": left_nodes, "created_iter_999_edges_left": left_edges},
    }
    name = "load_test_2min.json" if args.minutes else "load_test.json"
    (config.ROOT / "results" / name).write_text(json.dumps(res, indent=1))
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
