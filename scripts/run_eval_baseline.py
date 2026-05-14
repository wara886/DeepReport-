"""Run Phase 0 eval baselines and write comparable outputs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time
from typing import Any, Dict

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.agents.multi_agent_orchestrator import MultiAgentOrchestrator
from src.eval.evaluator import BaselineEvaluator
from src.eval.schema import EvalCase, load_eval_cases, write_case_schema
from src.models import ModelAdapter


BASELINE_0 = "baseline_0_single_prompt"
BASELINE_1 = "baseline_1_single_rag"
BASELINE_2 = "baseline_2_current_workflow"
BASELINE_3 = "baseline_3_gaprouter_routed_rework"
BASELINE_4 = "baseline_4_dynamic_multiagent_router"
BASELINE_5 = "baseline_5_adjudicator_source_conflict"
SUPPORTED_BASELINES = (BASELINE_0, BASELINE_1, BASELINE_2, BASELINE_3, BASELINE_4, BASELINE_5)


class SinglePromptModelAdapter:
    def __init__(self, config_path: str):
        self.model = ModelAdapter.from_config(config_path=config_path)

    def __call__(self, case: EvalCase, case_root: Path) -> Dict[str, Any]:
        started = time.perf_counter()
        reports = case_root / "reports"
        outputs = case_root / "outputs"
        reports.mkdir(parents=True, exist_ok=True)
        outputs.mkdir(parents=True, exist_ok=True)
        prompt = _single_prompt(case)
        response = self.model.generate(prompt=prompt, system_prompt="You are a financial research report writer.")
        if not response.success:
            return _failed_stub_result(
                case=case,
                case_root=case_root,
                baseline_id=BASELINE_0,
                error=response.error,
                total_latency_sec=time.perf_counter() - started,
            )
        markdown = response.content.strip()
        artifacts = _write_basic_artifacts(
            case=case,
            case_root=case_root,
            baseline_id=BASELINE_0,
            markdown=markdown,
            claims=[],
            evidence=[],
            citations=[],
            verification={"passed": bool(markdown), "errors": [] if markdown else ["empty report"]},
            total_latency_sec=time.perf_counter() - started,
        )
        return {
            "status": "completed",
            "baseline_id": BASELINE_0,
            "markdown": markdown,
            "claims": [],
            "evidence": [],
            "citations": [],
            "verification": {"passed": bool(markdown), "errors": [] if markdown else ["empty report"]},
            "total_latency_sec": time.perf_counter() - started,
            "artifacts": artifacts,
        }


def run_single_rag_stub(case: EvalCase, case_root: Path) -> Dict[str, Any]:
    return _failed_stub_result(
        case=case,
        case_root=case_root,
        baseline_id=BASELINE_1,
        error="TODO: baseline_1_single_rag adapter is reserved for a single-agent RAG path and is not implemented yet.",
        total_latency_sec=0.0,
        status="not_implemented",
    )


class CurrentWorkflowAdapter:
    def __init__(
        self,
        config_path: str,
        raw_data_root: str,
        execution_mode: str,
        fast: bool,
        search_engines: list[str],
        retrieval_ranking_mode: str,
        baseline_id: str = BASELINE_2,
    ):
        self.config_path = config_path
        self.raw_data_root = raw_data_root
        self.execution_mode = execution_mode
        self.fast = fast
        self.search_engines = search_engines
        self.retrieval_ranking_mode = retrieval_ranking_mode
        self.baseline_id = baseline_id

    def __call__(self, case: EvalCase, case_root: Path) -> Dict[str, Any]:
        started = time.perf_counter()
        outputs = case_root / "outputs"
        reports = case_root / "reports"
        orchestrator = MultiAgentOrchestrator(
            output_dir=str(outputs),
            report_dir=str(reports),
            config_path=self.config_path,
            raw_data_root=self.raw_data_root,
        )
        artifacts = orchestrator.run(
            research_topic=case.query,
            symbol=case.symbol,
            period=case.period,
            requirements=[
                f"报告类型：{case.report_type}",
                "必须覆盖章节：" + "、".join(case.required_sections),
                "必须优先使用来源类型：" + "、".join(case.required_source_types),
                "所有关键结论必须绑定 evidence_id，并输出 Markdown、HTML、JSON、trace 和验证报告。",
            ],
            execution_mode=self.execution_mode,
            fast=self.fast,
            search_engines=self.search_engines,
            retrieval_ranking_mode=self.retrieval_ranking_mode,
        )
        artifacts = dict(artifacts)
        artifacts.setdefault("report_md", str(reports / "report.md"))
        artifacts.setdefault("report_json", str(reports / "report.json"))
        artifacts.setdefault("verification_report", str(outputs / "verification_report.json"))
        artifacts.setdefault("claims", str(outputs / "claims.json"))
        artifacts.setdefault("evidence", str(outputs / "evidence.json"))
        artifacts.setdefault("citations", str(outputs / "citations.json"))
        artifacts.setdefault("run_summary", str(outputs / "run_summary.json"))
        return {
            "status": "completed",
            "baseline_id": self.baseline_id,
            "total_latency_sec": time.perf_counter() - started,
            "artifacts": artifacts,
        }


def build_evaluator(args: argparse.Namespace) -> BaselineEvaluator:
    return BaselineEvaluator(
        adapters={
            BASELINE_0: SinglePromptModelAdapter(config_path=args.config_path),
            BASELINE_1: run_single_rag_stub,
            BASELINE_2: CurrentWorkflowAdapter(
                config_path=args.config_path,
                raw_data_root=args.raw_data_root,
                execution_mode=args.execution_mode,
                fast=args.fast,
                search_engines=args.search_engines.split(",") if args.search_engines else ["local_real_data", "local_evidence"],
                retrieval_ranking_mode=args.retrieval_ranking_mode,
                baseline_id=BASELINE_2,
            ),
            BASELINE_3: CurrentWorkflowAdapter(
                config_path=args.config_path,
                raw_data_root=args.raw_data_root,
                execution_mode=args.execution_mode,
                fast=args.fast,
                search_engines=args.search_engines.split(",") if args.search_engines else ["local_real_data", "local_evidence"],
                retrieval_ranking_mode=args.retrieval_ranking_mode,
                baseline_id=BASELINE_3,
            ),
            BASELINE_4: CurrentWorkflowAdapter(
                config_path=args.config_path,
                raw_data_root=args.raw_data_root,
                execution_mode="dynamic_multiagent",
                fast=args.fast,
                search_engines=args.search_engines.split(",") if args.search_engines else ["local_real_data", "local_evidence"],
                retrieval_ranking_mode=args.retrieval_ranking_mode,
                baseline_id=BASELINE_4,
            ),
            BASELINE_5: CurrentWorkflowAdapter(
                config_path=args.config_path,
                raw_data_root=args.raw_data_root,
                execution_mode="dynamic_multiagent",
                fast=args.fast,
                search_engines=args.search_engines.split(",") if args.search_engines else ["local_real_data", "local_evidence"],
                retrieval_ranking_mode=args.retrieval_ranking_mode,
                baseline_id=BASELINE_5,
            ),
        }
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Phase 0 eval baseline harness.")
    parser.add_argument("--baseline", choices=SUPPORTED_BASELINES, default=BASELINE_2)
    parser.add_argument("--cases", default="eval/cases", help="Eval case JSON/JSONL file or directory.")
    parser.add_argument("--output-root", default="eval_outputs")
    parser.add_argument("--run-id", default="")
    parser.add_argument("--max-cases", type=int, default=0)
    parser.add_argument("--config-path", default="configs/model_backends.yaml")
    parser.add_argument("--raw-data-root", default="data/raw/real_data")
    parser.add_argument("--execution-mode", choices=["dynamic", "static", "legacy_workflow", "routed_rework", "dynamic_multiagent"], default="dynamic")
    parser.add_argument("--fast", action="store_true", default=True)
    parser.add_argument("--no-fast", dest="fast", action="store_false")
    parser.add_argument("--search-engines", default="local_real_data,local_evidence")
    parser.add_argument("--retrieval-ranking-mode", default="hybrid_rerank")
    args = parser.parse_args(argv)

    write_case_schema(PROJECT_ROOT / "eval" / "cases" / "case_schema.json")
    cases = load_eval_cases(PROJECT_ROOT / args.cases if not Path(args.cases).is_absolute() else args.cases)
    if args.max_cases > 0:
        cases = cases[: args.max_cases]
    if not cases:
        raise ValueError(f"No eval cases found under {args.cases}")

    evaluator = build_evaluator(args)
    summary = evaluator.run(
        cases=cases,
        baseline_id=args.baseline,
        output_root=PROJECT_ROOT / args.output_root if not Path(args.output_root).is_absolute() else args.output_root,
        run_id=args.run_id or None,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def _single_prompt(case: EvalCase) -> str:
    return "\n".join(
        [
            f"请为 {case.market} 市场标的 {case.symbol} 撰写 {case.period} 的 {case.report_type}。",
            f"研究主题：{case.topic}",
            "必须覆盖章节：" + "、".join(case.required_sections),
            "必须使用或说明以下来源类型：" + "、".join(case.required_source_types),
            "请输出带引用占位符的 Markdown 报告。",
        ]
    )


def _failed_stub_result(
    case: EvalCase,
    case_root: Path,
    baseline_id: str,
    error: str,
    total_latency_sec: float,
    status: str = "failed",
) -> Dict[str, Any]:
    artifacts = _write_basic_artifacts(
        case=case,
        case_root=case_root,
        baseline_id=baseline_id,
        markdown="",
        claims=[],
        evidence=[],
        citations=[],
        verification={"passed": False, "errors": [error]},
        total_latency_sec=total_latency_sec,
        status=status,
    )
    return {
        "status": status,
        "baseline_id": baseline_id,
        "error": error,
        "markdown": "",
        "claims": [],
        "evidence": [],
        "citations": [],
        "verification": {"passed": False, "errors": [error]},
        "total_latency_sec": total_latency_sec,
        "artifacts": artifacts,
    }


def _write_basic_artifacts(
    case: EvalCase,
    case_root: Path,
    baseline_id: str,
    markdown: str,
    claims: list[Dict[str, Any]],
    evidence: list[Dict[str, Any]],
    citations: list[Dict[str, Any]],
    verification: Dict[str, Any],
    total_latency_sec: float,
    status: str = "completed",
) -> Dict[str, str]:
    reports = case_root / "reports"
    outputs = case_root / "outputs"
    reports.mkdir(parents=True, exist_ok=True)
    outputs.mkdir(parents=True, exist_ok=True)
    report_json = {
        "case_id": case.case_id,
        "baseline_id": baseline_id,
        "symbol": case.symbol,
        "period": case.period,
        "report_type": case.report_type,
        "markdown": markdown,
        "claims": claims,
        "citations": citations,
    }
    run_summary = {
        "case_id": case.case_id,
        "baseline_id": baseline_id,
        "status": status,
        "total_duration_sec": round(total_latency_sec, 4),
        "claim_count": len(claims),
        "evidence_count": len(evidence),
        "citation_count": len(citations),
        "verification_passed": bool(verification.get("passed")),
    }
    paths = {
        "report_md": reports / "report.md",
        "report_json": reports / "report.json",
        "verification_report": outputs / "verification_report.json",
        "claims": outputs / "claims.json",
        "evidence": outputs / "evidence.json",
        "citations": outputs / "citations.json",
        "run_summary": outputs / "run_summary.json",
    }
    paths["report_md"].write_text(markdown, encoding="utf-8")
    paths["report_json"].write_text(json.dumps(report_json, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    paths["verification_report"].write_text(json.dumps(verification, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    paths["claims"].write_text(json.dumps(claims, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    paths["evidence"].write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    paths["citations"].write_text(json.dumps(citations, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    paths["run_summary"].write_text(json.dumps(run_summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {key: str(value) for key, value in paths.items()}


if __name__ == "__main__":
    raise SystemExit(main())
