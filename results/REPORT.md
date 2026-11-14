# Results: a self-improving graph on HydraDB (2WikiMultihopQA)

All numbers are on the 87 entity-disjoint held-out questions unless stated. EM and F1 follow the 2Wiki evaluation script; intervals are bootstrap 95% CIs (1,000 resamples, seed 42). Every number below is reproducible from `results/` (`scripts/reproduce.py`, 10/10 checks pass).

## Held-out accuracy per iteration

| Run | it 0 | it 1 | it 2 | it 3 | it 4 | it 5 |
|---|---|---|---|---|---|---|
| learned, EM | 0.471 | 0.529 | 0.540 | 0.552 | 0.575 | 0.575 |
| learned, F1 | 0.597 | 0.646 | 0.663 | 0.683 | 0.700 | 0.700 |
| random (seed 42), EM | 0.471 | 0.483 | 0.483 | 0.494 | 0.517 | 0.517 |
| random (seed 42), F1 | 0.597 | 0.601 | 0.601 | 0.622 | 0.652 | 0.658 |
| random (seed 7), EM | 0.471 | 0.494 | 0.483 | 0.506 | 0.540 | 0.529 |
| random (seed 7), F1 | 0.597 | 0.613 | 0.607 | 0.638 | 0.664 | 0.671 |

Static graph (iteration-0, never changed): EM 0.471 [0.368, 0.575], F1 0.597 [0.505, 0.692]. BM25 (top-5 chunks, no graph): EM 0.230 [0.149, 0.322], F1 0.303 [0.213, 0.404]. Learned at iteration 5: EM 0.575 [0.471, 0.678], F1 0.700 [0.607, 0.786].

## Relations added, by iteration

| Iteration | learned | random (seed 42) | random (seed 7) |
|---|---|---|---|
| 1 | father, date of death | mother, award received | place of burial, mother |
| 2 | place of death, mother | sibling, inception | award received, publisher |
| 3 | spouse, country | spouse, country | employer, date of death |
| 4 | award received, employer | employer, date of death | country, father |
| 5 | inception, educated at | publisher, educated at | sibling, founded by |

## Paired comparisons (10,000 resamples, seed 42)

| Comparison | EM diff [95% CI], share ≤ 0 | F1 diff [95% CI], share ≤ 0 |
|---|---|---|
| learned vs random (seed 42), iteration 5 | +0.058 [0.011, 0.115], 0.6% | +0.042 [-0.007, 0.097], 5.0% |
| learned vs random (seed 7), iteration 5 | +0.046 [0.000, 0.103], 6.3% | +0.029 [-0.023, 0.085], 14.1% |
| learned iteration 5 vs static | +0.103 [0.035, 0.184], 0.2% | +0.103 [0.032, 0.179], 0.2% |
| static vs BM25 | +0.241 [0.126, 0.356], 0.0% | +0.293 [0.179, 0.404], 0.0% |

## Ablations (held-out EM, iterations 1, 3, 5)

| Iteration | learned | random 42 | random 7 | A1 growth only | A2 query-time extraction only | static |
|---|---|---|---|---|---|---|
| 1 | 0.529 | 0.483 | 0.494 | 0.471 | 0.471 | 0.471 |
| 3 | 0.552 | 0.494 | 0.506 | 0.471 | 0.471 | 0.471 |
| 5 | 0.575 | 0.517 | 0.529 | 0.471 | 0.471 | 0.471 |

A1 replays the learned schema sequence with query-time extraction off; A2 keeps the 8-relation schema with query-time extraction on. Both equal the static graph, at $0 (every prompt was cached). That is by construction: held-out entities are disjoint from the feedback ones, so repairs cannot help held-out, and query-time extraction can only extract relations in the active schema, while all 8 seed relations were already extracted from every chunk at ingest. The gain therefore needs both parts together: a schema that grows to include the relations questions ask for, and extraction at query time to fill them.

## Cost

Learning-phase spend: learned $2.584, random (seed 42) $0.645, random (seed 7) $0.649; total project spend $6.398 of the $9.00 cap, reserve untouched. Baselines: static graph $0.262, BM25 $0.172.

