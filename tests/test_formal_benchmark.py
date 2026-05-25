import json

import pytest

from src.agents.deep_analyze_agent import apply_formal_v1_claim_contract
from src.evaluation.formal_benchmark import _compact_prompt_evidence, _snapshot_search_manager, annotate_critical_claims, formal_traceable_claim_metrics, run_formal_benchmark
from src.evaluation.frozen_snapshot import build_frozen_snapshot
from src.schemas.claim import ClaimItem


def test_traceable_claim_rate_v1_requires_snapshot_citation_and_numeric_audit():
    result = formal_traceable_claim_metrics(
        claims=[
            {
                "claim_id": "cl_rev",
                "is_critical": True,
                "critical_claim_type": "revenue",
                "evidence_ids": ["ev_annual"],
                "numeric_values": {"revenue": 100.0},
            }
        ],
        citations=[{"evidence_id": "ev_annual", "claim_ids": ["cl_rev"], "used_in_report": True}],
        frozen_evidence_ids={"ev_annual"},
        numeric_audit={"claims": [{"claim_id": "cl_rev", "supported": False}]},
    )

    assert result["rate"] == 0.0
    assert result["issues"][0]["reason"] == "numeric_audit_failed"


def test_formal_claim_contract_does_not_infer_missing_critical_label():
    claims = annotate_critical_claims(
        [
            {
                "claim_id": "cl_rev",
                "section_name": "financial_analysis",
                "claim_text": "FY2024 revenue was 100.0.",
                "evidence_ids": ["ev_annual"],
                "numeric_values": {"revenue": 100.0},
            }
        ]
    )

    assert claims[0].get("is_critical") is not True
    assert claims[0].get("critical_claim_type", "") == ""


def test_formal_one_shot_claim_normalization_accepts_section_alias():
    claims = annotate_critical_claims(
        [
            {
                "claim_id": "cl_rev",
                "section": "financial_analysis",
                "text": "FY2024 revenue was 100.0.",
                "evidence_ids": ["ev_annual"],
                "is_critical": True,
                "critical_claim_type": "revenue",
            }
        ]
    )

    assert claims[0]["section_name"] == "financial_analysis"
    assert claims[0]["claim_text"] == "FY2024 revenue was 100.0."
    assert claims[0]["critical_claim_type"] == "revenue"


def test_formal_one_shot_prompt_evidence_excludes_raw_provider_payloads():
    compact = _compact_prompt_evidence(
        [
            {
                "evidence_id": "ev_1",
                "source_type": "eastmoney_financials",
                "content": "financial summary",
                "metadata": {"raw": {"unused": "very large provider payload"}},
            }
        ]
    )

    assert compact[0]["content"] == "financial summary"
    assert "metadata" not in compact[0]


def test_formal_snapshot_search_preserves_structured_metadata():
    manager = _snapshot_search_manager(
        [
            {
                "evidence_id": "ev_structured",
                "sample_id": "ev_structured",
                "source_type": "eastmoney_financials",
                "title": "FY2024 income table",
                "content": "revenue profit",
                "symbol": "300750.SZ",
                "period": "FY2024",
                "source_url": "https://example.com",
                "publish_time": "2025-03-01",
                "trust_level": "high",
                "metadata": {"table_type": "income", "raw": {"TOTAL_OPERATE_INCOME": 100.0}},
            }
        ]
    )

    result = manager.search(query="revenue", topk=1, engines=["formal_snapshot_bm25"])

    assert result["hits"][0]["raw"]["metadata"]["table_type"] == "income"
    assert result["hits"][0]["raw"]["metadata"]["raw"]["TOTAL_OPERATE_INCOME"] == 100.0


def test_formal_analyzer_contract_emits_explicit_structured_label():
    claims = apply_formal_v1_claim_contract(
        [
            ClaimItem(
                claim_id="cl_rev",
                section_name="financial_analysis",
                claim_text="FY2024 revenue was 100.0.",
                evidence_ids=["ev_annual"],
                numeric_values={"revenue": 100.0},
            )
        ]
    )

    assert claims[0].is_critical is True
    assert claims[0].critical_claim_type == "revenue"


