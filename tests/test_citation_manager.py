from src.report import build_citation_artifacts, build_citations


def test_build_citations_links_claims_and_report_usage():
    evidence_records = [
        {
            "evidence_id": "ev_fin",
            "title": "Financials",
            "content": "Revenue was 126.3B and gross margin improved.",
            "source_url": "https://example.com/fin",
            "source_type": "financials",
            "source_authority": "official",
            "authority_score": 1.0,
            "publish_time": "2026-01-31",
            "trust_level": "high",
        }
    ]
    claims = [
        {
            "claim_id": "cl_0001",
            "claim_text": "Revenue was 126.3B. [ev_fin]",
            "evidence_ids": ["ev_fin"],
        }
    ]

    citations = build_citations(evidence_records=evidence_records, claims=claims, markdown="Revenue [ev_fin]")

    assert citations == [
        {
            "citation_id": "ref_001",
            "evidence_id": "ev_fin",
            "title": "Financials",
            "source_url": "https://example.com/fin",
            "source_type": "financials",
            "source_authority": "official",
            "authority_score": 1.0,
            "publish_time": "2026-01-31",
            "trust_level": "high",
            "claim_ids": ["cl_0001"],
            "used_in_report": True,
            "content_preview": "Revenue was 126.3B and gross margin improved.",
        }
    ]


def test_build_citation_artifacts_appends_references_once():
    artifacts = build_citation_artifacts(
        evidence_records=[{"evidence_id": "ev_fin", "title": "Financials"}],
        claims=[{"claim_id": "cl_0001", "evidence_ids": ["ev_fin"]}],
        markdown="# Report\n\nBody [ev_fin]\n\n## References\n\n- stale",
        html="<html><body><h1>Report</h1></body></html>",
    )

    assert artifacts["markdown"].count("## 参考来源") == 1
    assert "[ev_fin] Financials" in artifacts["markdown"]
    assert "<h2>参考来源</h2>" in artifacts["html"]
    assert artifacts["citations"][0]["claim_ids"] == ["cl_0001"]
