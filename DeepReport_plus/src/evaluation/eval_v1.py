"""Eval v1 dataset contract helpers."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List

import pandas as pd


ALLOWED_TASK_TYPES = {"fundamental", "financial", "event"}
ALLOWED_SOURCE_SCOPE = {"filing", "news", "company_page", "financials", "market"}


@dataclass
class EvalCase:
    """Typed representation for one eval_v1 case."""

    case_id: str
    query: str
    task_type: str
    source_scope: List[str]
    gold_claims: List[str]
    gold_evidence_ids: List[str]
    gold_numeric_facts: List[Dict[str, str]]
    allow_fallback: bool
    symbol: str
    period: str

    def to_dict(self) -> Dict[str, object]:
        return {
            "case_id": self.case_id,
            "query": self.query,
            "task_type": self.task_type,
            "source_scope": list(self.source_scope),
            "gold_claims": list(self.gold_claims),
            "gold_evidence_ids": list(self.gold_evidence_ids),
            "gold_numeric_facts": list(self.gold_numeric_facts),
            "allow_fallback": bool(self.allow_fallback),
            "symbol": self.symbol,
            "period": self.period,
        }


def _require_str(row: Dict[str, object], key: str) -> str:
    value = str(row.get(key, "")).strip()
    if not value:
        raise ValueError(f"Field `{key}` is required and must be non-empty.")
    return value


def _require_list(row: Dict[str, object], key: str) -> List[object]:
    value = row.get(key, [])
    if not isinstance(value, list):
        raise ValueError(f"Field `{key}` must be a list.")
    return value


def validate_eval_case(row: Dict[str, object]) -> EvalCase:
    """Validate one case against eval_v1 schema and return typed object."""

    case_id = _require_str(row, "case_id")
    query = _require_str(row, "query")
    task_type = _require_str(row, "task_type")
    if task_type not in ALLOWED_TASK_TYPES:
        raise ValueError(f"Invalid `task_type`: {task_type}")

    source_scope_raw = _require_list(row, "source_scope")
    source_scope = [str(x).strip() for x in source_scope_raw if str(x).strip()]
    if not source_scope:
        raise ValueError("Field `source_scope` must contain at least one source.")
    invalid_sources = [x for x in source_scope if x not in ALLOWED_SOURCE_SCOPE]
    if invalid_sources:
        raise ValueError(f"Invalid `source_scope` values: {invalid_sources}")

    gold_claims = [str(x).strip() for x in _require_list(row, "gold_claims") if str(x).strip()]
    gold_evidence_ids = [str(x).strip() for x in _require_list(row, "gold_evidence_ids") if str(x).strip()]
    if not gold_claims:
        raise ValueError("Field `gold_claims` must contain at least one claim.")
    if not gold_evidence_ids:
        raise ValueError("Field `gold_evidence_ids` must contain at least one evidence id.")

    numeric_facts_raw = _require_list(row, "gold_numeric_facts")
    numeric_facts: List[Dict[str, str]] = []
    for idx, item in enumerate(numeric_facts_raw):
        if not isinstance(item, dict):
            raise ValueError(f"`gold_numeric_facts[{idx}]` must be an object.")
        metric = str(item.get("metric", "")).strip()
        value = str(item.get("value", "")).strip()
        unit = str(item.get("unit", "")).strip()
        period = str(item.get("period", "")).strip()
        if not metric or not value or not unit or not period:
            raise ValueError(f"`gold_numeric_facts[{idx}]` must include metric/value/unit/period.")
        numeric_facts.append(
            {
                "metric": metric,
                "value": value,
                "unit": unit,
                "period": period,
            }
        )

    allow_fallback = bool(row.get("allow_fallback", False))
    symbol = _require_str(row, "symbol")
    period = _require_str(row, "period")

    return EvalCase(
        case_id=case_id,
        query=query,
        task_type=task_type,
        source_scope=source_scope,
        gold_claims=gold_claims,
        gold_evidence_ids=gold_evidence_ids,
        gold_numeric_facts=numeric_facts,
        allow_fallback=allow_fallback,
        symbol=symbol,
        period=period,
    )


def load_eval_cases(path: str | Path) -> List[EvalCase]:
    """Load and validate eval_v1 cases from JSONL."""

    case_path = Path(path)
    if not case_path.exists():
        return []
    cases: List[EvalCase] = []
    for line in case_path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text:
            continue
        cases.append(validate_eval_case(dict(json.loads(text))))
    return cases


def write_eval_cases(path: str | Path, cases: Iterable[EvalCase]) -> Path:
    """Write validated eval_v1 cases to JSONL."""

    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    lines: List[str] = []
    for case in cases:
        item = case if isinstance(case, EvalCase) else validate_eval_case(dict(case))
        lines.append(json.dumps(item.to_dict(), ensure_ascii=False))
    out.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    return out


def write_eval_schema(path: str | Path) -> Path:
    """Write schema.json for eval_v1."""

    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "DeepReport++ Stage12 eval_v1 case schema",
        "type": "object",
        "required": [
            "case_id",
            "query",
            "task_type",
            "source_scope",
            "gold_claims",
            "gold_evidence_ids",
            "gold_numeric_facts",
            "allow_fallback",
            "symbol",
            "period",
        ],
        "properties": {
            "case_id": {"type": "string", "minLength": 1},
            "query": {"type": "string", "minLength": 1},
            "task_type": {"type": "string", "enum": sorted(ALLOWED_TASK_TYPES)},
            "source_scope": {
                "type": "array",
                "items": {"type": "string", "enum": sorted(ALLOWED_SOURCE_SCOPE)},
                "minItems": 1,
            },
            "gold_claims": {"type": "array", "items": {"type": "string"}, "minItems": 1},
            "gold_evidence_ids": {"type": "array", "items": {"type": "string"}, "minItems": 1},
            "gold_numeric_facts": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["metric", "value", "unit", "period"],
                    "properties": {
                        "metric": {"type": "string"},
                        "value": {"type": "string"},
                        "unit": {"type": "string"},
                        "period": {"type": "string"},
                    },
                },
            },
            "allow_fallback": {"type": "boolean"},
            "symbol": {"type": "string", "minLength": 1},
            "period": {"type": "string", "minLength": 1},
        },
        "additionalProperties": True,
    }
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(schema, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return out


def seed_eval_v1_cases(raw_root: str | Path, min_case_count: int = 30) -> List[EvalCase]:
    """Create deterministic seed cases from discovered symbol/period folders."""

    root = Path(raw_root)
    symbols_periods: List[tuple[str, str]] = []
    if root.exists():
        for symbol_dir in sorted([p for p in root.iterdir() if p.is_dir()]):
            for period_dir in sorted([p for p in symbol_dir.iterdir() if p.is_dir()]):
                symbols_periods.append((symbol_dir.name, period_dir.name))
    if not symbols_periods:
        return []

    templates = [
        (
            "fundamental",
            "总结{symbol}在{period}的业务基本面、优势与核心风险",
            ["company_page", "news", "filing"],
        ),
        (
            "financial",
            "分析{symbol}在{period}的营收、净利润、同比和毛利率质量",
            ["financials", "filing"],
        ),
        (
            "event",
            "结合{period}新闻，评估影响{symbol}估值的事件催化与风险",
            ["news", "filing"],
        ),
        (
            "financial",
            "请核查{symbol} {period}的关键财务数字是否有证据支撑",
            ["financials", "company_page"],
        ),
        (
            "fundamental",
            "给出{symbol} {period}的商业模式、护城河和增长约束",
            ["company_page", "news"],
        ),
        (
            "event",
            "判断{symbol}在{period}面临的监管、供应链与竞争事件风险",
            ["news", "filing", "market"],
        ),
    ]

    cases: List[EvalCase] = []
    for symbol, period in symbols_periods:
        financials_path = root / symbol / period / "financials.csv"
        numeric_facts = [
            {"metric": "revenue", "value": "unknown", "unit": "billion", "period": period},
            {"metric": "net_income", "value": "unknown", "unit": "billion", "period": period},
            {"metric": "yoy", "value": "unknown", "unit": "pct", "period": period},
            {"metric": "gross_margin", "value": "unknown", "unit": "pct", "period": period},
        ]
        if financials_path.exists():
            df = pd.read_csv(financials_path)
            if not df.empty:
                row = df.iloc[0]
                revenue = float(row.get("revenue_billion", 0.0))
                yoy = float(row.get("revenue_growth_pct", 0.0))
                gross_margin = float(row.get("gross_margin_pct", 0.0))
                net_margin = float(row.get("net_margin_pct", 0.0))
                net_income = revenue * net_margin / 100.0
                numeric_facts = [
                    {"metric": "revenue", "value": f"{revenue:.3f}", "unit": "billion", "period": period},
                    {"metric": "net_income", "value": f"{net_income:.3f}", "unit": "billion", "period": period},
                    {"metric": "yoy", "value": f"{yoy:.3f}", "unit": "pct", "period": period},
                    {"metric": "gross_margin", "value": f"{gross_margin:.3f}", "unit": "pct", "period": period},
                ]

        for idx, (task_type, query_tpl, scope) in enumerate(templates, start=1):
            case_id = f"ev1_{symbol.lower()}_{period.lower()}_{idx:02d}"
            query = query_tpl.format(symbol=symbol, period=period)
            evidence_base = [
                f"{symbol}:{period}:financials",
                f"{symbol}:{period}:filings",
                f"{symbol}:{period}:news",
            ]
            cases.append(
                EvalCase(
                    case_id=case_id,
                    query=query,
                    task_type=task_type,
                    source_scope=scope,
                    gold_claims=[
                        f"{symbol} {period} revenue claim should be evidence-grounded.",
                        f"{symbol} {period} margin claim should be evidence-grounded.",
                    ],
                    gold_evidence_ids=evidence_base,
                    gold_numeric_facts=numeric_facts,
                    allow_fallback=False,
                    symbol=symbol,
                    period=period,
                )
            )

    if len(cases) >= min_case_count:
        return cases[:min_case_count]

    repeated: List[EvalCase] = []
    cursor = 0
    while len(cases) + len(repeated) < min_case_count:
        base = cases[cursor % len(cases)]
        cursor += 1
        repeated.append(
            EvalCase(
                case_id=f"{base.case_id}_r{cursor:02d}",
                query=f"{base.query}（复核轮次 {cursor}）",
                task_type=base.task_type,
                source_scope=base.source_scope,
                gold_claims=base.gold_claims,
                gold_evidence_ids=base.gold_evidence_ids,
                gold_numeric_facts=base.gold_numeric_facts,
                allow_fallback=base.allow_fallback,
                symbol=base.symbol,
                period=base.period,
            )
        )
    return cases + repeated
