"""FAISS index interface placeholder for later stages."""

from __future__ import annotations

from typing import Dict, List


class FaissIndex:
    """Interface-only placeholder. Real FAISS implementation is intentionally deferred."""

    def __init__(self) -> None:
        self._enabled = False

    def add(self, vectors: List[List[float]], metadata: List[Dict[str, object]]) -> None:
        raise NotImplementedError("FAISS implementation is deferred. Use BM25 in Stage 7.")

    def search(self, query_vector: List[float], topk: int = 5) -> List[Dict[str, object]]:
        raise NotImplementedError("FAISS implementation is deferred. Use BM25 in Stage 7.")

