"""Graph snapshots, so the learned and random policies both start from the identical iteration-0 graph.

The HydraDB container keeps its data in .hydradb/store (a plain directory, about 20 MB). A snapshot is a copy of that
directory plus the Python-side state (data/state/index.json: id counter and name/alias dict). Restoring stops the
container, swaps the directory back, and starts it again.
"""
import json
import shutil
import subprocess
import time

from src import config

STORE = config.ROOT / ".hydradb" / "store"
STATE_FILES = ["index.json", "ingested.json"]
SNAP = config.SNAPSHOT_DIR / "iter0"
LIVE_PATH = config.STATE_DIR / "live_graph.json"  # which run / iteration / snapshot the live graph is in


def snap_dir(name):
    return config.SNAPSHOT_DIR / name


def get_live():
    return json.loads(LIVE_PATH.read_text()) if LIVE_PATH.exists() else {}


def set_live(**kw):
    """Record what the live graph is (run, iteration, the snapshot it was last restored from or saved as)."""
    cur = get_live()
    cur.update(kw)
    LIVE_PATH.parent.mkdir(parents=True, exist_ok=True)
    LIVE_PATH.write_text(json.dumps(cur))
    return cur


def _docker(*args):
    subprocess.run(["docker", *args], check=True, capture_output=True)


def _wait_ready(timeout=90):
    from neo4j import GraphDatabase

    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            d = GraphDatabase.driver(config.HYDRA_URI, auth=("neo4j", config.HYDRA_TOKEN))
            d.verify_connectivity()
            d.close()
            return
        except Exception:
            time.sleep(2)
    raise RuntimeError("HydraDB did not come back after restart")


def _restart_with(copy_fn):
    _docker("stop", "-t", "30", "hydradb")  # SIGTERM so the node flushes before we copy
    copy_fn()
    subprocess.run([str(config.ROOT / "scripts" / "start_hydradb.sh")], check=True, capture_output=True)
    _wait_ready()


def counts():
    from src.graph import Graph

    g = Graph()
    c = {"entities": g.read("MATCH (n:Entity) RETURN count(*) AS n")[0]["n"], "REL edges": len(g.load_edges()),
         "chunks": g.read("MATCH (n:Chunk) RETURN count(*) AS n")[0]["n"]}
    g.close()
    return c


def make_snapshot(name="iter0"):
    """Copy the live graph and state to data/snapshots/<name> (once). For iter0 the live graph must be the
    iteration-0 graph; other names save whatever the live graph currently is, with its run/iteration."""
    snap = snap_dir(name)
    if snap.exists():
        return json.loads((snap / "meta.json").read_text())
    meta = counts()
    meta["live"] = get_live()

    def copy():
        snap.mkdir(parents=True, exist_ok=True)
        shutil.copytree(STORE, snap / "store")
        for f in STATE_FILES:
            if (config.STATE_DIR / f).exists():
                shutil.copy(config.STATE_DIR / f, snap / f)

    _restart_with(copy)
    (snap / "meta.json").write_text(json.dumps(meta))
    return meta


def restore_snapshot(name="iter0"):
    """Put a saved graph and state back. Verifies the entity and edge counts match the snapshot."""
    snap = snap_dir(name)
    meta = json.loads((snap / "meta.json").read_text())

    def copy():
        shutil.rmtree(STORE)
        shutil.copytree(snap / "store", STORE)
        for f in STATE_FILES:
            if (snap / f).exists():
                shutil.copy(snap / f, config.STATE_DIR / f)

    _restart_with(copy)
    now = counts()
    expected = {k: v for k, v in meta.items() if k != "live"}
    if now != expected:
        raise RuntimeError(f"restore mismatch: snapshot {expected}, restored {now}")
    set_live(**{**meta.get("live", {}), "snapshot": name})
    return now
