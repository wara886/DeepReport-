import pytest

from src.db.init_db import init_db
from src.llm.harness import LLMHarness, LLMHarnessSchemaError
from src.services.report_task_service import ReportTaskService


class StaticBackend:
    name = "static"

    def __init__(self, payload):
        self.payload = payload

    def generate_structured(self, **kwargs):
        return self.payload


def build_harness(tmp_path, backend):
    engine = init_db(f"sqlite:///{tmp_path / 'harness_schema.db'}")
    report_service = ReportTaskService(
        engine=engine,
        output_root=tmp_path / "outputs",
        report_root=tmp_path / "reports",
        memory_root=tmp_path / "memory",
    )
    return LLMHarness(session_factory=report_service.session, backend=backend)


def test_llm_harness_accepts_schema_valid_output(tmp_path):
    harness = build_harness(tmp_path, StaticBackend({"claim": "收入增长", "confidence": 0.82}))

    result = harness.run_prompt(
        prompt_key="claim_verifier",
        input={"claim": "收入增长"},
        schema={
            "type": "object",
            "required": ["claim", "confidence"],
            "properties": {"claim": {"type": "string"}, "confidence": {"type": "number"}},
        },
    )

    assert result.status == "success"
    assert result.schema_valid is True
    assert result.output["confidence"] == 0.82


def test_llm_harness_rejects_schema_invalid_output(tmp_path):
    harness = build_harness(tmp_path, StaticBackend({"claim": "收入增长", "confidence": "high"}))

    with pytest.raises(LLMHarnessSchemaError):
        harness.run_prompt(
            prompt_key="claim_verifier",
            input={"claim": "收入增长"},
            schema={
                "type": "object",
                "required": ["claim", "confidence"],
                "properties": {"claim": {"type": "string"}, "confidence": {"type": "number"}},
            },
        )
