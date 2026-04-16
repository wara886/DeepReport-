"""CLI main for Stage 4 claim-first pipeline."""

from __future__ import annotations

import argparse
import json

from src.app.pipeline import run_pipeline


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Stage 4 claim-first pipeline.")
    parser.add_argument("--output-dir", default="data/outputs")
    parser.add_argument("--report-dir", default="data/reports")
    parser.add_argument("--features-root", default="data/features")
    parser.add_argument("--writer-mode", default="template_only", choices=["template_only", "backend_generate"])
    parser.add_argument("--writer-backend", default="mock", choices=["mock", "local_small", "remote"])
    parser.add_argument("--writer-backend-config-path", default="configs/model_backends.yaml")
    parser.add_argument("--writer-debug-path", default="")
    parser.add_argument("--retrieval-query", default="")
    parser.add_argument("--retrieval-topk", type=int, default=5)
    parser.add_argument("--retrieval-curated-dir", default="data/curated")
    parser.add_argument("--retrieval-ranking-mode", default="bm25", choices=["bm25", "reranker"])
    parser.add_argument("--reranker-checkpoint-path", default="data/outputs/checkpoints/reranker_checkpoint.json")
    args = parser.parse_args()

    result = run_pipeline(
        output_dir=args.output_dir,
        report_dir=args.report_dir,
        features_root=args.features_root,
        writer_mode=args.writer_mode,
        writer_backend=args.writer_backend,
        writer_backend_config_path=args.writer_backend_config_path,
        writer_debug_path=(args.writer_debug_path or None),
        retrieval_query=args.retrieval_query,
        retrieval_topk=args.retrieval_topk,
        retrieval_curated_dir=args.retrieval_curated_dir,
        retrieval_ranking_mode=args.retrieval_ranking_mode,
        reranker_checkpoint_path=args.reranker_checkpoint_path,
    )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
