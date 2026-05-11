"""Stage 4 analyst that builds claim table from programmatic features."""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List

import pandas as pd

from src.schemas.claim import ClaimItem


class Analyst:
    """Rule-based analyst for claim generation."""

    def __init__(self, features_root: str = "data/features"):
        self.features_root = Path(features_root)

    def _read_parquet(self, name: str) -> pd.DataFrame:
        path = self.features_root / name
        if not path.exists():
            return pd.DataFrame()
        return pd.read_parquet(path)

    @staticmethod
    def _parse_evidence_ids(raw: object) -> List[str]:
        text = str(raw or "").strip()
        if not text:
            return []
        return [item for item in text.split("|") if item]

    def build_claims(self) -> List[ClaimItem]:
        ratio_df = self._read_parquet("financial_ratios.parquet")
        trend_df = self._read_parquet("trend_analysis.parquet")
        peer_df = self._read_parquet("peer_compare.parquet")
        risk_df = self._read_parquet("risk_signals.parquet")

        claims: List[ClaimItem] = []
        claim_index = 1

        for _, row in ratio_df.iterrows():
            symbol = str(row.get("symbol", "")).strip()
            if not symbol:
                continue
            revenue = row.get("revenue_billion")
            revenue_growth = row.get("revenue_growth_pct")
            margin = row.get("gross_margin_pct")
            net_margin = row.get("net_margin_pct")
            roe = row.get("roe_pct")
            roa = row.get("roa_pct")
            operating_cash_flow = row.get("operating_cash_flow_billion")
            evidence_id = str(row.get("sample_id", ""))

            if pd.notna(revenue):
                claims.append(
                    ClaimItem(
                        claim_id=f"cl_{claim_index:04d}",
                        section_name="financial_analysis",
                        claim_text=f"{symbol} reported revenue around {float(revenue):.1f}B in the available sample.",
                        evidence_ids=[evidence_id] if evidence_id else [],
                        numeric_values={"revenue_billion": float(revenue)},
                        risk_level="medium",
                        confidence=0.8,
                        notes="Derived from financial_ratios.parquet",
                    )
                )
                claim_index += 1

            if pd.notna(margin):
                claims.append(
                    ClaimItem(
                        claim_id=f"cl_{claim_index:04d}",
                        section_name="financial_analysis",
                        claim_text=f"{symbol} gross margin is estimated near {float(margin):.1f}%.",
                        evidence_ids=[evidence_id] if evidence_id else [],
                        numeric_values={"gross_margin_pct": float(margin)},
                        risk_level="low",
                        confidence=0.78,
                        notes="Parsed from textual financial summary.",
                    )
                )
                claim_index += 1

            if pd.notna(revenue_growth):
                claims.append(
                    ClaimItem(
                        claim_id=f"cl_{claim_index:04d}",
                        section_name="financial_analysis",
                        claim_text=f"{symbol} revenue growth is estimated near {float(revenue_growth):.1f}% in the sample period.",
                        evidence_ids=[evidence_id] if evidence_id else [],
                        numeric_values={"revenue_growth_pct": float(revenue_growth)},
                        risk_level="medium",
                        confidence=0.76,
                        notes="Derived from financial_ratios.parquet",
                    )
                )
                claim_index += 1

            if pd.notna(net_margin):
                claims.append(
                    ClaimItem(
                        claim_id=f"cl_{claim_index:04d}",
                        section_name="financial_analysis",
                        claim_text=f"{symbol} net margin is approximately {float(net_margin):.1f}%.",
                        evidence_ids=[evidence_id] if evidence_id else [],
                        numeric_values={"net_margin_pct": float(net_margin)},
                        risk_level="low",
                        confidence=0.74,
                        notes="Derived from financial_ratios.parquet",
                    )
                )
                claim_index += 1

            if pd.notna(roe):
                claims.append(
                    ClaimItem(
                        claim_id=f"cl_{claim_index:04d}",
                        section_name="financial_analysis",
                        claim_text=f"{symbol} return on equity (ROE) is around {float(roe):.1f}%.",
                        evidence_ids=[evidence_id] if evidence_id else [],
                        numeric_values={"roe_pct": float(roe)},
                        risk_level="low",
                        confidence=0.73,
                        notes="Derived from financial_ratios.parquet",
                    )
                )
                claim_index += 1

            if pd.notna(roa):
                claims.append(
                    ClaimItem(
                        claim_id=f"cl_{claim_index:04d}",
                        section_name="financial_analysis",
                        claim_text=f"{symbol} return on assets (ROA) is around {float(roa):.1f}%.",
                        evidence_ids=[evidence_id] if evidence_id else [],
                        numeric_values={"roa_pct": float(roa)},
                        risk_level="low",
                        confidence=0.72,
                        notes="Derived from financial_ratios.parquet",
                    )
                )
                claim_index += 1

            if pd.notna(operating_cash_flow):
                claims.append(
                    ClaimItem(
                        claim_id=f"cl_{claim_index:04d}",
                        section_name="financial_analysis",
                        claim_text=f"{symbol} operating cash flow is estimated near {float(operating_cash_flow):.1f}B.",
                        evidence_ids=[evidence_id] if evidence_id else [],
                        numeric_values={"operating_cash_flow_billion": float(operating_cash_flow)},
                        risk_level="medium",
                        confidence=0.75,
                        notes="Derived from financial_ratios.parquet",
                    )
                )
                claim_index += 1

        for _, row in trend_df.iterrows():
            symbol = str(row.get("symbol", "")).strip()
            evidence_count = int(row.get("evidence_count", 0))
            source_count = int(row.get("unique_sources", 0))
            evidence_ids = self._parse_evidence_ids(row.get("sample_ids", ""))
            claims.append(
                ClaimItem(
                    claim_id=f"cl_{claim_index:04d}",
                    section_name="business_overview",
                    claim_text=f"{symbol} currently has {evidence_count} evidence rows from {source_count} source types.",
                    evidence_ids=evidence_ids,
                    numeric_values={
                        "evidence_count": float(evidence_count),
                        "unique_sources": float(source_count),
                    },
                    risk_level="low",
                    confidence=0.75,
                    notes="Coverage-level claim from trend_analysis.parquet",
                )
            )
            claim_index += 1

        peer_rank_map: Dict[str, int] = {}
        for _, row in peer_df.iterrows():
            symbol = str(row.get("symbol", "")).strip()
            rank = int(row.get("peer_rank", 0))
            evidence_ids = self._parse_evidence_ids(row.get("sample_ids", ""))
            peer_rank_map[symbol] = rank
            claims.append(
                ClaimItem(
                    claim_id=f"cl_{claim_index:04d}",
                    section_name="valuation",
                    claim_text=f"{symbol} ranks #{rank} by average trust-weighted evidence quality in current peer set.",
                    evidence_ids=evidence_ids,
                    numeric_values={
                        "peer_rank": float(rank),
                        "avg_trust_weight": float(row.get("avg_trust_weight", 0.0)),
                    },
                    risk_level="medium",
                    confidence=0.72,
                    notes="Relative ranking signal from peer_compare.parquet",
                )
            )
            claim_index += 1

        for _, row in risk_df.iterrows():
            symbol = str(row.get("symbol", "")).strip()
            risk_level = str(row.get("risk_level", "medium")).strip() or "medium"
            risk_ratio = float(row.get("risk_ratio", 0.0))
            evidence_ids = self._parse_evidence_ids(row.get("sample_ids", ""))
            claims.append(
                ClaimItem(
                    claim_id=f"cl_{claim_index:04d}",
                    section_name="risks",
                    claim_text=f"{symbol} has a {risk_level} risk signal level with ratio {risk_ratio:.2f}.",
                    evidence_ids=evidence_ids,
                    numeric_values={"risk_ratio": risk_ratio},
                    risk_level=risk_level,
                    confidence=0.7,
                    notes="Risk keyword ratio from risk_signals.parquet",
                )
            )
            claim_index += 1

        return claims
