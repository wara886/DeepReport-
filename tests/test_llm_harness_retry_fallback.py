import time

from sqlalchemy import select

from src.db.init_db import init_db
from src.db.models import LLMRun
from src.llm.harness import LLMHarness
from src.services.report_task_service import ReportTaskService


class FailingBackend:
    name = "primary"

    def __init__(self):
        self.calls = 0

    def generate_structured(self, **kwargs):
        self.calls += 1
        raise RuntimeError("primary failed")


class FallbackBackend:
    name = "fallback"

    def generate_structured(self, **kwargs):
        return {"ok": True, "source": "fallback"}


class SlowBackend:
    name = "slow-primary"

    def generate_structured(self, **kwargs):
        time.sleep(0.2)
        return {"ok": True, "source": "slow"}


def test_llm_harness_retries_and_uses_fallback(tmp_path):
    engine = init_db(f"sqlite:///{tmp_path / 'harness_retry.db'}")
    report_service = ReportTaskService(
        engine=engine,
        output_root=tmp_path / "outputs",
        report_root=tmp_path / "reports",
        memory_root=tmp_path / "memory",
    )
    primary = FailingBackend()
    harness = LLMHarness(
        session_factory=report_service.session,
        backend=primary,
        fallback_backend=FallbackBackend(),
        max_retries=2,
    )

    result = harness.run_prompt(
        prompt_key="fact_extractor",
        input={"text": "revenue increased"},
        schema={"type": "object", "required": ["ok"], "properties": {"ok": {"type": "boolean"}}},
    )
    with report_service.session() as session:
        run = session.scalar(select(LLMRun).where(LLMRun.run_id == result.run_id))

    assert primary.calls == 2
    assert result.status == "success"
    assert result.fallback_used is True
    assert result.attempt_count == 3
    assert result.output["source"] == "fallback"
    assert run is not None
    assert run.metadata_json["attempt_errors"] == [
        {"backend": "primary", "attempt": 1, "fallback": False, "error": "primary failed"},
        {"backend": "primary", "attempt": 2, "fallback": False, "error": "primary failed"},
    ]


def test_llm_harness_times_out_primary_and_records_fallback(tmp_path):
    engine = init_db(f"sqlite:///{tmp_path / 'harness_timeout.db'}")
    report_service = ReportTaskService(
        engine=engine,
        output_root=tmp_path / "outputs",
        report_root=tmp_path / "reports",
        memory_root=tmp_path / "memory",
    )
    harness = LLMHarness(
        session_factory=report_service.session,
        backend=SlowBackend(),
        fallback_backend=FallbackBackend(),
        timeout_seconds=0.01,
        max_retries=1,
    )

    result = harness.run_prompt(
        prompt_key="claim_verifier",
        input={"claim": "收入增长"},
        schema={"type": "object", "required": ["ok"], "properties": {"ok": {"type": "boolean"}}},
        task_id="task-timeout",
        model_role="verifier",
    )
    with report_service.session() as session:
        run = session.scalar(select(LLMRun).where(LLMRun.run_id == result.run_id))

    assert result.status == "success"
    assert result.fallback_used is True
    assert result.attempt_count == 2
    assert result.output["source"] == "fallback"
    assert run is not None
    assert run.model_name == "fallback"
    assert run.task_id == "task-timeout"
    assert run.metadata_json["attempt_errors"][0]["backend"] == "slow-primary"
    assert "timed out" in run.metadata_json["attempt_errors"][0]["error"]
