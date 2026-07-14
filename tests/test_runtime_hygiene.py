from pathlib import Path

from scripts.runtime_hygiene import build_baseline, clean_ephemeral


def test_clean_ephemeral_is_dry_run_by_default(tmp_path):
    (tmp_path / "logs").mkdir()
    (tmp_path / "logs" / "app.log").write_text("log", encoding="utf-8")
    (tmp_path / "data" / "reports_user").mkdir(parents=True)
    report = tmp_path / "data" / "reports_user" / "report.md"
    report.write_text("keep", encoding="utf-8")

    targets = clean_ephemeral(tmp_path, apply=False)

    assert "logs" in targets
    assert (tmp_path / "logs" / "app.log").exists()
    assert report.exists()


def test_clean_ephemeral_never_removes_user_reports(tmp_path):
    (tmp_path / "tmp").mkdir()
    (tmp_path / "tmp" / "scratch.txt").write_text("delete", encoding="utf-8")
    (tmp_path / "data" / "reports_user").mkdir(parents=True)
    report = tmp_path / "data" / "reports_user" / "report.md"
    report.write_text("keep", encoding="utf-8")

    clean_ephemeral(tmp_path, apply=True)

    assert not (tmp_path / "tmp").exists()
    assert report.exists()


def test_baseline_does_not_include_secret_values(tmp_path, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "super-secret")
    (tmp_path / "configs").mkdir()
    (tmp_path / "configs" / "runtime.yaml").write_text("enabled: true\n", encoding="utf-8")
    _init_git_repo(tmp_path)

    baseline = build_baseline(tmp_path)

    assert baseline["credentials"]["DEEPSEEK_API_KEY"] is True
    assert "super-secret" not in str(baseline)


def _init_git_repo(path: Path) -> None:
    import subprocess

    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=path, check=True)
    subprocess.run(["git", "add", "."], cwd=path, check=True)
    subprocess.run(["git", "commit", "-qm", "fixture"], cwd=path, check=True)
