"""Shared retrieval diagnostic helpers for evidence recall quality."""

from __future__ import annotations

from typing import Any


def build_retrieval_coverage(
    *,
    candidates: list[Any],
    returned: list[dict[str, Any]],
    company: str | None = None,
    source_type: str | None = None,
    mode_effective: str = "",
) -> dict[str, Any]:
    """Build a stable coverage contract for DB and file-backed retrieval."""

    returned_sources = sorted({_source_type(item) for item in returned if _source_type(item)})
    candidate_sources = sorted({_source_type(item) for item in candidates if _source_type(item)})
    returned_source_groups = {_canonical_source_group(source) for source in returned_sources}
    required_sources = required_sources_for_query(company=company, source_type=source_type)
    missing_sources = [source for source in required_sources if _canonical_source_group(source) not in returned_source_groups]
    gaps = retrieval_gaps(
        candidate_count=len(candidates),
        returned_count=len(returned),
        missing_sources=missing_sources,
        mode_effective=mode_effective,
    )
    return {
        "candidate_count": len(candidates),
        "returned_count": len(returned),
        "candidate_sources": candidate_sources,
        "returned_sources": returned_sources,
        "required_sources": required_sources,
        "missing_sources": missing_sources,
        "evidence_ready": bool(returned),
        "quality_ready": bool(returned) and not missing_sources,
        "gaps": gaps,
        "summary": coverage_summary(
            candidate_count=len(candidates),
            returned_count=len(returned),
            missing_sources=missing_sources,
            mode_effective=mode_effective,
        ),
    }


def required_sources_for_query(*, company: str | None, source_type: str | None = None) -> list[str]:
    if source_type:
        return [source_type]
    normalized = _norm(company)
    if not normalized:
        return []
    if any(token in normalized for token in ["nvda", "nvidia", "aapl", "apple", "msft", "tesla", "tsla", "baba"]):
        return ["sec_edgar"]
    if any(token in normalized for token in ["0700", "tencent", "9988"]):
        return ["hkex"]
    if any(token in normalized for token in ["600", "300", "002", "贵州", "宁德", "比亚迪"]):
        return ["cninfo"]
    return []


def retrieval_gaps(
    *,
    candidate_count: int,
    returned_count: int,
    missing_sources: list[str],
    mode_effective: str,
) -> list[dict[str, Any]]:
    gaps: list[dict[str, Any]] = []
    if candidate_count <= 0:
        gaps.append(
            {
                "type": "no_candidates",
                "label": "没有候选证据",
                "description": "当前筛选条件下没有可检索证据，请先补充采集或手动导入资料。",
                "next_view": "ingestion",
            }
        )
    elif returned_count <= 0:
        gaps.append(
            {
                "type": "no_hits",
                "label": "没有命中证据",
                "description": "已有候选证据，但查询词、公司或期间没有形成有效命中。",
                "next_view": "evidence",
            }
        )
    if missing_sources:
        gaps.append(
            {
                "type": "source_gap",
                "label": "来源覆盖不足",
                "description": "当前结果缺少：" + "、".join(missing_sources),
                "sources": missing_sources,
                "next_view": "datasources",
            }
        )
    if mode_effective in {"keyword_only", "quality_rule_only", "bm25"}:
        gaps.append(
            {
                "type": "fusion_degraded",
                "label": "融合信号不足",
                "description": "当前检索只命中了单一路径，建议补充更多证据或更具体的查询词。",
                "next_view": "manual",
            }
        )
    if mode_effective == "no_hits":
        gaps.append(
            {
                "type": "retrieval_failed",
                "label": "检索未命中",
                "description": "没有可用于支持研报主张的召回结果，正式研报不应引用该查询结果。",
                "next_view": "ingestion",
            }
        )
    return gaps


def coverage_summary(
    *,
    candidate_count: int,
    returned_count: int,
    missing_sources: list[str],
    mode_effective: str,
) -> str:
    if returned_count <= 0:
        return "未召回可用证据，需要补充来源或调整查询。"
    if missing_sources:
        return "已召回证据，但来源覆盖仍需补齐。"
    if mode_effective in {"keyword_quality_fusion", "hybrid"}:
        return "关键词和证据质量信号同时命中，可进入证据复核。"
    if candidate_count > returned_count:
        return "已从候选证据中筛出相关结果，建议继续核对原文。"
    return "已召回可复核证据。"


def _source_type(item: Any) -> str:
    if isinstance(item, dict):
        return str(item.get("source_type") or "").strip()
    return str(getattr(item, "source_type", "") or "").strip()


def _canonical_source_group(source: str) -> str:
    normalized = str(source or "").strip().lower()
    if normalized in {"cninfo", "cninfo_announcement", "cninfo_announcements", "exchange_announcement", "exchange_announcements"}:
        return "cninfo"
    if normalized in {"hkex", "hkex_announcement", "hkex_announcements", "hkex_annual_report"}:
        return "hkex"
    if normalized in {"sec", "sec_edgar", "official_10k", "official_10q", "official_filing"}:
        return "sec_edgar"
    return normalized


def _norm(value: str | None) -> str:
    return "".join(str(value or "").strip().lower().split())
