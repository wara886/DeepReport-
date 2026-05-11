"""Writer fallback trace helpers."""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List


@dataclass
class WriterTraceEvent:
    case_id: str
    query: str
    task_type: str
    retrieved_doc_count: int
    reranked_topk_ids: List[str]
    evidence_coverage: float
    verifier_accept_rate: float
    writer_mode: str
    fallback_reason: str
    final_report_path: str

    def to_dict(self) -> Dict[str, object]:
        return {
            "case_id": self.case_id,
            "query": self.query,
            "task_type": self.task_type,
            "retrieved_doc_count": self.retrieved_doc_count,
            "reranked_topk_ids": list(self.reranked_topk_ids),
            "evidence_coverage": round(float(self.evidence_coverage), 4),
            "verifier_accept_rate": round(float(self.verifier_accept_rate), 4),
            "writer_mode": self.writer_mode,
            "fallback_reason": self.fallback_reason,
            "final_report_path": self.final_report_path,
        }


def append_writer_trace(path: str | Path, event: WriterTraceEvent) -> Path:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(event.to_dict(), ensure_ascii=False)
    with out.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")
    return out


def read_writer_trace(path: str | Path) -> List[Dict[str, object]]:
    trace = Path(path)
    if not trace.exists():
        return []
    rows: List[Dict[str, object]] = []
    for line in trace.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text:
            continue
        rows.append(dict(json.loads(text)))
    return rows


def aggregate_writer_trace(rows: Iterable[Dict[str, object]], group_key: str = "task_type") -> Dict[str, Dict[str, object]]:
    grouped: Dict[str, List[Dict[str, object]]] = {}
    for row in rows:
        grouped.setdefault(str(row.get(group_key, "unknown")), []).append(row)

    output: Dict[str, Dict[str, object]] = {}
    for key, items in grouped.items():
        total = len(items)
        fallback_count = sum(1 for item in items if str(item.get("writer_mode", "")) == "fallback")
        avg_evidence = sum(float(item.get("evidence_coverage", 0.0)) for item in items) / float(total) if total else 0.0
        avg_verifier = (
            sum(float(item.get("verifier_accept_rate", 0.0)) for item in items) / float(total) if total else 0.0
        )
        output[key] = {
            "count": total,
            "fallback_rate": round(float(fallback_count) / float(total), 4) if total else 0.0,
            "evidence_coverage_mean": round(avg_evidence, 4),
            "verifier_accept_rate_mean": round(avg_verifier, 4),
        }
    return output


def export_writer_trace_csv(rows: Iterable[Dict[str, object]], path: str | Path) -> Path:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    data = list(rows)
    headers = [
        "case_id",
        "query",
        "task_type",
        "retrieved_doc_count",
        "reranked_topk_ids",
        "evidence_coverage",
        "verifier_accept_rate",
        "writer_mode",
        "fallback_reason",
        "final_report_path",
    ]
    with out.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=headers)
        writer.writeheader()
        for row in data:
            item = dict(row)
            item["reranked_topk_ids"] = "|".join(str(x) for x in list(item.get("reranked_topk_ids", [])))
            writer.writerow({k: item.get(k, "") for k in headers})
    return out

