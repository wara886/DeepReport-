"""Dense/vector retriever adapter with safe fallback metadata."""

from __future__ import annotations

from typing import Any

from src.retrieval.chroma_index import ChromaIndex


class DenseRetriever:
    def __init__(self, records: list[Any], *, index_factory: Any | None = None) -> None:
        self.records = records
        self.index_factory = index_factory or ChromaIndex

    def search(self, query: str, *, topk: int = 10) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        try:
            index = self.index_factory()
            index.add_records(self.records)
            hits = index.search(query=query, topk=topk)
            output: list[dict[str, Any]] = []
            for hit in hits:
                item = dict(hit)
                item["vector_score"] = float(item.get("vector_score", item.get("score", 0.0)) or 0.0)
                item["score"] = item["vector_score"]
                output.append(item)
            return output, {"backend": getattr(index, "backend", "vector"), "hit_count": len(output), "available": True}
        except Exception as exc:  # noqa: BLE001 - retrieval layer must degrade safely.
            return [], {"backend": "disabled", "hit_count": 0, "available": False, "error": str(exc)}
