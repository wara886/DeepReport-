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

    def __init__(
        self,
        model_name: str = DEFAULT_EMBEDDING_MODEL,
        persistent_path: str | None = "data/vector_db",
        collection_name: str = "finsight_local_evidence",
    ):
        ensure_model_cache_env()
        self.model_name = model_name
        self.persistent_path = persistent_path
        self.collection_name = collection_name
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
            self._collection = self._client.get_or_create_collection(name=collection_name)
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
        self._records = _dedupe_records_by_identity(records)
        docs = [record.searchable_text for record in self._records]
        embeddings = embed_texts(docs, model_name=self.model_name)
        self._embedding_backend = embedding_backend_for_model(self.model_name)
        self._vectors = embeddings

        if self._collection is not None:
            self._collection.upsert(
                ids=_unique_record_ids(self._records),
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
                row["vector_score"] = _vector_score_from_metadata(row, query_vector, fallback_distance=distance, records=self._records, vectors=self._vectors)
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


def _vector_score_from_metadata(
    metadata: Dict[str, object],
    query_vector: Sequence[float],
    *,
    fallback_distance: object,
    records: Sequence[EvidenceRecord],
    vectors: Sequence[Sequence[float]],
) -> float:
    sample_id = str(metadata.get("sample_id") or "")
    evidence_id = str(metadata.get("evidence_id") or "")
    chunk_id = str(metadata.get("chunk_id") or "")
    identity_key = str(metadata.get("identity_key") or "")
    for record, vector in zip(records, vectors):
        record_sample_id = str(getattr(record, "sample_id", "") or "")
        record_evidence_id = str(getattr(record, "evidence_id", "") or record_sample_id)
        record_chunk_id = str(getattr(record, "chunk_id", "") or record_sample_id)
        record_identity_key = str(getattr(record, "identity_key", "") or "")
        if identity_key and identity_key == record_identity_key:
            return cosine_similarity(query_vector, vector)
        if sample_id and sample_id == record_sample_id:
            return cosine_similarity(query_vector, vector)
        if evidence_id and evidence_id == record_evidence_id:
            return cosine_similarity(query_vector, vector)
        if chunk_id and chunk_id == record_chunk_id:
            return cosine_similarity(query_vector, vector)
    try:
        return max(0.0, 1.0 - float(fallback_distance or 0.0))
    except (TypeError, ValueError):
        return 0.0


def _unique_record_ids(records: Sequence[EvidenceRecord]) -> List[str]:
    seen: Dict[str, int] = {}
    output: List[str] = []
    for index, record in enumerate(records):
        raw_id = str(
            getattr(record, "identity_key", "")
            or getattr(record, "sample_id", "")
            or getattr(record, "evidence_id", "")
            or f"record_{index}"
        )
        count = seen.get(raw_id, 0)
        seen[raw_id] = count + 1
        output.append(raw_id if count == 0 else f"{raw_id}__dup_{count}")
    return output


def _dedupe_records_by_identity(records: Sequence[EvidenceRecord]) -> List[EvidenceRecord]:
    output: List[EvidenceRecord] = []
    seen: set[str] = set()
    for index, record in enumerate(records):
        key = str(
            getattr(record, "identity_key", "")
            or getattr(record, "sample_id", "")
            or getattr(record, "evidence_id", "")
            or f"record_{index}"
        )
        if key in seen:
            continue
        seen.add(key)
        output.append(record)
    return output
