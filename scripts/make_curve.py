"""Write results/curve.json: held-out EM and F1 (with bootstrap 95% CIs) per iteration for every run, plus baselines."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import config  # noqa: E402
from src.curve import build_curve  # noqa: E402

c = build_curve()
(config.ROOT / "results" / "curve.json").write_text(json.dumps(c, indent=1))
for name, r in c["runs"].items():
    print(f"{r['label']:18s} EM " + "  ".join(f"{v:.3f}" for v in r["em"]) + "   F1 " + "  ".join(f"{v:.3f}" for v in r["f1"]))
for name, b in c["baselines"].items():
    print(f"{b['label']:18s} EM {b['em']:.3f}   F1 {b['f1']:.3f}")

# Paired comparisons (10,000 resamples, seed 42) saved next to the curve.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from compare import compare  # noqa: E402

R = config.ROOT / "results"
pairs = {
    "learned_iter5_vs_random_iter5": (R / "learned/iter5/heldout.jsonl", R / "random/iter5/heldout.jsonl"),
    "learned_iter5_vs_random_s7_iter5": (R / "learned/iter5/heldout.jsonl", R / "random_s7/iter5/heldout.jsonl"),
    "learned_iter5_vs_static_graph": (R / "learned/iter5/heldout.jsonl", R / "iter0_static_graph/heldout.jsonl"),
    "learned_iter5_vs_open_vocab": (R / "learned/iter5/heldout.jsonl", R / "open_vocab/heldout.jsonl"),
    "open_vocab_vs_static_graph": (R / "open_vocab/heldout.jsonl", R / "iter0_static_graph/heldout.jsonl"),
    "static_graph_vs_bm25": (R / "iter0_static_graph/heldout.jsonl", R / "iter0_bm25/heldout.jsonl"),
}
out = {k: compare(a, b) for k, (a, b) in pairs.items() if a.exists() and b.exists()}
(R / "comparisons.json").write_text(json.dumps(out, indent=1))
print("wrote results/comparisons.json:", list(out))
