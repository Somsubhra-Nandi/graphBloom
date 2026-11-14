"""Exact match and F1 as in the 2WikiMultihopQA / HotpotQA evaluation script.

normalize_answer: lowercase, drop punctuation, drop articles (a, an, the), collapse whitespace.
F1 is token overlap; if either side is yes / no / noanswer and the two differ, F1 is 0.
"""
import random
import re
import string
from collections import Counter


def normalize_answer(s):
    s = (s or "").lower()
    s = "".join(ch for ch in s if ch not in set(string.punctuation))
    s = re.sub(r"\b(a|an|the)\b", " ", s)
    return " ".join(s.split())


def exact_match(pred, gold):
    return float(normalize_answer(pred) == normalize_answer(gold))


def f1_score(pred, gold):
    p, g = normalize_answer(pred), normalize_answer(gold)
    special = {"yes", "no", "noanswer"}
    if (p in special or g in special) and p != g:
        return 0.0
    pt, gt = p.split(), g.split()
    common = Counter(pt) & Counter(gt)
    same = sum(common.values())
    if same == 0:
        return 0.0
    prec, rec = same / len(pt), same / len(gt)
    return 2 * prec * rec / (prec + rec)


def bootstrap_ci(values, resamples=1000, seed=42, alpha=0.05):
    """95% percentile bootstrap confidence interval for the mean of `values`."""
    n = len(values)
    if n == 0:
        return None
    rng = random.Random(seed)
    means = sorted(sum(values[rng.randrange(n)] for _ in range(n)) / n for _ in range(resamples))
    return [round(means[int(alpha / 2 * resamples)], 4), round(means[int((1 - alpha / 2) * resamples) - 1], 4)]
