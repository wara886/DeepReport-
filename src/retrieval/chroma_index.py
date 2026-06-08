"""Optional Chroma-style vector retrieval with lightweight local fallback."""

from __future__ import annotations

import hashlib
import math
from typing import Dict, List, Sequence

from src.retrieval.evidence_store import EvidenceRecord
from src.retrieval.bm25_index import tokenize
from src.utils.logging import get_task_logger, log_vector_search
from src.utils.model_cache import embedding_local_files_only, ensure_model_cache_env

logger = get_task_logger(__name__, task_id="-")


DEFAULT_EMBEDDING_MODEL = "BAAI/bge-small-en-v1.5"
_EMBEDDER_CACHE: Dict[str, object] = {}


class ChromaIndex:
    """A small vector index that prefers Chroma, then falls back to in-memory search.

    Args:
        model_name: SentenceTransformer 模型名
        persistent_path: 若提供，使用 PersistentClient 持久化到磁盘；
                         否则使用 EphemeralClient（原有行为，进程退出后数据丢失）。
                         例如: "data/vector_db"
    """

    def __init__(self, model_name: str = DEFAULT_EMBEDDING_MODEL, persistent_path: str | None = "data/vector_db"):
        ensure_model_cache_env()
        self.model_name = model_name
        self.persistent_path = persistent_path
        self._records: List[EvidenceRecord] = []
        self._vectors: List[List[float]] = []
        self._backend = "memory"
        self._embedding_backend = "unknown"

        try:
            import chromadb  # type: ignore

            if persistent_path:
                self._client = chromadb.PersistentClient(path=persistent_path)
                self._backend = f"chromadb_persistent({persistent_path})"
            else:
                self._client = chromadb.EphemeralClient()
                self._backend = "chromadb"
            self._collection = self._client.get_or_create_collection(name="finsight_local_evidence")
        except Exception:
            self._client = None
            self._collection = None

    @property
    def backend(self) -> str:
        return self._backend

    @property
    def embedding_backend(self) -> str:
        return self._embedding_backend

    def add_records(self, records: Sequence[EvidenceRecord]) -> None:
        self._records = list(records)
        docs = [record.searchable_text for record in self._records]
        embeddings = embed_texts(docs, model_name=self.model_name)
        self._embedding_backend = embedding_backend_for_model(self.model_name)
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
            scores = [float(row.get("vector_score", 0.0)) for row in output]
            log_vector_search(logger, query, topk, len(output), scores, backend=self.backend)
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
        scores = [float(item.get("vector_score", 0.0)) for item in scored[:topk]]
        log_vector_search(logger, query, topk, len(scored[:topk]), scores, backend=self.backend)
        return scored[:topk]


def embed_texts(texts: Sequence[str], model_name: str = DEFAULT_EMBEDDING_MODEL) -> List[List[float]]:
    cache_root = ensure_model_cache_env()
    embedder = _EMBEDDER_CACHE.get(model_name)
    if embedder is None:
        try:
            from sentence_transformers import SentenceTransformer  # type: ignore

            embedder = SentenceTransformer(
                model_name,
                cache_folder=str(cache_root / "sentence_transformers"),
                local_files_only=embedding_local_files_only(),
            )
            _EMBEDDER_CACHE[model_name] = embedder
        except Exception:
            embedder = False
            _EMBEDDER_CACHE[model_name] = embedder

    if embedder and embedder is not False:
        vectors = embedder.encode(list(texts), normalize_embeddings=True)
        return [[float(value) for value in vector] for vector in vectors]
    return [_hash_embed(text) for text in texts]


def embedding_backend_for_model(model_name: str = DEFAULT_EMBEDDING_MODEL) -> str:
    embedder = _EMBEDDER_CACHE.get(model_name)
    if embedder is False:
        return "hash_fallback"
    if embedder is not None:
        return "sentence_transformers"
    return "not_loaded"


def cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return dot / (left_norm * right_norm)


def _hash_embed(text: str, dims: int = 96) -> List[float]:
    vector = [0.0] * dims
    for token in tokenize(str(text)):
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
