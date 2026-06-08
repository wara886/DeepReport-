"""Step 2: Analyze 15-run cross-market retrieval data.

Reads archived data from data/market_simulation_15/, produces:
1. cross_market_comparison.json - structured comparison across all 15 runs
2. Per-market text summaries

Run: python -m scripts.analyze_market_data_15
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
import sys
import re

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

BASE = Path("data/market_simulation_15")
MARKETS = ["A_SHARE", "HK", "US"]


def _read_json(path: Path) -> dict | list | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _mojibake_ratio(text: str) -> float:
    """Estimate mojibake ratio — count characters like +, .8853 etc that
    indicate GB2312 bytes decoded as Latin-1."""
    if not text or len(text) < 10:
        return 0.0
    mojibake_chars = len(re.findall(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', text))
    isolated_digits = len(re.findall(r'(?<![0-9a-zA-Z])[0-9]{2,}(?![0-9a-zA-Z])', text))
    # High density of non-CJK/non-ASCII printable suggests mojibake
    cjk = len(re.findall(r'[一-鿿㐀-䶿]', text))
    total_printable = sum(1 for c in text if c.isprintable() and not c.isspace())
    if total_printable < 10:
        return 0.0
    # If CJK ratio is very low (<5%) for Chinese text, it's likely mojibake
    return max(0.0, 1.0 - (cjk / max(total_printable, 1)))


# ── Analysis functions ─────────────────────────────────────────────────

def analyze_evidence(evidence_list: list[dict]) -> dict:
    """Comprehensive evidence analysis."""
    if not evidence_list:
        return {"count": 0, "source_types": {}, "content_stats": {}}

    src_types = Counter()
    content_lengths = []
    has_structured = {"has_evidence_id": 0, "has_symbol": 0, "has_period": 0, "has_metadata": 0}
    non_empty_content = 0

    for ev in evidence_list:
        st = str(ev.get("source_type", ev.get("engine", "unknown")))
        src_types[st] += 1
        c = str(ev.get("content", ev.get("snippet", "")))
        if c.strip():
            content_lengths.append(len(c))
            non_empty_content += 1
        if ev.get("evidence_id"):
            has_structured["has_evidence_id"] += 1
        if ev.get("symbol"):
            has_structured["has_symbol"] += 1
        if ev.get("period"):
            has_structured["has_period"] += 1
        if ev.get("metadata") or ev.get("key_points"):
            has_structured["has_metadata"] += 1

    content_lengths = content_lengths or [0]
    return {
        "count": len(evidence_list),
        "non_empty_content": non_empty_content,
        "source_type_distribution": dict(src_types.most_common()),
        "content_stats": {
            "avg_chars": round(sum(content_lengths) / len(content_lengths), 1),
            "max_chars": max(content_lengths),
            "min_chars": min(content_lengths),
            "median_chars": sorted(content_lengths)[len(content_lengths) // 2],
        },
        "structured_fields": has_structured,
    }


def analyze_financial_metrics(fm: dict | list | None) -> dict:
    if not fm:
        return {"count": 0, "source_types": {}}
    if isinstance(fm, dict):
        metrics_list = fm.get("metrics", [])
    else:
        metrics_list = fm
    if not isinstance(metrics_list, list):
        return {"count": 0}

    src_types = Counter()
    metric_names = set()
    for m in metrics_list:
        if isinstance(m, dict):
            src_types[str(m.get("source_type", "unknown"))] += 1
            if m.get("metric_name"):
                metric_names.add(m["metric_name"])

    return {
        "count": len(metrics_list),
        "distinct_metrics": len(metric_names),
        "source_types": dict(src_types.most_common()),
    }


def analyze_search_meta(sm: dict | None) -> dict:
    if not sm:
        return {"engines_used": [], "engine_count": 0, "all_engines": []}
    engines = sm.get("engines", {}) if isinstance(sm, dict) else {}
    if not isinstance(engines, dict):
        return {"engines_used": [], "engine_count": 0}
    used = []
    all_keys = list(engines.keys())
    for k, v in engines.items():
        if isinstance(v, dict):
            hits = v.get("hits") or v.get("meta", {}).get("hits")
            if hits:
                used.append(k)
        elif isinstance(v, list):
            if v:
                used.append(k)
    return {"engines_used": used, "engine_count": len(used), "all_engines": all_keys}


def analyze_pdf_chunks(chunks_path: Path) -> dict:
    if not chunks_path.exists() or chunks_path.stat().st_size == 0:
        return {"exists": False, "count": 0}

    try:
        lines = [l for l in chunks_path.read_text(encoding="utf-8").split("\n") if l.strip()]
        count = len(lines)
        if count == 0:
            return {"exists": True, "count": 0}
        chunks = [json.loads(l) for l in lines[:10]]  # sample first 10
        content_lengths = []
        mojibake_scores = []
        for c in chunks:
            txt = str(c.get("content", c.get("text", "")))
            content_lengths.append(len(txt))
            mojibake_scores.append(_mojibake_ratio(txt))

        return {
            "exists": True,
            "count": count,
            "sample_content_stats": {
                "avg_chars": round(sum(content_lengths) / len(content_lengths), 1) if content_lengths else 0,
                "max_chars": max(content_lengths) if content_lengths else 0,
            },
            "mojibake_analysis": {
                "avg_mojibake_ratio": round(sum(mojibake_scores) / len(mojibake_scores), 3) if mojibake_scores else 0,
                "has_mojibake": any(m > 0.3 for m in mojibake_scores),
            },
        }
    except Exception:
        return {"exists": True, "count": -1, "error": "parse_failed"}


def analyze_citations(citations_list: list | None) -> dict:
    if not citations_list:
        return {"count": 0}
    src_types = Counter()
    for c in citations_list:
        if isinstance(c, dict):
            st = str(c.get("source_type", c.get("source", "unknown")))
            src_types[st] += 1
    return {"count": len(citations_list), "source_types": dict(src_types.most_common())}


# ── Main ────────────────────────────────────────────────────────────────

def analyze_run(run_dir: Path, label: str) -> dict:
    evidence = _read_json(run_dir / "evidence.json") or []
    financial_metrics = _read_json(run_dir / "financial_metrics.json")
    search_meta = _read_json(run_dir / "search_meta.json")
    citations = _read_json(run_dir / "citations.json")
    tables = _read_json(run_dir / "tables.json")

    return {
        "label": label,
        "evidence": analyze_evidence(evidence),
        "financial_metrics": analyze_financial_metrics(financial_metrics),
        "search": analyze_search_meta(search_meta),
        "citations": analyze_citations(citations),
        "tables": {"count": len(tables) if isinstance(tables, list) else 0},
        "pdf_chunks": analyze_pdf_chunks(run_dir / "pdf_section_chunks.jsonl"),
        "has_pdf_summaries": (run_dir / "pdf_section_summaries.json").exists() and (run_dir / "pdf_section_summaries.json").stat().st_size > 10,
        "has_currency_audit": (run_dir / "currency_audit.json").exists(),
        "has_official_evidence": (run_dir / "official_evidence_manifest.json").exists(),
    }


def print_run_summary(label: str, r: dict) -> None:
    ev = r["evidence"]
    fm = r["financial_metrics"]
    pdf = r["pdf_chunks"]
    src_types = list(ev.get("source_type_distribution", {}).keys())
    print(f"  [{label}]")
    print(f"    Evidence: {ev['count']} items | types: {src_types[:4]}")
    print(f"    Content:  avg {ev.get('content_stats', {}).get('avg_chars', 0):.0f} chars {ev.get('content_stats', {}).get('min_chars', 0)}-{ev.get('content_stats', {}).get('max_chars', 0)}")
    print(f"    Fin.met:  {fm['count']} from {list(fm.get('source_types', {}).keys())[:3]}")
    if pdf["exists"]:
        mb = pdf.get("mojibake_analysis", {})
        print(f"    PDF:      {pdf['count']} chunks | mojibake_ratio={mb.get('avg_mojibake_ratio', 'N/A')}")
    print(f"    Search:   {r['search']['engine_count']} engines used ({r['search']['engines_used']})")
    print(f"    Citations: {r['citations']['count']}")
    print()


if __name__ == "__main__":
    all_results = []

    for market in MARKETS:
        market_dir = BASE / market
        if not market_dir.exists():
            continue

        run_dirs = sorted(market_dir.iterdir()) if market_dir.is_dir() else []
        print(f"\n{'='*60}")
        print(f" {market} — {len(run_dirs)} runs")
        print(f"{'='*60}")

        for rd in run_dirs:
            if not rd.is_dir():
                continue
            label = rd.name
            analysis = analyze_run(rd, label)
            all_results.append({"market": market, **analysis})
            print_run_summary(label, analysis)

    # Aggregate per market
    print(f"\n{'='*60}")
    print(" CROSS-MARKET AGGREGATE")
    print(f"{'='*60}")

    for market in MARKETS:
        market_results = [r for r in all_results if r["market"] == market]
        if not market_results:
            continue

        total_evidence = sum(r["evidence"]["count"] for r in market_results)
        total_fin = sum(r["financial_metrics"]["count"] for r in market_results)
        runs_with_pdf = sum(1 for r in market_results if r["pdf_chunks"]["exists"])
        all_src_types = Counter()
        content_lens = []
        for r in market_results:
            all_src_types.update(r["evidence"].get("source_type_distribution", {}))
            cs = r["evidence"].get("content_stats", {})
            if cs.get("avg_chars", 0) > 0:
                content_lens.append(cs["avg_chars"])
        avg_content = round(sum(content_lens) / len(content_lens), 1) if content_lens else 0

        print(f"\n{market} ({len(market_results)} runs):")
        print(f"  Avg evidence/run:   {total_evidence // len(market_results)}")
        print(f"  Avg financial/run:  {total_fin // len(market_results)}")
        print(f"  Runs with PDF:      {runs_with_pdf}/{len(market_results)}")
        print(f"  Avg content chars:  {avg_content}")
        print(f"  Source types:       {list(all_src_types.keys())}")

    # Save full comparison
    comp_path = BASE / "cross_market_comparison.json"
    comp_path.write_text(json.dumps(all_results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nFull comparison saved: {comp_path}")
