"""Stage 4 orchestrator for planner -> analyst -> writer -> verifier."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict

from src.agents.analyst import Analyst
from src.agents.planner import Planner
from src.agents.verifier import Verifier
from src.agents.writer import Writer
from src.evaluation.per_claim_verification import export_per_claim_verification
from src.retrieval.retrieve import retrieve_evidence_with_mode


class Orchestrator:
    """Run claim-first pipeline and persist artifacts."""

    def __init__(
        self,
        output_dir: str = "data/outputs",
        report_dir: str = "data/reports",
        features_root: str = "data/features",
        writer_mode: str = "template_only",
        writer_backend: str = "mock",
        writer_backend_config_path: str = "configs/model_backends.yaml",
        writer_debug_path: str | None = None,
        retrieval_query: str = "",
        retrieval_topk: int = 5,
        retrieval_curated_dir: str = "data/curated",
        retrieval_ranking_mode: str = "bm25",
        reranker_checkpoint_path: str = "data/outputs/checkpoints/reranker_checkpoint.json",
        verifier_checkpoint_path: str = "data/outputs/checkpoints/verifier_checkpoint.json",
    ):
        self.output_dir = Path(output_dir)
        self.report_dir = Path(report_dir)
        self.planner = Planner()
        self.analyst = Analyst(features_root=features_root)
        self.writer = Writer(
            mode=writer_mode,
            backend=writer_backend,
            backend_config_path=writer_backend_config_path,
            debug_output_path=writer_debug_path or str(self.output_dir / "writer_debug.json"),
        )
        self.verifier = Verifier()
        self.retrieval_query = retrieval_query
        self.retrieval_topk = retrieval_topk
        self.retrieval_curated_dir = retrieval_curated_dir
        self.retrieval_ranking_mode = retrieval_ranking_mode
        self.reranker_checkpoint_path = reranker_checkpoint_path
        self.verifier_checkpoint_path = verifier_checkpoint_path

    def run(self) -> Dict[str, str]:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.report_dir.mkdir(parents=True, exist_ok=True)

        plan = self.planner.build_plan()
        claims = self.analyst.build_claims()
        retrieval_hits = []
        retrieval_meta = {
            "mode": "bm25",
            "checkpoint_path": self.reranker_checkpoint_path,
            "checkpoint_used": False,
            "fallback_used": False,
        }
        if self.retrieval_query.strip():
            retrieval_hits, retrieval_meta = retrieve_evidence_with_mode(
                query=self.retrieval_query,
                topk=self.retrieval_topk,
                curated_dir=self.retrieval_curated_dir,
                ranking_mode=self.retrieval_ranking_mode,
                reranker_checkpoint_path=self.reranker_checkpoint_path,
                log=True,
            )
            retrieval_path = self.output_dir / "retrieval_results_used.json"
            retrieval_path.write_text(
                json.dumps({"query": self.retrieval_query, "hits": retrieval_hits, "meta": retrieval_meta}, indent=2),
                encoding="utf-8",
            )

        markdown = self.writer.render_markdown(
            plan,
            claims,
            retrieval_hits=retrieval_hits,
            retrieval_meta=retrieval_meta,
        )
        verification = self.verifier.verify(claims, markdown)

        claim_path = self.output_dir / "claim_table.json"
        report_path = self.report_dir / "report.md"
        verify_path = self.output_dir / "verification_report.json"
        writer_debug_path = Path(self.writer.debug_output_path or (self.output_dir / "writer_debug.json"))

        claim_path.write_text(
            json.dumps([item.to_dict() for item in claims], indent=2),
            encoding="utf-8",
        )
        report_path.write_text(markdown, encoding="utf-8")
        verify_path.write_text(json.dumps(verification, indent=2), encoding="utf-8")
        per_claim_outputs = export_per_claim_verification(
            claim_path=claim_path,
            output_dir=self.output_dir,
            checkpoint_path=self.verifier_checkpoint_path,
        )

        return {
            "claim_table": str(claim_path),
            "report_markdown": str(report_path),
            "verification_report": str(verify_path),
            "writer_debug": str(writer_debug_path),
            "per_claim_verification_json": str(per_claim_outputs["per_claim_verification_json"]),
            "per_claim_verification_csv": str(per_claim_outputs["per_claim_verification_csv"]),
        }
