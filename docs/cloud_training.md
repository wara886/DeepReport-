# Cloud Training Guide (Stage 11C)

## Scope

Stage 11C validates only one real minimal chain for **reranker**:

`build_reranker_dataset -> upload_to_cloud -> train_reranker -> download_from_cloud -> infer_reranker -> local pipeline reconnect`

Rewriter and verifier remain out of this validation stage.

## Offline Input Constraint

Training consumes only exported offline files. No online data fetch is allowed in training scripts.

Required input:

- `data/outputs/training/reranker/dataset.parquet` (or configured equivalent)

## Config

- Cloud transfer/runtime: `configs/cloud_train.yaml`
- Reranker training/infer paths: `configs/reranker.yaml`

Important keys:

- `cloud.transfer.remote_host`
- `cloud.transfer.remote_port`
- `cloud.transfer.remote_user`
- `cloud.transfer.remote_base_dir`
- `cloud.transfer.local_export_dir`
- `cloud.transfer.local_checkpoint_dir`
- `cloud.transfer.log_path`
- `reranker.training.dataset_path`
- `reranker.checkpoint_path`
- `reranker.inference.input_path`
- `reranker.inference.output_path`

## Upload / Download

Upload script (supports env + CLI args, `dry-run`, `local_simulation`):

```bash
bash scripts/upload_to_cloud.sh --local-simulation --dry-run
```

Download script:

```bash
bash scripts/download_from_cloud.sh --local-simulation --dry-run
```

Both scripts append logs to `transfer_debug.log`.

## Train

```bash
python -m src.training.train_reranker \
  --cloud-config configs/cloud_train.yaml \
  --reranker-config configs/reranker.yaml
```

Checkpoint output:

- `data/outputs/checkpoints/reranker_checkpoint.json` (or configured path)

## Infer

```bash
python -m src.training.infer_reranker \
  --cloud-config configs/cloud_train.yaml \
  --reranker-config configs/reranker.yaml
```

Output:

- `data/outputs/reranked_results.json` (or configured path)

## Local Reconnect and Fallback

Retrieval supports mode switch:

- `bm25` (original sort)
- `reranker` (uses checkpoint path)

If checkpoint is missing, reranker path automatically falls back to BM25 score ordering and emits fallback metadata/logs.

Pipeline entry points:

- `src.retrieval.retrieve.retrieve_evidence_with_mode`
- `src.app.pipeline.run_pipeline(... retrieval_ranking_mode=..., reranker_checkpoint_path=...)`
