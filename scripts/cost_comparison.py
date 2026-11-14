"""Cost comparison of the learned and random policies, and iterations-to-match.

  .venv/bin/python scripts/cost_comparison.py
The learned run's per-iteration cost split (held-out / feedback / repair) comes from the logs of the original run
(data/state/learn_dry_run.log for iterations 0-1, learn_learned.log for 2-5); the committed learned results were later
rebuilt from the response cache at $0, so their own summary files read 0. Random run totals are from the spend ledger.
"""
import ast
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import config  # noqa: E402

R, S = config.ROOT / "results", config.STATE_DIR


def parse_log(path):
    out, it = {}, None
    for line in open(path):
        m = re.match(r"=== \w+ iteration (\d+) ===", line)
        if m:
            it = int(m.group(1))
            out.setdefault(it, {"heldout": 0.0, "feedback": 0.0, "repair": 0.0})
        elif it is not None and line.strip().startswith("held-out:"):
            out[it]["heldout"] = float(re.search(r"cost \$([\d.]+)", line).group(1))
        elif it is not None and line.strip().startswith("feedback ("):
            out[it]["feedback"] = float(re.search(r"cost \$([\d.]+)", line).group(1))
        elif it is not None and line.strip().startswith("repair extraction:"):
            out[it]["repair"] = ast.literal_eval(line.split("repair extraction:")[1].strip())["cost_usd"]
    return out


def main():
    split = parse_log(S / "learn_dry_run.log")
    split.update({k: v for k, v in parse_log(S / "learn_learned.log").items() if k >= 2})
    for k, v in split.items():
        v["total"] = round(v["heldout"] + v["feedback"] + v["repair"], 5)
    curve = json.loads((R / "curve.json").read_text())
    costs = json.loads((R / "costs.json").read_text())["learning_phase_usd"]
    learned = curve["runs"]["learned"]
    em = dict(zip(learned["iterations"], learned["em"]))
    cum, cum_heldout_side, tot, ho = {}, {}, 0.0, 0.0
    for k in range(6):
        tot += split[k]["total"]
        ho += split[k]["heldout"] + split[k]["repair"]
        cum[k], cum_heldout_side[k] = round(tot, 4), round(ho, 4)

    def calls(run):
        n = 0
        for k in range(6):
            p = R / run / f"iter{k}" / "heldout.jsonl"
            n += sum(len(json.loads(l)["trace"].get("query_extraction", [])) for l in open(p))
        return n

    out = {"learned_iteration_cost_split_usd": split, "learned_cumulative_usd": cum, "learned_cumulative_heldout_and_repair_only_usd": cum_heldout_side, "iterations_to_match": {}}
    for name in ("random", "random_s7"):
        r = curve["runs"][name]
        target = r["em"][r["iterations"].index(5)]
        k = next((k for k in sorted(em) if em[k] >= target), None)
        out["iterations_to_match"][name] = {
            "random_iteration5_em": target, "first_learned_iteration_with_em_at_least_that": k,
            "learned_em_at_that_iteration": em.get(k),
            "learned_cumulative_cost_usd_all_in": cum.get(k), "learned_cumulative_cost_usd_heldout_and_repair_only": cum_heldout_side.get(k),
            "random_full_five_iteration_cost_usd": costs[name],
        }
    base = curve["baselines"]["static_graph"]["em"]
    out["gain_over_static_em"] = {n: round(r["em"][-1] - base, 4) for n, r in curve["runs"].items()}
    out["total_cost_usd"] = {n: costs[n] for n in ("learned", "random", "random_s7")}
    out["usd_per_0.01_em_gain_over_static"] = {n: round(costs[n] / (out["gain_over_static_em"][n] * 100), 3) for n in ("learned", "random", "random_s7")}
    out["query_time_extraction_calls_total"] = {"learned": calls("learned"), "random": calls("random"), "random_s7": calls("random_s7")}
    out["learned_repair_chunks_total"] = sum(json.loads((R / "learned" / f"iter{k}" / "summary.json").read_text()).get("repair_extraction", {}).get("chunks_extracted", 0) for k in range(1, 6))
    (R / "cost_comparison.json").write_text(json.dumps(out, indent=1))
    print("learned per-iteration cost split (held-out / feedback / repair / total):")
    for k in range(6):
        v = split[k]
        print(f"  iter {k}: {v['heldout']:.3f} / {v['feedback']:.3f} / {v['repair']:.3f} / {v['total']:.3f}   EM {em[k]:.3f}   cumulative ${cum[k]:.3f} (held-out+repair only ${cum_heldout_side[k]:.3f})")
    for n, m in out["iterations_to_match"].items():
        print(f"{n}: iteration-5 EM {m['random_iteration5_em']:.4f} -> learned matches at iteration {m['first_learned_iteration_with_em_at_least_that']} (EM {m['learned_em_at_that_iteration']:.4f}); learned spent ${m['learned_cumulative_cost_usd_all_in']:.3f} all-in (${m['learned_cumulative_cost_usd_heldout_and_repair_only']:.3f} excluding feedback evaluation) vs random's full ${m['random_full_five_iteration_cost_usd']:.3f}")
    print("total cost:", out["total_cost_usd"], "| $ per +0.01 EM over static:", out["usd_per_0.01_em_gain_over_static"])
    print("query-time extraction calls:", out["query_time_extraction_calls_total"], "| learned repair chunks:", out["learned_repair_chunks_total"])


if __name__ == "__main__":
    main()
