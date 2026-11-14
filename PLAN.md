# Self-improving graph on HydraDB: Track 1 plan

As of 2026-11-14. Build time: 30 hours.

## Summary

We build a graph search system on HydraDB that starts from a cheap, shallow knowledge graph and uses its own failed answers to decide what to extract next and which relations to trust.

The demo must prove one claim: on held-out questions about entities the system never received feedback on, a learned policy beats a random policy at the same extraction budget, and the gap widens over five iterations.

- **Track:** 1, the self-improving graph.
- **Mechanisms:** gap-driven ingestion (schema growth plus targeted extraction) and relation reweighting. Alias addition is a small third.
- **Benchmark:** 2WikiMultihopQA, 250 questions pooled into one corpus of 1,748 paragraphs.
- **Stack:** Python and FastAPI, HydraDB v0.4.0 over Bolt with the Neo4j Python driver, Streamlit for the demo.
- **Deadline:** submission is due 16 Nov 2026 at 09:00 IST.

## Core idea

The system learns at the schema level, not per question, so what it learns transfers to questions it has never seen.

Fully extracting a knowledge graph with an LLM is expensive. We start with a shallow graph and let failures decide where extraction effort goes.

- **What it ingests:** the extraction schema grows. A failure reveals a relation type the shallow pass never extracted, for example `spouse`. The system adds it and extracts it only from chunks about the relevant entity type.
- **How it queries:** traversal weights are learned per (question type, relation type) and stored on `RelType` nodes, so they apply to unseen questions.

Per-edge weights and per-question ingestion only help when the same question is asked again. We avoid both.

## Benchmark and split

We use 2WikiMultihopQA with 150 feedback questions and an entity-disjoint held-out set. 100 candidates were drawn and 87 survive the entity filter (seed 42, `scripts/make_split.py`).

- **Why this dataset:** answers are short, so exact match and F1 work without an LLM judge. It labels question types and ships gold evidence triples, which make failure diagnosis mechanical. Confirm the format in the first hour.
- **Corpus:** the paragraphs of all 250 questions pooled into one store, deduplicated by title to 1,748 paragraphs, so retrieval is not handed the right ten paragraphs. `context` is dropped from the feedback and held-out files for the same reason.
- **Entity-disjoint held-out:** drop any held-out question that shares an entity with the evidence of a feedback question.
- **Leakage rule:** gold answers and gold evidence are read only for the 150 feedback questions. Held-out labels are used for scoring and nothing else.
- **Fixed seed** for sampling and the split, recorded in the repo.

## Graph model in HydraDB

The graph holds the knowledge, the learned policy and the history of its own changes.

| Element | Kind | Key properties | Purpose |
| --- | --- | --- | --- |
| `Chunk` | Node | `id`, `title`, `text` | Raw text |
| `Entity` | Node | `id`, `name`, `aliases`, `type`, literal attributes | Things questions are about. Dates and other literals live here as properties. Name and alias lookup is done in a Python dict, not in the graph |
| `REL` | Edge, Entity to Entity | `type`, `confidence`, `src_chunk`, `created_iter` | One generic edge type, so weights can be applied by its `type` property |
| `MENTIONS` | Edge, Chunk to Entity | `chunk` | Lets targeted extraction find the chunks for a seed entity |
| `EXTRACTED` | Edge, Chunk to RelType | `rel_type`, `chunk` | Records which relation types were already extracted from a chunk. Filtered by equality on `rel_type` |
| `RelType` | Node | `name`, `qtype`, `weight`, `blame_count` | The learned policy, one node per (question type, relation type). Loaded into a Python dict once per iteration and written back at the end of it |
| `Mutation` | Node | `iter`, `kind`, `reason`, `question_id` | Provenance for every change, and the source of the before/after diff |

Edge score during traversal is `RelType.weight` times `REL.confidence`, computed in Python.

Every node has a non-negative integer `id` from a persisted counter. Every property is always written with a default value, because `IS NULL` is not available.

## Seed schema

The shallow ingest extracts 8 relations. The rest are held back so that schema growth has room to show. The counts are evidence triples in the 2WikiMultihopQA dev split.

