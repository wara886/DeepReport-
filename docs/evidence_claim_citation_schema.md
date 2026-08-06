# Evidence, Claim And Citation Contract

FinSight separates retrieved material from conclusions and rendered citations. This makes unsupported conclusions detectable before delivery.

## Minimal Objects

An evidence record captures source identity and period:

```json
{
  "evidence_id": "AAPL_FY2024_10K_p42_001",
  "source_type": "filing",
  "title": "Apple FY2024 Form 10-K",
  "source_url": "https://example.com/apple-10k",
  "publish_time": "2024-11-01",
  "content": "Net sales were disclosed for FY2024.",
  "symbol": "AAPL",
  "period": "FY2024",
  "trust_level": "high"
}
```

A claim explicitly binds its material statement to evidence and numeric lineage:

```json
{
  "claim_id": "AAPL_2024_claim_001",
  "section_name": "financial_analysis",
  "claim_text": "Revenue increased year-over-year in FY2024.",
  "is_critical": true,
  "critical_claim_type": "revenue",
  "evidence_ids": ["AAPL_FY2024_10K_p42_001"],
  "numeric_values": {
    "revenue": 100.0
  },
  "numeric_lineage": {
    "metric": "revenue",
    "period": "FY2024",
    "source": "10-K"
  }
}
```

A rendered citation states that the report actually used the linked evidence:

```json
{
  "evidence_id": "AAPL_FY2024_10K_p42_001",
  "claim_ids": ["AAPL_2024_claim_001"],
  "used_in_report": true
}
```

## Verification Rules

- A factual claim without `evidence_ids` is not deliverable as supported fact.
- A critical numeric claim must cite approved evidence and pass the production numeric-consistency gate.
- A citation only counts as traceable when it is present in the rendered report.
- Valuation and charts carry their own source lineage and are checked alongside narrative claims.
