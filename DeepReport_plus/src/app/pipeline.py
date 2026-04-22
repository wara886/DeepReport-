"""Stage 4 pipeline entry."""

from __future__ import annotations

from typing import Dict

from src.agents.orchestrator import Orchestrator


def run_pipeline(
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
) -> Dict[str, str]:
    orchestrator = Orchestrator(
        output_dir=output_dir,
        report_dir=report_dir,
        features_root=features_root,
        writer_mode=writer_mode,
        writer_backend=writer_backend,
        writer_backend_config_path=writer_backend_config_path,
        writer_debug_path=writer_debug_path,
        retrieval_query=retrieval_query,
        retrieval_topk=retrieval_topk,
        retrieval_curated_dir=retrieval_curated_dir,
        retrieval_ranking_mode=retrieval_ranking_mode,
        reranker_checkpoint_path=reranker_checkpoint_path,
        verifier_checkpoint_path=verifier_checkpoint_path,
    )
    return orchestrator.run()
