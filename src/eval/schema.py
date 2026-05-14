"""Schema helpers for Phase 0 eval cases and baseline outputs."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Literal


Difficulty = Literal["easy", "normal", "hard"]

ALLOWED_DIFFICULTIES = {"easy", "normal", "hard"}
DEFAULT_CASE_SCHEMA_PATH = Path("eval/cases/case_schema.json")


@dataclass(frozen=True)
class EvalCase:
    case_id: str
    symbol: str
    market: str
    period: str
    topic: str
    report_type: str
    required_sections: List[str]
    required_source_types: List[str]
    difficulty: Difficulty
    tags: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "case_id": self.case_id,
            "symbol": self.symbol,
            "market": self.market,
            "period": self.period,
            "topic": self.topic,
            "report_type": self.report_type,
            "required_sections": list(self.required_sections),
            "required_source_types": list(self.required_source_types),
            "difficulty": self.difficulty,
            "tags": list(self.tags),
        }

    @property
    def query(self) -> str:
        sections = "、".join(self.required_sections)
        return f"{self.symbol} {self.period} {self.topic}，报告类型：{self.report_type}，必须覆盖：{sections}。"


def case_json_schema() -> Dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "DeepReport++ Phase 0 eval case",
        "type": "object",
        "required": [
            "case_id",
            "symbol",
            "market",
            "period",
            "topic",
            "report_type",
            "required_sections",
            "required_source_types",
            "difficulty",
            "tags",
        ],
        "properties": {
            "case_id": {"type": "string", "minLength": 1},
            "symbol": {"type": "string", "minLength": 1},
            "market": {"type": "string", "minLength": 1},
            "period": {"type": "string", "minLength": 1},
            "topic": {"type": "string", "minLength": 1},
            "report_type": {"type": "string", "minLength": 1},
            "required_sections": {"type": "array", "items": {"type": "string", "minLength": 1}, "minItems": 1},
            "required_source_types": {"type": "array", "items": {"type": "string", "minLength": 1}, "minItems": 1},
            "difficulty": {"type": "string", "enum": sorted(ALLOWED_DIFFICULTIES)},
            "tags": {"type": "array", "items": {"type": "string", "minLength": 1}},
        },
        "additionalProperties": True,
    }


def validate_eval_case(row: Dict[str, Any]) -> EvalCase:
    case_id = _required_str(row, "case_id")
    symbol = _required_str(row, "symbol").upper()
    market = _required_str(row, "market")
    period = _required_str(row, "period")
    topic = _required_str(row, "topic")
    report_type = _required_str(row, "report_type")
    required_sections = _required_str_list(row, "required_sections")
    required_source_types = _required_str_list(row, "required_source_types")
    difficulty = _required_str(row, "difficulty")
    if difficulty not in ALLOWED_DIFFICULTIES:
        raise ValueError(f"Invalid difficulty `{difficulty}`; expected one of {sorted(ALLOWED_DIFFICULTIES)}.")
    tags = _optional_str_list(row, "tags")
    return EvalCase(
        case_id=case_id,
        symbol=symbol,
        market=market,
        period=period,
        topic=topic,
        report_type=report_type,
        required_sections=required_sections,
        required_source_types=required_source_types,
        difficulty=difficulty,  # type: ignore[arg-type]
        tags=tags,
    )


def load_eval_cases(path: str | Path) -> List[EvalCase]:
    case_path = Path(path)
    if case_path.is_dir():
        files = sorted(case_path.rglob("*.json")) + sorted(case_path.rglob("*.jsonl"))
        cases: List[EvalCase] = []
        for file_path in files:
            if file_path.name == "case_schema.json":
                continue
            cases.extend(load_eval_cases(file_path))
        return cases
    if not case_path.exists():
        raise FileNotFoundError(f"Eval case path not found: {case_path}")
    if case_path.suffix == ".jsonl":
        return [validate_eval_case(json.loads(line)) for line in case_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    data = json.loads(case_path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        return [validate_eval_case(dict(item)) for item in data]
    if isinstance(data, dict) and isinstance(data.get("cases"), list):
        return [validate_eval_case(dict(item)) for item in data["cases"]]
    if isinstance(data, dict):
        return [validate_eval_case(data)]
    raise ValueError(f"Unsupported eval case file content: {case_path}")


def write_eval_cases_jsonl(path: str | Path, cases: Iterable[EvalCase | Dict[str, Any]]) -> Path:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for case in cases:
        item = case if isinstance(case, EvalCase) else validate_eval_case(dict(case))
        rows.append(json.dumps(item.to_dict(), ensure_ascii=False))
    out.write_text("\n".join(rows) + ("\n" if rows else ""), encoding="utf-8")
    return out


def write_case_schema(path: str | Path = DEFAULT_CASE_SCHEMA_PATH) -> Path:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(case_json_schema(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return out


def _required_str(row: Dict[str, Any], key: str) -> str:
    value = row.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Field `{key}` is required and must be a non-empty string.")
    return value.strip()


def _required_str_list(row: Dict[str, Any], key: str) -> List[str]:
    values = row.get(key)
    if not isinstance(values, list):
        raise ValueError(f"Field `{key}` is required and must be a list.")
    normalized = [str(value).strip() for value in values if str(value).strip()]
    if not normalized:
        raise ValueError(f"Field `{key}` must contain at least one non-empty string.")
    return normalized


def _optional_str_list(row: Dict[str, Any], key: str) -> List[str]:
    values = row.get(key, [])
    if not isinstance(values, list):
        raise ValueError(f"Field `{key}` must be a list when provided.")
    return [str(value).strip() for value in values if str(value).strip()]
