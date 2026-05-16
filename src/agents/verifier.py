"""Rule-based verifier for core report outputs."""

from __future__ import annotations

from pathlib import Path
import re
from typing import Any, Dict, List

from src.data.source_authority import grade_source_authority
from src.evaluation.multimodal_consistency import audit_multimodal_consistency
from src.evaluation.valuation_audit import audit_valuation_model
from src.schemas.claim import ClaimItem


class Verifier:
    """Validate claim table and rendered markdown report."""

    def verify(
        self,
        claims: List[ClaimItem],
        markdown: str,
        evidence_records: List[Dict[str, Any]] | None = None,
        charts: List[Dict[str, Any]] | None = None,
        tables: List[Dict[str, Any]] | None = None,
        valuation: Dict[str, Any] | None = None,
        use_candidate_grounded_rule: bool = False,
        expected_symbol: str | None = None,
    ) -> Dict[str, object]:
        errors: List[str] = []
        warnings: List[str] = []
        evidence_records = evidence_records or []
        charts = charts or []
        tables = tables or []
        valuation = valuation or {}

        if not claims:
            errors.append("No claims generated.")

        has_financial_claim = any(item.section_name == "financial_analysis" for item in claims)
        if not has_financial_claim:
            warnings.append("No financial_analysis claims found.")

        missing_ids = [item.claim_id for item in claims if not item.claim_id]
        if missing_ids:
            errors.append(f"Claims missing IDs: {', '.join(missing_ids)}")

        low_conf_count = sum(1 for item in claims if item.confidence < 0.5)
        if low_conf_count > 0:
            warnings.append(f"{low_conf_count} claims have confidence lower than 0.5.")

        grounded_count = sum(1 for item in claims if item.confidence >= 0.75)
        if use_candidate_grounded_rule:
            warnings.append(
                "Candidate grounded rule was requested, but experimental grounded/shadow modules were removed in the core cleanup."
            )

        required_sections = [
            ("## Executive Summary", ["## Executive Summary", "# Executive Summary", "## 执行摘要", "# 执行摘要"]),
            ("## Financial Analysis", ["## Financial Analysis", "# Financial Analysis", "## 财务分析", "# 财务分析"]),
            ("## Risk Assessment", ["## Risk Assessment", "# Risk Assessment", "## 风险评估", "# 风险评估"]),
        ]
        for canonical, aliases in required_sections:
            if not any(alias in markdown for alias in aliases):
                errors.append(f"Missing required header in report: {canonical}")

        _check_company_report_sections(claims=claims, markdown=markdown, errors=errors)
        _check_target_symbol_alignment(
            expected_symbol=expected_symbol,
            claims=claims,
            markdown=markdown,
            evidence_records=evidence_records,
            errors=errors,
            warnings=warnings,
        )
        _check_evidence_support(claims=claims, evidence_records=evidence_records, markdown=markdown, errors=errors, warnings=warnings)
        _check_primary_source_support(claims=claims, evidence_records=evidence_records, errors=errors, warnings=warnings)
        _check_chart_support(claims=claims, evidence_records=evidence_records, charts=charts, warnings=warnings)
        multimodal_consistency = audit_multimodal_consistency(
            charts=charts,
            tables=tables,
            claims=[claim.to_dict() for claim in claims],
            evidence_records=evidence_records,
            markdown=markdown,
            require_files=False,
        )
        if charts and not multimodal_consistency.get("passed", False):
            errors.append("Multimodal consistency check failed.")
        valuation_audit = audit_valuation_model(valuation)
        if valuation and not valuation_audit.get("passed", False):
            errors.append("Valuation reproducibility check failed.")

        return {
            "passed": len(errors) == 0,
            "error_count": len(errors),
            "warning_count": len(warnings),
            "errors": errors,
            "warnings": warnings,
            "claim_count": len(claims),
            "grounded_claim_count": grounded_count,
            "expected_symbol": str(expected_symbol or "").upper(),
            "multimodal_consistency": multimodal_consistency,
            "valuation_audit": valuation_audit,
        }


def _check_company_report_sections(claims: List[ClaimItem], markdown: str, errors: List[str]) -> None:
    section_headers = {
        "financial_statements": ["## 三表摘要", "# 三表摘要", "## Financial Statements"],
        "ownership_governance": ["## 股权结构与公司治理", "# 股权结构与公司治理", "## Ownership and Governance"],
        "strategy_business": ["## 战略与主营业务", "# 战略与主营业务", "## Strategy and Business"],
        "peer_compare": ["## 同行对比", "# 同行对比", "## Peer Comparison"],
        "valuation": ["## 估值观察", "# 估值观察", "## Valuation"],
        "valuation_sensitivity": ["## 估值敏感性", "# 估值敏感性", "## Valuation Sensitivity"],
    }
    claim_sections = {claim.section_name for claim in claims}
    for section_name, aliases in section_headers.items():
        if section_name in claim_sections and not any(alias in markdown for alias in aliases):
            errors.append(f"Missing required company-report header for claim section: {section_name}")


