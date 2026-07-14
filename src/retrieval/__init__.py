"""Retrieval layer exports for lexical and local vector retrieval."""

from src.retrieval.bm25_index import BM25Index
from src.retrieval.chroma_index import ChromaIndex
from src.retrieval.chunking import EvidenceChunk, chunk_record, chunk_records
from src.retrieval.evidence_store import EvidenceRecord, EvidenceStore

__all__ = [
    "EvidenceRecord",
    "EvidenceStore",
    "BM25Index",
    "ChromaIndex",
    "retrieve_evidence",
    "retrieve_evidence_with_mode",
    "EvidenceChunk",
    "chunk_record",
    "chunk_records",
]


def __getattr__(name: str):
    if name in {"retrieve_evidence", "retrieve_evidence_with_mode"}:
        from src.retrieval import retrieve as _retrieve

        return getattr(_retrieve, name)
    raise AttributeError(name)
