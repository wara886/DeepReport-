"""Copy key retrieval artifacts from existing runs to market_simulation dirs,
and produce a structured analysis of each market's data profile.

Run from repo root: python -m scripts.archive_market_data
"""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import sys
from collections import Counter

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

BASE = Path("data/market_simulation")

# Latest completed runs for each market
MARKET_RUNS = {
    "A_SHARE": Path("data/outputs_user/runs/20260601_160636_600519.ss_fy2025_collaborative/outputs"),
    "HK": Path("data/outputs_user/runs/20260601_131000_0700.hk_fy2025_collaborative/outputs"),
    "US": Path("data/outputs_user/runs/20260601_175312_tsla_fy2025_collaborative/outputs"),
}

KEY_ARTIFACTS = [
    "evidence.json",
    "claims.json",
    "financial_metrics.json",
    "search_meta.json",
    "citations.json",
    "tables.json",
    "analysis_artifacts.json",
    "research_blackboard.json",
    "pdf_section_chunks.jsonl",
    "pdf_section_summaries.json",
    "pdf_extraction_audit.json",
    "pdf_manifest.json",
    "official_evidence_manifest.json",
    "evidence_coverage.json",
    "currency_audit.json",
    "section_dossiers.json",
    "mcp_manifest.json",
    "company_profile_extracted.json",
    "valuation_model.json",
]


def _safe_read_json(path: Path) -> dict | list | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data
    except Exception:
        return None


def _safe_read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def analyze_evidence(evidence_list: list[dict]) -> dict:
    """Analyze the evidence records for source_type distribution."""
    if not evidence_list:
        return {"count": 0, "source_types": {}, "content_length_range": "N/A"}

    src_types = Counter()
    for ev in evidence_list:
        st = str(ev.get("source_type", ev.get("engine", "unknown")))
        src_types[st] += 1

    lengths = [len(str(ev.get("content", ev.get("snippet", "")))) for ev in evidence_list if ev.get("content") or ev.get("snippet")]
    return {
        "count": len(evidence_list),
        "source_types": dict(src_types.most_common()),
        "content_length_avg": round(sum(lengths) / len(lengths), 1) if lengths else 0,
        "content_length_max": max(lengths) if lengths else 0,
        "content_length_min": min(lengths) if lengths else 0,
    }


def analyze_claims(claims_list: list[dict]) -> dict:
    if not claims_list:
        return {"count": 0, "sections": {}}
    sections = Counter()
    for c in claims_list:
        sec = str(c.get("target_section", c.get("section", "unknown")))
        sections[sec] += 1
    return {
        "count": len(claims_list),
        "sections": dict(sections.most_common()),
    }


def analyze_search_meta(search_meta: dict) -> dict:
    engines = search_meta.get("engines", {}) if isinstance(search_meta, dict) else {}
    return {
        "engine_count": len(engines),
        "engines_used": list(engines.keys()) if isinstance(engines, dict) else [],
        "engines": engines if isinstance(engines, dict) else {},
    }


def analyze_pdf_artifacts(market_dir: Path) -> dict:
    """Check PDF-related artifacts to see if PDF pipeline was active."""
    result = {"has_pdf_chunks": False, "has_pdf_summaries": False, "pdf_chunk_count": 0}
    chunks_file = market_dir / "pdf_section_chunks.jsonl"
    summaries_file = market_dir / "pdf_section_summaries.json"

    if chunks_file.exists():
        count = sum(1 for _ in chunks_file.open(encoding="utf-8") if _.strip())
        result["has_pdf_chunks"] = count > 0
        result["pdf_chunk_count"] = count

    if summaries_file.exists():
        summaries = _safe_read_json(summaries_file)
        if isinstance(summaries, dict) and summaries.get("sections"):
            result["has_pdf_summaries"] = True
            result["pdf_summary_sections"] = list(summaries["sections"].keys())

    return result


