"""Citation table builder for multi-agent reports."""

from __future__ import annotations

from html import escape
from typing import Any, Dict, List
from urllib.parse import urlparse


REFERENCES_HEADER = "## 参考来源"

# Source types / authority patterns considered weak for financial valuation claims
_WEAK_NEWS_SOURCES = frozenset({
    "aastocks", "eastmoney", "eastmoney.com", "cnyes", "wallstreetcn",
    "stcn.com", "stcn", "yicai", "caixin", "sina.com", "163.com",
    "sohu.com", "ifeng.com", "hexun.com", "gelonghui", "xueqiu",
})

# Claim section names that are valuation-related — weak news must not be the sole support
_VALUATION_SECTIONS = frozenset({
    "valuation", "company_valuation", "dcf_valuation", "pe_valuation",
    "ps_valuation", "valuation_summary",
})


def _url_dedup_key(url: str) -> str:
    """Normalise a URL to a canonical key for deduplication (strip query/fragment)."""
    if not url:
        return ""
    try:
        p = urlparse(url)
        return f"{p.scheme}://{p.netloc}{p.path}".rstrip("/").lower()
    except Exception:
        return url.lower()


def _is_weak_news_source(item: Dict[str, Any]) -> bool:
    url = str(item.get("source_url") or item.get("url") or "").lower()
    authority = str(item.get("source_authority") or "").lower()
    authority_level = str(item.get("authority_level") or "").lower()
    source_type = str(item.get("source_type") or "").lower()
    title = str(item.get("title") or "").lower()
    if authority in {"official", "company_official"} or authority_level == "primary":
        return False
    if authority == "market_data" or authority_level == "market_data" or source_type in {"market", "market_api", "market_data"}:
        return False
    for pattern in _WEAK_NEWS_SOURCES:
        if pattern in url or pattern in authority:
            return True
    # Low authority score is also a signal
    try:
        if float(item.get("authority_score") or 0) < 0.25:
            return True
    except (TypeError, ValueError):
        pass
    return False


