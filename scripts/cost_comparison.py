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

from src import config, llm  # noqa: E402

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


def per_1000(out, split, curve):
    """One-time versus recurring cost. One-time (learned only): evaluating and diagnosing the feedback questions and
    the repair extractions. Recurring, per query: planner + answer + query-time extraction. Planner dollars come from the
    cached usage of each system's own planner prompts; answer and extraction dollars use the learned run's unit costs
    (answer prompts are similar in size across systems). Extraction calls per query = the run's total query-time calls
    over its 87 held-out questions, an estimate of what a new question costs once its facts have to be extracted."""
    from src.query import PLAN_SCHEMA, PLAN_SYSTEM, plan_prompt
    from src.schema import ActiveSchema

    unit = json.loads((R / "unit_costs.json").read_text())
    qs = [json.loads(l)["question"] for l in open(config.SPLIT_DIR / "heldout.jsonl")]

    def planner_usd(names):
        us = [llm.cached_usage(config.EXTRACT_MODEL, plan_prompt(q, names), PLAN_SYSTEM, PLAN_SCHEMA, config.PLAN_MAX_TOKENS) for q in qs]
        us = [u for u in us if u]
        return sum(llm.price(config.EXTRACT_MODEL, *u) for u in us) / len(us) if us else unit["planner_usd_per_query"]

    vocab = {
        "learned": ActiveSchema.load(config.RUNS_DIR / "learned" / "schema.json").names(),
        "random": ActiveSchema.load(config.RUNS_DIR / "random" / "schema.json").names(),
        "random_s7": ActiveSchema.load(config.RUNS_DIR / "random_s7" / "schema.json").names(),
        "open_vocab": json.loads((R / "open_vocab" / "summary.json").read_text())["vocabulary"],
    }
    calls = dict(out["query_time_extraction_calls_total"])
    calls["open_vocab"] = json.loads((R / "open_vocab" / "summary.json").read_text())["splits"]["heldout"]["query_extraction_calls"]
    em = {n: curve["runs"][n]["em"][-1] for n in ("learned", "random", "random_s7")}
    em["open_vocab"] = curve["baselines"]["open_vocab"]["em"]
    one_time = round(sum(split[k]["feedback"] + split[k]["repair"] for k in range(6)), 4)
    res = {}
    for name in ("learned", "random", "random_s7", "open_vocab"):
        per_q_ext = calls[name] / len(qs)
        parts = {"planner": planner_usd(vocab[name]), "answer": unit["answer_usd_per_query"], "query_time_extraction": per_q_ext * unit["extraction_usd_per_call"]}
        recurring = sum(parts.values())
        ot = one_time if name == "learned" else 0.0
        res[name] = {
            "vocabulary_size": len(vocab[name]), "final_held_out_em": round(em[name], 4),
            "one_time_usd": ot, "recurring_usd_per_1000_queries": round(recurring * 1000, 2),
            "recurring_parts_usd_per_1000": {k: round(v * 1000, 2) for k, v in parts.items()},
            "query_time_extraction_calls_per_query": round(per_q_ext, 3),
            "total_usd_for_1000_queries": round(ot + recurring * 1000, 2),
            "total_usd_for_10000_queries": round(ot + recurring * 10000, 2),
        }
    res["note"] = ("One-time cost is only the learned policy's feedback evaluation, diagnosis and repair extraction. Random and open-vocabulary "
                   "have no dollar one-time cost but both take their relations from the gold evidence of the feedback questions (the candidate pool), "
                   "i.e. they assume someone already knows which relations matter. Held-out re-evaluation at each iteration is experiment overhead and is excluded.")
    return res


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
    out["per_1000_future_queries"] = per_1000(out, split, curve)
    (R / "cost_comparison.json").write_text(json.dumps(out, indent=1))
    print("learned per-iteration cost split (held-out / feedback / repair / total):")
    for k in range(6):
        v = split[k]
        print(f"  iter {k}: {v['heldout']:.3f} / {v['feedback']:.3f} / {v['repair']:.3f} / {v['total']:.3f}   EM {em[k]:.3f}   cumulative ${cum[k]:.3f} (held-out+repair only ${cum_heldout_side[k]:.3f})")
    for n, m in out["iterations_to_match"].items():
        print(f"{n}: iteration-5 EM {m['random_iteration5_em']:.4f} -> learned matches at iteration {m['first_learned_iteration_with_em_at_least_that']} (EM {m['learned_em_at_that_iteration']:.4f}); learned spent ${m['learned_cumulative_cost_usd_all_in']:.3f} all-in (${m['learned_cumulative_cost_usd_heldout_and_repair_only']:.3f} excluding feedback evaluation) vs random's full ${m['random_full_five_iteration_cost_usd']:.3f}")
    print("total cost:", out["total_cost_usd"], "| $ per +0.01 EM over static:", out["usd_per_0.01_em_gain_over_static"])
    print("query-time extraction calls:", out["query_time_extraction_calls_total"], "| learned repair chunks:", out["learned_repair_chunks_total"])
    print("\nper 1,000 future queries (one-time / recurring per 1,000 / total for 1,000 / EM):")
    for n, v in out["per_1000_future_queries"].items():
        if n != "note":
            print(f"  {n:11s} one-time ${v['one_time_usd']:.2f}  recurring ${v['recurring_usd_per_1000_queries']:.2f}  (planner {v['recurring_parts_usd_per_1000']['planner']:.2f} + answer {v['recurring_parts_usd_per_1000']['answer']:.2f} + extraction {v['recurring_parts_usd_per_1000']['query_time_extraction']:.2f}; {v['query_time_extraction_calls_per_query']:.2f} calls/query)  total for 1,000 ${v['total_usd_for_1000_queries']:.2f}  EM {v['final_held_out_em']:.3f}")


if __name__ == "__main__":
    main()

