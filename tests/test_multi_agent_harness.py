import json
from pathlib import Path

from src.evaluation.multi_agent_harness import _contest_checklist, _failure_taxonomy, _retrieval_ablation, run_multi_agent_evaluation
from tests.test_multi_agent_workflow import FakeJsonModel


def _write_jsonl(path: Path, rows):
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")


def test_multi_agent_harness_writes_eval_outputs(tmp_path: Path):
    raw_root = tmp_path / "raw"
    period_dir = raw_root / "AAPL" / "2025Q4"
    period_dir.mkdir(parents=True)
    (period_dir / "company_profile.json").write_text(
        json.dumps({"company_name": "Apple Inc.", "description": "Consumer technology company."}),
        encoding="utf-8",
    )
    (period_dir / "financials.csv").write_text(
        "symbol,period,revenue_billion,revenue_growth_pct,gross_margin_pct,net_margin_pct,roe_pct,roa_pct,operating_cash_flow_billion,free_cash_flow_billion,source_url,publish_time,trust_level,notes\n"
        "AAPL,2025Q4,126.3,11.2,46.8,24.6,150.0,28.0,32.0,29.0,https://example.com/fin,2026-01-31,high,Revenue 126.3B gross margin 46.8%.\n",
        encoding="utf-8",
    )
    (period_dir / "market.csv").write_text(
        "symbol,period,close,volume,source_url,publish_time,trust_level\nAAPL,2025Q4,200,1000000,https://example.com/mkt,2026-01-31,medium\n",
        encoding="utf-8",
    )
    (period_dir / "filings.jsonl").write_text(
        json.dumps({"title": "AAPL filing", "content": "Revenue 126.3B.", "source_url": "https://example.com/filing"}) + "\n",
        encoding="utf-8",
    )
    (period_dir / "news.jsonl").write_text(
        json.dumps({"title": "AAPL news", "content": "Risk update.", "source_url": "https://example.com/news"}) + "\n",
        encoding="utf-8",
    )

    cases_path = tmp_path / "cases.jsonl"
    _write_jsonl(
        cases_path,
        [
            {
                "case_id": "ev1_aapl_001",
                "query": "分析AAPL 2025Q4财务表现",
                "task_type": "financial",
                "source_scope": ["financials", "filing"],
                "gold_claims": ["AAPL 2025Q4 营收为 126.300 billion。"],
                "gold_evidence_ids": ["AAPL:2025Q4:financials"],
                "gold_numeric_facts": [
                    {"metric": "revenue", "value": "126.3", "unit": "billion", "period": "2025Q4"},
                    {"metric": "gross_margin", "value": "46.8", "unit": "pct", "period": "2025Q4"},
                ],
                "allow_fallback": False,
                "symbol": "AAPL",
                "period": "2025Q4",
            }
        ],
    )
    config_path = tmp_path / "eval.yaml"
    config_path.write_text(
        f"""
evaluation:
  max_samples: 1
  raw_root: {raw_root.as_posix()}
  eval_case_path: {cases_path.as_posix()}
  multi_agent:
    output_root: {(tmp_path / "out").as_posix()}
    max_samples: 1
    variants:
      - id: dynamic_fast
        execution_mode: dynamic
        fast: true
        engines: [local_real_data]
        retrieval_ranking_mode: hybrid_rerank
""".strip(),
        encoding="utf-8",
    )

    summary = run_multi_agent_evaluation(config_path=str(config_path), model=FakeJsonModel())

    out = tmp_path / "out"
    rows = (out / "per_report_metrics.jsonl").read_text(encoding="utf-8").splitlines()
    assert summary["report_count"] == 1
    assert summary["sample_count"] == 1
    assert "retrieval_ablation" in summary
    assert "hybrid_rerank" in summary["retrieval_ablation"]["modes"]
    assert summary["contest_checklist_score_mean"] > 0
    assert "verification_pass_rate" in summary
    assert "unsupported_fallback_rate" in summary
    assert "skill_routed_task_rate" in summary
    assert "citation_support_rate" in summary
    assert "numeric_audit_pass_rate" in summary
    assert "failure_taxonomy_summary" in summary
    assert len(summary["regression_topics"]) >= 5
    assert len(rows) == 1
    assert (out / "evaluation_summary.json").exists()
    assert (out / "per_case_numeric_audit_v1.jsonl").exists()
    assert "Regression Topics" in (out / "summary.md").read_text(encoding="utf-8")
    row = json.loads(rows[0])
    assert row["variant_id"] == "dynamic_fast"
    assert row["memory_enabled"] is False
    assert row["durable_memory_enabled"] is False
    assert row["durable_memory_available"] is False
    assert "contest_checklist" in row
    assert "selected_skill_names" in row
    assert "unsupported_fallback_count" in row


def test_retrieval_ablation_summarizes_mode_deltas():
    summary = _retrieval_ablation(
        [
            {
                "ranking_mode": "bm25",
                "evidence_alignment": 0.5,
                "evidence_coverage": 0.8,
                "rule_verifier_passed": False,
                "retrieval_fallback_used": False,
                "retrieved_doc_count": 3,
            },
            {
                "ranking_mode": "hybrid_rerank",
                "evidence_alignment": 0.75,
                "evidence_coverage": 1.0,
                "rule_verifier_passed": True,
                "retrieval_fallback_used": False,
                "retrieved_doc_count": 5,
            },
        ]
    )

    assert summary["modes"]["bm25"]["report_count"] == 1
    assert summary["comparisons"]["bm25_vs_hybrid_rerank"]["evidence_alignment_delta"] == 0.25


def test_contest_checklist_and_failure_taxonomy_detect_gaps():
    checklist = _contest_checklist(
        markdown="# Report\n\n## 执行摘要\n\n## 财务分析\n",
        claims=[
            {
                "section_name": "financial_analysis",
                "claim_text": "AAPL revenue was 126.3B.",
                "evidence_ids": ["missing"],
                "numeric_values": {"revenue_billion": 126.3},
            }
        ],
        evidence_records=[],
        verification={"passed": False, "errors": ["Target symbol mismatch: expected AAPL, but evidence symbols are NADA."]},
        chart_consistency={"passed": False},
        local_meta={"failure_reason": "no_records_for_symbol_period"},
        required_headers=["## 执行摘要", "## 财务分析", "## 风险评估"],
    )
    taxonomy = _failure_taxonomy(
        contest=checklist,
        verification={"passed": False, "errors": ["Target symbol mismatch: expected AAPL, but evidence symbols are NADA."]},
        local_meta={"failure_reason": "no_records_for_symbol_period"},
        chart_consistency={"passed": False},
    )

    assert checklist["score"] < checklist["max_score"]
    assert "entity_mismatch" in taxonomy
    assert "section_missing" in taxonomy
    assert "retrieval:no_records_for_symbol_period" in taxonomy