def build_citations(
    evidence_records: List[Dict[str, Any]],
    claims: List[Dict[str, Any]],
    markdown: str = "",
) -> List[Dict[str, Any]]:
    """Build a normalized citation table from evidence and claims.

    Deduplication rules applied here:
    1. Same evidence_id → keep first occurrence.
    2. Same canonical URL → merge into the first-seen record (keep highest score).
    3. Weak news sources are flagged and excluded from valuation-only claims.
    4. Evidence with no linked claims is included but flagged as unlinked.
    """

    claim_ids_by_evidence = _claim_ids_by_evidence(claims)
    # Build section map: evidence_id → set of claim section_names it supports
    section_by_evidence: Dict[str, set] = {}
    for claim in claims:
        if not isinstance(claim, dict):
            continue
        section = str(claim.get("section_name") or "")
        for eid in claim.get("evidence_ids", []):
            section_by_evidence.setdefault(str(eid), set()).add(section)

    # Step 1: deduplicate by evidence_id
    evidence_by_id: Dict[str, Dict[str, Any]] = {}
    for item in evidence_records:
        if not isinstance(item, dict):
            continue
        evidence_id = str(item.get("evidence_id") or item.get("sample_id") or "").strip()
        if not evidence_id or evidence_id in evidence_by_id:
            continue
        evidence_by_id[evidence_id] = item

    # Step 2: deduplicate by canonical URL — merge duplicates into the highest-score record
    url_to_primary: Dict[str, str] = {}  # canonical_url → primary evidence_id
    id_redirect: Dict[str, str] = {}     # secondary_id → primary_id
    for evidence_id, item in list(evidence_by_id.items()):
        url = str(item.get("source_url") or item.get("url") or "")
        key = _url_dedup_key(url)
        if not key:
            continue
        if key not in url_to_primary:
            url_to_primary[key] = evidence_id
        else:
            primary_id = url_to_primary[key]
            primary = evidence_by_id[primary_id]
            # Keep the record with the higher score as primary
            if float(item.get("score") or 0) > float(primary.get("score") or 0):
                id_redirect[primary_id] = evidence_id
                url_to_primary[key] = evidence_id
                del evidence_by_id[primary_id]
            else:
                id_redirect[evidence_id] = primary_id
                del evidence_by_id[evidence_id]

    # Remap claim_ids_by_evidence through redirects
    remapped_claim_ids: Dict[str, List[str]] = {}
    for eid, cids in claim_ids_by_evidence.items():
        canonical = id_redirect.get(eid, eid)
        existing = remapped_claim_ids.setdefault(canonical, [])
        for cid in cids:
            if cid not in existing:
                existing.append(cid)

    ordered_ids = _ordered_evidence_ids(claims=claims, evidence_by_id=evidence_by_id, id_redirect=id_redirect)
    citations = []
    for index, evidence_id in enumerate(ordered_ids, start=1):
        item = evidence_by_id.get(evidence_id, {})
        linked_claims = remapped_claim_ids.get(evidence_id, [])
        is_unlinked = len(linked_claims) == 0
        is_weak = _is_weak_news_source(item)

        # Detect if this evidence is only linked to valuation claims and is a weak source
        linked_sections = section_by_evidence.get(evidence_id, set())
        valuation_only = bool(linked_sections) and linked_sections.issubset(_VALUATION_SECTIONS)
        weak_on_valuation = is_weak and valuation_only

        citation = {
            "citation_id": f"ref_{index:03d}",
            "evidence_id": evidence_id,
            "title": str(item.get("title") or evidence_id),
            "source_url": str(item.get("source_url") or item.get("url") or ""),
            "source_type": str(item.get("source_type") or "unknown"),
            "source_authority": str(item.get("source_authority") or ""),
            "authority_score": float(item.get("authority_score", 0.0) or 0.0),
            "publish_time": str(item.get("publish_time") or ""),
            "trust_level": str(item.get("trust_level") or ""),
            "claim_ids": linked_claims,
            "used_in_report": f"[{evidence_id}]" in markdown or evidence_id in markdown,
            "content_preview": str(item.get("content") or item.get("snippet") or "")[:240],
        }
        # Keep the serialized citation table compact and backward-compatible:
        # absence means False, while true flags remain explicit for QA views.
        if is_unlinked:
            citation["is_unlinked"] = True
        if is_weak:
            citation["is_weak_source"] = True
        if weak_on_valuation:
            citation["weak_on_valuation"] = True
        citations.append(citation)
    return citations


def build_citation_artifacts(
    evidence_records: List[Dict[str, Any]],
    claims: List[Dict[str, Any]],
    markdown: str,
    html: str,
) -> Dict[str, Any]:
    """Build citation sidecars and attach references to report artifacts."""

    citations = build_citations(evidence_records=evidence_records, claims=claims, markdown=markdown)
    citations_markdown = render_citations_markdown(citations)
    return {
        "citations": citations,
        "citations_markdown": citations_markdown,
        "markdown": append_references_to_markdown(markdown, citations),
        "html": append_references_to_html(html, citations),
    }


def render_citations_markdown(citations: List[Dict[str, Any]]) -> str:
    lines = [REFERENCES_HEADER, ""]
    if not citations:
        lines.append("- 暂无参考来源。")
        lines.append("")
        return "\n".join(lines)

    linked_count = sum(1 for c in citations if not c.get("is_unlinked"))
    total_count = len(citations)
    lines.append(f"> 共 {total_count} 条来源，其中 {linked_count} 条已关联至具体结论。")
    lines.append("")

    for item in citations:
        title = str(item.get("title") or item.get("evidence_id") or "Untitled")
        evidence_id = str(item.get("evidence_id") or "")
        source_url = str(item.get("source_url") or "")
        source_type = str(item.get("source_type") or "unknown")
        source_authority = str(item.get("source_authority") or "unknown")
        publish_time = str(item.get("publish_time") or "")
        claim_ids = ", ".join(str(v) for v in item.get("claim_ids", [])) or "未关联"
        flags = []
        if item.get("is_unlinked"):
            flags.append("⚠ 未关联结论")
        if item.get("weak_on_valuation"):
            flags.append("⚠ 弱来源挂靠估值")
        elif item.get("is_weak_source"):
            flags.append("⚠ 弱来源")
        flag_str = f"  [{', '.join(flags)}]" if flags else ""
        if source_url:
            lines.append(f"- [{evidence_id}] {title} ({source_type}/{source_authority}, {publish_time}) - {source_url}{flag_str}")
        else:
            lines.append(f"- [{evidence_id}] {title} ({source_type}/{source_authority}, {publish_time}){flag_str}")
        lines.append(f"  - 支持结论: {claim_ids}")
    lines.append("")
    return "\n".join(lines)