def test_formal_benchmark_refuses_incomplete_snapshot(tmp_path):
    config = _write_formal_config(tmp_path, two_cases=True)
    _write_source(tmp_path, "case_a", "AAPL")
    build_frozen_snapshot(config, source_root=tmp_path / "sources", snapshot_root=tmp_path / "snapshot")

    with pytest.raises(ValueError, match="snapshot is incomplete"):
        run_formal_benchmark(config, snapshot_root=tmp_path / "snapshot", output_root=tmp_path / "out", model=FakeFormalModel())


def test_formal_benchmark_runs_three_variants_on_same_frozen_case(tmp_path):
    config = _write_formal_config(tmp_path, two_cases=False)
    _write_source(tmp_path, "case_a", "AAPL")
    build_frozen_snapshot(config, source_root=tmp_path / "sources", snapshot_root=tmp_path / "snapshot")

    summary = run_formal_benchmark(
        config,
        snapshot_root=tmp_path / "snapshot",
        output_root=tmp_path / "out",
        model=FakeFormalModel(),
        multi_agent_factory=FakeFormalOrchestrator,
    )

    assert summary["case_count"] == 1
    assert summary["report_count"] == 3
    assert set(summary["variants"]) == {"direct_llm", "single_agent_rag", "multi_agent_rag"}
    for variant in summary["variants"].values():
        assert variant["overall"]["traceable_claim_rate_v1"] == 1.0
    assert len({row["snapshot_case_sha256"] for row in summary["records"]}) == 1
    assert (tmp_path / "out" / "formal_results_overall.csv").exists()
    assert (tmp_path / "out" / "formal_secondary_metrics.csv").exists()
    report = (tmp_path / "out" / "formal_benchmark_report.md").read_text(encoding="utf-8")
    assert "frozen evidence snapshot" in report
    assert "Secondary Diagnostics" in report
    assert "Failure Taxonomy" in report
    assert "Failure Retrospective" in report
    assert "100.00%" in report
    assert summary["variants"]["direct_llm"]["secondary"]["evaluated_run_count"] == 1
    assert summary["variants"]["direct_llm"]["secondary"]["micro_traceable_claim_rate_v1"] == 1.0
    assert FakeFormalOrchestrator.last_run["search_engines"] == ["formal_snapshot_bm25"]
    assert FakeFormalOrchestrator.last_run["enable_remote_data"] is False
    assert FakeFormalOrchestrator.last_run["execution_mode"] == "diagnostic_full"
    assert FakeFormalOrchestrator.last_run["claim_contract"] == "formal_v1"
    assert FakeFormalOrchestrator.last_run["allow_document_enrichment"] is False
    resumed = run_formal_benchmark(
        config,
        snapshot_root=tmp_path / "snapshot",
        output_root=tmp_path / "out",
        model=FakeFormalModel(),
        multi_agent_factory=FakeFormalOrchestrator,
        variant_ids=["direct_llm"],
        case_ids=["case_a"],
        reuse_existing=True,
    )
    assert resumed["report_count"] == 3
    assert (tmp_path / "out" / "formal_runs_checkpoint.jsonl").exists()


