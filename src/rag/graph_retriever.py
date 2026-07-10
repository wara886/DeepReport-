"""Graph retriever placeholder for the P2.1 Hybrid RAG contract.

The entity/relation store is implemented in P2.2. This adapter keeps the
retrieval contract stable without inventing graph data.
"""

from __future__ import annotations

from typing import Any


class GraphRetriever:
    def __init__(self, records: list[Any] | None = None) -> None:
        self.records = records or []

    def search(self, query: str, *, topk: int = 10) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        del query, topk
        return [], {"backend": "not_configured", "hit_count": 0, "available": False}