def append_references_to_markdown(markdown: str, citations: List[Dict[str, Any]]) -> str:
    base = _strip_existing_references(markdown).rstrip()
    return base + "\n\n" + render_citations_markdown(citations)


def append_references_to_html(html: str, citations: List[Dict[str, Any]]) -> str:
    html = _strip_existing_html_references(html).rstrip()
    refs = ["<section><h2>参考来源</h2>"]
    if citations:
        refs.append("<ul>")
        for item in citations:
            evidence_id = escape(str(item.get("evidence_id", "")))
            title = escape(str(item.get("title", evidence_id)))
            source_url = str(item.get("source_url") or "")
            source_type = escape(str(item.get("source_type", "unknown")))
            source_authority = escape(str(item.get("source_authority", "unknown")))
            if source_url:
                safe_url = escape(source_url, quote=True)
                refs.append(f'<li><strong>[{evidence_id}]</strong> <a href="{safe_url}">{title}</a> ({source_type}/{source_authority})</li>')
            else:
                refs.append(f"<li><strong>[{evidence_id}]</strong> {title} ({source_type}/{source_authority})</li>")
        refs.append("</ul>")
    else:
        refs.append("<p>暂无参考来源。</p>")
    refs.append("</section>")
    block = "\n".join(refs)
    if "</body>" in html:
        return html.replace("</body>", block + "\n</body>")
    return html.rstrip() + "\n" + block + "\n"


def _claim_ids_by_evidence(claims: List[Dict[str, Any]]) -> Dict[str, List[str]]:
    mapping: Dict[str, List[str]] = {}
    for index, claim in enumerate(claims, start=1):
        if not isinstance(claim, dict):
            continue
        claim_id = str(claim.get("claim_id") or f"cl_{index:04d}")
        for evidence_id in claim.get("evidence_ids", []):
            evidence_id = str(evidence_id)
            mapping.setdefault(evidence_id, [])
            if claim_id not in mapping[evidence_id]:
                mapping[evidence_id].append(claim_id)
    return mapping


def _ordered_evidence_ids(
    claims: List[Dict[str, Any]],
    evidence_by_id: Dict[str, Dict[str, Any]],
    id_redirect: Dict[str, str] | None = None,
) -> List[str]:
    redirect = id_redirect or {}
    ordered = []
    for claim in claims:
        if not isinstance(claim, dict):
            continue
        for evidence_id in claim.get("evidence_ids", []):
            canonical = redirect.get(str(evidence_id), str(evidence_id))
            if canonical in evidence_by_id and canonical not in ordered:
                ordered.append(canonical)
    for evidence_id in evidence_by_id:
        if evidence_id not in ordered:
            ordered.append(evidence_id)
    return ordered


def _strip_existing_references(markdown: str) -> str:
    marker = f"\n{REFERENCES_HEADER}"
    if marker in markdown:
        return markdown[: markdown.index(marker)]
    if markdown.startswith(REFERENCES_HEADER):
        return ""
    legacy_marker = "\n## References"
    if legacy_marker in markdown:
        return markdown[: markdown.index(legacy_marker)]
    if markdown.startswith("## References"):
        return ""
    return markdown


def _strip_existing_html_references(html: str) -> str:
    lower = html.lower()
    markers = ["<section><h2>references</h2>", "<section><h2>参考来源</h2>"]
    indexes = [lower.find(marker) for marker in markers if lower.find(marker) >= 0]
    index = min(indexes) if indexes else -1
    if index < 0:
        return html
    body_index = lower.find("</body>", index)
    if body_index < 0:
        return html[:index]
    return html[:index] + html[body_index:]
