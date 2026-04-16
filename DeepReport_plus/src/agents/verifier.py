"""Rule-based verifier for Stage 4 outputs."""

from __future__ import annotations

from typing import Dict, List

from src.schemas.claim import ClaimItem


class Verifier:
    """Validate claim table and rendered markdown report."""

    def verify(self, claims: List[ClaimItem], markdown: str) -> Dict[str, object]:
        errors: List[str] = []
        warnings: List[str] = []

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

        required_headers = [
            "## Executive Summary",
            "## Financial Analysis",
            "## Risk Assessment",
        ]
        for header in required_headers:
            if header not in markdown:
                errors.append(f"Missing required header in report: {header}")

        return {
            "passed": len(errors) == 0,
            "error_count": len(errors),
            "warning_count": len(warnings),
            "errors": errors,
            "warnings": warnings,
            "claim_count": len(claims),
        }