def _check_target_symbol_alignment(
    expected_symbol: str | None,
    claims: List[ClaimItem],
    markdown: str,
    evidence_records: List[Dict[str, Any]],
    errors: List[str],
    warnings: List[str],
) -> None:
    symbol = str(expected_symbol or "").strip().upper()
    if not symbol:
        return

    evidence_symbols = sorted(
        {
            str(record.get("symbol") or record.get("metadata", {}).get("symbol") or "").strip().upper()
            for record in evidence_records
            if isinstance(record, dict)
            and str(record.get("symbol") or record.get("metadata", {}).get("symbol") or "").strip()
        }
    )
    if evidence_symbols and symbol not in evidence_symbols:
        errors.append(f"Target symbol mismatch: expected {symbol}, but evidence symbols are {', '.join(evidence_symbols)}.")

    claim_text = " ".join(claim.claim_text for claim in claims)
    mentioned_symbols = _ticker_mentions(f"{markdown}\n{claim_text}")
    non_target_mentions = sorted(token for token in mentioned_symbols if token != symbol)
    if symbol not in mentioned_symbols and claims:
        warnings.append(f"Target symbol {symbol} is not explicitly mentioned in report claims or markdown.")
    if non_target_mentions and symbol not in evidence_symbols:
        warnings.append(f"Report mentions non-target ticker-like tokens: {', '.join(non_target_mentions[:8])}.")


def _check_evidence_support(
    claims: List[ClaimItem],
    evidence_records: List[Dict[str, Any]],
    markdown: str,
    errors: List[str],
    warnings: List[str],
) -> None:
    evidence_by_id = {
        str(item.get("evidence_id") or item.get("sample_id") or ""): item
        for item in evidence_records
        if isinstance(item, dict) and str(item.get("evidence_id") or item.get("sample_id") or "")
    }
    available_ids = set(evidence_by_id)
    for claim in claims:
        if not claim.evidence_ids:
            warnings.append(f"Claim {claim.claim_id} has no evidence_ids.")
            continue
        missing = [evidence_id for evidence_id in claim.evidence_ids if evidence_id not in available_ids]
        if missing:
            errors.append(f"Claim {claim.claim_id} references missing evidence ids: {', '.join(missing)}")
        uncited = [evidence_id for evidence_id in claim.evidence_ids if evidence_id not in markdown]
        if uncited:
            errors.append(f"Claim {claim.claim_id} evidence ids are not cited in markdown: {', '.join(uncited)}")
        _check_numeric_support(claim=claim, evidence_by_id=evidence_by_id, warnings=warnings)


def _check_numeric_support(
    claim: ClaimItem,
    evidence_by_id: Dict[str, Dict[str, Any]],
    warnings: List[str],
) -> None:
    if not claim.numeric_values:
        return
    if _is_derived_numeric_claim(claim):
        return
    evidence_numbers: List[float] = []
    for evidence_id in claim.evidence_ids:
        record = evidence_by_id.get(evidence_id)
        if not record:
            continue
        evidence_numbers.extend(_numbers_from_record(record))
    for key, value in claim.numeric_values.items():
        if not _has_close_number(float(value), evidence_numbers):
            warnings.append(f"Claim {claim.claim_id} numeric value {key}={value} was not found in linked evidence.")


def _check_primary_source_support(
    claims: List[ClaimItem],
    evidence_records: List[Dict[str, Any]],
    errors: List[str],
    warnings: List[str],
) -> None:
    evidence_by_id = {
        str(item.get("evidence_id") or item.get("sample_id") or ""): item
        for item in evidence_records
        if isinstance(item, dict) and str(item.get("evidence_id") or item.get("sample_id") or "")
    }
    for claim in claims:
        if not _requires_primary_financial_source(claim):
            continue
        linked_records = [evidence_by_id[evidence_id] for evidence_id in claim.evidence_ids if evidence_id in evidence_by_id]
        if not linked_records:
            continue
        if not any(_has_explicit_source_metadata(record) for record in linked_records):
            warnings.append(
                f"Claim {claim.claim_id} cannot be checked for primary-source support because linked evidence has no source metadata."
            )
            continue
        grades = [_authority_grade(record) for record in linked_records]
        if not any(grade.get("authority_level") == "primary" for grade in grades):
            errors.append(
                f"Claim {claim.claim_id} is a core financial claim but has no primary evidence source."
            )
        elif any(grade.get("authority_level") in {"secondary", "tertiary", "unknown"} for grade in grades):
            warnings.append(
                f"Claim {claim.claim_id} mixes primary evidence with lower-authority sources; keep the primary source as the controlling citation."
            )


def _requires_primary_financial_source(claim: ClaimItem) -> bool:
    if not claim.numeric_values or _is_derived_numeric_claim(claim):
        return False
    if _is_market_numeric_claim(claim) or _is_macro_numeric_claim(claim):
        return False
    text = f"{claim.section_name} {claim.claim_text} {claim.notes}".lower()
    financial_markers = [
        "financial",
        "revenue",
        "net income",
        "gross margin",
        "operating income",
        "cash flow",
        "free cash flow",
        "eps",
        "profit",
        "income statement",
        "balance sheet",
        "营收",
        "收入",
        "净利润",
        "毛利率",
        "现金流",
    ]
    return claim.section_name in {"financial_analysis", "financial_statements"} or any(marker in text for marker in financial_markers)


