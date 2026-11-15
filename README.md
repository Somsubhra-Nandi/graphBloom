# GraphBloom

A knowledge graph that starts shallow and learns which facts it is missing from the questions it gets wrong, so it only pays to extract what people actually ask about.

Demo: https://graphbloom.vercel.app

## Result

Held-out accuracy on 87 questions about entities the system never saw during learning, from the 2WikiMultihopQA benchmark. EM is exact match; F1 is word overlap. Ranges are 95% bootstrap intervals (1,000 resamples, seed 42).

| System | EM | EM 95% range | F1 | F1 95% range |
|---|---|---|---|---|
| **Learned** (5 rounds) | 0.575 | 0.471 to 0.678 | 0.700 | 0.607 to 0.786 |
| Random picks (seed 42) | 0.517 | 0.414 to 0.621 | 0.658 | 0.567 to 0.748 |
| Random picks (seed 7) | 0.529 | 0.425 to 0.632 | 0.671 | 0.579 to 0.757 |
| Open vocabulary (told the 14 candidate relations up front, one pass) | 0.552 | 0.448 to 0.655 | 0.692 | 0.599 to 0.779 |
| Static graph (never learns) | 0.471 | 0.368 to 0.575 | 0.597 | 0.505 to 0.692 |
| BM25 keyword search (top 5 paragraphs, no graph) | 0.230 | 0.149 to 0.322 | 0.303 | 0.213 to 0.404 |

Starting from the same shallow graph (EM 0.471), learned reached 0.529 after one round and 0.575 after five. Paired differences in EM, with 95% range (10,000 resamples):

- learned over static: +0.103 (0.035 to 0.184)
- learned over random, seed 42: +0.058 (0.011 to 0.115)
- learned over random, seed 7: +0.046 (0.000 to 0.103)
- learned over open vocabulary: +0.023 (0.000 to 0.058)
- static over BM25: +0.241 (0.126 to 0.356)

Learned spent $2.58 of API calls in the learning phase (Claude Haiku 4.5 for every call).

## How it works

1. **Read.** Each paragraph is read once into a small graph that has 8 kinds of link (director, date of birth, country and so on).
2. **Ask.** Practice questions are answered by following links. When a link is missing, the path ends at a dead end, and the system records which kind of link was missing.
3. **Fix.** For the most-missed kinds of link, the source text is read again for just that one kind and the new links are added. Five rounds took the graph from 8 kinds of link to 18.
4. **Check.** The new graph is scored on questions it has never seen. Answers come from the model reading the graph path and the source paragraphs; the graph only decides which paragraphs and facts it sees.

## What this does and does not show

- **Small test.** 87 held-out questions, one split, one benchmark. Differences of a few points are within noise.
- **Learning beats random modestly.** A random choice of what to extract also helps (0.517 and 0.529). Learned is ahead by 0.058 and 0.046 EM. For seed 7 the range starts at 0.000, and the F1 differences include zero. Learned matched random's final accuracy after one round, and random needed all five.
- **It does not beat knowing the relations; it replaces needing to know them.** A version told the right link types up front scores 0.552 against learned's 0.575, which is within noise (learned ahead by +0.023, range 0.000 to 0.058). Learning finds those link types from feedback and ends with a smaller schema (18 kinds of link against 22).
- **Learning uses gold evidence.** The feedback questions come with the correct supporting facts, and the learner reads the missing link types from them. The random and open-vocabulary baselines draw from the same list. Learning from real users without labels is not built yet (see the roadmap).
- **Both parts are needed.** Growing the list of link types without extracting the facts changes nothing: that run equals the static graph at every round.

## Speed under load

50 questions at once. The language model is replaced by saved answers, so these numbers are the graph alone; a real question adds one to three seconds for the model.

| | questions | median | slowest 5% | slowest | errors |
|---|---|---|---|---|---|
| No writes | 750 | 121 ms | 169 ms | 237 ms | 0 |
| While a writer adds 2,707 nodes a second for 120 s | 28,800 | 149 ms | 209 ms | 411 ms | 0 |

The writer committed 325,200 nodes and 325,200 edges in that time; its batches of 200 took 28 ms (median) and 77 ms (slowest 5%). The test data was deleted afterwards and the saved graph restored.

## Cost

