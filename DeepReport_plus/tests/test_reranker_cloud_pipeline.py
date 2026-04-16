import json
import os
import shutil
import subprocess
from pathlib import Path

import yaml

from src.training.infer_reranker import rerank_hits_with_meta

REPO_ROOT = Path(__file__).resolve().parent.parent


def _has_bash() -> bool:
    return shutil.which("bash") is not None


def test_fallback_without_checkpoint():
    hits = [{"sample_id": "s1", "score": 1.0, "trust_level": "high"}]
    ranked, meta = rerank_hits_with_meta(hits, checkpoint_path="data/outputs/checkpoints/not_exists.json")
    assert ranked[0]["rerank_score"] == 1.0
    assert meta["fallback_used"] is True
    assert meta["mode"] == "bm25"


def test_reranker_branch_with_checkpoint(tmp_path: Path):
    ckpt = tmp_path / "reranker_checkpoint.json"
    ckpt.write_text(json.dumps({"trained": True}), encoding="utf-8")
    hits = [{"sample_id": "s1", "score": 1.0, "trust_level": "high"}]
    ranked, meta = rerank_hits_with_meta(hits, checkpoint_path=str(ckpt))
    assert ranked[0]["rerank_score"] > 1.0
    assert meta["fallback_used"] is False
    assert meta["mode"] == "reranker"


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
