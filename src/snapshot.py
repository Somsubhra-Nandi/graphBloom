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


def make_snapshot():
    """Copy the live graph and state to data/snapshots/iter0 (once). The live graph must be the iteration-0 graph."""
    if SNAP.exists():
        return json.loads((SNAP / "meta.json").read_text())
    meta = counts()

    def copy():
        SNAP.mkdir(parents=True, exist_ok=True)
        shutil.copytree(STORE, SNAP / "store")
        for f in STATE_FILES:
            if (config.STATE_DIR / f).exists():
                shutil.copy(config.STATE_DIR / f, SNAP / f)

    _restart_with(copy)
    (SNAP / "meta.json").write_text(json.dumps(meta))
    return meta


def restore_snapshot():
    """Put the iteration-0 graph and state back. Verifies the entity and edge counts match the snapshot."""
    meta = json.loads((SNAP / "meta.json").read_text())

    def copy():
        shutil.rmtree(STORE)
        shutil.copytree(SNAP / "store", STORE)
        for f in STATE_FILES:
            if (SNAP / f).exists():
                shutil.copy(SNAP / f, config.STATE_DIR / f)

    _restart_with(copy)
    now = counts()
    if now != meta:
        raise RuntimeError(f"restore mismatch: snapshot {meta}, restored {now}")
    return now
