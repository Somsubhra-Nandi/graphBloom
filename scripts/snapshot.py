"""Save or restore a named graph snapshot (data/snapshots/<name>).
  .venv/bin/python scripts/snapshot.py save learned_iter5
  .venv/bin/python scripts/snapshot.py restore learned_iter5
Restoring stops and restarts the HydraDB container and verifies the entity and edge counts.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import snapshot  # noqa: E402

cmd, name = sys.argv[1], sys.argv[2]
if cmd == "save":
    print("saved", name, snapshot.make_snapshot(name))
elif cmd == "restore":
    print("restored", name, snapshot.restore_snapshot(name))
else:
    sys.exit("usage: snapshot.py save|restore NAME")
