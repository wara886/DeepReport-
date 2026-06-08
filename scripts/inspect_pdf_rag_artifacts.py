"""Inspect PDF RAG v2 artifacts for a completed run.

Usage:
    python scripts/inspect_pdf_rag_artifacts.py
    python scripts/inspect_pdf_rag_artifacts.py --run-id 20260601_120000_600519.ss_fy2025_collaborative
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

OUTPUT_ROOTS = [
    Path("data/outputs_user"),
    Path("data/outputs_dev"),
    Path("data/outputs/multi_agent"),
]


def find_latest_run(symbol: str = "600519.SS") -> tuple[Path, str] | None:
    """Find the latest run directory for the given symbol."""
    candidates: list[tuple[Path, str, float]] = []
    for root in OUTPUT_ROOTS:
        runs_dir = root / "runs"
        if not runs_dir.exists():
            continue
        for run_dir in runs_dir.iterdir():
            name = run_dir.name.lower()
            sym = symbol.lower().replace(".", "")
            if sym not in name.replace(".", "").replace("_", ""):
                continue
            mtime = run_dir.stat().st_mtime
            candidates.append((run_dir, name, mtime))
    if not candidates:
        return None
    candidates.sort(key=lambda x: x[2], reverse=True)
    best = candidates[0]
    return (best[0] / "outputs", best[1])


def read_json(path: Path, default: Any = None) -> Any:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return default


def inspect_run(outputs_dir: Path, run_name: str) -> dict[str, Any]:
    """Inspect all PDF RAG artifacts in a run."""
    result: dict[str, Any] = {
        "run_name": run_name,
        "outputs_dir": str(outputs_dir),
    }

    # Check for PDF RAG v2 artifacts
    artifacts = {
        "pdf_section_chunks.jsonl": outputs_dir / "pdf_section_chunks.jsonl",
        "pdf_table_chunks.jsonl": outputs_dir / "pdf_table_chunks.jsonl",
        "pdf_extraction_audit.json": outputs_dir / "pdf_extraction_audit.json",
        "annual_report_sections.json": outputs_dir / "annual_report_sections.json",
        "pdf_sections.json": outputs_dir / "pdf_sections.json",
        "pdf_manifest.json": outputs_dir / "pdf_manifest.json",
        "request_state.json": outputs_dir / "request_state.json",
        "run_summary.json": outputs_dir / "run_summary.json",
    }

    present = {}
    for name, path in artifacts.items():
        present[name] = path.exists()
    result["artifacts_present"] = present

    # Read request state for symbol/period
    rs = read_json(outputs_dir / "request_state.json", {})
    result["symbol"] = rs.get("symbol", "?")
    result["period"] = rs.get("period", "?")

    # Inspect PDF extraction audit
    audit = read_json(outputs_dir / "pdf_extraction_audit.json", {})
    if audit:
        result["pdf_audit"] = {
            "source_url": audit.get("source_url", ""),
            "page_count": audit.get("page_count", 0),
            "pages_scanned": audit.get("pages_scanned", 0),
            "section_map_pages": audit.get("section_map", {}),
            "embedding_model": audit.get("embedding_model", "?"),
        }

    # Inspect section chunks
    chunks_path = outputs_dir / "pdf_section_chunks.jsonl"
    section_summary: dict[str, dict[str, Any]] = {}
    if chunks_path.exists():
        for line in chunks_path.read_text(encoding="utf-8").strip().split("\n"):
            if not line:
                continue
            try:
                chunk = json.loads(line)
            except Exception:
                continue
            st = chunk.get("section_type", "unknown")
            if st not in section_summary:
                section_summary[st] = {
                    "count": 0,
                    "usable_count": 0,
                    "noise_count": 0,
                    "top_chunks": [],
                    "evidence_quality": chunk.get("evidence_quality", "?"),
                    "usable_for_generation": chunk.get("usable_for_generation", False),
                }
            s = section_summary[st]
            s["count"] += 1
            if chunk.get("usable_for_generation"):
                s["usable_count"] += 1
            if chunk.get("is_noise"):
                s["noise_count"] += 1
            text = chunk.get("text_clean") or chunk.get("summary_zh") or ""
            if text and len(s["top_chunks"]) < 5:
                s["top_chunks"].append(text[:300])
    result["section_summary"] = section_summary

    # Inspect old-format pdf_sections
    pdf_sections = read_json(outputs_dir / "pdf_sections.json", [])
    if isinstance(pdf_sections, list) and pdf_sections:
        result["legacy_pdf_sections_count"] = len(pdf_sections)
        # Check for raw snippet leakage
        raw_count = sum(1 for s in pdf_sections if isinstance(s, dict) and len(str(s.get("snippet", ""))) > 100)
        result["legacy_raw_snippets"] = raw_count

    return result


def print_report(result: dict[str, Any]) -> None:
    """Print a formatted inspection report."""
    print(f"\n{'='*60}")
    print(f"PDF RAG Audit: {result.get('run_name', '?')}")
    print(f"Symbol: {result.get('symbol', '?')}  Period: {result.get('period', '?')}")
    print(f"{'='*60}")

    artifacts = result.get("artifacts_present", {})
    print("\n--- Artifacts ---")
    for name, present in sorted(artifacts.items()):
        status = "[OK]" if present else "[MISS]"
        print(f"  {status} {name}")

    audit = result.get("pdf_audit", {})
    if audit:
        print(f"\n--- PDF Audit ---")
        print(f"  source_url: {audit.get('source_url', '?')[:100]}")
        print(f"  pages: {audit.get('page_count', '?')} scanned={audit.get('pages_scanned', '?')}")
        print(f"  embedding: {audit.get('embedding_model', '?')}")
        sm = audit.get("section_map_pages", {})
        if sm:
            print(f"  section_map:")
            for k, v in sm.items():
                pages = v if isinstance(v, (list, tuple)) else [v]
                print(f"    {k}: pages {pages}")

    legacy = result.get("legacy_pdf_sections_count", 0)
    if legacy:
        print(f"\n--- Legacy PDF sections: {legacy} ({result.get('legacy_raw_snippets', 0)} raw) ---")

    section_summary = result.get("section_summary", {})
    if section_summary:
        print(f"\n--- Section Summary ---")
        for st, info in sorted(section_summary.items()):
            usable = info.get("usable_count", 0)
            total = info.get("count", 0)
            noise = info.get("noise_count", 0)
            quality = info.get("evidence_quality", "?")
            print(f"  [{st}] total={total} usable={usable} noise={noise} quality={quality}")
            for i, chunk_text in enumerate(info.get("top_chunks", [])):
                preview = chunk_text[:120].replace("\n", " ")
                print(f"    chunk {i+1}: {preview}...")
    else:
        print("\n  No PDF RAG v2 section chunks found.")

    print(f"\n{'='*60}\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect PDF RAG v2 artifacts")
    parser.add_argument("--run-id", type=str, default="", help="Specific run directory name")
    parser.add_argument("--symbol", type=str, default="600519.SS", help="Symbol to find latest run for")
    args = parser.parse_args()

    if args.run_id:
        for root in OUTPUT_ROOTS:
            outputs_dir = root / "runs" / args.run_id / "outputs"
            if outputs_dir.exists():
                result = inspect_run(outputs_dir, args.run_id)
                print_report(result)
                return
        print(f"[FAIL] Run not found: {args.run_id}")
        sys.exit(1)

    found = find_latest_run(args.symbol)
    if not found:
        print(f"[FAIL] No runs found for {args.symbol}")
        sys.exit(1)

    outputs_dir, run_name = found
    result = inspect_run(outputs_dir, run_name)
    print_report(result)


if __name__ == "__main__":
    main()