class FakeFormalOrchestrator:
    last_run = {}

    def __init__(self, output_dir, report_dir, search_manager, **_kwargs):
        self.outputs = output_dir
        self.reports = report_dir
        self.search_manager = search_manager

    def run(self, symbol, period, **kwargs):
        from pathlib import Path

        FakeFormalOrchestrator.last_run = dict(kwargs)
        result = self.search_manager.search(
            query=f"{symbol} {period} revenue",
            topk=10,
            engines=kwargs["search_engines"],
            symbol=symbol,
            period=period,
        )
        evidence = [hit["raw"] for hit in result["hits"]]
        outputs = Path(self.outputs)
        reports = Path(self.reports)
        outputs.mkdir(parents=True, exist_ok=True)
        reports.mkdir(parents=True, exist_ok=True)
        artifacts = {
            "claims.json": [_revenue_claim()],
            "evidence.json": evidence,
            "financial_metrics.json": {},
            "tables.json": [],
            "valuation_model.json": {},
            "valuation_sensitivity.json": {},
            "charts.json": [],
            "chart_consistency.json": {"passed": True},
        }
        for name, payload in artifacts.items():
            outputs.joinpath(name).write_text(json.dumps(payload), encoding="utf-8")
        reports.joinpath("report.md").write_text(_markdown(), encoding="utf-8")
        return {"report_md": str(reports / "report.md")}


class FakeFormalModel:
    model_name = "fake-formal"

    def generate_json(self, prompt, system_prompt=None, **_kwargs):
        if system_prompt and "formal benchmark" in system_prompt:
            return {"claims": [_revenue_claim()], "markdown": _markdown()}
        if system_prompt and "DeepAnalyzeAgent" in system_prompt:
            return {"claims": [_revenue_claim()]}
        if system_prompt and "FinalAnswerAgent" in system_prompt:
            return {"markdown": _markdown(), "summary": "formal", "citation_count": 1}
        return {"passed": True, "errors": [], "warnings": []}


def _write_formal_config(tmp_path, two_cases):
    cases = """
    - {case_id: case_a, market: US, company_name: Apple, canonical_symbol: AAPL}
"""
    if two_cases:
        cases += "    - {case_id: case_b, market: US, company_name: Microsoft, canonical_symbol: MSFT}\n"
    path = tmp_path / "formal.yaml"
    path.write_text(
        f"""
benchmark:
  id: test_formal
  period: FY2024
  dataset_version: test_v1
  snapshot_root: {str(tmp_path / 'snapshot').replace(chr(92), '/')}
  output_root: {str(tmp_path / 'out').replace(chr(92), '/')}
  model_config_path: configs/model_backends.yaml
  variants:
    - {{id: direct_llm}}
    - {{id: single_agent_rag}}
    - {{id: multi_agent_rag}}
  cases:
{cases.rstrip()}
""".strip(),
        encoding="utf-8",
    )
    return path


def _write_source(tmp_path, case_id, symbol):
    root = tmp_path / "sources" / case_id
    root.mkdir(parents=True)
    root.joinpath("evidence.jsonl").write_text(json.dumps(_evidence(symbol)) + "\n", encoding="utf-8")


def _evidence(symbol):
    return {
        "evidence_id": "ev_annual",
        "source_type": "financials",
        "title": f"{symbol} FY2024 revenue annual filing",
        "source_url": "https://example.com/annual",
        "publish_time": "2025-03-01",
        "content": f"{symbol} FY2024 revenue was 100.0. Profit and cash flow were disclosed.",
        "symbol": symbol,
        "period": "FY2024",
        "trust_level": "high",
    }


def _revenue_claim():
    return {
        "claim_id": "cl_rev",
        "section_name": "financial_analysis",
        "claim_text": "FY2024 revenue was 100.0.",
        "evidence_ids": ["ev_annual"],
        "numeric_values": {"revenue": 100.0},
        "risk_level": "low",
        "confidence": 0.9,
        "notes": "frozen evidence",
        "is_critical": True,
        "critical_claim_type": "revenue",
    }


def _markdown():
    return """# Company Report

## 执行摘要
FY2024 revenue was 100.0. [ev_annual]

## 三表摘要
利润表收入为 100.0；资产负债表和现金流量表存在数据缺口说明。 [ev_annual]

## 财务分析
FY2024 revenue was 100.0. [ev_annual]

## 估值观察
估值不可用原因：冻结证据未包含足够估值输入。 [ev_annual]

## 风险评估
风险在于数据覆盖有限。 [ev_annual]

## 投资结论
基于已冻结证据，维持审慎观察。 [ev_annual]
"""
