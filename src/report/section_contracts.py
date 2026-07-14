"""Contract-first generation: SectionEvidenceContract defines what each report section
can use as evidence, enforcing source-type routing and fact-level granularity.

This module replaces the old approach where FinalAnswerAgent had unrestricted access
to global evidence_records, claims, peer_rows, and citations.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional


# ── canonical section keys ──────────────────────────────────────────────

SECTION_TITLES: Dict[str, str] = {
    "executive_summary": "执行摘要",
    "business_overview": "业务概览",
    "ownership_governance": "股权结构与公司治理",
    "strategy_business": "战略与主营业务",
    "three_statement_summary": "三表摘要",
    "financial_analysis": "财务分析",
    "peer_compare": "同行对比",
    "valuation": "估值观察",
    "valuation_sensitivity": "估值敏感性",
    "risk_factors": "风险评估",
    "investment_conclusion": "投资结论",
    "period_note": "数据期间说明",
    "currency_data_quality": "货币与数据质量说明",
}

ALL_SECTION_KEYS = list(SECTION_TITLES.keys())

# ── evidence source type constants ──────────────────────────────────────

# PDF official filing sources
SRC_ANNUAL_REPORT_PDF_SUMMARY = "annual_report_pdf_section_summary"
SRC_ANNUAL_REPORT_PDF_CHUNK = "annual_report_pdf_chunk"
SRC_OFFICIAL_FILING = "official_filing"
SRC_SEC_EDGAR = "sec_edgar"
SRC_SEC_10K_FILING = "sec_10k_filing"
SRC_SEC_10K_SECTION = "sec_10k_section"

# Financial structured sources
SRC_INCOME_TABLE = "income_table"
SRC_BALANCE_TABLE = "balance_table"
SRC_CASHFLOW_TABLE = "cashflow_table"
SRC_FINANCIAL_METRIC = "financial_metric"
SRC_THIRD_PARTY_STRUCTURED = "third_party_structured"

# Market / reference sources
SRC_MARKET_DATA = "market_data"
SRC_PEER_DATA = "peer_data"
SRC_VALUATION_MODEL = "valuation_model"

# Other
SRC_YAHOO_PROFILE = "yahoo_profile"
SRC_WEB_SEARCH = "web_search"
SRC_INDUSTRY_POLICY = "industry_policy"

# ── allowed source type policies per section ────────────────────────────

# Qualitative sections: PDF / official filing / SEC 10-K only, NO financial tables
ALLOWED_QUALITATIVE_PDF_ONLY = {
    SRC_ANNUAL_REPORT_PDF_SUMMARY,
    SRC_ANNUAL_REPORT_PDF_CHUNK,
    SRC_OFFICIAL_FILING,
    SRC_SEC_EDGAR,
    SRC_SEC_10K_FILING,
    SRC_SEC_10K_SECTION,
}

# Financial sections: can use both PDF/official and structured financial data
ALLOWED_FINANCIAL = {
    SRC_ANNUAL_REPORT_PDF_SUMMARY,
    SRC_ANNUAL_REPORT_PDF_CHUNK,
    SRC_OFFICIAL_FILING,
    SRC_SEC_EDGAR,
    SRC_SEC_10K_FILING,
    SRC_SEC_10K_SECTION,
    SRC_INCOME_TABLE,
    SRC_BALANCE_TABLE,
    SRC_CASHFLOW_TABLE,
    SRC_FINANCIAL_METRIC,
    SRC_THIRD_PARTY_STRUCTURED,
}

# Financial tables only
ALLOWED_FINANCIAL_TABLES_ONLY = {
    SRC_INCOME_TABLE,
    SRC_BALANCE_TABLE,
    SRC_CASHFLOW_TABLE,
    SRC_FINANCIAL_METRIC,
    SRC_THIRD_PARTY_STRUCTURED,
}

# ── forbidden source type policies ──────────────────────────────────────

FORBIDDEN_SECTION_SOURCE_TYPES: Dict[str, List[str]] = {
    # Qualitative sections must NOT cite financial tables as primary evidence
    "business_overview": [
        SRC_INCOME_TABLE, SRC_BALANCE_TABLE, SRC_CASHFLOW_TABLE,
        SRC_FINANCIAL_METRIC, SRC_THIRD_PARTY_STRUCTURED,
    ],
    "ownership_governance": [
        SRC_INCOME_TABLE, SRC_BALANCE_TABLE, SRC_CASHFLOW_TABLE,
        SRC_FINANCIAL_METRIC, SRC_THIRD_PARTY_STRUCTURED,
        SRC_PEER_DATA, SRC_MARKET_DATA,
    ],
    "strategy_business": [
        SRC_INCOME_TABLE, SRC_BALANCE_TABLE, SRC_CASHFLOW_TABLE,
        SRC_THIRD_PARTY_STRUCTURED,
    ],
    "risk_factors": [
        SRC_INCOME_TABLE, SRC_BALANCE_TABLE, SRC_CASHFLOW_TABLE,
        SRC_FINANCIAL_METRIC, SRC_THIRD_PARTY_STRUCTURED,
    ],
    "investment_conclusion": [
        SRC_INCOME_TABLE, SRC_BALANCE_TABLE, SRC_CASHFLOW_TABLE,
    ],
}


# ── data contracts ──────────────────────────────────────────────────────


@dataclass
class Fact:
    """A single atomic fact for a report section."""
    fact_type: str  # e.g. "business_model", "revenue", "governance_structure"
    text: str  # clean Chinese prose
    evidence_ids: List[str] = field(default_factory=list)
    source_types: List[str] = field(default_factory=list)
    quality: str = "ok"  # ok | weak | inferred


@dataclass
class PeerGroupDef:
    """A peer group with explicit labeling."""
    group_label: str  # e.g. "direct_competitor", "cross_market_reference"
    symbols: List[str] = field(default_factory=list)
    description: str = ""


@dataclass
class SectionEvidenceContract:
    """Contract that defines what evidence a single report section can use."""
    section_key: str
    title: str
    status: str = "gap"  # supported | partial | fallback | gap
    facts: List[Fact] = field(default_factory=list)
    allowed_source_types: List[str] = field(default_factory=list)
    forbidden_source_types: List[str] = field(default_factory=list)
    citation_evidence_ids: List[str] = field(default_factory=list)
    blocked_reasons: List[str] = field(default_factory=list)
    quality_flags: List[str] = field(default_factory=list)
    render_policy: Dict[str, bool] = field(default_factory=lambda: {
        "allow_llm_rewrite": False,
        "allow_fallback": True,
    })
    deterministic_text: str = ""
    peer_groups: List[PeerGroupDef] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def add_fact(self, fact_type: str, text: str,
                 evidence_ids: Optional[List[str]] = None,
                 source_types: Optional[List[str]] = None,
                 quality: str = "ok") -> None:
        self.facts.append(Fact(
            fact_type=fact_type,
            text=text,
            evidence_ids=evidence_ids or [],
            source_types=source_types or [],
            quality=quality,
        ))
        # Track evidence IDs for citation binding
        for eid in (evidence_ids or []):
            if eid not in self.citation_evidence_ids:
                self.citation_evidence_ids.append(eid)

    def add_blocked_reason(self, reason: str) -> None:
        if reason not in self.blocked_reasons:
            self.blocked_reasons.append(reason)

    def add_quality_flag(self, flag: str) -> None:
        if flag not in self.quality_flags:
            self.quality_flags.append(flag)


# ── contract collection ─────────────────────────────────────────────────


@dataclass
class ReportSectionContracts:
    """Collection of all section contracts for one report."""
    contracts: Dict[str, SectionEvidenceContract] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=lambda: {
        "latest_available_period": "",
        "period_mismatch": False,
        "period_conflicts": [],
        "target_symbol": "",
        "target_period": "",
        "pdf_rag_available": False,
    })

    def ensure(self, section_key: str) -> SectionEvidenceContract:
        if section_key not in self.contracts:
            title = SECTION_TITLES.get(section_key, section_key)
            forbidden = FORBIDDEN_SECTION_SOURCE_TYPES.get(section_key, [])
            allowed = list(ALLOWED_QUALITATIVE_PDF_ONLY)
            self.contracts[section_key] = SectionEvidenceContract(
                section_key=section_key,
                title=title,
                allowed_source_types=allowed,
                forbidden_source_types=forbidden,
            )
        return self.contracts[section_key]

    def get(self, section_key: str) -> Optional[SectionEvidenceContract]:
        return self.contracts.get(section_key)

    def all_statuses(self) -> Dict[str, str]:
        return {k: v.status for k, v in self.contracts.items()}

    def all_blocked_reasons(self) -> Dict[str, List[str]]:
        return {k: v.blocked_reasons for k, v in self.contracts.items()}

    def top_blockers(self, max_items: int = 5) -> List[str]:
        """Flatten top blockers from all contracts for the delivery gate."""
        blockers: List[str] = []
        for contract in self.contracts.values():
            for reason in contract.blocked_reasons:
                label = f"{contract.section_key}:{reason}"
                if label not in blockers:
                    blockers.append(label)
        for flag in self.quality_flags():
            label = f"quality:{flag}"
            if label not in blockers:
                blockers.append(label)
        return blockers[:max_items]

    def quality_flags(self) -> List[str]:
        seen: List[str] = []
        for contract in self.contracts.values():
            for flag in contract.quality_flags:
                if flag not in seen:
                    seen.append(flag)
        return seen

    def to_dict(self) -> Dict[str, Any]:
        return {
            "metadata": dict(self.metadata),
            "contracts": {k: v.to_dict() for k, v in self.contracts.items()},
        }

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "ReportSectionContracts":
        raw_contracts = payload.get("contracts") if isinstance(payload.get("contracts"), dict) else {}
        contracts: Dict[str, SectionEvidenceContract] = {}
        for section_key, raw in raw_contracts.items():
            if not isinstance(raw, dict):
                continue
            facts = [Fact(**item) for item in raw.get("facts", []) if isinstance(item, dict)]
            peer_groups = [PeerGroupDef(**item) for item in raw.get("peer_groups", []) if isinstance(item, dict)]
            contracts[str(section_key)] = SectionEvidenceContract(
                section_key=str(raw.get("section_key") or section_key),
                title=str(raw.get("title") or SECTION_TITLES.get(str(section_key), section_key)),
                status=str(raw.get("status") or "gap"),
                facts=facts,
                allowed_source_types=list(raw.get("allowed_source_types") or []),
                forbidden_source_types=list(raw.get("forbidden_source_types") or []),
                citation_evidence_ids=list(raw.get("citation_evidence_ids") or []),
                blocked_reasons=list(raw.get("blocked_reasons") or []),
                quality_flags=list(raw.get("quality_flags") or []),
                render_policy=dict(raw.get("render_policy") or {}),
                deterministic_text=str(raw.get("deterministic_text") or ""),
                peer_groups=peer_groups,
            )
        return cls(
            contracts=contracts,
            metadata=dict(payload.get("metadata") or {}) if isinstance(payload.get("metadata"), dict) else {},
        )

    def to_json_file(self, path: str) -> None:
        import json
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)


# ── PDF boilerplate detection ───────────────────────────────────────────

PDF_BOILERPLATE_PATTERNS = [
    "年度报告",
    "四、",
    "五、",
    "√适用",
    "□不适用",
    "√适用□不适用",
    "报告期内主要经营情况",
    "公司信息",
    "联系人和联系方式",
    "主要财务指标",
    "法定代表人",
    "释义",
    "审计报告",
    "独立审计师",
    "independent auditor",
    "table of contents",
    "重要提示",
    "声明",
    "免责",
    "disclaimer",
]


def text_contains_pdf_boilerplate(text: str) -> List[str]:
    """Check if text contains PDF formatting residues. Returns matched patterns."""
    found: List[str] = []
    lowered = text.lower()
    for pattern in PDF_BOILERPLATE_PATTERNS:
        if pattern.lower() in lowered:
            found.append(pattern)
    return found


def clean_pdf_boilerplate(text: str) -> str:
    """Remove known PDF formatting residues from text."""
    import re
    for pattern in PDF_BOILERPLATE_PATTERNS:
        text = text.replace(pattern, "")
    # Remove chapter/section numbering patterns: "四、", "五、", "(一)", "(二)" etc.
    text = re.sub(r"[一二三四五六七八九十]+[、．.]", "", text)
    text = re.sub(r"（[一二三四五六七八九十]+）", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


# ── half-sentence / fragment detection ──────────────────────────────────

FRAGMENT_PATTERNS = [
    "将共同决定其",
    "在该领域的竞争地位将取决于",
    "品牌力/渠道覆盖",
    "行业竞争格局和公司战略执行综上",
    "需关注",
    "需要关注",
    "主要体现在",
    "的相关",
    "下文章节展开分析",
    "在上市公司领域",
    "所在领域的业务布局",
    "的关键在于",
    "持续深耕",
    "巩固核心竞争力",
    "长期发展空间",
]


def text_contains_fragments(text: str) -> List[str]:
    """Detect half-sentences / template fragments. Returns matched patterns."""
    found: List[str] = []
    for pattern in FRAGMENT_PATTERNS:
        if pattern in text:
            found.append(pattern)
    return found


def has_sentence_fragments(text: str) -> bool:
    return bool(text_contains_fragments(text))
