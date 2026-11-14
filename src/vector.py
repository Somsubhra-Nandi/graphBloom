"""Vector-only baseline retriever: top-k chunks for a question, no graph.

sentence-transformers could not be installed (PyPI unreachable: DNS failure), and neither could rank_bm25,
so this is a small in-repo Okapi BM25 over title + text. It costs nothing and needs no network. The retriever
interface (`top_k(question, k)`) is what a sentence-transformers retriever would also expose.
"""
import json
import math
import re
from collections import Counter

from src import config
from src.graph import normalize

_STOP = set("a an the of and or in on at to for is was were are be by with as from that this it its which who whom whose what when where did do does has have had".split())


def tokens(text):
    return [t for t in normalize(text).split() if t not in _STOP]


class BM25Retriever:
    def __init__(self, k1=1.5, b=0.75):
        self.k1, self.b = k1, b
        self.docs = [json.loads(l) for l in open(config.SPLIT_DIR / "corpus.jsonl")]
        self.tf = [Counter(tokens(d["title"] + " " + d["text"])) for d in self.docs]
        self.len = [sum(c.values()) for c in self.tf]
        self.avg = sum(self.len) / len(self.len)
        df = Counter(t for c in self.tf for t in c)
        n = len(self.docs)
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}
        self.inv = {}
        for i, c in enumerate(self.tf):
            for t in c:
                self.inv.setdefault(t, []).append(i)

    def top_k(self, question, k=config.ANSWER_MAX_CHUNKS):
        scores = Counter()
        for t in set(tokens(question)):
            if t not in self.idf:
                continue
            for i in self.inv[t]:
                f = self.tf[i][t]
                scores[i] += self.idf[t] * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * self.len[i] / self.avg))
        ranked = sorted(scores, key=lambda i: (-scores[i], i))[:k]  # ties broken by corpus position: stable
        return [{"title": self.docs[i]["title"], "text": self.docs[i]["text"], "score": round(scores[i], 4)} for i in ranked]
