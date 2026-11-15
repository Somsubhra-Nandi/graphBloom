"""Cost of extracting all 22 relations up front versus our approach, and a projection to 100k and 1M documents.
Arithmetic on measured numbers only, $0: every input and output token count comes from the response cache of the real
shallow ingest (8 relations, Message Batches API). Writes results/cost_projection.json.
  .venv/bin/python scripts/cost_projection.py
"""
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import ingest  # noqa: E402
import learn  # noqa: E402
from src import config  # noqa: E402
from src.graph import normalize  # noqa: E402

R = config.ROOT / "results"
PIN, POUT = config.PRICE_PER_MTOK[config.EXTRACT_MODEL]
BATCH = config.BATCH_DISCOUNT
CORPUS_CHUNKS = 1748  # chunks in the learned_iter5 graph

corpus = [json.loads(x) for x in open(config.SPLIT_DIR / "corpus.jsonl")]
feedback = [json.loads(x) for x in open(config.SPLIT_DIR / "feedback.jsonl")]
pool = learn.candidate_pool(feedback)
assert len(pool) == 14, len(pool)


def chars(prompt, schema):
    return len(ingest.SYSTEM) + len(prompt) + len(json.dumps(schema))


def prompt22(chunk):
    base = ingest.build_prompt(chunk)
    extra = "".join(
        f"- {r}: " + (f"the {r} of the subject: a date, written as in the text" if info["literal"] else f"the subject's {r}: the object is the entity that is the {r} of the subject") + "\n"
        for r, info in pool.items()
    )
    head, tail = base.split("\n\nRules:", 1)
    return head + "\n" + extra.rstrip("\n") + "\n\nRules:" + tail


schema22 = json.loads(json.dumps(ingest.SCHEMA))
schema22["properties"]["triples"]["items"]["properties"]["relation"]["enum"] = list(config.SEED_RELATIONS) + list(pool)

in8 = out8 = ch8 = ch22 = n = 0
pts = []  # (characters, measured input tokens) per chunk
for c in corpus:
    u = ingest.chunk_usage(c)
    if not u:
        continue
    n += 1
    in8 += u[0]
    out8 += u[1]
    ch8 += chars(ingest.build_prompt(c), ingest.SCHEMA)
    pts.append((chars(ingest.build_prompt(c), ingest.SCHEMA), u[0]))
    ch22 += chars(prompt22(c), schema22)
assert n == len(corpus), f"{n} of {len(corpus)} chunks priced from the cache"
# tokens per character is the slope of measured input tokens against prompt characters across the chunks (the intercept
# absorbs the fixed tool-call overhead); the extra relations add characters at that slope
mx, my = ch8 / n, in8 / n
tok_per_char = sum((x - mx) * (y - my) for x, y in pts) / sum((x - mx) ** 2 for x, _ in pts)
in22_per = my + tok_per_char * (ch22 - ch8) / n

# output: the extractor writes one triple per fact. More relations means more facts per chunk; the gold evidence of the
# feedback questions says how many more (triples in any of the 22 relations over triples in the 8 seeds).
seeds = {normalize(r) for r in config.SEED_RELATIONS}
allrel = seeds | {normalize(r) for r in pool}
ev = Counter()
for q in feedback:
    for _, rel, _ in q["evidences"]:
        k = normalize(rel)
        ev["seed" if k in seeds else "pool" if k in allrel else "other"] += 1
mult = (ev["seed"] + ev["pool"]) / ev["seed"]
out8_per = out8 / n


def per_chunk(in_tok, out_tok, batch):
    return (in_tok * PIN + out_tok * POUT) / 1e6 * (BATCH if batch else 1)


c8 = {m: per_chunk(in8 / n, out8_per, m == "batch") for m in ("normal", "batch")}
c22 = {m: per_chunk(in22_per, out8_per * mult, m == "batch") for m in ("normal", "batch")}
c22_low = {m: per_chunk(in22_per, out8_per, m == "batch") for m in ("normal", "batch")}

cc = json.loads((R / "cost_comparison.json").read_text())["per_1000_future_queries"]
learned_one_time = cc["learned"]["one_time_usd"]
per1k = {"ours_recurring": cc["learned"]["recurring_usd_per_1000_queries"],
         "ours_extraction_part": cc["learned"]["recurring_parts_usd_per_1000"]["query_time_extraction"],
         "full_extraction_recurring": cc["open_vocab"]["recurring_parts_usd_per_1000"]["planner"] + cc["open_vocab"]["recurring_parts_usd_per_1000"]["answer"]}


def money(x):
    return round(x, 2) if x >= 10 else round(x, 4)


