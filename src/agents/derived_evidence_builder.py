"""Build derived evidence records from internal model outputs.

Internal models (valuation, financial metrics, peer comparison, charts)
produce analysis that should be converted to standard evidence records
so they can be traced, cited, and used for claim grounding.
"""

from __future__ import annotations

from typing import Any, Dict, List


def build_derived_evidence(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Extract internal model outputs from orchestrator state and return derived evidence records.

    Scans state for financial_metrics, valuation_analysis, peer_analysis,
    three_statement_analysis, and tables, converting each to a standard
    derived-evidence record with input_evidence_ids where possible.
    """
    derived: List[Dict[str, Any]] = []
    symbol = str(state.get("symbol", "")).upper() or "unknown"
    period = str(state.get("period", "")).upper() or "unknown"

    analysis_artifacts: dict = {}
    if isinstance(state.get("analysis_artifacts"), dict):
        analysis_artifacts = dict(state["analysis_artifacts"])
    blackboard: dict = {}
    if isinstance(state.get("research_blackboard"), dict):
        blackboard = dict(state["research_blackboard"])

    # ── financial_metrics ──
    financial_metrics = analysis_artifacts.get("financial_metrics", {})
    if isinstance(financial_metrics, dict) and financial_metrics:
        evidence_ids = _collect_evidence_ids(state)
        derived.append({
            "evidence_id": f"internal_financial_metrics_{symbol}_{period}_v1",
            "source_type": "internal_model",
            "trust_level": "derived",
            "title": f"{symbol} {period} 财务指标",
            "content": _fmt_dict_summary(financial_metrics, max_keys=25),
            "input_evidence_ids": evidence_ids,
            "input_claim_ids": [],
            "assumptions": ["基于可获取的财务报表和公开数据"],
            "limitations": ["财务指标为内部计算值，可能与官方口径存在差异"],
            "generated_by_agent": "three_statement_analysis",
            "symbol": symbol,
            "period": period,
        })

    # ── valuation_analysis ──
    valuation = analysis_artifacts.get("valuation", {})
    if not isinstance(valuation, dict) or not valuation:
        valuation = blackboard.get("valuation_analysis", {})
    if not isinstance(valuation, dict) or not valuation:
        valuation = analysis_artifacts.get("valuation_model", {})
    if isinstance(valuation, dict) and valuation:
        content_parts = []
        for method in ("dcf", "dcf_model", "pe_ratio", "pb_ratio", "relative_valuation", "comparables", "blended_equity_value_billion", "target_price"):
            val = valuation.get(method) or valuation.get(f"{method}_value")
            if val is not None:
                content_parts.append(f"{method}: {val}")
        derived.append({
            "evidence_id": f"internal_valuation_{symbol}_{period}_v1",
            "source_type": "internal_model",
            "trust_level": "derived",
            "title": f"{symbol} {period} 估值分析",
            "content": "; ".join(content_parts) if content_parts else str(valuation),
            "input_evidence_ids": _collect_evidence_ids(state),
            "input_claim_ids": _collect_claim_ids(state),
            "assumptions": valuation.get("assumptions", ["标准估值模型假设"]),
            "limitations": valuation.get("limitations", ["估值依赖公开数据和模型假设"]),
            "generated_by_agent": "valuation_analysis",
            "symbol": symbol,
            "period": period,
        })

    sensitivity = analysis_artifacts.get("valuation_sensitivity", {})
    if isinstance(sensitivity, dict) and sensitivity:
        derived.append({
            "evidence_id": f"internal_valuation_sensitivity_{symbol}_{period}_v1",
            "source_type": "internal_model",
            "trust_level": "derived",
            "title": f"{symbol} {period} 估值敏感性分析",
            "content": _fmt_dict_summary(sensitivity, max_keys=20),
            "input_evidence_ids": _collect_evidence_ids(state),
            "input_claim_ids": _collect_claim_ids(state),
            "assumptions": ["基于估值模型情景假设生成敏感性结果"],
            "limitations": ["敏感性结果依赖模型假设，不等同于外部披露事实"],
            "generated_by_agent": "valuation_sensitivity",
            "symbol": symbol,
            "period": period,
        })

    # ── peer_analysis ──
    peer = analysis_artifacts.get("peer_analysis", {})
    if not isinstance(peer, dict) or not peer:
        peer = blackboard.get("peer_analysis", {})
    if isinstance(peer, dict) and peer:
        derived.append({
            "evidence_id": f"internal_peer_comparison_{symbol}_{period}_v1",
            "source_type": "internal_model",
            "trust_level": "derived",
            "title": f"{symbol} {period} 同行对比",
            "content": _fmt_dict_summary(peer, max_keys=20),
            "input_evidence_ids": _collect_evidence_ids(state),
            "input_claim_ids": _collect_claim_ids(state),
            "assumptions": ["同行公司基于行业分类和市值筛选"],
            "limitations": ["同行数据可能不完整，对比结果仅供参考"],
            "generated_by_agent": "peer_analysis",
            "symbol": symbol,
            "period": period,
        })

    # ── tables ──
    tables = analysis_artifacts.get("tables", [])
    if isinstance(tables, list):
        for i, table in enumerate(tables):
            if not isinstance(table, dict):
                continue
            table_id = str(table.get("table_id", f"table_{i}"))
            derived.append({
                "evidence_id": f"internal_table_{symbol}_{period}_{table_id}_v1",
                "source_type": "derived_metric",
                "trust_level": "derived",
                "title": str(table.get("title", f"财务表格 {i+1}")),
                "content": str(table.get("markdown", str(table))),
                "input_evidence_ids": _collect_evidence_ids(state),
                "input_claim_ids": [],
                "assumptions": ["基于已获取的结构化财务数据"],
                "limitations": ["表格数据为结构化呈现，可能不包含所有脚注信息"],
                "generated_by_agent": str(table.get("generated_by", "analysis")),
                "symbol": symbol,
                "period": period,
            })

    return derived


def _collect_evidence_ids(state: Dict[str, Any]) -> List[str]:
    """Collect evidence_ids from state for evidence tracing."""
    ids: List[str] = []
    records = state.get("evidence_records", [])
    if isinstance(records, list):
        for r in records:
            if isinstance(r, dict) and r.get("evidence_id"):
                ids.append(str(r["evidence_id"]))
    return ids


def _collect_claim_ids(state: Dict[str, Any]) -> List[str]:
    """Collect claim_ids from state for claim tracing."""
    ids: List[str] = []
    claims = state.get("claims", [])
    if isinstance(claims, list):
        for c in claims:
            if isinstance(c, dict) and c.get("claim_id"):
                ids.append(str(c["claim_id"]))
    return ids


def _fmt_dict_summary(d: dict, max_keys: int = 20) -> str:
    """Format a dict as a concise text summary."""
    parts: List[str] = []
    for i, (k, v) in enumerate(d.items()):
        if i >= max_keys:
            parts.append(f"... 等 {len(d)} 项")
            break
        if isinstance(v, (int, float)):
            parts.append(f"{k}: {v}")
        elif isinstance(v, str) and len(v) < 120:
            parts.append(f"{k}: {v}")
        elif isinstance(v, list) and len(v) <= 5:
            parts.append(f"{k}: {v}")
        else:
            parts.append(f"{k}: ({type(v).__name__})")
    return "; ".join(parts)
