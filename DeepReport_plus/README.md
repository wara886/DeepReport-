# Open DeepReport++

本项目受 `DeepReport` 工程骨架启发，但不直接复制其业务逻辑。

`Open DeepReport++` 是一个面向公司/个股研报的分阶段系统，强调：

- evidence/claim 可追溯
- 配置驱动
- 本地可运行闭环
- 云端训练与本地 fallback 解耦

## Quick Start

```bash
python scripts/run_local_smoke.py --config configs/local_smoke.yaml
python -m pytest -q
```

## Stage Smoke Commands

```bash
python scripts/run_stage2_data_smoke.py
python scripts/run_stage3_feature_smoke.py
python scripts/run_stage4_pipeline_smoke.py
python scripts/run_stage5_chart_smoke.py
python scripts/run_stage6_backend_smoke.py
python scripts/run_stage7_retrieval_smoke.py
python scripts/run_stage8_dataset_smoke.py
python scripts/run_stage9_training_smoke.py
python scripts/run_stage10_export_smoke.py
```

## Real Data Minimal Ingestion (Stage 11A)

Stage 11A adds a minimal `real_data/local_file` closed-loop without removing the existing mock baseline.

### Coexistence Model

- mock chain remains unchanged (`data/raw/mock` -> `data/curated` -> `data/features` -> `data/reports`)
- real_data chain is isolated:
  - `data/raw/real_data`
  - `data/curated_real`
  - `data/features_real`
  - `data/reports_real`

Switch is configuration-driven via `configs/local_real_smoke.yaml`:

- `real_data.data_mode=mock`
- or `real_data.data_mode=local_file_real`

### Real Data Sample Layout

```text
data/raw/real_data/<symbol>/<period>/
  company_profile.json
  financials.csv
  market.csv
  news.jsonl
  filings.jsonl
```

Detailed contract: [docs/real_data_contract.md](./docs/real_data_contract.md)

### Run Real Data Smoke

```bash
python scripts/run_stage11a_real_data_smoke.py
```

Expected outputs:

- `data/curated_real/*.parquet`
- `data/curated_real/real_data_manifest.parquet`
- `data/features_real/*.parquet`
- `data/features_real/feature_report_real.json`
- `data/reports_real/report.md`
- `data/reports_real/report.html`
- `data/reports_real/report.json`

## Real Writer Backend (Stage 11B)

Stage 11B adds one real writer backend path (`remote`) while keeping:

- `template_only`
- `mock`
- fallback-to-template behavior

### Configure Backend

Main backend config is in `configs/model_backends.yaml`:

- `writer_backend.mode`: `template_only | mock | remote | local_small`
- common generation params:
  - `timeout`
  - `retry`
  - `max_tokens`
  - `temperature`
- backend-specific params:
  - `model_name`
  - `base_url` (remote)

Environment variables supported for remote:

- `WRITER_REMOTE_BASE_URL`
- `WRITER_REMOTE_API_KEY`
- `WRITER_REMOTE_MODEL`

`configs/local_real_smoke.yaml` controls runtime selection:

- `generation.writer_mode: template_only | backend_generate`
- `generation.backend: mock | remote | local_small`
- `generation.backend_config_path: configs/model_backends.yaml`

### Fallback Behavior

If backend call times out, returns error, or returns empty content, writer automatically falls back to template rendering.
Debug payload is written to `writer_debug.json` with:

- `backend_mode`
- `generation_time`
- `fallback_triggered`
- `section_count`
- `error_message`

### Run Stage 11B Smoke

```bash
python scripts/run_stage11b_writer_backend_smoke.py
```

By config switch, the same script can run either:

- `real_data` chain (writes into `data/reports_real/`)
- or `mock` chain (writes into `data/reports/`)

## Cloud Training (Stage 11C, Reranker Only)

Stage 11C validates only the reranker cloud-training loop:

1. build offline dataset
2. upload to cloud (or local simulation)
3. train reranker
4. download checkpoint
5. run local reranker infer
6. reconnect ranking into local pipeline

Run minimal chain:

```bash
bash scripts/run_stage11c_reranker_cloud_validation.sh --local-simulation
```

Transfer scripts support env/CLI params and dry-run:

```bash
bash scripts/upload_to_cloud.sh --local-simulation --dry-run
bash scripts/download_from_cloud.sh --local-simulation --dry-run
```

Required variables (env or args):

- `REMOTE_HOST`
- `REMOTE_PORT`
- `REMOTE_USER`
- `REMOTE_BASE_DIR`
- `LOCAL_EXPORT_DIR`
- `LOCAL_CHECKPOINT_DIR`

Fallback:

- If reranker checkpoint is missing, retrieval automatically falls back to original BM25 ordering.