def at(docs):
    return {
        "documents": docs,
        "full_extraction_22_relations": {"normal": money(c22["normal"] * docs), "batch": money(c22["batch"] * docs),
                                         "batch_if_output_does_not_grow": money(c22_low["batch"] * docs)},
        "shallow_ingest_8_relations": {"normal": money(c8["normal"] * docs), "batch": money(c8["batch"] * docs)},
        "extra_for_the_14_relations_in_one_pass": {"normal": money((c22["normal"] - c8["normal"]) * docs), "batch": money((c22["batch"] - c8["batch"]) * docs)},
    }


docs_list = [CORPUS_CHUNKS, 100_000, 1_000_000]
queries_list = [1_000, 10_000, 100_000, 1_000_000]


def totals(docs, queries, batch=True):
    k = "batch" if batch else "normal"
    full = c22[k] * docs + per1k["full_extraction_recurring"] * queries / 1000
    ours = c8[k] * docs + learned_one_time + per1k["ours_recurring"] * queries / 1000
    return {"documents": docs, "queries": queries, "full_extraction_total": money(full), "ours_total": money(ours)}


# queries at which ours stops being cheaper: extra recurring cost of query-time extraction against the extra ingest bill
extra_per_doc = c22["batch"] - c8["batch"]
extra_per_query = (per1k["ours_recurring"] - per1k["full_extraction_recurring"]) / 1000


def break_even(docs):
    return max(0, round((extra_per_doc * docs - learned_one_time) / extra_per_query))


scaling = []  # the extra cost of the 14 relations beyond the shallow ingest, as documents grow
for i in range(25):
    d = round(CORPUS_CHUNKS * (1_000_000 / CORPUS_CHUNKS) ** (i / 24))
    scaling.append({"documents": d, "full_extra_batch": money(extra_per_doc * d)})
ours_extra = {str(q): money(learned_one_time + extra_per_query * q) for q in queries_list}  # does not depend on documents

out = {
    "note": "Arithmetic on measured token counts, $0. Ingest ran through the Message Batches API at 50% price; query-time extraction needs an answer now, so it is priced at the normal rate.",
    "model": config.EXTRACT_MODEL, "price_per_mtok": {"input": PIN, "output": POUT, "batch_discount": BATCH},
    "measured_shallow_ingest": {"chunks": n, "input_tokens_per_chunk": round(in8 / n), "output_tokens_per_chunk": round(out8_per),
                                "usd_per_chunk": {k: round(v, 6) for k, v in c8.items()}, "usd_total": {k: round(v * n, 4) for k, v in c8.items()}},
    "full_extraction_model": {"relations": 22, "input_tokens_per_chunk": round(in22_per), "tokens_per_char": round(tok_per_char, 4),
                              "output_multiplier": round(mult, 3), "output_multiplier_basis": f"gold evidence of the {len(feedback)} feedback questions: {ev['seed']} triples in the 8 seed relations, {ev['pool']} more in the 14 pool relations",
                              "output_tokens_per_chunk": round(out8_per * mult),
                              "usd_per_chunk": {k: round(v, 6) for k, v in c22.items()}, "usd_per_chunk_if_output_does_not_grow": {k: round(v, 6) for k, v in c22_low.items()}},
    "ours": {"learned_one_time_usd": learned_one_time, "per_1000_queries_usd": per1k,
             "learned_cost_assumption": "held constant with corpus size: it depends on the 150 feedback questions and the repair chunks they touch, not on how many documents exist"},
    "projection": [at(x) for x in docs_list],
    "totals": [totals(x, q) for x in docs_list for q in queries_list],
    "break_even_queries": {str(x): break_even(x) for x in docs_list},
    "scaling": scaling,
    "ours_extra_by_queries": ours_extra,
    "caveats": ["The corpus is 1,748 short single-paragraph chunks; 100k and 1M documents are scaled linearly from the measured per-chunk cost.",
                "Both approaches pay the shallow ingest: the shallow pass is most of the cost of a full pass, because the paragraph text dominates the input.",
                "The output multiplier is an estimate from gold evidence counts, not a measurement; the lower bound with no output growth is also given.",
                "Query-time extraction is priced per question; repeated questions about the same entities reuse earlier extractions, so the per-question figure is an upper estimate for repeated topics.",
                "Full extraction is shown as the 22 relations in a single pass. It also has no query-time extraction, so its per-query cost is planner plus answer only."],
}
(R / "cost_projection.json").write_text(json.dumps(out, indent=1))
print(json.dumps({k: out[k] for k in ("measured_shallow_ingest", "full_extraction_model", "projection", "break_even_queries")}, indent=1))