Per 1,000 questions, after setup (from the cached prompts of the 87 held-out questions; extraction calls per question are estimated from each run's total):

| System | Per 1,000 questions | EM |
|---|---|---|
| Learned | $4.21 | 0.575 |
| Random (seed 42) | $3.77 | 0.517 |
| Random (seed 7) | $3.77 | 0.529 |
| Open vocabulary | $4.04 | 0.552 |

Learned pays one-time $1.76 for feedback evaluation, diagnosis and repairs. It costs slightly more per question than the others because it extracts more of what questions need.

**Against extracting everything up front.** From the measured token counts of the real ingest (1,190 input and 179 output tokens per paragraph at 8 link types, run through the batch API at half price) we projected extracting all 22 link types in one pass. The input side is measured; the output growth (1.605x) is an estimate from the gold evidence counts, and the lower bound with no growth is in `results/cost_projection.json`.

| Documents | Shallow ingest, 8 link types (batch) | Extract all 22 (batch) | Extract all 22 (normal price) |
|---|---|---|---|
| 1,748 | $1.82 | $2.63 | $5.26 |
| 100,000 | $104.19 | $150.42 | $300.85 |
| 1,000,000 | $1,042 | $1,504 | $3,008 |

Both approaches pay for the shallow pass. What differs is the extra cost of the other 14 link types: for full extraction it grows with the number of documents ($462.29 at 1 million); for ours it is a one-time $1.76 plus the cost of the questions asked, so it does not depend on the number of documents (an assumption: the one-time cost was measured on one corpus). Totals including questions, at the batch rate:

| Documents, questions | Extract all up front | Ours |
|---|---|---|
| 100,000, 10,000 | $182.02 | $148.05 |
| 1,000,000, 10,000 | $1,536 | $1,086 |

At our own 1,748 documents, extracting everything is cheaper. Ours is cheaper past roughly 26,500 documents at 10,000 questions, and stops being cheaper once the questions asked exceed about 439,000 over 1 million documents. These are linear projections from one small corpus of short paragraphs.

**Who it is for.** Large collections where most documents are rarely asked about: legal discovery, enterprise archives, research libraries.

**Who it is not for.** Small collections that are asked about heavily. There, extracting everything up front is cheaper.

## Reproduce

Everything below needs Python 3.13, Docker, and `pip install -r requirements.txt`. The graph database is HydraDB 0.4.0 in a local container (`scripts/start_hydradb.sh`).

**At $0, from the replay bundle (no API key).** Every model call was cached by its exact input, and the bundle holds that cache and the saved final graph, so the replay makes no API calls and spends nothing. The bundle is `replay-bundle.zip`, an asset of the [v1.0 release](https://github.com/Somsubhra-Nandi/graphBloom/releases/tag/v1.0).

```bash
# 1. download the bundle from the v1.0 release and unzip it at the repo root
curl -L -o replay-bundle.zip https://github.com/Somsubhra-Nandi/graphBloom/releases/download/v1.0/replay-bundle.zip
unzip replay-bundle.zip                 # creates .cache/llm and data/snapshots/learned_iter5

# 2. Python environment (3.13)
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

# 3. start HydraDB (local container) and restore the saved final graph
scripts/start_hydradb.sh
.venv/bin/python scripts/snapshot.py restore learned_iter5   # checks 3,791 entities and 2,718 links

# 4. re-run the replay checks
.venv/bin/python scripts/reproduce.py
```

Expected end of the output: `9/9 checks passed, 1 skipped`. The checks recompute every EM and F1 from the stored predictions, rebuild `results/curve.json` and the paired intervals, and replay the 87 held-out questions through the restored graph and the cache, which must give the stored iteration-5 predictions with 0 differing and 0 cache misses. The one skipped check regenerates the data split from seed 42 and needs the benchmark download at `data/raw/dev.json`; with that file in place all 10 run. `.env` is not needed.

**On your own documents.**

1. Put one JSON object per paragraph, with `title` and `text`, in `data/split/corpus.jsonl` (or point `SPLIT_DIR` in `src/config.py` at your own folder), and set `ANTHROPIC_API_KEY` in `.env`.
2. Shallow ingest: `.venv/bin/python scripts/ingest.py --estimate-only` prints the cost first; `--all` runs it through the batch API. Edit `SEED_RELATIONS` in `src/config.py` to the link types your documents have.
3. Ask questions: `QueryEngine().answer("...")` in `src/query.py` returns the path, the dead ends and the answer.
4. Learning (`scripts/learn.py --policy learned --until 5`) needs feedback questions with their correct supporting facts, in `data/split/feedback.jsonl`. Without those it cannot run today.

## Roadmap

Learn from user thumbs-down, and from dead ends, without labelled feedback questions.

## Repository

- `src/`: ingest, graph, planner and query code
- `scripts/`: ingest, learning, baselines, load test, cost projection, demo export
- `results/`: every result file; `REPORT_overnight.md` has the full tables and caveats
- `demo/`: the static demo site (`demo/README.md` covers running and deploying it)