- **Included:** `director` (7,592), `date of birth` (4,976), `publication date` (2,184), `country of citizenship` (2,146), `place of birth` (1,648), `country of origin` (754), `performer` (426), `composer` (262). Together they are 64% of all evidence triples.
- **Held back:** `father` (3,203), `date of death` (2,551), `spouse` (1,198), `mother` (1,156), `place of death` (1,015), `country` (657), `educated at` (249), `place of burial`, `employer`, `child`, `sibling`.

Share of questions whose evidence relations are all in the seed schema, so iteration 0 can in principle answer them:

| Question type | Full dev split | 150 feedback questions |
| --- | --- | --- |
| inference | 0% | 0% |
| compositional | 28% | 21% |
| bridge_comparison | 70% | 70% |
| comparison | 78% | 72% |

Inference and compositional questions have the most room to improve. Comparison and bridge_comparison start mostly covered.

## Query path

A question is answered by a weighted beam traversal of at most three hops, one Cypher call per hop.

1. An LLM call returns the seed entities, the question type and the relation chain it expects, for example `director` then `spouse`.
2. Seeds resolve to entity ids through the Python name and alias dict.
3. The beam expands one hop per Cypher call. Each call fetches candidate edges with `ORDER BY r.confidence DESC LIMIT 200`. Python then scores them as `RelType.weight` times `REL.confidence` and keeps the top k paths.
4. If the beam dead-ends, the per-query extraction budget may be spent (see Extraction budget), then the hop is retried.
5. The LLM answers from the winning paths, the literal attributes on their entities, and the source chunks of their edges.
6. The answer, the paths used and the chunks read are logged for the classifier.

One hop per call keeps each query simple. Cypher cannot order by a computed expression, so the weighted ordering happens in Python.

## Learning loop

Each iteration answers the 150 feedback questions, classifies every failure by how much of the gold evidence chain the graph covered, and applies one repair per failure.

| Failure | What to check | Repair |
| --- | --- | --- |
| Entity gap | A starting entity cannot be resolved to a node | Add the alias to the existing entity, in the Python dict and in the graph |
| Extraction gap | A gold evidence triple has no matching edge or attribute in the graph | Raise `blame_count` on RelType(question type, relation). Once the relation is in the active schema, extract it from the gold subject's chunks |
| Ranking gap | The evidence is in the graph but was not on the retrieved paths | Raise the weight of relation types on the gold chain, decay those on the chosen path |
| Reasoning gap | The evidence was retrieved and the answer is still wrong | Log only. No graph change |

Implementation notes:

- **Evidence coverage, not answer paths.** Comparison questions and literal answers (yes, no, dates) have no path from seed to answer, so the check is per gold triple.
- **Match triples by subject and object.** The extractor may say `married_to` where the gold says `spouse`. Check that the two endpoints are linked, then map relation names.
- **Store literals** as entity attributes, or every date question stays an extraction gap forever.
- **Reader tuning is out of scope.** It is not graph improvement.
- **Every repair writes a `Mutation` node** with its reason and the question that caused it.

The loop then re-scores the held-out set and records one point on the curve. Run five iterations.

### What is learned: the active schema

The thing being learned is the active schema, the set of relations the planner may use and the system extracts. It starts as the 8 seed relations and, for the static run, stays that way. The planner's relation vocabulary is always the active schema.

- **Candidate pool:** the relations in the gold evidence of the 150 feedback questions, minus the active schema. Feedback only, recorded with the run.
- **Learned policy:** each iteration, add the relations with the highest `blame_count` (summed over question types), at most 2 per iteration, and only those with `blame_count` of at least 2. Each extraction gap adds 1 to the blame of its (question type, relation), creating the `RelType` if it is new.
- **Random policy:** each iteration, add the same number of relations the learned policy added that iteration, drawn uniformly at random from the candidate pool (seed 42).
- **Identical across learned, random and static:** the query-time extraction budget, `CHAIN_BOOST`, k, the fetch limit and every prompt. They live in `config.py` and are recorded in each run's output.
- **Feedback is re-answered only at iterations 0, 2 and 5.** At the other iterations the feedback questions are diagnosed without an answer call (planner and beam, then gold-evidence coverage), and repairs still run. Reasoning gaps are judged only when the question was re-answered.
- **Repair extraction (learned only, feedback):** for each extraction gap whose relation is in the active schema, extract that relation from the gold subject's own chunks, skipping chunks that already have an `EXTRACTED` edge for it. Run as a batch. Written with `EXTRACTED` edges and `Mutation` nodes.
- **Both policies start from the same iteration-0 graph snapshot** (`scripts/learn.py` restores it), so the runs cannot contaminate each other.

