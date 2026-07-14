"""Extract evidence-ready sections from SEC annual report filings."""

from __future__ import annotations

from html import unescape
import json
import re
from pathlib import Path
from typing import Any


ITEM_PATTERNS: list[tuple[str, list[str]]] = [
    ("business", [r"\bItem\s+1\.?\s+Bus\s*iness\b"]),
    ("risk_factors", [r"\bItem\s+1A\.?\s+Ris\s*k\s+Factors\b"]),
    ("mda", [r"\bItem\s+7\.?\s+Management'?s\s+Discussion", r"\bItem\s+7\.?\s+MD&A\b"]),
    ("market_risk", [r"\bItem\s+7A\.?\s+Quantitative"]),
    ("financial_statements", [r"\bItem\s+8\.?\s+Financial\s+Statements"]),
]

SUBSECTION_PATTERNS: list[tuple[str, list[str]]] = [
    ("segments", [r"\bSegment\s+(?:Information|Revenue|Results|Data)\b", r"\bRevenue\s+by\s+(?:Segment|Geography|Region)\b"]),
    ("competition", [r"\bCompetition\b", r"\bCompetitive\s+(?:Landscape|Environment|Position)\b"]),
    ("liquidity", [r"\bLiquidity\s+and\s+Capital\s+Resources\b", r"\bCapital\s+Resources\b"]),
    ("governance", [r"\bCorporate\s+Governance\b", r"\bBoard\s+of\s+Directors\b"]),
]

MAX_CHUNK_CHARS: dict[str, int] = {
    "business": 4500,
    "risk_factors": 6500,
    "mda": 6500,
    "market_risk": 2500,
    "financial_statements": 1500,
    "segments": 3000,
    "competition": 2500,
    "liquidity": 3500,
    "governance": 2500,
}


class AnnualReportSectionExtractor:
    """Extract bounded filing sections without returning a full 10-K body."""

    def __init__(self, html_text: str = "", html_path: str | Path = ""):
        self.html_text = html_text
        if not self.html_text and html_path:
            path = Path(html_path)
            if path.exists():
                self.html_text = path.read_text(encoding="utf-8", errors="replace")
        self.plain = _html_to_plain(self.html_text)

    def extract(
        self,
        symbol: str = "",
        period: str = "",
        filing_url: str = "",
        filing_title: str = "",
        filing_evidence_id: str = "",
    ) -> dict[str, Any]:
        """Return annual-report sections and coverage metadata."""

        source_id = filing_evidence_id or f"sec_10k_{str(symbol).lower()}_{str(period).lower()}"
        sections: dict[str, list[dict[str, Any]]] = {}
        for section_key, patterns in ITEM_PATTERNS:
            sections[section_key] = self._extract_item_section(
                section_key=section_key,
                patterns=patterns,
                source_id=source_id,
                filing_url=filing_url,
            )

        for section_key, patterns in SUBSECTION_PATTERNS:
            scope = sections.get("business") or sections.get("mda") or []
            scoped_text = "\n\n".join(str(item.get("text") or "") for item in scope)
            sections[section_key] = self._extract_keyword_section(
                section_key=section_key,
                patterns=patterns,
                source_id=source_id,
                filing_url=filing_url,
                scoped_text=scoped_text or self.plain,
            )

        return {
            "source_id": source_id,
            "source_url": filing_url,
            "filing_title": filing_title,
            "symbol": symbol,
            "period": period,
            "sections": sections,
            "coverage": {key: bool(value) for key, value in sections.items()},
            "section_count": sum(len(value) for value in sections.values()),
        }

    def _extract_item_section(
        self,
        section_key: str,
        patterns: list[str],
        source_id: str,
        filing_url: str,
    ) -> list[dict[str, Any]]:
        ranges = _item_heading_ranges(self.plain)
        wanted = _wanted_item_for_section(section_key)
        text = ""
        if wanted and wanted in ranges:
            start, end = ranges[wanted]
            text = self.plain[start:end]
        if not text:
            text = _extract_by_patterns(self.plain, patterns, MAX_CHUNK_CHARS.get(section_key, 3000))
        return _make_chunks(section_key, text, source_id=source_id, filing_url=filing_url)

    def _extract_keyword_section(
        self,
        section_key: str,
        patterns: list[str],
        source_id: str,
        filing_url: str,
        scoped_text: str,
    ) -> list[dict[str, Any]]:
        text = _extract_by_patterns(scoped_text, patterns, MAX_CHUNK_CHARS.get(section_key, 2500), boundary_lines=80)
        return _make_chunks(section_key, text, source_id=source_id, filing_url=filing_url, max_chunks=2)

    def to_json(self, output_path: str | Path, **extra: Any) -> Path:
        data = self.extract(**extra)
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return path


