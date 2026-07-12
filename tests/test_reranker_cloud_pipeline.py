import json
import os
import shutil
import subprocess
from pathlib import Path

import yaml

from src.training.infer_reranker import rerank_hits_with_meta
from src.training.train_reranker import train_reranker

REPO_ROOT = Path(__file__).resolve().parent.parent


def _has_bash() -> bool:
    return shutil.which("bash") is not None


def test_fallback_without_checkpoint(monkeypatch):
    monkeypatch.setattr(
        "src.training.infer_reranker._load_reranker_runtime_config",
        lambda: {"use_base_model_without_checkpoint": False},
    )
    hits = [{"sample_id": "s1", "score": 1.0, "trust_level": "high"}]
    ranked, meta = rerank_hits_with_meta(hits, checkpoint_path="data/outputs/checkpoints/not_exists.json")
    assert ranked[0]["rerank_score"] == 1.0
    assert meta["fallback_used"] is True
    assert meta["mode"] == "bm25"


def test_reranker_resolves_project_local_bundle(monkeypatch, tmp_path: Path):
    model_dir = tmp_path / "rerankers" / "bge-reranker-base"
    model_dir.mkdir(parents=True)
    (model_dir / "config.json").write_text("{}", encoding="utf-8")
    (model_dir / "model.safetensors").write_bytes(b"model")
    monkeypatch.setenv("FINSIGHT_MODEL_CACHE_ROOT", str(tmp_path))
    monkeypatch.setattr(
        "src.training.infer_reranker._load_cross_encoder",
        lambda model_name, local_files_only: _FakeCrossEncoder(model_name),
    )

    ranked, meta = rerank_hits_with_meta(
        [{"sample_id": "s1", "content": "revenue", "score": 0.1}],
        query="revenue",
        checkpoint_path=str(tmp_path / "missing.json"),
    )

    assert ranked[0]["rerank_score"] == 0.9
    assert meta["backend"] == "cross_encoder"
    assert meta["resolved_model_path"] == str(model_dir.resolve())


class _FakeCrossEncoder:
    def __init__(self, model_name: str) -> None:
        self.model_name = model_name

    def predict(self, pairs):
        return [0.9 for _ in pairs]


def test_reranker_branch_with_checkpoint(tmp_path: Path):
    ckpt = tmp_path / "reranker_checkpoint.json"
    ckpt.write_text(json.dumps({"trained": True}), encoding="utf-8")
    hits = [{"sample_id": "s1", "score": 1.0, "trust_level": "high"}]
    ranked, meta = rerank_hits_with_meta(hits, checkpoint_path=str(ckpt))
    assert ranked[0]["rerank_score"] > 1.0
    assert meta["fallback_used"] is False
    assert meta["mode"] == "reranker"
    assert meta["backend"] in {"financial_heuristic", "cross_encoder"}


def test_financial_heuristic_reranker_prefers_authoritative_numeric_chunk(tmp_path: Path):
    ckpt = tmp_path / "reranker_checkpoint.json"
    ckpt.write_text(json.dumps({"trained": True, "model_name": "missing-local-model"}), encoding="utf-8")
    hits = [
        {
            "sample_id": "news_1",
            "title": "General market note",
            "content": "Apple demand commentary without the exact margin figure.",
            "source_type": "news",
            "source_url": "https://example.com/news",
            "score": 1.2,
            "trust_level": "medium",
        },
        {
            "sample_id": "metric_1",
            "title": "AAPL financial metric",
            "content": "AAPL 2025Q4 gross_margin_pct = 46.8.",
            "source_type": "financials",
            "source_url": "https://www.sec.gov/aapl",
            "chunk_type": "metric",
            "numeric_values": {"gross_margin_pct": 46.8},
            "score": 0.8,
            "trust_level": "high",
        },
    ]

    ranked, meta = rerank_hits_with_meta(
        hits,
        query="AAPL gross margin 46.8",
        checkpoint_path=str(ckpt),
    )

    assert ranked[0]["sample_id"] == "metric_1"
    assert ranked[0]["rerank_components"]["numeric_match"] > 0
    assert ranked[0]["rerank_components"]["source_authority"] >= 1.0
    assert meta["backend"] == "financial_heuristic"
    assert "numeric_match" in meta["score_components"]


