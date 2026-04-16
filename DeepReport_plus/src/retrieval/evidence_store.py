"""Local evidence store built from curated parquet files."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List

import pandas as pd


@dataclass
class EvidenceRecord:
    sample_id: str
    source_type: str
    symbol: str
    period: str
    title: str
    publish_time: str
    content: str
    source_url: str
    trust_level: str

    @classmethod
    def from_dict(cls, data: Dict[str, str]) -> "EvidenceRecord":
        return cls(
            sample_id=str(data.get("sample_id", "")),
            source_type=str(data.get("source_type", "")),
            symbol=str(data.get("symbol", "")),
            period=str(data.get("period", "")),
            title=str(data.get("title", "")),
            publish_time=str(data.get("publish_time", "")),
            content=str(data.get("content", "")),
            source_url=str(data.get("source_url", "")),
            trust_level=str(data.get("trust_level", "")),
        )

    def to_dict(self) -> Dict[str, str]:
        return {
            "sample_id": self.sample_id,
            "source_type": self.source_type,
            "symbol": self.symbol,
            "period": self.period,
            "title": self.title,
            "publish_time": self.publish_time,
            "content": self.content,
            "source_url": self.source_url,
            "trust_level": self.trust_level,
        }

    @property
    def searchable_text(self) -> str:
        return f"{self.title} {self.content}".strip()


class EvidenceStore:
    """In-memory evidence store for retrieval modules."""

    def __init__(self, records: List[EvidenceRecord]):
        self.records = records

    @classmethod
    def from_curated_parquet(cls, curated_dir: str | Path = "data/curated") -> "EvidenceStore":
        curated_path = Path(curated_dir)
        paths = sorted(curated_path.glob("*.parquet"))
        if not paths:
            return cls(records=[])

        frames = [pd.read_parquet(p) for p in paths]
        merged = pd.concat(frames, ignore_index=True)
        records = [EvidenceRecord.from_dict(dict(row)) for _, row in merged.iterrows()]
        return cls(records=records)

    def filter(self, symbol: str | None = None, period: str | None = None) -> List[EvidenceRecord]:
        output = self.records
        if symbol:
            output = [r for r in output if r.symbol == symbol]
        if period:
            output = [r for r in output if r.period == period]
        return output

