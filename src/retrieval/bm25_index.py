"""Minimal BM25 implementation for local retrieval."""

from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Dict, Iterable, List, Sequence, Tuple

from src.retrieval.evidence_store import EvidenceRecord


TOKEN_RE = re.compile(r"[a-zA-Z0-9_]+")


def tokenize(text: str) -> List[str]:
    return [m.group(0).lower() for m in TOKEN_RE.finditer(text or "")]


@dataclass
class BM25Hit:
    score: float
    record: EvidenceRecord


class BM25Index:
    """Simple BM25 index for evidence documents."""

    def __init__(self, records: Sequence[EvidenceRecord], k1: float = 1.5, b: float = 0.75):
        self.records = list(records)
        self.k1 = k1
        self.b = b
        self.doc_tokens: List[List[str]] = [tokenize(r.searchable_text) for r in self.records]
        self.doc_len = [len(tokens) for tokens in self.doc_tokens]
        self.avgdl = (sum(self.doc_len) / len(self.doc_len)) if self.doc_len else 0.0
        self.tf: List[Counter] = [Counter(tokens) for tokens in self.doc_tokens]
        self.df: Dict[str, int] = defaultdict(int)
        for counter in self.tf:
            for term in counter.keys():
                self.df[term] += 1
        self.doc_count = len(self.records)

    def _idf(self, term: str) -> float:
        n_q = self.df.get(term, 0)
        if self.doc_count == 0:
            return 0.0
        # Standard BM25 idf with +1 to keep positive range.
        return math.log(1 + (self.doc_count - n_q + 0.5) / (n_q + 0.5))

    def search(self, query: str, topk: int = 5) -> List[BM25Hit]:
        if not self.records:
            return []

        q_terms = tokenize(query)
        if not q_terms:
            return []

        scores: List[Tuple[float, EvidenceRecord]] = []
        for idx, record in enumerate(self.records):
            tf = self.tf[idx]
            dl = self.doc_len[idx]
            score = 0.0
            for term in q_terms:
                f_qd = tf.get(term, 0)
                if f_qd == 0:
                    continue
                idf = self._idf(term)
                denom = f_qd + self.k1 * (1 - self.b + self.b * (dl / (self.avgdl or 1.0)))
                score += idf * ((f_qd * (self.k1 + 1)) / (denom or 1.0))
            if score > 0:
                scores.append((score, record))

        scores.sort(key=lambda x: x[0], reverse=True)
        return [BM25Hit(score=s, record=r) for s, r in scores[:topk]]

