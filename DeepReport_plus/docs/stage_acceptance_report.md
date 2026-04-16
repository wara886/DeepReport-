# Stage Acceptance Report

Date: 2026-04-16  
Scope: Stage 2 through Stage 10 smoke acceptance (sequential run)

## Command Log

1. `python scripts/run_stage2_data_smoke.py`  
   Status: `PASS`
2. `python scripts/run_stage3_feature_smoke.py`  
   Status: `PASS`
3. `python scripts/run_stage4_pipeline_smoke.py`  
   Status: `PASS`
4. `python scripts/run_stage5_chart_smoke.py`  
   Status: `PASS`
5. `python scripts/run_stage6_backend_smoke.py`  
   Status: `PASS`
6. `python scripts/run_stage7_retrieval_smoke.py`  
   Status: `PASS`
7. `python scripts/run_stage8_dataset_smoke.py`  
   Status: `PASS`
8. `python scripts/run_stage9_training_smoke.py`  
   Status: `PASS`
9. `python scripts/run_stage10_export_smoke.py`  
   Status: `PASS`

## Stage Summary

| Stage | Entry | Result | Key Output |
| --- | --- | --- | --- |
| 2 | `run_stage2_data_smoke.py` | PASS | `data/curated/*.parquet` |
| 3 | `run_stage3_feature_smoke.py` | PASS | `data/features/*.parquet`, `feature_report.json` |
| 4 | `run_stage4_pipeline_smoke.py` | PASS | `claim_table.json`, `report.md`, `verification_report.json` |
| 5 | `run_stage5_chart_smoke.py` | PASS | chart PNG files, `chart_metadata.json` |
| 6 | `run_stage6_backend_smoke.py` | PASS | backend path + fallback path both executable |
| 7 | `run_stage7_retrieval_smoke.py` | PASS | `retrieval_results.json` |
| 8 | `run_stage8_dataset_smoke.py` | PASS | reranker/rewriter/verifier parquet+jsonl, `dataset_report.json` |
| 9 | `run_stage9_training_smoke.py` | PASS | checkpoint files + infer outputs |
| 10 | `run_stage10_export_smoke.py` | PASS | `report.md`, `report.html`, `report.json` |

## Artifact Check (exists + size)

- `data/curated/market.parquet` (3009 bytes)
- `data/curated/financials.parquet` (2994 bytes)
- `data/curated/news.parquet` (3055 bytes)
- `data/curated/filings.parquet` (3045 bytes)
- `data/features/feature_report.json` (371 bytes)
- `data/features/financial_ratios.parquet` (4148 bytes)
- `data/features/trend_analysis.parquet` (3511 bytes)
- `data/features/peer_compare.parquet` (3565 bytes)
- `data/features/risk_signals.parquet` (3482 bytes)
- `data/outputs/claim_table.json` (3433 bytes)
- `data/outputs/verification_report.json` (123 bytes)
- `data/reports/report.md` (1383 bytes)
- `data/outputs/chart_metadata.json` (682 bytes)
- `data/outputs/charts/revenue_line.png` (8999 bytes)
- `data/outputs/charts/risk_ratio_bar.png` (5285 bytes)
- `data/outputs/charts/coverage_table.png` (6640 bytes)
- `data/outputs/retrieval_results.json` (884 bytes)
- `data/outputs/training/dataset_report.json` (531 bytes)
- `data/outputs/training/reranker/dataset.parquet` (3656 bytes)
- `data/outputs/training/reranker/dataset.jsonl` (356 bytes)
- `data/outputs/training/rewriter/dataset.parquet` (4843 bytes)
- `data/outputs/training/rewriter/dataset.jsonl` (2700 bytes)
- `data/outputs/training/verifier/dataset.parquet` (4576 bytes)
- `data/outputs/training/verifier/dataset.jsonl` (1691 bytes)
- `data/outputs/checkpoints/reranker_checkpoint.json` (87 bytes)
- `data/outputs/checkpoints/rewriter_checkpoint.json` (101 bytes)
- `data/outputs/checkpoints/verifier_checkpoint.json` (94 bytes)
- `data/outputs/reranked_results.json` (969 bytes)
- `data/outputs/verification_infer_report.json` (301 bytes)
- `data/outputs/rewriter_infer_results.json` (1551 bytes)
- `data/reports/report.html` (2677 bytes)
- `data/reports/report.json` (4511 bytes)

## Residual Risks

1. Stage 9 cloud transfer scripts are templates (`rsync` lines commented), so true remote transfer is not yet validated.
2. Stage 6/9 model backends are lightweight placeholders, not full model serving/inference integrations.
3. Some shell checks previously showed intermittent `Test-Path` false negatives in this environment; recursive directory listing was used for final artifact confirmation.
4. Validation currently focuses on smoke behavior and file outputs; no stress/performance tests have been run.

## Recommendation

Run one optional end-to-end regression command set under CI (or a clean shell session) that executes Stage 2-10 smoke scripts and fails fast on missing artifacts, then archive this report for release baseline.

