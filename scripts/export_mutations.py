"""Save the live graph's Mutation nodes to results/<run>/mutations.jsonl (graph restores wipe them).
  .venv/bin/python scripts/export_mutations.py learned
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import config  # noqa: E402
from src.graph import Graph  # noqa: E402
from src.mutations import export  # noqa: E402

run = sys.argv[1]
n = export(Graph(), config.ROOT / "results" / run / "mutations.jsonl")
print(f"exported {n} mutations to results/{run}/mutations.jsonl")
