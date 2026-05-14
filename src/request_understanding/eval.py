"""Evaluation helpers for RequestUnderstandingAgent."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List

from src.agents.request_understanding_agent import RequestUnderstandingAgent


def load_request_understanding_cases(path: str | Path) -> List[Dict[str, Any]]:
    case_path = Path(path)
    rows: List[Dict[str, Any]] = []
    for line in case_path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if text:
            rows.append(dict(json.loads(text)))
    return rows


def evaluate_request_understanding_cases(
    cases: Iterable[Dict[str, Any]],
    agent: RequestUnderstandingAgent | None = None,
) -> Dict[str, Any]:
    parser = agent or RequestUnderstandingAgent(model=None)
    rows = []
    for case in cases:
        request = parser.parse(str(case.get("query", "")))
        expected_clarification = bool(case.get("expected_clarification_needed", False))
        predicted_clarification = bool(request.clarification_needed)
        expected_symbol = str(case.get("expected_symbol", "")).upper()
        expected_market = str(case.get("expected_market", ""))
        row = {
            "case_id": str(case.get("case_id", "")),
            "entity_resolution_accuracy": _bool_score(
                (request.symbol == expected_symbol and request.market == expected_market)
                if expected_symbol or expected_market
                else predicted_clarification
            ),
            "report_type_accuracy": _bool_score(request.report_type == str(case.get("expected_report_type", ""))),
            "period_parse_accuracy": _bool_score(request.period.type == str(case.get("expected_period_type", ""))),
            "clarification_tp": predicted_clarification and expected_clarification,
            "clarification_fp": predicted_clarification and not expected_clarification,
            "clarification_fn": (not predicted_clarification) and expected_clarification,
            "clarification_tn": (not predicted_clarification) and not expected_clarification,
            "predicted": request.to_dict(),
        }
        rows.append(row)
    return summarize_request_understanding_eval(rows)


def summarize_request_understanding_eval(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    tp = sum(1 for row in rows if row.get("clarification_tp"))
    fp = sum(1 for row in rows if row.get("clarification_fp"))
    fn = sum(1 for row in rows if row.get("clarification_fn"))
    return {
        "case_count": len(rows),
        "entity_resolution_accuracy": _mean(row.get("entity_resolution_accuracy", 0.0) for row in rows),
        "report_type_accuracy": _mean(row.get("report_type_accuracy", 0.0) for row in rows),
        "period_parse_accuracy": _mean(row.get("period_parse_accuracy", 0.0) for row in rows),
        "clarification_precision": round(tp / float(tp + fp), 4) if (tp + fp) else 1.0,
        "clarification_recall": round(tp / float(tp + fn), 4) if (tp + fn) else 1.0,
        "rows": rows,
    }


def _bool_score(value: bool) -> float:
    return 1.0 if value else 0.0


def _mean(values: Iterable[Any]) -> float:
    nums = [float(value or 0.0) for value in values]
    return round(sum(nums) / float(len(nums)), 4) if nums else 0.0
