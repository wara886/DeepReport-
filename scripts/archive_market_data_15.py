"""Step 1: Archive 15 runs of retrieval artifacts for cross-market analysis.

Copies key output files from 15 selected runs into
data/market_simulation_15/{A_SHARE, HK, US}/{label}/

Run: python -m scripts.archive_market_data_15
"""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

BASE = Path("data/market_simulation_15")
RUNS_ROOT_USER = Path("data/outputs_user/runs")
RUNS_ROOT_MULTI = Path("data/outputs/multi_agent/runs")

KEY_FILES = [
    "evidence.json",
    "financial_metrics.json",
    "search_meta.json",
    "analysis_artifacts.json",
    "citations.json",
    "tables.json",
    "currency_audit.json",
    "official_evidence_manifest.json",
    "pdf_section_chunks.jsonl",
    "pdf_section_summaries.json",
    "pdf_extraction_audit.json",
    "pdf_manifest.json",
    "claims.json",
    "company_profile_extracted.json",
    "valuation_model.json",
    "research_blackboard.json",
    "mcp_manifest.json",
    "run_summary.json",
]

# ── 15 selected runs ──────────────────────────────────────────────────

A_SHARE_RUNS = [
    ("run1_203938_no_pdf", RUNS_ROOT_USER / "20260531_203938_600519.ss_fy2025_collaborative" / "outputs"),
    ("run2_225928_with_pdf", RUNS_ROOT_USER / "20260531_225928_600519.ss_fy2025_collaborative" / "outputs"),
    ("run3_093638_fy2024", RUNS_ROOT_USER / "20260601_093638_600519.ss_fy2024_collaborative" / "outputs"),
    ("run4_205204_multi_q1", RUNS_ROOT_MULTI / "20260522_205204_600519.ss_2026q1_collaborative" / "outputs"),
    ("run5_124637_largest", RUNS_ROOT_MULTI / "20260528_124637_600519.ss_2026q1_collaborative" / "outputs"),
]

HK_RUNS = [
    ("run1_183403", RUNS_ROOT_USER / "20260531_183403_0700.hk_fy2025_collaborative" / "outputs"),
    ("run2_194511", RUNS_ROOT_USER / "20260531_194511_0700.hk_fy2025_collaborative" / "outputs"),
    ("run3_131000", RUNS_ROOT_USER / "20260601_131000_0700.hk_fy2025_collaborative" / "outputs"),
    ("run4_153004_multi", RUNS_ROOT_MULTI / "20260521_153004_0700.hk_2026q1_collaborative" / "outputs"),
    ("run5_112514_largest", RUNS_ROOT_MULTI / "20260530_112514_0700.hk_2026q1_collaborative" / "outputs"),
]

US_RUNS = [
    ("TSLA_175312", RUNS_ROOT_USER / "20260601_175312_tsla_fy2025_collaborative" / "outputs"),
    ("AAPL_110922", RUNS_ROOT_MULTI / "20260530_110922_aapl_fy2025_collaborative" / "outputs"),
    ("NVDA_130259", RUNS_ROOT_MULTI / "20260530_130259_nvda_fy2025_collaborative" / "outputs"),
    ("GOOGL_182726", RUNS_ROOT_USER / "20260531_182726_googl_fy2025_collaborative" / "outputs"),
    ("AMD_124745", RUNS_ROOT_MULTI / "20260530_124745_amd_2026q1_collaborative" / "outputs"),
]


def copy_artifacts(label: str, src_dir: Path, dst_dir: Path) -> dict:
    """Copy key artifact files from src_dir to dst_dir. Returns file manifest."""
    dst_dir.mkdir(parents=True, exist_ok=True)
    manifest = {}
    for fname in KEY_FILES:
        src = src_dir / fname
        dst = dst_dir / fname
        if src.exists():
            try:
                shutil.copy2(str(src), str(dst))
                size_kb = round(dst.stat().st_size / 1024, 1)
                manifest[fname] = f"OK {size_kb}KB"
            except Exception as e:
                manifest[fname] = f"ERR {e}"
        else:
            manifest[fname] = "MISSING"
    return manifest


def archive_market(name: str, runs: list[tuple[str, Path]]) -> None:
    print(f"\n{'='*60}")
    print(f"Archiving {name} — {len(runs)} runs")
    print(f"{'='*60}")

    for label, src_dir in runs:
        dst_dir = BASE / name / label
        if not src_dir.exists():
            print(f"  [SKIP] {label}: source not found {src_dir}")
            continue
        manifest = copy_artifacts(label, src_dir, dst_dir)
        ok = sum(1 for v in manifest.values() if v.startswith("OK"))
        total = len(manifest)
        print(f"  [{label}] {ok}/{total} files copied → {dst_dir}")
        # Write manifest
        (dst_dir / "_manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )


if __name__ == "__main__":
    BASE.mkdir(parents=True, exist_ok=True)
    archive_market("A_SHARE", A_SHARE_RUNS)
    archive_market("HK", HK_RUNS)
    archive_market("US", US_RUNS)
    print(f"\nDone. Files archived to {BASE}/")
