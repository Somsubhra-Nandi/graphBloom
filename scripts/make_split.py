"""Build the feedback / entity-disjoint held-out split and the pooled corpus.

Run: .venv/bin/python scripts/make_split.py
Seed 42. Reads data/raw/dev.json, writes data/split/{feedback,heldout,corpus}.jsonl and split_report.json.
"""
import json
import random
import re
from collections import Counter, defaultdict
from pathlib import Path

from inspect_dataset import is_literal

SEED = 42
N_FEEDBACK = 150
N_HELDOUT_CANDIDATES = 100
MIN_HELDOUT = 70
DEV = Path("data/raw/dev.json")
OUT = Path("data/split")

PAREN = re.compile(r"\s*\([^)]*\)\s*$")


def norm(name):
    """Normalise an entity name: lowercase, strip a trailing '(film)'-style qualifier."""
    return PAREN.sub("", name).strip().lower()


def entities(rec):
    """Entities in the evidence: every non-literal subject or object."""
    return {norm(x) for s, _, o in rec["evidences"] for x in (s, o) if not is_literal(x)}


def stratified_counts(pool_by_type, total):
    """Split `total` across types in proportion to the dev distribution (largest remainder)."""
    n = sum(len(v) for v in pool_by_type.values())
    raw = {t: total * len(v) / n for t, v in pool_by_type.items()}
    out = {t: int(x) for t, x in raw.items()}
    for t in sorted(raw, key=lambda t: raw[t] - out[t], reverse=True)[: total - sum(out.values())]:
        out[t] += 1
    return out


def main():
    data = json.load(open(DEV))
    rng = random.Random(SEED)
    by_type = defaultdict(list)
    for r in data:
        by_type[r["type"]].append(r)
    for t in sorted(by_type):  # sorted for a stable order, then seeded shuffle
        rng.shuffle(by_type[t])

    # Feedback: first N_FEEDBACK of each type's shuffled list, stratified.
    fb_counts = stratified_counts(by_type, N_FEEDBACK)
    feedback = []
    cursor = {}
    for t in sorted(by_type):
        feedback += by_type[t][: fb_counts[t]]
        cursor[t] = fb_counts[t]
    fb_ents = set().union(*(entities(r) for r in feedback))

    # Held-out candidates: drawn next in the same shuffled lists, stratified.
    # Start with N_HELDOUT_CANDIDATES; if fewer than MIN_HELDOUT survive, draw more batches of the
    # same size (never reusing a record) until enough survive.
    candidates, survivors, rounds = [], [], 0
    while len(survivors) < MIN_HELDOUT:
        rounds += 1
        counts = stratified_counts(by_type, N_HELDOUT_CANDIDATES)
        batch = []
        for t in sorted(by_type):
            batch += by_type[t][cursor[t] : cursor[t] + counts[t]]
            cursor[t] += counts[t]
        if not batch:
            raise SystemExit("ran out of dev questions before reaching the minimum")
        candidates += batch
        survivors += [r for r in batch if not (entities(r) & fb_ents)]
    dropped = [r for r in candidates if entities(r) & fb_ents]

    # Entity-disjoint among the kept held-out is not required; only against feedback.
    heldout = survivors

    # Shared-entity diagnostics: what is causing the drops.
    shared = Counter(e for r in dropped for e in entities(r) & fb_ents)

    # Leakage rule: only the 150 feedback questions expose gold evidence. Held-out records keep the
    # question and the gold answer (needed for scoring) but drop `evidences` and `supporting_facts`,
    # so no code that loads held-out data can read gold evidence, even by accident. `context` is
    # dropped from both files because the paragraphs live in corpus.jsonl, pooled, so retrieval is
    # not handed the right ten paragraphs.
    def feedback_rec(r):
        return {k: r[k] for k in ("_id", "type", "question", "answer", "evidences", "supporting_facts")}

    def heldout_rec(r):
        return {k: r[k] for k in ("_id", "type", "question", "answer")}

    # Corpus: paragraphs of every drawn question (feedback + all candidates, kept or dropped).
    corpus, conflicts = {}, 0
    for r in feedback + candidates:
        for title, sents in r["context"]:
            if title in corpus:
                conflicts += corpus[title]["sentences"] != sents
                continue
            corpus[title] = {"title": title, "sentences": sents, "text": " ".join(sents)}

    OUT.mkdir(parents=True, exist_ok=True)
    for name, rows in (
        ("feedback", [feedback_rec(r) for r in feedback]),
        ("heldout", [heldout_rec(r) for r in heldout]),
        ("corpus", list(corpus.values())),
    ):
        with open(OUT / f"{name}.jsonl", "w") as f:
            for row in rows:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")

    report = {
        "seed": SEED,
        "feedback": dict(Counter(r["type"] for r in feedback)),
        "candidates_drawn": len(candidates),
        "candidate_rounds": rounds,
        "candidates_by_type": dict(Counter(r["type"] for r in candidates)),
        "heldout_survivors": len(heldout),
        "heldout_survivors_by_type": dict(Counter(r["type"] for r in heldout)),
        "dropped": len(dropped),
        "feedback_entities": len(fb_ents),
        "top_shared_entities": shared.most_common(15),
        "corpus_paragraphs": len(corpus),
        "corpus_title_conflicts": conflicts,
        "questions_in_corpus": len(feedback) + len(candidates),
    }
    json.dump(report, open(OUT / "split_report.json", "w"), indent=1, ensure_ascii=False)
    print(json.dumps(report, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