def test_train_reranker_writes_feature_calibration_checkpoint(tmp_path: Path):
    dataset_path = tmp_path / "dataset.parquet"
    checkpoint_path = tmp_path / "reranker_checkpoint.json"
    import pandas as pd

    pd.DataFrame(
        [
            {
                "query": "AAPL gross margin 46.8",
                "doc_id": "pos",
                "doc_text": "AAPL financials gross margin 46.8.",
                "source_type": "financials",
                "source_url": "https://www.sec.gov/aapl",
                "trust_level": "high",
                "hard_negative": False,
                "score": 0.8,
                "label": 1,
            },
            {
                "query": "AAPL gross margin 46.8",
                "doc_id": "neg",
                "doc_text": "General commentary without precise margin.",
                "source_type": "news",
                "source_url": "https://example.com/news",
                "trust_level": "medium",
                "hard_negative": True,
                "score": 0.9,
                "label": 0,
            },
        ]
    ).to_parquet(dataset_path, index=False)

    out = train_reranker(dataset_path=str(dataset_path), checkpoint_path=str(checkpoint_path))
    payload = json.loads(Path(out).read_text(encoding="utf-8"))

    assert payload["model_name"] == "BAAI/bge-reranker-base"
    assert payload["training_mode"] == "feature_calibrated_heuristic"
    assert payload["feature_weights"]["query_overlap"] >= 0.9
    assert "numeric_match" in payload["feature_names"]


def test_reranker_uses_checkpoint_feature_weights(tmp_path: Path):
    ckpt = tmp_path / "reranker_checkpoint.json"
    ckpt.write_text(
        json.dumps(
            {
                "trained": True,
                "model_name": "missing-local-model",
                "feature_weights": {
                    "base_score": 0.1,
                    "query_overlap": 0.1,
                    "numeric_match": 5.0,
                    "source_authority": 0.1,
                    "freshness": 0.0,
                    "chunk_type": 0.0,
                },
            }
        ),
        encoding="utf-8",
    )
    hits = [
        {
            "sample_id": "base_heavy",
            "title": "AAPL general update",
            "content": "General revenue discussion.",
            "source_type": "news",
            "score": 10.0,
            "trust_level": "medium",
        },
        {
            "sample_id": "numeric_match",
            "title": "AAPL financial metric",
            "content": "AAPL gross_margin_pct = 46.8.",
            "source_type": "financials",
            "score": 0.1,
            "trust_level": "high",
        },
    ]

    ranked, meta = rerank_hits_with_meta(hits, query="AAPL gross margin 46.8", checkpoint_path=str(ckpt))

    assert ranked[0]["sample_id"] == "numeric_match"
    assert meta["feature_weights"]["numeric_match"] == 5.0


