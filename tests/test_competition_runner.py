import json
import zipfile

from scripts.run_competition import (
    REQUIRED_DOCX,
    _build_baseline_deepseek_workflow,
    _ranking_mode_for_run,
    _search_engines_for_run,
    main,
)


def test_competition_runner_packages_existing_company_artifacts(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    outputs = tmp_path / "data" / "outputs" / "multi_agent"
    reports = tmp_path / "data" / "reports" / "multi_agent"
    outputs.mkdir(parents=True)
    reports.mkdir(parents=True)
    (outputs / "run_summary.json").write_text(
        json.dumps(
            {
                "model": "fake",
                "verification_passed": True,
                "multimodal_consistency_passed": True,
                "company_report_overall_score": 0.91,
                "evidence_count": 3,
                "claim_count": 5,
                "citation_count": 5,
            }
        ),
        encoding="utf-8",
    )
    (outputs / "verification_report.json").write_text(json.dumps({"passed": True}), encoding="utf-8")
    (outputs / "multimodal_consistency.json").write_text(json.dumps({"passed": True}), encoding="utf-8")
    (outputs / "evidence.json").write_text(
        json.dumps(
            [
                {
                    "evidence_id": "ev_profile",
                    "source_type": "company_profile",
                    "content": "Apple designs consumer electronics and services.",
                    "metadata": {"sector": "Technology", "industry": "Consumer Electronics"},
                },
                {"evidence_id": "ev_market", "source_type": "market_api", "content": "AAPL market snapshot."},
            ]
        ),
        encoding="utf-8",
    )
    (outputs / "claims.json").write_text(json.dumps([{"claim_id": "cl_1", "claim_text": "AAPL claim."}]), encoding="utf-8")
    (outputs / "analysis_artifacts.json").write_text(
        json.dumps({"peer_context": {"peer_count": 3}}),
        encoding="utf-8",
    )
    (reports / "report.md").write_text(
        "# 公司研究报告\n\n## 执行摘要\n\n- AAPL revenue was supported by evidence. [ev_1]\n" * 12,
        encoding="utf-8",
    )

    code = main(["--skip-company-run", "--output-dir", str(tmp_path / "competition"), "--symbol", "AAPL"])

    summary = json.loads((tmp_path / "competition" / "competition_run_summary.json").read_text(encoding="utf-8"))
    industry_md = (tmp_path / "competition" / "industry_report.md").read_text(encoding="utf-8")
    macro_md = (tmp_path / "competition" / "macro_report.md").read_text(encoding="utf-8")
    assert code == 0
    assert summary["competition_passed"] is True
    assert summary["industry_report_generated_by"] == "IndustryResearchAgent"
    assert summary["macro_report_generated_by"] == "MacroResearchAgent"
    assert summary["independent_source_record_count"] == 0
    assert summary["independent_source_meta"]["failure_reason"] == "remote_sources_disabled"
    assert "Consumer Electronics" in industry_md
    assert "MacroResearchAgent" in macro_md
    assert "dedicated Industry/Macro agents remain future work" not in summary["limitations"][0]
    assert (tmp_path / "competition" / "industry_report.json").exists()
    assert (tmp_path / "competition" / "macro_report.json").exists()
    with zipfile.ZipFile(tmp_path / "competition" / "results.zip", "r") as zf:
        assert sorted(zf.namelist()) == sorted(REQUIRED_DOCX)


def test_competition_fast_mode_defaults_to_lightweight_retrieval():
    assert _search_engines_for_run("", fast=True) == ["local_real_data"]
    assert _search_engines_for_run("", fast=True, realtime_data=True) == [
        "local_real_data",
        "sec_edgar",
        "cninfo_announcements",
        "exchange_announcements",
        "eastmoney_financials",
        "yahoo_finance",
        "eastmoney",
        "independent_macro",
        "local_evidence",
    ]
    assert _ranking_mode_for_run("", fast=True) == "bm25"
    assert _search_engines_for_run("local_real_data,local_evidence", fast=True) == ["local_real_data", "local_evidence"]
    assert _ranking_mode_for_run("hybrid_rerank", fast=True) == "hybrid_rerank"


def test_baseline_deepseek_workflow_preserves_audit_buckets(tmp_path):
    payload = _build_baseline_deepseek_workflow(
        symbol="AMD",
        period="2025Q4",
        strict_markdown="# AMD\n\n## 执行摘要\n\n- AMD revenue claim. [ev_1]",
        evidence_records=[{"evidence_id": "ev_1", "content": "AMD revenue evidence."}],
        claims=[
            {"claim_id": "c1", "claim_text": "AMD revenue claim.", "evidence_ids": ["ev_1"]},
            {"claim_id": "c2", "claim_text": "AMD market share claim.", "evidence_ids": []},
            {"claim_id": "c3", "claim_text": "AMD unsupported claim.", "evidence_ids": ["missing"]},
        ],
        verification={"passed": False},
        model_config_path=str(tmp_path / "missing_model_config.yaml"),
    )

    markdown = payload["markdown"]
    audit = payload["report_json"]["audit"]
    rewrite = payload["report_json"]["evidence_grounded_rewrite"]
    assert "## 证据审计分层" in markdown
    assert audit["verified"][0]["claim_id"] == "c1"
    assert audit["pending_verification"][0]["claim_id"] == "c2"
    assert audit["unsupported"][0]["claim_id"] == "c3"
    assert rewrite["verified_rewrite_count"] == 1
    assert rewrite["rows"][0]["rewrite_result"].endswith("[ev_1]")
    assert rewrite["rows"][1]["verifier_status"] == "pending"
    assert payload["meta"]["model_used"] is False
