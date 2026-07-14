import json

from src.evaluation.delivery_gate import build_delivery_gate
from src.evaluation.evidence_retrieval_attribution import build_evidence_retrieval_attribution, write_evidence_retrieval_attribution
from src.evaluation.report_quality import load_quality_artifacts, resolve_run_paths


def test_attribution_detects_missing_retrieval_and_source_data(tmp_path):
    outputs, reports = _dirs(tmp_path)

    artifact = build_evidence_retrieval_attribution(outputs, reports_dir=reports, run_dir=tmp_path / "run")

    assert artifact["retrieval_summary"]["retrieval_not_run"] is True
    assert artifact["section_results"]["financial_analysis"]["root_cause"] == "retrieval_not_run"
    assert any(row["cause"] == "retrieval_not_run" for row in artifact["overall_root_causes"])


def test_attribution_detects_retrieval_no_candidates_and_similarity_unavailable(tmp_path):
    outputs, reports = _dirs(tmp_path)
    _write(
        outputs,
        "search_meta.json",
        {
            "engine_meta": {
                "local_evidence": {
                    "mode": "hybrid_rerank",
                    "source_record_count": 0,
                    "candidate_count": 0,
                    "returned_hit_count": 0,
                    "chunking_enabled": True,
                    "coverage": {"missing_sources": ["hkex"]},
                }
            }
        },
    )

    artifact = build_evidence_retrieval_attribution(outputs, reports_dir=reports)
    causes = artifact["section_results"]["valuation"]["root_causes"]

    assert "retrieval_no_candidates" in causes
    assert "similarity_unavailable" in causes
    assert "source_data_missing" in causes


def test_attribution_marks_bm25_only_when_candidates_return_without_vector_scores(tmp_path):
    outputs, reports = _dirs(tmp_path)
    _write(
        outputs,
        "search_meta.json",
        {
            "engine_meta": {
                "local_evidence": {
                    "mode": "bm25",
                    "source_record_count": 3,
                    "candidate_count": 3,
                    "returned_hit_count": 2,
                    "chunking_enabled": True,
                    "vector_hit_count": 0,
                }
            }
        },
    )
    _write(outputs, "evidence.json", [{"evidence_id": "ev1", "source_type": "cninfo_announcement", "period": "FY2025", "symbol": "600519.SS"}])
    _write(outputs, "section_dossiers.json", {"valuation": {"supporting_evidence_ids": ["ev1"]}})

    artifact = build_evidence_retrieval_attribution(outputs, reports_dir=reports)

    assert artifact["retrieval_summary"]["similarity_status"] == "bm25_only"
    assert "similarity_bm25_only" in artifact["section_results"]["valuation"]["root_causes"]


def test_attribution_detects_low_vector_similarity_and_chunk_metadata_gap(tmp_path):
    outputs, reports = _dirs(tmp_path)
    _write(
        outputs,
        "search_meta.json",
        {
            "engine_meta": {
                "local_evidence": {
                    "mode": "hybrid_rerank",
                    "source_record_count": 3,
                    "candidate_count": 3,
                    "returned_hit_count": 2,
                    "chunking_enabled": True,
                    "vector_hit_count": 2,
                    "vector_score_max": 0.03,
                    "vector_score_mean": 0.02,
                }
            }
        },
    )
    _write(
        outputs,
        "evidence.json",
        [
            {"evidence_id": "ev1", "source_type": "annual_report_pdf_chunk", "content": "risk text"},
            {"evidence_id": "ev2", "source_type": "annual_report_pdf_chunk", "content": "financial text"},
        ],
    )
    _write(outputs, "section_dossiers.json", {"valuation": {"supporting_evidence_ids": ["ev1"]}})
    _write(outputs, "report_section_contracts.json", {"contracts": {"valuation": {"status": "supported", "citation_evidence_ids": ["ev1"]}}})

    artifact = build_evidence_retrieval_attribution(outputs, reports_dir=reports)
    causes = artifact["section_results"]["valuation"]["root_causes"]

    assert "similarity_low" in causes
    assert "chunk_metadata_missing" in causes
    assert artifact["retrieval_summary"]["vector_score_max"] == 0.03


def test_attribution_detects_writer_not_using_available_evidence(tmp_path):
    outputs, reports = _dirs(tmp_path)
    _write(
        outputs,
        "search_meta.json",
        {
            "engine_meta": {
                "local_evidence": {
                    "source_record_count": 2,
                    "candidate_count": 2,
                    "returned_hit_count": 2,
                    "vector_hit_count": 2,
                    "vector_score_max": 0.42,
                    "chunking_enabled": True,
                }
            }
        },
    )
    _write(outputs, "evidence.json", [{"evidence_id": "ev1", "source_type": "sec_edgar", "period": "FY2024", "symbol": "AAPL", "chunk_id": "c1", "metadata": {"section_type": "valuation"}}])
    _write(outputs, "section_dossiers.json", {"valuation": {"supporting_evidence_ids": ["ev1"]}})
    _write(outputs, "report_section_contracts.json", {"contracts": {"valuation": {"status": "supported", "citation_evidence_ids": ["ev1"]}}})
    _write(outputs, "section_verification.json", {"section_results": {"valuation": {"status": "passed"}}})
    _write(outputs, "llm_quality_review.json", {"issues": [{"severity": "fatal", "message": "估值缺少同行对比和敏感性实质内容"}]})

    artifact = build_evidence_retrieval_attribution(outputs, reports_dir=reports)

    assert artifact["section_results"]["valuation"]["root_cause"] == "writer_not_using_available_evidence"


