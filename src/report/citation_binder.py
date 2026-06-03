"""Citation Binder: post-hoc citation binding from section contracts.

The LLM no longer writes citation numbers like [1][2][3] or [ev_123].
Instead, each SectionEvidenceContract records evidence_ids, and the CitationBinder:

1. Maps evidence_ids to stable citation numbers
2. Enforces source-type policies per section
3. Replaces any LLM-written citations with bound ones
4. Produces citation_map.json and citation_binding_audit.json

Key rules:
- qualitative sections (business_overview, governance, strategy, risk):
  may NOT bind income/balance/cashflow/third_party_structured financial tables
- financial sections may bind financial tables
- risk fallbacks may NOT bind cashflow table
- same evidence_id = same citation number across all sections
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, Set

from src.report.section_contracts import (
    ReportSectionContracts,
    SectionEvidenceContract,
    SRC_INCOME_TABLE,
    SRC_BALANCE_TABLE,
    SRC_CASHFLOW_TABLE,
    SRC_THIRD_PARTY_STRUCTURED,
    SRC_FINANCIAL_METRIC,
    FORBIDDEN_SECTION_SOURCE_TYPES,
)


# ── config: which sections are "qualitative" (no financial table citations) ──

QUALITATIVE_SECTIONS = {
    "business_overview",
    "ownership_governance",
    "strategy_business",
    "risk_factors",
    "investment_conclusion",
}

FINANCIAL_SOURCE_TYPES = {
    SRC_INCOME_TABLE,
    SRC_BALANCE_TABLE,
    SRC_CASHFLOW_TABLE,
    SRC_THIRD_PARTY_STRUCTURED,
    SRC_FINANCIAL_METRIC,
}


@dataclass
class BindResult:
    """Result of binding citations for one section."""
    section_key: str
    status: str  # ok | mismatch | blocked
    bound_citation_ids: List[str] = field(default_factory=list)
    blocked_reasons: List[str] = field(default_factory=list)


class CitationBinder:
    """Post-hoc citation binder that enforces section-level source policies."""

    def __init__(self, evidence_records: Optional[List[Dict[str, Any]]] = None):
        self.evidence_records = evidence_records or []
        self.evidence_by_id: Dict[str, Dict[str, Any]] = {}
        self._index_evidence()

        # Global citation number assignment
        self._id_to_number: Dict[str, int] = {}
        self._number_to_id: Dict[int, str] = {}
        self._next_number = 1

        # Per-section binding audit
        self.bind_results: List[BindResult] = []
        self.mismatches: List[str] = []

    def _index_evidence(self) -> None:
        for rec in self.evidence_records:
            if not isinstance(rec, dict):
                continue
            eid = str(rec.get("evidence_id") or rec.get("sample_id") or "").strip()
            if eid and eid not in self.evidence_by_id:
                self.evidence_by_id[eid] = rec

    def assign_citation_number(self, evidence_id: str) -> int:
        """Assign or retrieve a stable citation number for this evidence_id."""
        if evidence_id not in self._id_to_number:
            self._id_to_number[evidence_id] = self._next_number
            self._number_to_id[self._next_number] = evidence_id
            self._next_number += 1
        return self._id_to_number[evidence_id]

    def get_citation_map(self) -> Dict[str, int]:
        """Return {evidence_id: citation_number} map."""
        return dict(self._id_to_number)

    def get_reverse_map(self) -> Dict[int, str]:
        """Return {citation_number: evidence_id} map."""
        return dict(self._number_to_id)

    def bind_contract(self, contract: SectionEvidenceContract) -> BindResult:
        """Bind citations for one section contract, enforcing source-type policy."""
        result = BindResult(section_key=contract.section_key, status="ok")
        forbidden = set(contract.forbidden_source_types)
        is_qualitative = contract.section_key in QUALITATIVE_SECTIONS

        evidence_records_index = getattr(self, 'evidence_records', [])
        evidence_by_id = getattr(self, 'evidence_by_id', {})

        for eid in contract.citation_evidence_ids:
            if not eid:
                continue

            # Check source type of this evidence record
            record = evidence_by_id.get(eid, {})
            source_type = str(record.get("source_type", "") or "")

            # Enforce forbidden source types
            if source_type in forbidden:
                result.status = "mismatch"
                msg = f"{contract.section_key}: evidence {eid} has source_type={source_type} (forbidden)"
                result.blocked_reasons.append(msg)
                self.mismatches.append(msg)
                continue

            # Qualitative sections: prevent financial table binding
            if is_qualitative and source_type in FINANCIAL_SOURCE_TYPES:
                result.status = "mismatch"
                msg = (f"{contract.section_key}: qualitative section cannot bind financial "
                       f"evidence {eid} (source_type={source_type})")
                result.blocked_reasons.append(msg)
                self.mismatches.append(msg)
                continue

            # Risk fallback: prevent cashflow table binding
            if contract.section_key == "risk_factors" and source_type == SRC_CASHFLOW_TABLE:
                result.status = "mismatch"
                msg = f"risk_factors: fallback cannot bind cashflow evidence {eid}"
                result.blocked_reasons.append(msg)
                self.mismatches.append(msg)
                continue

            # Assign citation number
            num = self.assign_citation_number(eid)
            result.bound_citation_ids.append(f"[{num}]")

        return result

    def bind_all(self, contracts: ReportSectionContracts) -> List[BindResult]:
        """Bind citations for all contracts.

        Returns list of BindResult. Updates contract status + blocked_reasons.
        """
        self.bind_results = []
        for sk in contracts.contracts:
            contract = contracts.contracts[sk]
            result = self.bind_contract(contract)
            self.bind_results.append(result)

            if result.status == "mismatch":
                for reason in result.blocked_reasons:
                    contract.add_blocked_reason(reason)

        return self.bind_results

    def strip_llm_citations(self, markdown: str) -> str:
        """Remove LLM-written [1][2][3] or [ev_123] style citations from markdown.

        Keeps only numbers that match bound citations, removes all others.
        """
        # Remove [ev_XXX] or [src_XXX] patterns (any letter_underscore_id)
        markdown = re.sub(r'\[[a-zA-Z]+_\w+\]', '', markdown)

        # Remove standalone [N] citations (will be re-inserted by renderer)
        # But preserve numbers that match our bound citations
        known_numbers = set(self._number_to_id.keys())

        def _replace_citation(m: re.Match) -> str:
            num_str = m.group(1)
            if num_str and int(num_str) in known_numbers:
                return m.group(0)  # keep bound citations
            return ''  # remove unbound ones

        # Pattern matches [N] or [N, M] or [N-M] style
        markdown = re.sub(r'\[(\d+)\]', _replace_citation, markdown)
        # Clean up double spaces and artifacts
        markdown = re.sub(r' +', ' ', markdown)
        markdown = re.sub(r'\n{3,}', '\n\n', markdown)
        return markdown.strip()

    def inject_bound_citations(self, markdown: str, contracts: ReportSectionContracts) -> str:
        """Inject bound citation markers into markdown sections.

        For each section, adds bound citation markers at the end of the section body.
        This is a fallback — the primary approach is that contracts define evidence_ids
        and the renderer uses them directly.
        """
        output = markdown
        for sk, contract in contracts.contracts.items():
            if not contract.citation_evidence_ids:
                continue
            # Find the section in markdown by heading
            heading = contract.title
            pattern = re.compile(rf"(?m)^##\s+{re.escape(heading)}\s*$")
            match = pattern.search(output)
            if not match:
                continue
            # Find end of section
            next_header = re.search(r"(?m)^##\s+", output[match.end():])
            end = match.end() + next_header.start() if next_header else len(output)
            body = output[match.end():end].strip()

            # Get bound citation numbers
            bound_nums = []
            for eid in contract.citation_evidence_ids:
                if eid in self._id_to_number:
                    bound_nums.append(str(self._id_to_number[eid]))

            if bound_nums:
                citation_marker = f" [{', '.join(bound_nums)}]"
                # Only append if not already present
                if citation_marker not in body:
                    output = output[:end] + citation_marker + "\n\n" + output[end:]
        return output

    def to_citation_map(self) -> Dict[str, Any]:
        """Build the citation_map.json structure."""
        entries = []
        for evidence_id, number in self._id_to_number.items():
            record = self.evidence_by_id.get(evidence_id, {})
            entries.append({
                "citation_number": number,
                "evidence_id": evidence_id,
                "title": str(record.get("title", "") or ""),
                "source_url": str(record.get("source_url", "") or ""),
                "source_type": str(record.get("source_type", "") or ""),
                "trust_level": str(record.get("trust_level", "") or ""),
            })
        return {"citation_map": entries}

    def to_audit(self) -> Dict[str, Any]:
        """Build the citation_binding_audit.json structure."""
        return {
            "total_evidence_ids_seen": len(self._id_to_number),
            "total_mismatches": len(self.mismatches),
            "mismatches": self.mismatches[:20],
            "section_bindings": [
                asdict(r) for r in self.bind_results
            ],
            "citation_map": self._id_to_number,
        }

    def write_artifacts(self, output_dir: str) -> Dict[str, str]:
        """Write citation_map.json and citation_binding_audit.json."""
        import os
        os.makedirs(output_dir, exist_ok=True)

        map_path = os.path.join(output_dir, "citation_map.json")
        with open(map_path, "w", encoding="utf-8") as f:
            json.dump(self.to_citation_map(), f, ensure_ascii=False, indent=2)

        audit_path = os.path.join(output_dir, "citation_binding_audit.json")
        with open(audit_path, "w", encoding="utf-8") as f:
            json.dump(self.to_audit(), f, ensure_ascii=False, indent=2)

        return {"citation_map": map_path, "citation_binding_audit": audit_path}
