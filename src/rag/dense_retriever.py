"""Dense/vector retriever adapter with safe fallback metadata."""

from __future__ import annotations

import hashlib
from typing import Any

from src.retrieval.chroma_index import ChromaIndex


class DenseRetriever:
    def __init__(self, records: list[Any], *, index_factory: Any | None = None) -> None:
        self.records = records
        self.index_factory = index_factory or (
            lambda: ChromaIndex(
                persistent_path=None,
                collection_name=_ephemeral_collection_name(self.records),
            )
        )

    def search(self, query: str, *, topk: int = 10) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        if not self.records:
            return [], {"backend": "no_records", "hit_count": 0, "available": False}
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
            embedding_backend = str(getattr(index, "embedding_backend", "unknown"))
            return output, {
                "backend": getattr(index, "backend", "vector"),
                "embedding_backend": embedding_backend,
                "semantic_available": embedding_backend == "sentence_transformers",
                "degraded": embedding_backend == "hash_fallback",
                "hit_count": len(output),
                "available": True,
            }
        except Exception as exc:  # noqa: BLE001 - retrieval layer must degrade safely.
            return [], {"backend": "disabled", "hit_count": 0, "available": False, "error": str(exc)}


def _ephemeral_collection_name(records: list[Any]) -> str:
    identities: list[str] = []
    for index, record in enumerate(records):
        value = (
            getattr(record, "identity_key", "")
            or getattr(record, "sample_id", "")
            or getattr(record, "evidence_id", "")
        )
        if not value and hasattr(record, "to_dict"):
            payload = record.to_dict()
            value = payload.get("identity_key") or payload.get("sample_id") or payload.get("evidence_id")
        identities.append(str(value or index))
    digest = hashlib.sha1("|".join(sorted(identities)).encode("utf-8")).hexdigest()[:16]
    return f"finsight_ephemeral_{digest}"
