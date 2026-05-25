"""Generic gap resolver for company-report data repair constraints."""

from __future__ import annotations

from typing import Any, Dict, List

from src.agents.base_agent import AgentTask, BaseAgent, TaskResult


class GapResolverAgent(BaseAgent):
    """Detect report delivery gaps without company-specific special cases."""

    def __init__(self):
        super().__init__(name="GapResolverAgent")

    def get_capabilities(self) -> List[str]:
        return [
            "detect missing three-statement coverage",
            "detect valuation, peer, sensitivity, governance, and PDF consumption gaps",
            "produce repair constraints for writer and planner",
        ]

    def execute_task(self, task: AgentTask) -> TaskResult:
        evidence = _as_list(task.parameters.get("evidence_records"))
        claims = _as_list(task.parameters.get("claims"))
        markdown = str(task.parameters.get("markdown") or "")
        analysis = task.parameters.get("analysis_artifacts", {})
        analysis = analysis if isinstance(analysis, dict) else {}
        quality_plan = task.parameters.get("quality_remediation_plan", {})
        quality_plan = quality_plan if isinstance(quality_plan, dict) else {}
        symbol = str(task.parameters.get("symbol") or "")
        period = str(task.parameters.get("period") or "")

        financial_metrics = analysis.get("financial_metrics", {}) if isinstance(analysis.get("financial_metrics"), dict) else {}
        tables = _as_list(analysis.get("tables"))
        pdf_sections = _as_list(analysis.get("pdf_sections"))
        valuation = analysis.get("valuation", {}) if isinstance(analysis.get("valuation"), dict) else {}
        peer_context = analysis.get("peer_context", {}) if isinstance(analysis.get("peer_context"), dict) else {}

        gaps: List[Dict[str, Any]] = []
        required_sections: List[str] = []

        table_types = _table_types(tables)
        statement_gap_disclosed = _text_has_any(
            markdown,
            ["三表摘要暂不可用", "三表缺口", "未完整形成可引用证据", "three-statement data gap"],
        )
        for table_type, section_name, label in [
            ("income_statement", "financial_statements", "income statement"),
            ("balance_sheet", "financial_statements", "balance sheet"),
            ("cash_flow_statement", "financial_statements", "cash flow statement"),
        ]:
            if table_type not in table_types and not statement_gap_disclosed:
                gaps.append(_gap(table_type, "blocker", f"Missing {label} in artifacts and body."))
                required_sections.append(section_name)

        if table_types and not _text_has_any(markdown, ["利润表", "资产负债表", "现金流", "income statement", "balance sheet", "cash flow"]):
            gaps.append(_gap("three_statement_body", "blocker", "Statement artifacts exist but body does not consume them."))
            required_sections.append("financial_statements")

        if not valuation or not valuation.get("valuation_available"):
            if not _text_has_any(markdown, ["估值不可用原因", "valuation unavailable", "P/E", "P/B", "P/S"]):
                gaps.append(_gap("valuation", "blocker", "Valuation is unavailable but body lacks a clear reason."))
                required_sections.append("valuation")

        if not peer_context or int(peer_context.get("peer_count", 0) or 0) == 0:
            if not _text_has_any(markdown, ["同行", "可比公司", "peer"]):
                gaps.append(_gap("peer_compare", "warning", "Peer context is missing and body lacks peer comparison boundaries."))
                required_sections.append("peer_compare")

        if not _text_has_any(markdown, ["敏感性", "scenario", "sensitivity"]):
            gaps.append(_gap("valuation_sensitivity", "warning", "Sensitivity analysis is missing from body."))
            required_sections.append("valuation_sensitivity")

        if not _text_has_any(markdown, ["股权", "治理", "shareholder", "governance"]):
            gaps.append(_gap("ownership_governance", "warning", "Ownership/governance section is missing from body."))
            required_sections.append("ownership_governance")

        if pdf_sections and not _claims_have_source(claims, "pdf_section") and not _text_has_any(markdown, ["PDF", "公告片段", "年报"]):
            gaps.append(_gap("pdf_consumption", "warning", "PDF sections exist but are not consumed by claims/body."))
            required_sections.extend(["strategy_business", "ownership_governance", "risks"])

        source_failures = _source_failures(task.parameters.get("search_meta", {}))
        for failure in source_failures:
            gaps.append(_gap("data_source_failure", "warning", failure))

        for issue in quality_plan.get("issues", []) if isinstance(quality_plan.get("issues"), list) else []:
            if isinstance(issue, dict) and str(issue.get("severity", "")).lower() in {"fatal", "blocker"}:
                gaps.append(_gap(str(issue.get("category") or "quality_gate"), "blocker", str(issue.get("message") or issue)))

        required_sections = sorted(set(required_sections))
        repair_constraints = {
            "symbol": symbol,
            "period": period,
            "required_backfill_sections": required_sections,
            "free_public_source_boundary": "Use only free public sources; memory is not evidence.",
            "must_explain_unresolved_gaps": [gap["gap_type"] for gap in gaps if gap["severity"] in {"blocker", "warning"}],
        }
        summary = {
            "symbol": symbol,
            "period": period,
            "gap_count": len(gaps),
            "blocker_count": sum(1 for gap in gaps if gap["severity"] == "blocker"),
            "warning_count": sum(1 for gap in gaps if gap["severity"] == "warning"),
            "required_backfill_sections": required_sections,
            "financial_metric_count": int(financial_metrics.get("metric_count", 0) or 0),
            "table_types": sorted(table_types),
            "source_failure_count": len(source_failures),
        }
        return self.success(
            task,
            output={
                "gap_resolution_trace": gaps,
                "data_repair_summary": summary,
                "repair_constraints": repair_constraints,
                "required_backfill_sections": required_sections,
            },
            metadata={"gap_count": len(gaps), "required_backfill_sections": required_sections},
        )


def _as_list(value: Any) -> List[Any]:
    return value if isinstance(value, list) else []


def _table_types(tables: List[Any]) -> set[str]:
    output: set[str] = set()
    for table in tables:
        if not isinstance(table, dict):
            continue
        raw = str(table.get("table_type") or table.get("statement") or "").lower()
        if raw:
            output.add(raw)
        for row in table.get("rows", []) if isinstance(table.get("rows"), list) else []:
            if isinstance(row, dict):
                row_type = str(row.get("statement") or row.get("table_type") or "").lower()
                if row_type:
                    output.add(row_type)
    return output


def _text_has_any(text: str, terms: List[str]) -> bool:
    lowered = text.lower()
    return any(term.lower() in lowered for term in terms)


def _claims_have_source(claims: List[Any], source_type: str) -> bool:
    for claim in claims:
        raw = claim.to_dict() if hasattr(claim, "to_dict") else claim
        if isinstance(raw, dict) and source_type in str(raw.get("notes", "")):
            return True
    return False


def _source_failures(search_meta: Any) -> List[str]:
    if not isinstance(search_meta, dict):
        return []
    engine_meta = search_meta.get("engine_meta", search_meta)
    failures: List[str] = []
    if isinstance(engine_meta, dict):
        for engine, meta in engine_meta.items():
            if not isinstance(meta, dict):
                continue
            reason = str(meta.get("failure_reason") or meta.get("error") or "")
            if reason and reason not in {"", "no_records_for_symbol", "no_records_for_symbol_period"}:
                failures.append(f"{engine}: {reason}")
    return failures


def _gap(gap_type: str, severity: str, message: str) -> Dict[str, Any]:
    return {"gap_type": gap_type, "severity": severity, "message": message, "route": "final_answer"}
