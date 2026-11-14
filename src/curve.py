"""Per-iteration held-out numbers for the learned and random runs plus the static and BM25 baselines.

build_curve() reads results/<run>/iter<k>/summary.json directly, so it also works while learn.py is still running.
scripts/make_curve.py saves the result as results/curve.json for the demo chart.
"""
import json
import time

from src import config

RUNS = {"learned": "learned", "random": "random (seed 42)", "random_s7": "random (seed 7)"}
BASELINES = {"static_graph": "results/iter0_static_graph/summary.json", "bm25": "results/iter0_bm25/summary.json", "open_vocab": "results/open_vocab/summary.json"}


def build_curve(results=None):
    results = results or config.ROOT / "results"
    runs = {}
    for name, label in RUNS.items():
        d = results / name
        if not d.exists():
            continue
        pts = {}
        for p in d.glob("iter*/summary.json"):
            s = json.loads(p.read_text())
            o = s["heldout"]["overall"]
            if "em" not in o:
                continue
            pts[int(p.parent.name[4:])] = {"em": o["em"], "em_ci95": o["em_ci95"], "f1": o["f1"], "f1_ci95": o["f1_ci95"],
                                           "cost_usd": s.get("cost_usd"), "added": s.get("added", []), "questions": s["heldout"].get("questions")}
        if not pts:
            continue
        ks = sorted(pts)
        state_p = d / "state.json"
        state = json.loads(state_p.read_text()) if state_p.exists() else {}
        runs[name] = {
            "label": label, "policy": state.get("policy", name), "seed": state.get("seed"),
            "iterations": ks,
            "em": [pts[k]["em"] for k in ks], "em_ci95": [pts[k]["em_ci95"] for k in ks],
            "f1": [pts[k]["f1"] for k in ks], "f1_ci95": [pts[k]["f1_ci95"] for k in ks],
            "added": {str(k): pts[k]["added"] for k in ks}, "cost_usd": [pts[k]["cost_usd"] for k in ks],
        }
    baselines = {}
    for name, rel in BASELINES.items():
        p = config.ROOT / rel
        if p.exists():
            o = json.loads(p.read_text())["splits"]["heldout"]["overall"]
            baselines[name] = {"label": {"static_graph": "static graph", "bm25": "BM25", "open_vocab": "open vocabulary (one pass)"}[name], "em": o["em"], "em_ci95": o["em_ci95"], "f1": o["f1"], "f1_ci95": o["f1_ci95"]}
    cp = results / "costs.json"
    if cp.exists():  # real dollars from the ledger; per-iteration files can read 0 for runs reproduced from cache
        costs = json.loads(cp.read_text())
        for name, r in runs.items():
            r["cost_total_usd"] = costs["learning_phase_usd"].get(name)
        if "learned" in runs and len(runs["learned"]["iterations"]) == len(costs["learned_per_iteration_usd"]):
            runs["learned"]["cost_usd"] = [costs["learned_per_iteration_usd"][str(k)] for k in runs["learned"]["iterations"]]
    return {"split": "heldout", "n_questions": 87, "runs": runs, "baselines": baselines, "updated": time.strftime("%Y-%m-%d %H:%M:%S")}