def test_transfer_scripts_argument_parsing(tmp_path: Path):
    if not _has_bash():
        return

    export_dir = tmp_path / "export"
    export_dir.mkdir(parents=True, exist_ok=True)
    (export_dir / "dataset.parquet").write_text("dummy", encoding="utf-8")
    remote_dir = tmp_path / "remote"
    ckpt_dir = tmp_path / "checkpoints"
    log_path = tmp_path / "transfer_debug.log"

    cmd_upload = [
        "bash",
        "scripts/upload_to_cloud.sh",
        "--remote-host",
        "127.0.0.1",
        "--remote-port",
        "2222",
        "--remote-user",
        "tester",
        "--remote-base-dir",
        str(remote_dir),
        "--local-export-dir",
        str(export_dir),
        "--local-checkpoint-dir",
        str(ckpt_dir),
        "--log-path",
        str(log_path),
        "--local-simulation",
        "--dry-run",
    ]
    subprocess.run(cmd_upload, check=True, cwd=REPO_ROOT)

    cmd_download = [
        "bash",
        "scripts/download_from_cloud.sh",
        "--remote-host",
        "127.0.0.1",
        "--remote-port",
        "2222",
        "--remote-user",
        "tester",
        "--remote-base-dir",
        str(remote_dir),
        "--local-export-dir",
        str(export_dir),
        "--local-checkpoint-dir",
        str(ckpt_dir),
        "--log-path",
        str(log_path),
        "--local-simulation",
        "--dry-run",
    ]
    subprocess.run(cmd_download, check=True, cwd=REPO_ROOT)

    content = log_path.read_text(encoding="utf-8")
    assert "remote_host=127.0.0.1" in content
    assert "remote_port=2222" in content
    assert "dry_run=1" in content
    assert "local_simulation=1" in content


def test_local_simulation_mode_end_to_end(tmp_path: Path):
    if not _has_bash():
        return

    retrieval_path = tmp_path / "retrieval_results.json"
    retrieval_payload = {
        "query": "revenue",
        "hits": [
            {
                "sample_id": "ev_1",
                "title": "Revenue update",
                "content": "Revenue increased",
                "score": 1.0,
                "trust_level": "high",
            }
        ],
    }
    retrieval_path.write_text(json.dumps(retrieval_payload, indent=2), encoding="utf-8")

    export_dir = tmp_path / "local_export"
    checkpoint_dir = tmp_path / "local_ckpt"
    output_path = tmp_path / "reranked_results.json"
    remote_base = tmp_path / "sim_remote"

    cloud_cfg = {
        "runtime": {"mode": "cloud_train", "dry_run": False},
        "cloud": {
            "device": "cpu",
            "gpu_memory_gb": 0,
            "offline_only": True,
            "local_simulation": True,
            "transfer": {
                "remote_host": "",
                "remote_port": 22,
                "remote_user": "",
                "remote_base_dir": str(remote_base),
                "local_export_dir": str(export_dir),
                "local_checkpoint_dir": str(checkpoint_dir),
                "log_path": str(tmp_path / "transfer_debug.log"),
            },
        },
    }
    cloud_cfg_path = tmp_path / "cloud_train.yaml"
    cloud_cfg_path.write_text(yaml.safe_dump(cloud_cfg, sort_keys=False), encoding="utf-8")

    reranker_cfg = {
        "reranker": {
            "enabled": True,
            "model_name": "reranker-test",
            "topk": 10,
            "batch_size": 4,
            "checkpoint_path": str(checkpoint_dir / "reranker_checkpoint.json"),
            "training": {"dataset_path": str(export_dir / "dataset.parquet")},
            "inference": {
                "input_path": str(retrieval_path),
                "output_path": str(output_path),
                "mode": "reranker",
            },
        }
    }
    reranker_cfg_path = tmp_path / "reranker.yaml"
    reranker_cfg_path.write_text(yaml.safe_dump(reranker_cfg, sort_keys=False), encoding="utf-8")

    cmd = [
        "bash",
        "scripts/run_stage11c_reranker_cloud_validation.sh",
        "--cloud-config",
        str(cloud_cfg_path),
        "--reranker-config",
        str(reranker_cfg_path),
        "--remote-base-dir",
        str(remote_base),
        "--local-export-dir",
        str(export_dir),
        "--local-checkpoint-dir",
        str(checkpoint_dir),
        "--local-simulation",
    ]
    env = os.environ.copy()
    env["LOCAL_SIMULATION"] = "1"
    subprocess.run(cmd, check=True, cwd=REPO_ROOT, env=env)

    assert (checkpoint_dir / "reranker_checkpoint.json").exists()
    assert output_path.exists()
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload.get("hits")
