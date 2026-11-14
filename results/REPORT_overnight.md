# Results: a self-improving graph on HydraDB (2WikiMultihopQA)

All numbers are on the 87 entity-disjoint held-out questions unless stated. EM and F1 follow the 2Wiki evaluation script; intervals are bootstrap 95% CIs (1,000 resamples, seed 42). Everything here is reproducible from `results/` (`scripts/reproduce.py`; `scripts/make_report.py` rebuilds this file).

## Held-out accuracy per iteration

| Run | it 0 | it 1 | it 2 | it 3 | it 4 | it 5 |
|---|---|---|---|---|---|---|
| learned, EM | 0.471 | 0.529 | 0.540 | 0.552 | 0.575 | 0.575 |
| learned, F1 | 0.597 | 0.646 | 0.663 | 0.683 | 0.700 | 0.700 |
| random (seed 42), EM | 0.471 | 0.483 | 0.483 | 0.494 | 0.517 | 0.517 |
| random (seed 42), F1 | 0.597 | 0.601 | 0.601 | 0.622 | 0.652 | 0.658 |
| random (seed 7), EM | 0.471 | 0.494 | 0.483 | 0.506 | 0.540 | 0.529 |
| random (seed 7), F1 | 0.597 | 0.613 | 0.607 | 0.638 | 0.664 | 0.671 |

Static graph (iteration 0, never changed): EM 0.471 [0.368, 0.575], F1 0.597 [0.505, 0.692]. BM25 (top-5 chunks, no graph): EM 0.230 [0.149, 0.322], F1 0.303 [0.213, 0.404]. Open vocabulary (one pass, see below): EM 0.552 [0.448, 0.655], F1 0.692 [0.599, 0.779]. Learned at iteration 5: EM 0.575 [0.471, 0.678], F1 0.700 [0.607, 0.786].

## Relations added, by iteration

| Iteration | learned | random (seed 42) | random (seed 7) |
|---|---|---|---|
| 1 | father, date of death | mother, award received | place of burial, mother |
| 2 | place of death, mother | sibling, inception | award received, publisher |
| 3 | spouse, country | spouse, country | employer, date of death |
| 4 | award received, employer | employer, date of death | country, father |
| 5 | inception, educated at | publisher, educated at | sibling, founded by |

The candidate pool (relations in the gold evidence of the feedback questions, minus the 8 seed relations) has **14** relations. By iteration 5 the learned run had added 10 of them and never added `publisher`, `sibling`, `place of burial`, `founded by` (each seen in at most 2 feedback questions); each random seed had also added 10.

## Paired comparisons (10,000 resamples, seed 42)

| Comparison | EM diff [95% CI], share ≤ 0 | F1 diff [95% CI], share ≤ 0 |
|---|---|---|
| learned vs random (seed 42), iteration 5 | +0.058 [0.011, 0.115], 0.6% | +0.042 [-0.007, 0.097], 5.0% |
| learned vs random (seed 7), iteration 5 | +0.046 [0.000, 0.103], 6.3% | +0.029 [-0.023, 0.085], 14.1% |
| learned iteration 5 vs open vocabulary | +0.023 [0.000, 0.058], 13.1% | +0.008 [-0.022, 0.044], 31.9% |
| learned iteration 5 vs static | +0.103 [0.035, 0.184], 0.2% | +0.103 [0.032, 0.179], 0.2% |
| open vocabulary vs static | +0.081 [0.023, 0.149], 0.9% | +0.095 [0.027, 0.167], 0.3% |
| static vs BM25 | +0.241 [0.126, 0.356], 0.0% | +0.293 [0.179, 0.404], 0.0% |

## Ablation: growth only (A1)

| Iteration | learned | random 42 | random 7 | A1 growth only | static |
|---|---|---|---|---|---|
| 1 | 0.529 | 0.483 | 0.494 | 0.471 | 0.471 |
| 3 | 0.552 | 0.494 | 0.506 | 0.471 | 0.471 |
| 5 | 0.575 | 0.517 | 0.529 | 0.471 | 0.471 |

