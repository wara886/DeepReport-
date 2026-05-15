import json
from pathlib import Path

from src.agents.durable_memory import DurableMemoryStore


def test_durable_memory_persists_working_episodic_and_domain(tmp_path):
    store = DurableMemoryStore(root=tmp_path / "memory", max_domain_items=3, max_episodic_items=2)
    state = {
        "symbol": "AAPL",
        "period": "2025Q4",
        "conversation_context": {"session_id": "s1"},
        "verification_report": {"passed": True, "errors": []},
        "company_report_scorecard": {"overall_score": 0.91},
    }
    summary = {
        "research_topic": "Analyze AAPL 2025Q4",
        "symbol": "AAPL",
        "period": "2025Q4",
        "claim_count": 3,
        "citation_count": 3,
        "chart_count": 2,
        "company_report_overall_score": 0.91,
    }

    paths = store.persist_run(state=state, run_summary=summary)

    assert paths["run_id"]
    for key in ["working_snapshot", "episodic_snapshot", "domain_memory"]:
        assert Path(paths[key]).exists()

    snapshot = json.loads(Path(paths["working_snapshot"]).read_text(encoding="utf-8"))
    assert snapshot["decision"] == "verification_passed"
    assert snapshot["quality_metrics"]["overall_score"] == 0.91


def test_durable_memory_context_brief_is_bounded_and_not_evidence(tmp_path):
    store = DurableMemoryStore(root=tmp_path / "memory")
    for index in range(3):
        store.persist_run(
            state={
                "symbol": "AAPL",
                "period": "2025Q4",
                "verification_report": {"passed": index % 2 == 0},
            },
            run_summary={
                "research_topic": f"Analyze AAPL run {index}",
                "symbol": "AAPL",
                "period": "2025Q4",
                "claim_count": index + 1,
                "citation_count": index + 1,
            },
        )

    brief = store.build_context_brief(symbol="AAPL", period="2025Q4", max_chars=500)

    assert len(brief) <= 500
    assert "DurableMemory" in brief
    assert "Do not use this as evidence" in brief
    assert "AAPL" in brief