def annual_sections_to_evidence_records(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Convert extractor output into citation-ready evidence records."""

    records: list[dict[str, Any]] = []
    sections = payload.get("sections", {}) if isinstance(payload, dict) else {}
    if not isinstance(sections, dict):
        return records
    symbol = str(payload.get("symbol") or "")
    period = str(payload.get("period") or "")
    source_url = str(payload.get("source_url") or "")
    for section_key, chunks in sections.items():
        if not isinstance(chunks, list):
            continue
        for chunk in chunks:
            if not isinstance(chunk, dict):
                continue
            evidence_id = str(chunk.get("evidence_id") or "")
            text = str(chunk.get("text") or "").strip()
            if not evidence_id or not text:
                continue
            records.append(
                {
                    "evidence_id": evidence_id,
                    "sample_id": evidence_id,
                    "source_type": "sec_10k_section",
                    "title": str(chunk.get("citation_title") or f"SEC 10-K {_section_label(section_key)}"),
                    "source_url": str(chunk.get("source_url") or source_url),
                    "publish_time": "",
                    "content": text,
                    "symbol": symbol,
                    "period": period,
                    "trust_level": "high",
                    "metadata": {
                        "provider": "SEC EDGAR",
                        "section_key": section_key,
                        "section_label": _section_label(section_key),
                        "source_id": payload.get("source_id", ""),
                        "chunk_index": chunk.get("chunk_index", 0),
                        "extraction_method": "sec_10k_item_sections_v1",
                    },
                }
            )
    return records


def _item_heading_ranges(text: str) -> dict[str, tuple[int, int]]:
    heading_re = re.compile(
        r"(?i)\bItem\s+(1A|1B|1C|1|2|3|4|5|6|7A|7|8|9A|9B|9C|9)\.?\s+"
        r"(?:Bus\s*iness|Ris\s*k\s+Factors|Unresolved|Cybersecurity|Properties|Legal|Mine|Market|"
        r"Selected|Management|Quantitative|Financial|Changes|Controls|Other)",
    )
    raw_matches = list(heading_re.finditer(text))
    best_by_item: dict[str, re.Match[str]] = {}
    score_by_item: dict[str, int] = {}
    for match in raw_matches:
        item = match.group(1).upper()
        score = _heading_score(text, match, item)
        if score > score_by_item.get(item, -999):
            best_by_item[item] = match
            score_by_item[item] = score
    matches = sorted(best_by_item.values(), key=lambda item: item.start())
    ranges: dict[str, tuple[int, int]] = {}
    for idx, match in enumerate(matches):
        item = match.group(1).upper()
        start = match.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else min(len(text), start + 7000)
        ranges.setdefault(item, (start, end))
    return ranges


def _heading_score(text: str, match: re.Match[str], item: str) -> int:
    before = text[max(0, match.start() - 250) : match.start()]
    after = text[match.end() : match.end() + 700]
    score = 1
    if "Table of Contents" in before and re.search(r"\bPage\b|\bPart\s+[I,V,X]+\b", after[:250]):
        score -= 6
    if re.search(r"\bItem\s+\d+[A-Z]?\.?\s+", after[:220], flags=re.IGNORECASE):
        score -= 5
    if item == "1" and re.search(r"Our Company|pioneered accelerated|business overview|products", after, flags=re.IGNORECASE):
        score += 8
    if item == "1A" and re.search(r"The following risk factors|could harm our business|financial condition|results of operations", after, flags=re.IGNORECASE):
        score += 8
    if item == "1A" and re.search(r"^\s*The following risk factors", after, flags=re.IGNORECASE):
        score += 12
    if item == "1A" and re.search(r"for a discussion", after[:220], flags=re.IGNORECASE):
        score -= 5
    if item == "7" and re.search(r"Results of Operations|Liquidity|Management.?s discussion", after, flags=re.IGNORECASE):
        score += 8
    if item == "7" and re.search(r"^\s*The following discussion", after, flags=re.IGNORECASE):
        score += 10
    if item == "7" and re.search(r"The following discussion", after[:350], flags=re.IGNORECASE):
        score += 10
    if item == "7" and re.search(r"\bItem\s+7A\b", after[:180], flags=re.IGNORECASE):
        score -= 6
    if item == "7A" and re.search(r"market risk|interest rate|foreign currency", after, flags=re.IGNORECASE):
        score += 5
    if item == "7A" and re.search(r"^\s*(Investment|Interest Rate|Foreign Currency)", after, flags=re.IGNORECASE):
        score += 8
    if item == "8" and re.search(r"financial statements|consolidated", after, flags=re.IGNORECASE):
        score += 5
    if item == "8" and re.search(r"^\s*The information required by this Item", after, flags=re.IGNORECASE):
        score += 8
    if len(after.strip()) > 250:
        score += 1
    return score


def _wanted_item_for_section(section_key: str) -> str:
    return {
        "business": "1",
        "risk_factors": "1A",
        "mda": "7",
        "market_risk": "7A",
        "financial_statements": "8",
    }.get(section_key, "")


def _extract_by_patterns(text: str, patterns: list[str], max_chars: int, boundary_lines: int = 220) -> str:
    lines = text.splitlines()
    for idx, line in enumerate(lines):
        if not any(re.search(pattern, line, flags=re.IGNORECASE) for pattern in patterns):
            continue
        collected: list[str] = []
        for line2 in lines[idx + 1 : idx + 1 + boundary_lines]:
            stripped = line2.strip()
            if not stripped:
                continue
            if re.match(r"(?i)^\s*Item\s+\d+[A-Z]?\.?\s+", stripped) and collected:
                break
            collected.append(stripped)
            if sum(len(item) for item in collected) >= max_chars:
                break
        return "\n".join(collected)[:max_chars]
    return ""


def _make_chunks(
    section_key: str,
    text: str,
    source_id: str,
    filing_url: str,
    max_chunks: int = 3,
) -> list[dict[str, Any]]:
    cleaned = _clean_section_text(text)
    if len(cleaned) < 80:
        return []
    max_chars = MAX_CHUNK_CHARS.get(section_key, 3000)
    cleaned = cleaned[:max_chars]
    chunk_size = max(900, min(1800, max(1, len(cleaned) // max_chunks)))
    chunks: list[dict[str, Any]] = []
    pos = 0
    while pos < len(cleaned) and len(chunks) < max_chunks:
        piece = cleaned[pos : pos + chunk_size].strip()
        pos += chunk_size
        if len(piece) < 80:
            continue
        index = len(chunks) + 1
        evidence_id = f"{source_id}_{section_key}_{index}".replace("-", "_").lower()
        chunks.append(
            {
                "text": piece,
                "section_key": section_key,
                "evidence_id": evidence_id,
                "citation_title": f"SEC 10-K {_section_label(section_key)} (part {index})",
                "source_id": source_id,
                "source_url": filing_url,
                "chunk_index": index,
            }
        )
    return chunks


def _section_label(section_key: str) -> str:
    return {
        "business": "Item 1 Business",
        "risk_factors": "Item 1A Risk Factors",
        "mda": "Item 7 MD&A",
        "market_risk": "Item 7A Market Risk",
        "financial_statements": "Item 8 Financial Statements",
        "segments": "Segment Information",
        "competition": "Competition",
        "liquidity": "Liquidity and Capital Resources",
        "governance": "Corporate Governance",
    }.get(section_key, section_key.replace("_", " ").title())


def _html_to_plain(html: str) -> str:
    text = str(html or "")
    text = re.sub(r"<script[^>]*>.*?</script>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<ix:[^>]+>", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"</ix:[^>]+>", " ", text, flags=re.IGNORECASE)
    for tag in ("p", "div", "tr", "li", "br", "h1", "h2", "h3", "h4", "h5", "h6", "table"):
        text = re.sub(rf"<{tag}\b[^>]*>", "\n", text, flags=re.IGNORECASE)
        text = re.sub(rf"</{tag}>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = unescape(text)
    return _clean_section_text(text)


def _clean_section_text(text: str) -> str:
    text = str(text or "").replace("\xa0", " ")
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\n[ \t]+", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