A1 replays the learned schema sequence with query-time extraction off, so the graph stays the iteration-0 graph and only the planner vocabulary changes; it equals the static graph at every iteration ($0, every prompt was cached). Growing the schema on its own does nothing, because the facts have to be extracted. An earlier A2 (query-time extraction on the static schema) was removed because it is degenerate: the planner can only request the seed relations, which were all extracted at ingest, so query-time extraction never fires.

## Open-vocabulary baseline

The planner's vocabulary is the seed schema plus the whole candidate pool from the start (22 relations), query-time extraction is on with the same budget as the learned run (2 calls per query), and there is no feedback and no learning. Held-out only, one pass, run on the iteration-0 graph. It used 48 extraction calls (on 41 of 87 queries).

EM 0.552 [0.448, 0.655], F1 0.692 [0.599, 0.779]. Against learned iteration 5: EM +0.023 for learned [0.000, 0.058], 13.1% of resamples at or below zero (F1 +0.008 [-0.022, 0.044]): not distinguishable at 87 questions. Against static: EM +0.081 [0.023, 0.149].

| Question type | n | learned it 5 EM | open vocabulary EM |
|---|---|---|---|
| bridge_comparison | 16 | 0.875 [0.688, 1.000] | 0.875 [0.688, 1.000] |
| comparison | 21 | 0.714 [0.524, 0.905] | 0.714 [0.524, 0.905] |
| compositional | 38 | 0.421 [0.263, 0.579] | 0.421 [0.263, 0.579] |
| inference | 12 | 0.417 [0.167, 0.667] | 0.250 [0.000, 0.500] |

The two are identical on every type except inference (5 vs 3 of 12 correct). Two caveats: the pool comes from the gold relations of the feedback questions, so this baseline already assumes someone knows which relations matter (it is a comparison, not a deployable system); and its ledger cost ($0.13) is low only because most of its extraction and answer prompts were already cached from the learned run, so the cost comparison below uses unit costs.

## Cost

Learning-phase spend: learned $2.584, random (seed 42) $0.645, random (seed 7) $0.649, open vocabulary $0.130; the whole project stayed under the $9.00 cap and the reserve was never used. Baselines: static graph $0.262, BM25 $0.172.

**Iterations to match.** Random's iteration-5 EM is 0.517 (seed 42) and 0.529 (seed 7). The learned run first reaches EM at or above each at **iteration 1** (EM 0.529). To that point it had spent $0.899 all-in, or $0.241 on the held-out side plus repairs (the rest is evaluating and diagnosing the 150 feedback questions), against random's $0.645 and $0.649 for all five iterations.

**Per 1,000 future queries.** One-time cost is the learned policy's feedback evaluation, diagnosis and repair extraction. Recurring cost per query is planner + answer + query-time extraction (calls per new query estimated as each run's total query-time calls over its 87 held-out questions). Planner dollars come from each system's own cached prompts; answer and extraction dollars use the learned run's unit costs.

| System | Vocabulary | One-time | Recurring per 1,000 queries | Total for 1,000 queries | EM |
|---|---|---|---|---|---|
| learned (iteration 5) | 18 | $1.76 | $4.21 (planner 1.48, answer 1.66, extraction 1.07) | $5.97 | 0.575 |
| random (seed 42) | 18 | $0.00 | $3.77 (planner 1.48, answer 1.66, extraction 0.63) | $3.77 | 0.517 |
| random (seed 7) | 18 | $0.00 | $3.77 (planner 1.49, answer 1.66, extraction 0.63) | $3.77 | 0.529 |
| open vocabulary | 22 | $0.00 | $4.04 (planner 1.50, answer 1.66, extraction 0.88) | $4.04 | 0.552 |

One-time cost is only the learned policy's feedback evaluation, diagnosis and repair extraction. Random and open-vocabulary have no dollar one-time cost but both take their relations from the gold evidence of the feedback questions (the candidate pool), i.e. they assume someone already knows which relations matter. Held-out re-evaluation at each iteration is experiment overhead and is excluded. Learned's recurring premium over random is about $0.44 per 1,000 queries (more extraction calls: 0.67 per query vs 0.39) and about $0.17 over open vocabulary, and its one-time $1.76 never pays back in dollars against either; what it buys is finding the relations from feedback instead of being handed them.

## Load test

