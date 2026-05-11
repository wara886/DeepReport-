"""Optional Chroma-style vector retrieval with lightweight local fallback."""

from __future__ import annotations

import hashlib
import math
from typing import Dict, List, Sequence

from src.retrieval.evidence_store import EvidenceRecord


DEFAULT_EMBEDDING_MODEL = "BAAI/bge-small-en-v1.5"
_EMBEDDER_CACHE: Dict[str, object] = {}


class ChromaIndex:
    """A small vector index that prefers Chroma, then falls back to in-memory search."""

    def __init__(self, model_name: str = DEFAULT_EMBEDDING_MODEL):
        self.model_name = model_name
        self._records: List[EvidenceRecord] = []
        self._vectors: List[List[float]] = []
        self._backend = "memory"

        try:
            import chromadb  # type: ignore

            self._client = chromadb.EphemeralClient()
            self._collection = self._client.get_or_create_collection(name="deepreport_local_evidence")
            self._backend = "chromadb"
        except Exception:
            self._client = None
            self._collection = None

    @property
    def backend(self) -> str:
        return self._backend

    def add_records(self, records: Sequence[EvidenceRecord]) -> None:
        self._records = list(records)
        docs = [record.searchable_text for record in self._records]
        embeddings = embed_texts(docs, model_name=self.model_name)
        self._vectors = embeddings

        if self._collection is not None:
            self._collection.upsert(
                ids=[record.sample_id or f"record_{index}" for index, record in enumerate(self._records)],
                documents=docs,
                embeddings=embeddings,
                metadatas=[_sanitize_metadata(record.to_dict()) for record in self._records],
            )

    def search(self, query: str, topk: int = 5) -> List[Dict[str, object]]:
        if not self._records:
            return []

        query_vector = embed_texts([query], model_name=self.model_name)[0]
        if self._collection is not None:
            result = self._collection.query(
                query_embeddings=[query_vector],
                n_results=max(topk, 1),
                include=["distances", "metadatas"],
            )
            metadatas = result.get("metadatas", [[]])[0]
            distances = result.get("distances", [[]])[0]
            output = []
            for metadata, distance in zip(metadatas, distances):
                row = dict(metadata or {})
                row["vector_score"] = max(0.0, 1.0 - float(distance or 0.0))
                output.append(row)
            return output

        scored = []
        for record, vector in zip(self._records, self._vectors):
            scored.append(
                {
                    **record.to_dict(),
                    "vector_score": cosine_similarity(query_vector, vector),
                }
            )
        scored.sort(key=lambda item: float(item.get("vector_score", 0.0)), reverse=True)
        return scored[:topk]


def embed_texts(texts: Sequence[str], model_name: str = DEFAULT_EMBEDDING_MODEL) -> List[List[float]]:
    embedder = _EMBEDDER_CACHE.get(model_name)
    if embedder is None:
        try:
            from sentence_transformers import SentenceTransformer  # type: ignore

            embedder = SentenceTransformer(model_name)
            _EMBEDDER_CACHE[model_name] = embedder
        except Exception:
            embedder = False
            _EMBEDDER_CACHE[model_name] = embedder

    if embedder and embedder is not False:
        vectors = embedder.encode(list(texts), normalize_embeddings=True)
        return [[float(value) for value in vector] for vector in vectors]
    return [_hash_embed(text) for text in texts]


def cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return dot / (left_norm * right_norm)


def _hash_embed(text: str, dims: int = 96) -> List[float]:
    vector = [0.0] * dims
    for token in str(text).lower().split():
        digest = hashlib.sha1(token.encode("utf-8")).digest()
        bucket = int.from_bytes(digest[:2], "big") % dims
        sign = 1.0 if digest[2] % 2 == 0 else -1.0
        vector[bucket] += sign
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0.0:
        return vector
    return [value / norm for value in vector]


def _sanitize_metadata(metadata: Dict[str, object]) -> Dict[str, object]:
    """Keep metadata compatible with Chroma scalar-only constraints."""

    output: Dict[str, object] = {}
    for key, value in metadata.items():
        if value is None:
            output[key] = ""
        elif isinstance(value, (str, int, float, bool)):
            output[key] = value
        elif isinstance(value, (list, dict)):
            output[key] = str(value)
        else:
            output[key] = str(value)
    return output