## Extraction budget

Every held-out query may spend at most two targeted extraction calls. Which relations can be extracted depends on the active schema, which is where learned and random differ.

- **Trigger:** the planned chain dead-ends at an entity, or a planned date step is missing on the entity that should carry it. Leaves and date steps that follow a complete chain do not count. No labels are involved, so this is legal on held-out questions.
- **Policy:** extract the relation the planner asked for, which must be in the active schema, from that entity's own chunks, skipping chunks that already have an `EXTRACTED` edge for it. Normal (non-batch) calls, then the hop is retried.
- **Held-out only.** Feedback questions learn through repair extraction instead.
- **Cost unit:** one extraction call on one chunk for one relation type. Cost per call is roughly constant, so ranking by blame is enough. No improvement-per-cost estimate.
- **Why per query, not per iteration:** a global budget of 20 chunks per iteration covers about 100 of 1,748 chunks over five iterations. Held-out chunks would almost never be chosen and the curve would stay flat.
- **Control:** the same per-query budget with the schema grown by random relation draws. Learned against random at equal cost is the comparison that shows the learning matters. The random policy runs on held-out only (5 iterations of 87 questions), so it never sees the feedback questions.

## Evaluation

The headline chart is held-out accuracy over five iterations for the learned policy against three reference lines.

| Line | What it is | What it proves |
| --- | --- | --- |
| Learned policy | Full loop: schema growth, reweighting, budgeted extraction | The system improves with use |
| Random policy | Same per-query budget; the schema grows by the same number of relations per iteration, drawn at random from the candidate pool. Runs on held-out only, never on the feedback questions | The gain comes from learning, not from extra extraction |
| Static graph | The iteration-0 shallow graph, never changed | The floor |
| BM25 | Top-5 chunk retrieval by BM25, no graph | Whether the task needs the graph |

- **Metrics:** exact match and F1 on the entity-disjoint held-out set, plus a breakdown by question type and hop count.
- **Noise:** 87 held-out questions gives a noisy curve. Every score carries a bootstrap 95% confidence interval (1,000 resamples, seed 42), computed in `summary.json`. This replaces running extra seeds.
- **Ablations:** ingestion only, reweighting only, both.
- **Cost:** cumulative extraction calls per iteration, reported next to accuracy.
- **Load test:** 50 concurrent queries while a repair batch is writing. Report p50 and p95 latency.

## Generality

The algorithm is not tied to the dataset. It needs a corpus, questions and a feedback signal, behind three functions: `load_corpus()`, `load_questions()` and `score(answer, question)`.

| Feedback available | What still works |
| --- | --- |
| Gold answer and evidence (the benchmark) | All repairs, with evidence-coverage diagnosis |
| Gold answer only | All repairs, with coarser diagnosis from graph checks on the seed and answer entities |
| Thumbs down only | Schema growth, by re-reading chunks around the seed. Reweighting can only decay the path used |
| No feedback | Budgeted extraction on dead-ends and low path scores |

- **Classifier back-ends:** evidence coverage for the benchmark, answer-only and dead-end checks for real use, behind one interface.
- **Question types:** in production they come from the LLM's own classification or its predicted relation chain.
- **Limits:** the approach fits multi-hop factual lookup. It fits poorly for summarisation or "explain why" questions. It transfers across entities, not to relation types it has never seen fail.

## 30-hour build plan

The iteration-0 number must exist by hour 9. Everything after that is the loop.

| Hours | Work | Done when |
| --- | --- | --- |
| 0–2 | HydraDB in Docker. Test `MERGE`, `SET` on relationship properties, `UNWIND`, `ORDER BY` with `LIMIT`. Sample the data | Smoke-test script passes |
| 2–6 | Shallow ingest (chunks, entities, literals, a small seed schema) and the query pipeline | A question returns an answer with its path |
| 6–9 | Eval harness, entity-disjoint split, BM25 and static-graph baselines | Iteration-0 numbers saved to JSON. Due 15 Nov 12:00 IST |
| 9–14 | Evidence-coverage classifier, schema growth, budgeted targeted extraction | Failures are labelled and repairs write `Mutation` nodes |
| 14–18 | Reweighting and the random-policy control. Run five iterations | The curve exists |
| 18–21 | Ablations, bootstrap CIs, load test | Numbers for the README |
| 21–25 | Streamlit demo: curve, path viewer, mutation log | A two-minute walkthrough works |
| 25–28 | Pitch, README, demo video | Submission draft complete |
| 28–30 | Buffer and submit. The buffer ends 16 Nov 07:00 IST | Submitted |