def _is_market_numeric_claim(claim: ClaimItem) -> bool:
    keys = {str(key).lower() for key in claim.numeric_values}
    if not keys:
        return False
    market_keys = {
        "close",
        "latest_close",
        "last_close",
        "previous_close",
        "price",
        "market_price",
        "volume",
        "latest_volume",
        "change_pct",
        "monthly_change_pct",
        "one_month_change_pct",
        "market_cap",
        "market_cap_billion",
        "market_cap_billion_cny",
        "pe_ttm",
        "pb",
        "ps",
    }
    text = claim.claim_text.lower()
    market_markers = ["收盘价", "股价", "行情", "成交量", "市值", "market", "price", "volume"]
    return keys.issubset(market_keys) or any(marker in text for marker in market_markers)


def _is_macro_numeric_claim(claim: ClaimItem) -> bool:
    keys = {str(key).lower() for key in claim.numeric_values}
    if not keys:
        return False
    macro_keys = {
        "cpi",
        "inflation",
        "unemployment",
        "unemployment_rate",
        "fed_funds",
        "fedfunds",
        "policy_rate",
        "rate",
        "yield",
        "gdp",
    }
    text = claim.claim_text.lower()
    macro_markers = ["cpi", "通胀", "失业率", "利率", "federal reserve", "bls", "fred", "bea"]
    return keys.issubset(macro_keys) or any(marker in text for marker in macro_markers)


def _authority_grade(record: Dict[str, Any]) -> Dict[str, Any]:
    if record.get("authority_level"):
        return {
            "source_authority": str(record.get("source_authority", "")),
            "authority_level": str(record.get("authority_level", "")),
            "authority_score": record.get("authority_score", 0.0),
        }
    return grade_source_authority(record)


def _has_explicit_source_metadata(record: Dict[str, Any]) -> bool:
    return any(
        str(record.get(key, "")).strip()
        for key in ("source_type", "source_url", "url", "source_authority", "authority_level")
    )


def _is_derived_numeric_claim(claim: ClaimItem) -> bool:
    text = f"{claim.section_name} {claim.claim_text} {claim.notes}".lower()
    derived_markers = [
        "derived",
        "estimated",
        "valuation",
        "model",
        "rank",
        "peer",
        "coverage",
        "trend",
        "估算",
        "估值",
        "模型",
        "排名",
        "同行",
        "覆盖",
        "汇总",
        "生成",
        "计算",
        "视图",
    ]
    return any(marker in text for marker in derived_markers)


def _check_chart_support(
    claims: List[ClaimItem],
    evidence_records: List[Dict[str, Any]],
    charts: List[Dict[str, Any]],
    warnings: List[str],
) -> None:
    has_numeric_claim = any(bool(claim.numeric_values) for claim in claims)
    if has_numeric_claim and not charts:
        warnings.append("Report has numeric claims but no charts were generated.")
    for chart in charts:
        output_path = str(chart.get("output_path") or "")
        if output_path and not Path(output_path).exists():
            warnings.append(f"Chart output path does not exist: {output_path}")
        source_fields = str(chart.get("source_fields") or "")
        if "claims" in source_fields and not has_numeric_claim:
            warnings.append(f"Chart {chart.get('chart_id', '')} expects claim numeric values but none are available.")
        if "evidence_records" in source_fields and not evidence_records:
            warnings.append(f"Chart {chart.get('chart_id', '')} expects evidence records but none are available.")


def _numbers_from_record(record: Dict[str, Any]) -> List[float]:
    values: List[float] = []
    values.extend(_numbers_from_text(str(record.get("content", ""))))
    values.extend(_numbers_from_json(record.get("metadata", {})))
    return values


def _numbers_from_json(value: Any) -> List[float]:
    values: List[float] = []
    if isinstance(value, dict):
        for item in value.values():
            values.extend(_numbers_from_json(item))
    elif isinstance(value, list):
        for item in value:
            values.extend(_numbers_from_json(item))
    elif isinstance(value, (int, float)):
        values.append(float(value))
    elif isinstance(value, str):
        values.extend(_numbers_from_text(value))
    return values


def _numbers_from_text(text: str) -> List[float]:
    values = []
    for match in re.findall(r"-?\d+(?:\.\d+)?", text):
        try:
            values.append(float(match))
        except ValueError:
            continue
    return values


def _ticker_mentions(text: str) -> set[str]:
    stop_words = {
        "API",
        "B",
        "DCF",
        "EV",
        "HTML",
        "ID",
        "JSON",
        "LLM",
        "PDF",
        "PE",
        "PS",
        "Q",
        "ROA",
        "ROE",
        "USD",
    }
    return {
        token
        for token in re.findall(r"\b[A-Z]{2,6}\b", text)
        if token not in stop_words and not re.fullmatch(r"Q[1-4]", token)
    }


def _has_close_number(target: float, values: List[float]) -> bool:
    for value in values:
        tolerance = max(abs(target) * 0.01, 0.05)
        if abs(value - target) <= tolerance:
            return True
    return False