50 concurrent queries (the first 50 held-out questions through the full pipeline; the LLM is replaced by cache lookups, so the numbers are the graph path and cost nothing). Without writes: p50 121 ms, p95 169 ms, max 237 ms. With a writer looping batches of 200 nodes and 200 edges (`created_iter` = 999) for the full 120 seconds: 325,200 nodes and 325,200 edges committed (2,707 nodes/s; write batch p50 28 ms, p95 77 ms, max 126 ms), while 28,800 queries ran in 576 rounds: p50 149 ms, p95 209 ms, max 411 ms, 0 errors.

| 30 s window | queries | read p50 (ms) | read p95 (ms) | write batches | write batch p50 (ms) |
|---|---|---|---|---|---|
| 0-30 | 7,350 | 147 | 202 | 411 | 76 |
| 30-60 | 7,200 | 150 | 209 | 417 | 76 |
| 60-90 | 7,100 | 150 | 209 | 395 | 77 |
| 90-120 | 7,100 | 151 | 213 | 388 | 77 |
| 120-150 | 50 | 139 | 215 | 15 | 77 |

Cleanup took 146.2 s and left 0 test nodes and 0 edges with `created_iter` 999; the learned_iter5 snapshot was then restored and verified. The earlier 3-second version of this test gave p50 154 ms and p95 236 ms. A real query adds one planner and one answer call (about 1 to 3 s with the API); the graph side stays well under a second.

## Framing for the pitch (honest version)

Starting from a deliberately shallow graph and letting failed feedback questions decide which relations to extract raised held-out EM from 0.471 to 0.575 (+0.103, 95% CI [0.035, 0.184]) on questions about entities the system never got feedback on, against 0.230 for a plain BM25 retriever, for about $2.6 of API spend. That is what the data supports, and three controls temper it. A random policy with the same per-query budget also improves over static (0.517 and 0.529, about half the learned gain) because its candidate pool is, by construction, made of relations that appear in the feedback questions' gold evidence; learning adds ordering, reaching random's final accuracy after one iteration and ending +0.058 EM ahead of seed 42 [0.011, 0.115] and +0.046 ahead of seed 7 [0.000, 0.103], borderline, with F1 differences not significant. An open-vocabulary baseline that is simply told all 14 pool relations up front and runs one pass reaches EM 0.552, within noise of the learned run (+0.023 for learned, [0.000, 0.058]): so the learning loop does not beat knowing the right relations, it replaces having to know them, and it ends with a smaller schema (18 relations against 22). Growing the schema alone changes nothing (A1 equals static), so the gain needs the schema and query-time extraction together. On cost, learned pays $1.76 once for feedback evaluation, diagnosis and repairs and about $4.21 per 1,000 queries, against $3.77 for random and $4.04 for open vocabulary, so it is the most expensive of the four in dollars. The defensible pitch is "start cheap, deepen where questions ask, and learn which relations to deepen from feedback", on 87 held-out questions and one split; the graph also loses to BM25 on pure comparison questions (EM 0.71 vs 0.81, within noise at n=21).

## Assumptions and decisions made unattended

- I did not have the text of the earlier long prompt (steps 2-6); I worked from the instructions given and PLAN.md. **Load test:** 50 concurrent held-out queries during a repair-style write batch, with cache lookups in place of the LLM. **Reproducibility:** `scripts/reproduce.py`, ten offline checks. **Report:** this file; it was `results/REPORT.md` and is now `results/REPORT_overnight.md`, rebuilt by `scripts/make_report.py`.
- Correction: an earlier version of this report said the candidate pool had 17 relations. It has 14 (8 seed + 14 = 22 in the open-vocabulary vocabulary).
- A2 was removed from the ablations and `results/ablations/`; `results/curve.json` never contained it, and it now carries the open-vocabulary baseline instead.
- The first attempt at the 2-minute load test had a scoping bug in the writer thread (it died after one batch, so that run measured reads only); I killed it, fixed it and reran. The result above is from the rerun.
- The second random seed (7) ran because more than $1.20 of learning budget remained. The reserve was never used. Nothing was pushed.
- The learned run's committed results were reproduced from the response cache at $0 after I rebuilt the graph to save the `learned_iter5` snapshot; its original costs come from the first run's logs (`results/costs.json`).