- **Cache every LLM call** on disk by prompt hash, so reruns are free and reproducible.
- **Cut order if behind:** alias repair, then the second demo corpus, then UI polish.
- **Never cut:** the held-out curve and the random-policy control.

## Go-to-market pitch

The one-line pitch: start with a cheap graph, and it deepens only where your users ask.

- **Buyer:** teams running GraphRAG over large document sets who cannot afford full LLM extraction of every document.
- **Problem:** full graph extraction is paid up front for every chunk, including the ones nobody ever asks about.
- **Product:** a layer on HydraDB that spends extraction where queries prove it is needed and learns which relations matter for which questions.
- **Proof:** learned policy against random policy at the same budget, on entities the system had no feedback on.
- **Fit with the sponsor:** it extends HydraDB's own low-cost positioning from storage to ingestion.
- **Pricing idea:** usage based, per query or per extraction call saved.
- **If time allows:** run the same code on a second small corpus, such as HydraDB's own docs, for the live demo. One engine on two corpora shows it is not benchmark-specific.

Pitch what was measured. An incident-debugging story on a Wikipedia benchmark would not hold up under questions.

## Budget

Total spend for the whole project is capped at $10 and enforced in code at $9.00 (`src/llm.py`, ledger in `data/state/spend.json`). Phase caps: ingest $2.06 and smoke $0.47 (what they spent), learning $5.47, and a $1.00 reserve that needs `--use-reserve`. Cached calls cost nothing.

## Smoke test findings (v0.4.0)

The smoke test (`scripts/smoke_test.py`) against HydraDB v0.4.0 found four constraints. The design above follows them.

1. **No computed ordering.** `RETURN` takes only `binding.property` or `count(*)`. Weighted scoring happens in Python after a `LIMIT 200` fetch.
2. **Integer ids only.** Node ids are non-negative integers. Name and alias lookup lives in a Python dict.
3. **Writes only through `UNWIND`.** A standalone `MERGE ... SET` is rejected. All writes go through one helper, `write(query, rows)`, using `UNWIND ... MERGE/CREATE`. No other code builds write Cypher.
4. **No `IN`, `CONTAINS` or `IS NULL` in `WHERE`.** Extraction state is stored as `EXTRACTED` edges and filtered by equality. Every property is written with a default value.

## Risks and first-hour checks

The largest risk is that the BM25 baseline beats the graph overall, because flat RAG is strong on these benchmarks.

| Risk | Mitigation |
| --- | --- |
| BM25 baseline wins overall | Lead with the breakdown by question type and hop count, and with learned against random. Report the overall result plainly |
| HydraDB lacks a Cypher feature we assumed | Checked by `scripts/smoke_test.py` on 0.4.0. Constraints are listed in Smoke test findings. Re-run the smoke test if the image changes |
| Dataset format differs from what we assumed | Confirm evidence triples and question-type labels before writing the classifier |
| Curve is flat | Check that the budget is per query and that iteration 0 is shallow enough to leave room |
| Curve is noisy | Bootstrap 95% CIs on the held-out set |
| Label leakage | Gold data is read only for feedback questions. One code path loads labels, and the held-out loader does not call it |
| LLM cost or rate limits | Disk cache by prompt hash. Use a small, fast model for extraction |

First-hour checklist:

- [x] HydraDB v0.4.0 runs locally from the Docker image ([README](https://raw.githubusercontent.com/hydra-db/hydradb/main/README.md))
- [x] The Neo4j Python driver connects over Bolt
- [x] `MERGE`, `SET` on a relationship property, `UNWIND` batch writes and `ORDER BY` with `LIMIT` all work
- [x] 2WikiMultihopQA sample loaded, evidence triples and question types present
- [x] Submission deadline and required deliverables confirmed with the organisers (due 16 Nov 2026, 09:00 IST)