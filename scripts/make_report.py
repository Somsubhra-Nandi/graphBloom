"""Rebuild results/REPORT_overnight.md from the saved results (curve, comparisons, costs, ablation, open vocabulary,
load test, reproducibility). Run scripts/make_curve.py and scripts/cost_comparison.py first.
  .venv/bin/python scripts/make_report.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import config  # noqa: E402

R = config.ROOT / "results"
J = lambda p: json.loads((R / p).read_text())  # noqa: E731
c, cmp, cc, ab = J("curve.json"), J("comparisons.json"), J("cost_comparison.json"), J("ablations/summary.json")
lt2, lt1 = J("load_test_2min.json"), J("load_test.json")
ov = J("open_vocab/summary.json")
ovh = ov["splits"]["heldout"]
L, R42, R7 = c["runs"]["learned"], c["runs"]["random"], c["runs"]["random_s7"]
st, bm, op = c["baselines"]["static_graph"], c["baselines"]["bm25"], c["baselines"]["open_vocab"]
pool = ov["pool"]
f = lambda x: f"{x:.3f}"  # noqa: E731
ci = lambda x: f"[{x[0]:.3f}, {x[1]:.3f}]"  # noqa: E731
learned_added = {r for k in range(1, 6) for r in L["added"][str(k)]}
never = [r for r in pool if r not in learned_added]
pc = cc["per_1000_future_queries"]
m = []
a = m.append
a("# Results: a self-improving graph on HydraDB (2WikiMultihopQA)\n")
a("All numbers are on the 87 entity-disjoint held-out questions unless stated. EM and F1 follow the 2Wiki evaluation script; intervals are bootstrap 95% CIs (1,000 resamples, seed 42). Everything here is reproducible from `results/` (`scripts/reproduce.py`; `scripts/make_report.py` rebuilds this file).\n")
a("## Held-out accuracy per iteration\n")
a("| Run | " + " | ".join(f"it {k}" for k in L["iterations"]) + " |\n|---|" + "---|" * len(L["iterations"]))
for name, r in (("learned", L), ("random (seed 42)", R42), ("random (seed 7)", R7)):
    a(f"| {name}, EM | " + " | ".join(f(v) for v in r["em"]) + " |")
    a(f"| {name}, F1 | " + " | ".join(f(v) for v in r["f1"]) + " |")
a(f"\nStatic graph (iteration 0, never changed): EM {f(st['em'])} {ci(st['em_ci95'])}, F1 {f(st['f1'])} {ci(st['f1_ci95'])}. BM25 (top-5 chunks, no graph): EM {f(bm['em'])} {ci(bm['em_ci95'])}, F1 {f(bm['f1'])} {ci(bm['f1_ci95'])}. Open vocabulary (one pass, see below): EM {f(op['em'])} {ci(op['em_ci95'])}, F1 {f(op['f1'])} {ci(op['f1_ci95'])}. Learned at iteration 5: EM {f(L['em'][-1])} {ci(L['em_ci95'][-1])}, F1 {f(L['f1'][-1])} {ci(L['f1_ci95'][-1])}.\n")
a("## Relations added, by iteration\n")
a("| Iteration | learned | random (seed 42) | random (seed 7) |\n|---|---|---|---|")
for k in range(1, 6):
    a(f"| {k} | " + " | ".join(", ".join(r["added"][str(k)]) for r in (L, R42, R7)) + " |")
a(f"\nThe candidate pool (relations in the gold evidence of the feedback questions, minus the 8 seed relations) has **{len(pool)}** relations. By iteration 5 the learned run had added {len(learned_added)} of them and never added {', '.join(f'`{r}`' for r in never)} (each seen in at most 2 feedback questions); each random seed had also added 10.\n")
a("## Paired comparisons (10,000 resamples, seed 42)\n")
a("| Comparison | EM diff [95% CI], share ≤ 0 | F1 diff [95% CI], share ≤ 0 |\n|---|---|---|")
for k, lab in (("learned_iter5_vs_random_iter5", "learned vs random (seed 42), iteration 5"), ("learned_iter5_vs_random_s7_iter5", "learned vs random (seed 7), iteration 5"),
               ("learned_iter5_vs_open_vocab", "learned iteration 5 vs open vocabulary"), ("learned_iter5_vs_static_graph", "learned iteration 5 vs static"),
               ("open_vocab_vs_static_graph", "open vocabulary vs static"), ("static_graph_vs_bm25", "static vs BM25")):
    e, g = cmp[k]["em"], cmp[k]["f1"]
    a(f"| {lab} | {e['mean_diff']:+.3f} {ci(e['ci95'])}, {e['share_le_0']:.1%} | {g['mean_diff']:+.3f} {ci(g['ci95'])}, {g['share_le_0']:.1%} |")
a("\n## Ablation: growth only (A1)\n")
a("| Iteration | learned | random 42 | random 7 | A1 growth only | static |\n|---|---|---|---|---|---|")
for r in ab["rows"]:
    a(f"| {r['iteration']} | {f(r['learned_em'])} | {f(r['random42_em'])} | {f(r['random7_em'])} | {f(r['A1_growth_only_em'])} | {f(r['static_em'])} |")
a("\nA1 replays the learned schema sequence with query-time extraction off, so the graph stays the iteration-0 graph and only the planner vocabulary changes; it equals the static graph at every iteration ($0, every prompt was cached). Growing the schema on its own does nothing, because the facts have to be extracted. An earlier A2 (query-time extraction on the static schema) was removed because it is degenerate: the planner can only request the seed relations, which were all extracted at ingest, so query-time extraction never fires.\n")
a("## Open-vocabulary baseline\n")
a(f"The planner's vocabulary is the seed schema plus the whole candidate pool from the start ({len(ov['vocabulary'])} relations), query-time extraction is on with the same budget as the learned run (2 calls per query), and there is no feedback and no learning. Held-out only, one pass, run on the iteration-0 graph. It used {ovh['query_extraction_calls']} extraction calls (on {ovh['queries_with_extraction']} of 87 queries).\n")
o = ovh["overall"]
a(f"EM {f(o['em'])} {ci(o['em_ci95'])}, F1 {f(o['f1'])} {ci(o['f1_ci95'])}. Against learned iteration 5: EM {cmp['learned_iter5_vs_open_vocab']['em']['mean_diff']:+.3f} for learned {ci(cmp['learned_iter5_vs_open_vocab']['em']['ci95'])}, {cmp['learned_iter5_vs_open_vocab']['em']['share_le_0']:.1%} of resamples at or below zero (F1 {cmp['learned_iter5_vs_open_vocab']['f1']['mean_diff']:+.3f} {ci(cmp['learned_iter5_vs_open_vocab']['f1']['ci95'])}): not distinguishable at 87 questions. Against static: EM {cmp['open_vocab_vs_static_graph']['em']['mean_diff']:+.3f} {ci(cmp['open_vocab_vs_static_graph']['em']['ci95'])}.\n")
Lh = J("learned/iter5/summary.json")["heldout"]
a("| Question type | n | learned it 5 EM | open vocabulary EM |\n|---|---|---|---|")
for k, v in Lh["by_type"].items():
    a(f"| {k} | {v['n']} | {f(v['em'])} {ci(v['em_ci95'])} | {f(ovh['by_type'][k]['em'])} {ci(ovh['by_type'][k]['em_ci95'])} |")
a("\nThe two are identical on every type except inference (5 vs 3 of 12 correct). Two caveats: the pool comes from the gold relations of the feedback questions, so this baseline already assumes someone knows which relations matter (it is a comparison, not a deployable system); and its ledger cost ($" + f"{ovh['cost_usd']:.2f}" + ") is low only because most of its extraction and answer prompts were already cached from the learned run, so the cost comparison below uses unit costs.\n")
a("## Cost\n")
ms = cc["iterations_to_match"]
a(f"Learning-phase spend: learned ${cc['total_cost_usd']['learned']:.3f}, random (seed 42) ${cc['total_cost_usd']['random']:.3f}, random (seed 7) ${cc['total_cost_usd']['random_s7']:.3f}, open vocabulary ${ovh['cost_usd']:.3f}; the whole project stayed under the $9.00 cap and the reserve was never used. Baselines: static graph $0.262, BM25 $0.172.\n")
a(f"**Iterations to match.** Random's iteration-5 EM is {ms['random']['random_iteration5_em']:.3f} (seed 42) and {ms['random_s7']['random_iteration5_em']:.3f} (seed 7). The learned run first reaches EM at or above each at **iteration 1** (EM {ms['random']['learned_em_at_that_iteration']:.3f}). To that point it had spent ${ms['random']['learned_cumulative_cost_usd_all_in']:.3f} all-in, or ${ms['random']['learned_cumulative_cost_usd_heldout_and_repair_only']:.3f} on the held-out side plus repairs (the rest is evaluating and diagnosing the 150 feedback questions), against random's ${ms['random']['random_full_five_iteration_cost_usd']:.3f} and ${ms['random_s7']['random_full_five_iteration_cost_usd']:.3f} for all five iterations.\n")
a("**Per 1,000 future queries.** One-time cost is the learned policy's feedback evaluation, diagnosis and repair extraction. Recurring cost per query is planner + answer + query-time extraction (calls per new query estimated as each run's total query-time calls over its 87 held-out questions). Planner dollars come from each system's own cached prompts; answer and extraction dollars use the learned run's unit costs.\n")
a("| System | Vocabulary | One-time | Recurring per 1,000 queries | Total for 1,000 queries | EM |\n|---|---|---|---|---|---|")
for n, lab in (("learned", "learned (iteration 5)"), ("random", "random (seed 42)"), ("random_s7", "random (seed 7)"), ("open_vocab", "open vocabulary")):
    v = pc[n]
    a(f"| {lab} | {v['vocabulary_size']} | ${v['one_time_usd']:.2f} | ${v['recurring_usd_per_1000_queries']:.2f} (planner {v['recurring_parts_usd_per_1000']['planner']:.2f}, answer {v['recurring_parts_usd_per_1000']['answer']:.2f}, extraction {v['recurring_parts_usd_per_1000']['query_time_extraction']:.2f}) | ${v['total_usd_for_1000_queries']:.2f} | {f(v['final_held_out_em'])} |")
a(f"\n{pc['note']} Learned's recurring premium over random is about ${pc['learned']['recurring_usd_per_1000_queries'] - pc['random']['recurring_usd_per_1000_queries']:.2f} per 1,000 queries (more extraction calls: {pc['learned']['query_time_extraction_calls_per_query']:.2f} per query vs {pc['random']['query_time_extraction_calls_per_query']:.2f}) and about ${pc['learned']['recurring_usd_per_1000_queries'] - pc['open_vocab']['recurring_usd_per_1000_queries']:.2f} over open vocabulary, and its one-time ${pc['learned']['one_time_usd']:.2f} never pays back in dollars against either; what it buys is finding the relations from feedback instead of being handed them.\n")
a("## Load test\n")
w2, b2, d2 = lt2["writer"], lt2["baseline_no_writes"], lt2["with_concurrent_repair_writes"]
a(f"50 concurrent queries (the first 50 held-out questions through the full pipeline; the LLM is replaced by cache lookups, so the numbers are the graph path and cost nothing). Without writes: p50 {b2['p50_ms']} ms, p95 {b2['p95_ms']} ms, max {b2['max_ms']} ms. With a writer looping batches of 200 nodes and 200 edges (`created_iter` = 999) for the full {w2['seconds']:.0f} seconds: {w2['nodes_written']:,} nodes and {w2['edges_written']:,} edges committed ({w2['nodes_per_second']:,} nodes/s; write batch p50 {w2['write_batch_p50_ms']} ms, p95 {w2['write_batch_p95_ms']} ms, max {w2['write_batch_max_ms']} ms), while {d2['n']:,} queries ran in {d2['rounds']} rounds: p50 {d2['p50_ms']} ms, p95 {d2['p95_ms']} ms, max {d2['max_ms']} ms, {d2['errors']} errors.\n")
a("| 30 s window | queries | read p50 (ms) | read p95 (ms) | write batches | write batch p50 (ms) |\n|---|---|---|---|---|---|")
for w in lt2["per_30s_windows"]:
    a(f"| {w['seconds']} | {w['queries']:,} | {w['read_p50_ms']} | {w['read_p95_ms']} | {w['write_batches']} | {w['write_batch_p50_ms']} |")
cl = lt2["cleanup"]
a(f"\nCleanup took {cl['seconds']} s and left {cl['test_nodes_left']} test nodes and {cl['created_iter_999_edges_left']} edges with `created_iter` 999; the learned_iter5 snapshot was then restored and verified. The earlier 3-second version of this test gave p50 {lt1['with_concurrent_repair_writes']['p50_ms']} ms and p95 {lt1['with_concurrent_repair_writes']['p95_ms']} ms. A real query adds one planner and one answer call (about 1 to 3 s with the API); the graph side stays well under a second.\n")
a("## Framing for the pitch (honest version)\n")
a(f"Starting from a deliberately shallow graph and letting failed feedback questions decide which relations to extract raised held-out EM from {f(st['em'])} to {f(L['em'][-1])} ({cmp['learned_iter5_vs_static_graph']['em']['mean_diff']:+.3f}, 95% CI {ci(cmp['learned_iter5_vs_static_graph']['em']['ci95'])}) on questions about entities the system never got feedback on, against {f(bm['em'])} for a plain BM25 retriever, for about $2.6 of API spend. That is what the data supports, and three controls temper it. A random policy with the same per-query budget also improves over static ({f(R42['em'][-1])} and {f(R7['em'][-1])}, about half the learned gain) because its candidate pool is, by construction, made of relations that appear in the feedback questions' gold evidence; learning adds ordering, reaching random's final accuracy after one iteration and ending {cmp['learned_iter5_vs_random_iter5']['em']['mean_diff']:+.3f} EM ahead of seed 42 {ci(cmp['learned_iter5_vs_random_iter5']['em']['ci95'])} and {cmp['learned_iter5_vs_random_s7_iter5']['em']['mean_diff']:+.3f} ahead of seed 7 {ci(cmp['learned_iter5_vs_random_s7_iter5']['em']['ci95'])}, borderline, with F1 differences not significant. An open-vocabulary baseline that is simply told all {len(pool)} pool relations up front and runs one pass reaches EM {f(op['em'])}, within noise of the learned run ({cmp['learned_iter5_vs_open_vocab']['em']['mean_diff']:+.3f} for learned, {ci(cmp['learned_iter5_vs_open_vocab']['em']['ci95'])}): so the learning loop does not beat knowing the right relations, it replaces having to know them, and it ends with a smaller schema ({pc['learned']['vocabulary_size']} relations against {pc['open_vocab']['vocabulary_size']}). Growing the schema alone changes nothing (A1 equals static), so the gain needs the schema and query-time extraction together. On cost, learned pays ${pc['learned']['one_time_usd']:.2f} once for feedback evaluation, diagnosis and repairs and about ${pc['learned']['recurring_usd_per_1000_queries']:.2f} per 1,000 queries, against ${pc['random']['recurring_usd_per_1000_queries']:.2f} for random and ${pc['open_vocab']['recurring_usd_per_1000_queries']:.2f} for open vocabulary, so it is the most expensive of the four in dollars. The defensible pitch is \"start cheap, deepen where questions ask, and learn which relations to deepen from feedback\", on 87 held-out questions and one split; the graph also loses to BM25 on pure comparison questions (EM 0.71 vs 0.81, within noise at n=21).\n")
a("## Assumptions and decisions made unattended\n")
a("- I did not have the text of the earlier long prompt (steps 2-6); I worked from the instructions given and PLAN.md. **Load test:** 50 concurrent held-out queries during a repair-style write batch, with cache lookups in place of the LLM. **Reproducibility:** `scripts/reproduce.py`, ten offline checks. **Report:** this file; it was `results/REPORT.md` and is now `results/REPORT_overnight.md`, rebuilt by `scripts/make_report.py`.")
a("- Correction: an earlier version of this report said the candidate pool had 17 relations. It has 14 (8 seed + 14 = 22 in the open-vocabulary vocabulary).")
a("- A2 was removed from the ablations and `results/ablations/`; `results/curve.json` never contained it, and it now carries the open-vocabulary baseline instead.")
a("- The first attempt at the 2-minute load test had a scoping bug in the writer thread (it died after one batch, so that run measured reads only); I killed it, fixed it and reran. The result above is from the rerun.")
a("- The second random seed (7) ran because more than $1.20 of learning budget remained. The reserve was never used. Nothing was pushed.")
a("- The learned run's committed results were reproduced from the response cache at $0 after I rebuilt the graph to save the `learned_iter5` snapshot; its original costs come from the first run's logs (`results/costs.json`).")
(R / "REPORT_overnight.md").write_text("\n".join(m) + "\n")
print("wrote results/REPORT_overnight.md,", len("\n".join(m)), "chars")