def archive_market_data() -> None:
    for market_name, run_output_dir in MARKET_RUNS.items():
        print(f"\n{'='*60}")
        print(f"Archiving {market_name} from {run_output_dir}")
        print(f"{'='*60}")

        market_dir = BASE / market_name
        market_dir.mkdir(parents=True, exist_ok=True)

        artifacts_info = {}

        # Copy key artifacts
        for artifact_name in KEY_ARTIFACTS:
            src = run_output_dir / artifact_name
            if not src.exists():
                artifacts_info[artifact_name] = "NOT_FOUND"
                continue
            dst = market_dir / artifact_name
            try:
                shutil.copy2(str(src), str(dst))
                size_kb = round(dst.stat().st_size / 1024, 1)
                artifacts_info[artifact_name] = f"copied ({size_kb}KB)"
            except Exception as e:
                artifacts_info[artifact_name] = f"COPY_ERROR: {e}"

        # Now analyze the data from the copies
        evidence = _safe_read_json(market_dir / "evidence.json") or []
        claims = _safe_read_json(market_dir / "claims.json") or []
        search_meta = _safe_read_json(market_dir / "search_meta.json") or {}
        financial_metrics = _safe_read_json(market_dir / "financial_metrics.json") or {}
        citations = _safe_read_json(market_dir / "citations.json") or []
        tables = _safe_read_json(market_dir / "tables.json") or []
        pdf_audit = _safe_read_json(market_dir / "pdf_extraction_audit.json") or {}
        official_manifest = _safe_read_json(market_dir / "official_evidence_manifest.json") or {}
        currency_audit = _safe_read_json(market_dir / "currency_audit.json") or {}

        ev_analysis = analyze_evidence(evidence)
        claim_analysis = analyze_claims(claims)
        search_analysis = analyze_search_meta(search_meta)
        pdf_analysis = analyze_pdf_artifacts(market_dir)

        # Financial metrics summary
        fin_metrics_list = financial_metrics.get("metrics", []) if isinstance(financial_metrics, dict) else []
        fin_count = len(fin_metrics_list)
        fin_sources = Counter()
        for m in fin_metrics_list:
            if isinstance(m, dict):
                fin_sources[str(m.get("source_type", "unknown"))] += 1

        # Build data profile
        profile = {
            "market": market_name,
            "evidence": ev_analysis,
            "claims": claim_analysis,
            "search": search_analysis,
            "financial_metrics": {
                "count": fin_count,
                "source_types": dict(fin_sources),
            },
            "citations": {"count": len(citations) if isinstance(citations, list) else 0},
            "tables": {"count": len(tables) if isinstance(tables, list) else 0},
            "pdf": pdf_analysis,
            "official_evidence": {
                "symbol": official_manifest.get("symbol", ""),
                "count": len(official_manifest.get("evidence_ids", [])) if isinstance(official_manifest, dict) else 0,
            },
            "currency_audit": currency_audit if isinstance(currency_audit, dict) else {},
            "artifacts": artifacts_info,
        }

        profile_path = market_dir / "01_data_profile.json"
        profile_path.write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nProfile written: {profile_path}")
        print(f"  Evidence: {ev_analysis['count']} records from {list(ev_analysis['source_types'].keys())[:5]}")
        print(f"  Claims:   {claim_analysis['count']} across {len(claim_analysis['sections'])} sections")
        print(f"  Financial: {fin_count} metrics from {list(fin_sources.keys())[:5]}")
        print(f"  PDF chunks: {pdf_analysis['pdf_chunk_count']}")
        print(f"  Search engines: {search_analysis['engines_used']}")

    # Write a cross-market comparison
    print(f"\n{'='*60}")
    print("Cross-market comparison")
    print(f"{'='*60}")
    for market_name in MARKET_RUNS:
        profile_path = BASE / market_name / "01_data_profile.json"
        if not profile_path.exists():
            continue
        profile = _safe_read_json(profile_path)
        if not profile:
            continue
        ev = profile.get("evidence", {})
        fm = profile.get("financial_metrics", {})
        pdf = profile.get("pdf", {})
        search = profile.get("search", {})

        print(f"\n{market_name}:")
        print(f"  Evidence:     {ev.get('count', 0):>4} items, avg {ev.get('content_length_avg', 0):.0f} chars")
        print(f"  Source types: {list(ev.get('source_types', {}).keys())[:6]}")
        print(f"  Financial:    {fm.get('count', 0):>4} metrics from {list(fm.get('source_types', {}).keys())[:4]}")
        print(f"  PDF chunks:   {pdf.get('pdf_chunk_count', 0):>4}")
        print(f"  Engines:      {search.get('engines_used', [])}")


if __name__ == "__main__":
    archive_market_data()