**Iterations to match.** Random's iteration-5 EM is 0.517 (seed 42) and 0.529 (seed 7). The learned run first reaches EM ≥ each of those at **iteration 1** (EM 0.529). To that point it had spent $0.899 all-in, or $0.241 on the held-out side plus repairs (the rest is evaluating and diagnosing the 150 feedback questions, which random does not do), against random's $0.645 / $0.649 for all five iterations. All-in, learned is the more expensive policy ($0.25 per +0.01 EM over static, against $0.14 and $0.11 for random) because it pays for feedback diagnosis; it also made more query-time extraction calls (58 against 34 and 34) plus 114 repair extractions on feedback chunks (batched, 50% price). Per-iteration split in `results/cost_comparison.json`.

## Load test

50 concurrent queries (first 50 held-out questions through the full pipeline; LLM replaced by cache lookups, so the numbers are the graph path), 15 rounds each. Without writes: p50 125 ms, p95 178 ms. While a writer committed 14,600 nodes and 14,600 edges in batches of 200 (write batch p50 23 ms, p95 60 ms): p50 154 ms, p95 236 ms, 0 errors. A real query adds one planner call and one answer call (about 1 to 3 s with the API); the graph side stays well under a quarter second. The write window was about 3.2 s, so this shows no contention at this scale, not behaviour under sustained heavy writes.

## Framing for the pitch (honest version)

Starting from a deliberately shallow graph, letting failed feedback questions decide which relations to extract raised held-out EM from 0.471 to 0.575 (+0.103, 95% CI [+0.034, +0.184]) on questions about entities the system never got feedback on, against 0.230 for a plain BM25 retriever, for about $2.6 of API spend in total. That is the claim the data supports. Two things temper it. First, a random policy given the same per-query budget also improves over the static graph (EM 0.517 and 0.529, roughly half of the learned gain), because the candidate pool it draws from is, by construction, made of relations that appear in the gold evidence of the feedback questions, so almost any relation it adds is one that some question needs, and query-time extraction fills it in; with 17 pool relations and 2 drawn per iteration, random has added most of them by iteration 5. What learning adds on top is ordering: it picks the most-blamed relations first and reaches random's final accuracy after one iteration, ending +0.058 EM ahead of random seed 42 (CI [+0.012, +0.115]) and +0.046 ahead of seed 7 (CI [0.000, +0.103], borderline), with F1 differences not significant, on 87 questions and one split. Second, the gain needs both halves of the mechanism: growing the schema alone or running query-time extraction alone leaves accuracy exactly at the static level. So the defensible pitch is "start cheap and deepen where questions ask, and learn which relations to deepen first", not "learning beats everything"; the graph also loses to BM25 on pure comparison questions (EM 0.71 vs 0.81, within noise at n=21), and learned is the more expensive policy all-in because it pays to evaluate and diagnose feedback questions.

## Assumptions and decisions made unattended

- I did not have the text of the earlier long prompt (steps 2-6); I worked from this run's instructions and PLAN.md. Where a step was underspecified I chose as follows. **Step 3 (load test):** 50 concurrent held-out queries during a repair-style write batch, with the LLM replaced by cache lookups so it cost nothing; PLAN.md's wording was the spec. **Step 5 (reproducibility):** `scripts/reproduce.py`, ten offline checks listed above. **Step 6:** this report, plus `results/*.json` for the demo.
- A1 is "growth only" with no extraction at all, so the graph stays the iteration-0 graph and only the planner vocabulary changes; A2 is the static 8-relation schema with query-time extraction on. Both were estimated at $0 from the cache before running, and both ran.
- Iterations-to-match is reported all-in and excluding feedback evaluation, since the question of what counts as "cost" changes the conclusion.
- The second random seed (7) ran because $1.59 of learning budget remained, over the $1.20 threshold. The reserve was never used. Nothing was pushed.
- The learned run's committed results were reproduced from the response cache at $0 after I had to rebuild the graph to save the `learned_iter5` snapshot; its original costs come from the first run's logs (`results/costs.json`).
- Learning-phase budget remaining at the end: about $1.59 of $5.47.
