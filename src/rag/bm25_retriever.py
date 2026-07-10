"""BM25 retriever adapter for the P2 Hybrid RAG layer."""

from __future__ import annotations

from typing import Any

from src.retrieval.bm25_index import BM25Index


class BM25Retriever:
    def __init__(self, records: list[Any]) -> None:
        self.records = records

    def search(self, query: str, *, topk: int = 10) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        hits = BM25Index(self.records).search(query=query, topk=topk)
        output: list[dict[str, Any]] = []
        for hit in hits:
            item = hit.record.to_dict()
            item["bm25_score"] = float(hit.score)
            item["score"] = float(hit.score)
            output.append(item)
        return output, {"backend": "bm25", "hit_count": len(output)}
