"""Citation table builder for multi-agent reports."""

from __future__ import annotations

from html import escape
from typing import Any, Dict, List


REFERENCES_HEADER = "## 参考来源"


def build_citations(
    evidence_records: List[Dict[str, Any]],
    claims: List[Dict[str, Any]],
    markdown: str = "",
) -> List[Dict[str, Any]]:
    """Build a normalized citation table from evidence and claims."""

    claim_ids_by_evidence = _claim_ids_by_evidence(claims)
    evidence_by_id: Dict[str, Dict[str, Any]] = {}
    for item in evidence_records:
        if not isinstance(item, dict):
            continue
        evidence_id = str(item.get("evidence_id") or item.get("sample_id") or "").strip()
        if not evidence_id or evidence_id in evidence_by_id:
            continue
        evidence_by_id[evidence_id] = item

    ordered_ids = _ordered_evidence_ids(claims=claims, evidence_by_id=evidence_by_id)
    citations = []
    for index, evidence_id in enumerate(ordered_ids, start=1):
        item = evidence_by_id.get(evidence_id, {})
        metadata = item.get("metadata", {}) if isinstance(item.get("metadata"), dict) else {}
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
                "claim_ids": claim_ids_by_evidence.get(evidence_id, []),
                "used_in_report": f"[{evidence_id}]" in markdown or evidence_id in markdown,
                "content_preview": str(item.get("content") or item.get("snippet") or "")[:240],
            }
        page = metadata.get("page") or metadata.get("page_number") or item.get("page") or item.get("page_number")
        document_id = metadata.get("source_evidence_id") or metadata.get("section_id") or metadata.get("table_id")
        extraction_method = metadata.get("extraction_method")
        if page not in (None, ""):
            citation["page"] = page
        if document_id:
            citation["source_document_id"] = str(document_id)
        if extraction_method:
            citation["extraction_method"] = str(extraction_method)
        citations.append(citation)
    return citations


def build_citations_from_map(
    evidence_records: List[Dict[str, Any]],
    citation_map: Dict[str, Any] | List[Dict[str, Any]],
    claims: List[Dict[str, Any]] | None = None,
    markdown: str = "",
) -> List[Dict[str, Any]]:
    """Build normalized citations from a contract-mode citation map."""

    claims = claims or []
    evidence_by_id: Dict[str, Dict[str, Any]] = {}
    for item in evidence_records:
        if not isinstance(item, dict):
            continue
        evidence_id = str(item.get("evidence_id") or item.get("sample_id") or "").strip()
        if evidence_id and evidence_id not in evidence_by_id:
            evidence_by_id[evidence_id] = item

    entries: List[Dict[str, Any]] = []
    if isinstance(citation_map, dict) and isinstance(citation_map.get("citation_map"), list):
        entries = [item for item in citation_map.get("citation_map", []) if isinstance(item, dict)]
    elif isinstance(citation_map, dict):
        for evidence_id, number in citation_map.items():
            if not evidence_id:
                continue
            try:
                citation_number = int(number)
            except (TypeError, ValueError):
                continue
            record = evidence_by_id.get(str(evidence_id), {})
            entries.append(
                {
                    "citation_number": citation_number,
                    "evidence_id": str(evidence_id),
                    "title": str(record.get("title") or evidence_id),
                    "source_url": str(record.get("source_url") or record.get("url") or ""),
                    "source_type": str(record.get("source_type") or "unknown"),
                    "trust_level": str(record.get("trust_level") or ""),
                }
            )
    elif isinstance(citation_map, list):
        entries = [item for item in citation_map if isinstance(item, dict)]

    claim_ids_by_evidence = _claim_ids_by_evidence(claims)
    citations: List[Dict[str, Any]] = []
    for index, entry in enumerate(sorted(entries, key=lambda item: int(item.get("citation_number") or 999999)), start=1):
        evidence_id = str(entry.get("evidence_id") or "").strip()
        if not evidence_id:
            continue
        record = evidence_by_id.get(evidence_id, {})
        metadata = record.get("metadata", {}) if isinstance(record.get("metadata"), dict) else {}
        source_url = str(entry.get("source_url") or record.get("source_url") or record.get("url") or "")
        source_type = str(entry.get("source_type") or record.get("source_type") or "unknown")
        citation = {
            "citation_id": f"ref_{index:03d}",
            "citation_number": int(entry.get("citation_number") or index),
            "evidence_id": evidence_id,
            "title": str(entry.get("title") or record.get("title") or evidence_id),
            "source_url": source_url,
            "source_type": source_type,
            "source_authority": str(record.get("source_authority") or ""),
            "authority_score": float(record.get("authority_score", 0.0) or 0.0),
            "publish_time": str(record.get("publish_time") or ""),
            "trust_level": str(entry.get("trust_level") or record.get("trust_level") or ""),
            "claim_ids": claim_ids_by_evidence.get(evidence_id, []),
            "used_in_report": f"[{entry.get('citation_number') or index}]" in markdown or evidence_id in markdown,
            "content_preview": str(record.get("content") or record.get("snippet") or "")[:240],
        }
        page = metadata.get("page") or metadata.get("page_number") or record.get("page") or record.get("page_number")
        if page not in (None, ""):
            citation["page"] = page
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

    for item in citations:
        title = str(item.get("title") or item.get("evidence_id") or "Untitled")
        evidence_id = str(item.get("evidence_id") or "")
        source_url = str(item.get("source_url") or "")
        source_type = str(item.get("source_type") or "unknown")
        source_authority = str(item.get("source_authority") or "unknown")
        publish_time = str(item.get("publish_time") or "")
        if source_url:
            lines.append(f"- [{evidence_id}] {title} ({source_type}/{source_authority}, {publish_time}) - {source_url}")
        else:
            lines.append(f"- [{evidence_id}] {title} ({source_type}/{source_authority}, {publish_time})")
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


def _ordered_evidence_ids(claims: List[Dict[str, Any]], evidence_by_id: Dict[str, Dict[str, Any]]) -> List[str]:
    ordered = []
    for claim in claims:
        if not isinstance(claim, dict):
            continue
        for evidence_id in claim.get("evidence_ids", []):
            evidence_id = str(evidence_id)
            if evidence_id in evidence_by_id and evidence_id not in ordered:
                ordered.append(evidence_id)
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