def test_attribution_ignores_resolved_canonical_metric_differences(tmp_path):
    outputs, reports = _dirs(tmp_path)
    _write(
        outputs,
        "canonical_metrics.json",
        {
            "conflict_count": 1,
            "resolved_conflict_count": 1,
            "unresolved_conflict_count": 0,
            "conflicts": [{"metric_name": "revenue", "resolution_status": "resolved"}],
        },
    )

    artifact = build_evidence_retrieval_attribution(outputs, reports_dir=reports)

    assert artifact["canonical_metric_conflict_count"] == 0


def test_attribution_keeps_unresolved_canonical_metric_conflicts(tmp_path):
    outputs, reports = _dirs(tmp_path)
    _write(
        outputs,
        "canonical_metrics.json",
        {
            "conflict_count": 1,
            "resolved_conflict_count": 0,
            "unresolved_conflict_count": 1,
            "conflicts": [{"metric_name": "revenue", "resolution_status": "unresolved"}],
        },
    )

    artifact = build_evidence_retrieval_attribution(outputs, reports_dir=reports)

    assert artifact["canonical_metric_conflict_count"] == 1


def test_attribution_records_section_pack_similarity_and_report_usage(tmp_path):
    outputs, reports = _dirs(tmp_path)
    _write(
        outputs,
        "search_meta.json",
        {
            "engine_meta": {
                "local_evidence": {
                    "source_record_count": 2,
                    "candidate_count": 2,
                    "returned_hit_count": 2,
                    "vector_hit_count": 2,
                    "vector_score_max": 0.66,
                    "chunking_enabled": True,
                }
            }
        },
    )
    _write(
        outputs,
        "evidence.json",
        [
            {
                "evidence_id": "ev_used",
                "source_type": "sec_edgar",
                "period": "FY2024",
                "symbol": "AAPL",
                "chunk_id": "c1",
                "vector_score": 0.66,
                "metadata": {"section_type": "valuation"},
            },
            {
                "evidence_id": "ev_unused",
                "source_type": "sec_edgar",
                "period": "FY2024",
                "symbol": "AAPL",
                "chunk_id": "c2",
                "vector_score": 0.41,
                "metadata": {"section_type": "valuation"},
            },
        ],
    )
    _write(outputs, "section_dossiers.json", {"valuation": {"supporting_evidence_ids": ["ev_used", "ev_unused"]}})
    _write(outputs, "report_section_contracts.json", {"contracts": {"valuation": {"status": "supported", "citation_evidence_ids": ["ev_used", "ev_unused"]}}})
    (reports / "report.md").write_text("## 估值观察\n\n估值分析引用 ev_used 作为证据。", encoding="utf-8")

    artifact = build_evidence_retrieval_attribution(outputs, reports_dir=reports)
    usage = artifact["section_results"]["valuation"]["section_evidence_pack_usage"]

    assert usage["section_evidence_count"] == 2
    assert usage["used_in_report_count"] == 1
    assert usage["used_in_report_rate"] == 0.5
    assert usage["section_top_similarity"] == 0.66
    assert {row["evidence_id"]: row["used_in_report"] for row in usage["evidence"]} == {
        "ev_used": True,
        "ev_unused": False,
    }


def test_attribution_detects_stale_review_after_section_verification_passed(tmp_path):
    outputs, reports = _dirs(tmp_path)
    _write(outputs, "search_meta.json", {"engine_meta": {"local_evidence": {"source_record_count": 1, "candidate_count": 1, "returned_hit_count": 1, "vector_score_max": 0.5}}})
    _write(outputs, "evidence.json", [{"evidence_id": "ev1", "source_type": "sec_edgar", "period": "FY2024", "symbol": "AAPL", "chunk_id": "c1", "metadata": {"section_type": "conclusion"}}])
    _write(outputs, "section_dossiers.json", {"conclusion": {"supporting_evidence_ids": ["ev1"]}})
    _write(outputs, "report_section_contracts.json", {"contracts": {"conclusion": {"status": "supported", "citation_evidence_ids": ["ev1"]}}})
    _write(outputs, "section_verification.json", {"section_results": {"conclusion": {"status": "passed"}}})
    _write(outputs, "llm_quality_review.json", {"issues": [{"severity": "warning", "message": "投资结论内容空洞，暂不展开"}]})

    artifact = build_evidence_retrieval_attribution(outputs, reports_dir=reports)

    assert artifact["section_results"]["conclusion"]["root_cause"] == "review_stale_or_overstrict"


def test_attribution_is_loaded_and_surfaces_in_delivery_gate(tmp_path):
    outputs, reports = _dirs(tmp_path)
    _write(outputs, "verification_report.json", {"passed": True})
    _write(outputs, "quality_report.json", {"objective_pass": True, "total_score": 0.9, "issues": []})
    _write(outputs, "llm_quality_review.json", {"llm_review_pass": True, "total_score": 0.85, "issues": []})
    write_evidence_retrieval_attribution(outputs, reports_dir=reports, run_dir=tmp_path / "run")

    artifacts = load_quality_artifacts(resolve_run_paths(tmp_path / "run"))
    gate = build_delivery_gate(tmp_path / "run")

    assert artifacts["evidence_retrieval_attribution"]["status"] == "ready"
    assert gate["delivery_pass"] is True
    assert gate["evidence_retrieval_attribution"]["available"] is True
    assert any(issue["category"] == "retrieval_attribution" for issue in gate["issues"])


def _dirs(tmp_path):
    outputs = tmp_path / "run" / "company" / "outputs"
    reports = tmp_path / "run" / "company" / "reports"
    outputs.mkdir(parents=True)
    reports.mkdir(parents=True)
    return outputs, reports


def _write(root, name, payload):
    (root / name).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
