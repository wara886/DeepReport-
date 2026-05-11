"""Stage 12A evaluation harness: quality baseline and local optimization checks."""

from __future__ import annotations

import argparse
import json
import os
import re
import tempfile
import threading
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

import pandas as pd
import yaml

from src.app.pipeline import run_pipeline
from src.charts.render import attach_charts_to_report, render_all_charts
from src.data.fetch_company_profile import CompanyProfileFetcher
from src.data.fetch_filings import FilingsFetcher
from src.data.fetch_financials import FinancialsFetcher
from src.data.fetch_market import MarketFetcher
from src.data.fetch_news import NewsFetcher
from src.data.manifest import build_manifest, write_manifest_json, write_manifest_parquet
from src.evaluation.eval_v1 import load_eval_cases
from src.evaluation.numeric_audit import run_numeric_audit_for_case, summarize_numeric_audit
from src.features.financial_ratios import build_financial_ratios, save_financial_ratios
from src.features.peer_compare import build_peer_compare, save_peer_compare
from src.features.risk_signals import build_risk_signals, save_risk_signals
from src.features.trend_analysis import build_trend_features, save_trend_features
from src.templates.exporter import export_reports
from src.tracing.writer_trace import WriterTraceEvent, aggregate_writer_trace, append_writer_trace, export_writer_trace_csv
from src.training.infer_verifier import verify_claims
from src.utils.config import load_config


@dataclass
class EvalSample:
    case_id: str
    symbol: str
    period: str
    query: str = ""
    task_type: str = "unknown"
    allow_fallback: bool = False


@dataclass
class RemoteSimContext:
    config_path: str
    started: bool
    server: HTTPServer | None
    thread: threading.Thread | None
    temp_file: Path | None


_NUMERIC_PATTERNS = {
    "revenue_growth_pct": re.compile(r"revenue\s*growth\s*([0-9]+(?:\.[0-9]+)?)", flags=re.IGNORECASE),
    "net_margin_pct": re.compile(r"net\s*margin\s*([0-9]+(?:\.[0-9]+)?)", flags=re.IGNORECASE),
    "roe_pct": re.compile(r"roe[^0-9]*([0-9]+(?:\.[0-9]+)?)", flags=re.IGNORECASE),
    "roa_pct": re.compile(r"roa[^0-9]*([0-9]+(?:\.[0-9]+)?)", flags=re.IGNORECASE),
    "operating_cash_flow_billion": re.compile(
        r"operating\s*cash\s*flow\s*([0-9]+(?:\.[0-9]+)?)",
        flags=re.IGNORECASE,
    ),
}


def _read_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def _discover_samples(raw_root: Path, configured: List[Dict[str, str]], max_samples: int) -> List[EvalSample]:
    if configured:
        samples = [
            EvalSample(
                case_id=str(item.get("case_id", "")).strip()
                or f"{str(item.get('symbol', '')).strip()}:{str(item.get('period', '')).strip()}",
                symbol=str(item.get("symbol", "")).strip(),
                period=str(item.get("period", "")).strip(),
                query=str(item.get("query", "")).strip(),
                task_type=str(item.get("task_type", "unknown")).strip() or "unknown",
                allow_fallback=bool(item.get("allow_fallback", False)),
            )
            for item in configured
        ]
        return [s for s in samples if s.case_id and s.symbol and s.period][:max_samples]

    discovered: List[EvalSample] = []
    if not raw_root.exists():
        return discovered

    for symbol_dir in sorted([p for p in raw_root.iterdir() if p.is_dir()]):
        for period_dir in sorted([p for p in symbol_dir.iterdir() if p.is_dir()]):
            discovered.append(
                EvalSample(
                    case_id=f"{symbol_dir.name}:{period_dir.name}",
                    symbol=symbol_dir.name,
                    period=period_dir.name,
                )
            )
            if len(discovered) >= max_samples:
                return discovered
    return discovered


def _samples_from_eval_v1(eval_case_path: Path, max_samples: int) -> List[EvalSample]:
    if not eval_case_path.exists():
        return []
    cases = load_eval_cases(eval_case_path)
    samples: List[EvalSample] = []
    for case in cases[:max_samples]:
        samples.append(
            EvalSample(
                case_id=case.case_id,
                symbol=case.symbol,
                period=case.period,
                query=case.query,
                task_type=case.task_type,
                allow_fallback=case.allow_fallback,
            )
        )
    return samples


def _build_fetchers(sample: EvalSample, raw_root: Path, source_cfg: Dict[str, Dict[str, str]]):
    base = raw_root / sample.symbol / sample.period
    return [
        CompanyProfileFetcher(
            mode="local_file_real",
            real_data_root=str(raw_root),
            symbol=sample.symbol,
            period=sample.period,
            real_file_path=str(base / source_cfg["company_profile"]["filename"]),
        ),
        FinancialsFetcher(
            mode="local_file_real",
            real_data_root=str(raw_root),
            symbol=sample.symbol,
            period=sample.period,
            real_file_path=str(base / source_cfg["financials"]["filename"]),
        ),
        MarketFetcher(
            mode="local_file_real",
            real_data_root=str(raw_root),
            symbol=sample.symbol,
            period=sample.period,
            real_file_path=str(base / source_cfg["market"]["filename"]),
        ),
        NewsFetcher(
            mode="local_file_real",
            real_data_root=str(raw_root),
            symbol=sample.symbol,
            period=sample.period,
            real_file_path=str(base / source_cfg["news"]["filename"]),
        ),
        FilingsFetcher(
            mode="local_file_real",
            real_data_root=str(raw_root),
            symbol=sample.symbol,
            period=sample.period,
            real_file_path=str(base / source_cfg["filings"]["filename"]),
        ),
    ]


def _concat_parquet(folder: Path, exclude_names: Iterable[str] = ()) -> pd.DataFrame:
    paths = [p for p in sorted(folder.glob("*.parquet")) if p.name not in set(exclude_names)]
    if not paths:
        return pd.DataFrame()
    return pd.concat([pd.read_parquet(p) for p in paths], ignore_index=True)


def _prepare_data_and_features(
    sample: EvalSample,
    variant_id: str,
    raw_root: Path,
    source_cfg: Dict[str, Dict[str, str]],
    run_root: Path,
) -> Dict[str, Path]:
    curated_root = run_root / sample.symbol / sample.period / variant_id / "curated"
    features_root = run_root / sample.symbol / sample.period / variant_id / "features"
    outputs_root = run_root / sample.symbol / sample.period / variant_id / "outputs"
    reports_root = run_root / sample.symbol / sample.period / variant_id / "reports"
    curated_root.mkdir(parents=True, exist_ok=True)
    features_root.mkdir(parents=True, exist_ok=True)
    outputs_root.mkdir(parents=True, exist_ok=True)
    reports_root.mkdir(parents=True, exist_ok=True)

    manifest_rows: List[Dict[str, object]] = []
    for fetcher in _build_fetchers(sample, raw_root=raw_root, source_cfg=source_cfg):
        rows = fetcher.fetch()
        normalized = build_manifest(rows, source_type=fetcher.source_type, strict_required=True)
        write_manifest_parquet(normalized, curated_root / f"{fetcher.source_type}.parquet")
        manifest_rows.extend(normalized)

    write_manifest_parquet(manifest_rows, curated_root / "real_data_manifest.parquet")
    write_manifest_json(manifest_rows, curated_root / "real_data_manifest.json")

    manifest_df = _concat_parquet(curated_root, exclude_names=["real_data_manifest.parquet"])
    ratio_df = build_financial_ratios(manifest_df)
    trend_df = build_trend_features(manifest_df)
    peer_df = build_peer_compare(manifest_df)
    risk_df = build_risk_signals(manifest_df)

    save_financial_ratios(ratio_df, features_root / "financial_ratios.parquet")
    save_trend_features(trend_df, features_root / "trend_analysis.parquet")
    save_peer_compare(peer_df, features_root / "peer_compare.parquet")
    save_risk_signals(risk_df, features_root / "risk_signals.parquet")
    (features_root / "feature_report_real.json").write_text(
        json.dumps(
            {
                "input_rows": int(len(manifest_df)),
                "outputs": {
                    "financial_ratios_rows": int(len(ratio_df)),
                    "trend_analysis_rows": int(len(trend_df)),
                    "peer_compare_rows": int(len(peer_df)),
                    "risk_signals_rows": int(len(risk_df)),
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    return {
        "curated_root": curated_root,
        "features_root": features_root,
        "outputs_root": outputs_root,
        "reports_root": reports_root,
    }


def _metric_structure_completeness(report_md: str, required_headers: List[str]) -> float:
    if not required_headers:
        return 1.0
    hit = sum(1 for header in required_headers if header in report_md)
    return float(hit) / float(len(required_headers))


def _metric_numeric_consistency(claims: List[Dict[str, object]]) -> float:
    total = 0
    matched = 0
    for claim in claims:
        text = str(claim.get("claim_text", ""))
        numeric_values = claim.get("numeric_values") or {}
        if not isinstance(numeric_values, dict):
            continue
        for value in numeric_values.values():
            try:
                num = float(value)
            except (TypeError, ValueError):
                continue
            total += 1
            candidates = {f"{num:.0f}", f"{num:.1f}", f"{num:.2f}", str(value)}
            if any(c in text for c in candidates):
                matched += 1
    return (float(matched) / float(total)) if total > 0 else 1.0


def _metric_evidence_alignment(claims: List[Dict[str, object]], manifest_ids: set[str]) -> Tuple[float, float]:
    all_ids = 0
    aligned = 0
    claim_with_evidence = 0
    for claim in claims:
        evidence_ids = claim.get("evidence_ids") or []
        if not isinstance(evidence_ids, list) or not evidence_ids:
            continue
        claim_with_evidence += 1
        for eid in evidence_ids:
            all_ids += 1
            if str(eid) in manifest_ids:
                aligned += 1
    id_alignment = (float(aligned) / float(all_ids)) if all_ids > 0 else 1.0
    coverage = (float(claim_with_evidence) / float(len(claims))) if claims else 0.0
    return id_alignment, coverage


def _read_manifest_ids(manifest_path: Path) -> set[str]:
    if not manifest_path.exists():
        return set()
    df = pd.read_parquet(manifest_path)
    if "sample_id" not in df.columns:
        return set()
    return {str(v) for v in df["sample_id"].dropna().tolist()}


class _MockRemoteHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length).decode("utf-8"))
        plan = payload.get("plan", [])
        claims = payload.get("claims", [])

        by_section: Dict[str, List[Dict[str, object]]] = {}
        for item in claims:
            section = str(item.get("section_name", "")).strip()
            by_section.setdefault(section, []).append(item)

        lines = ["# Company Research Report", "", "Generated by backend: remote-sim", ""]
        for section in plan:
            title = str(section.get("section_title", "Section")).strip()
            name = str(section.get("section_name", "")).strip()
            lines.append(f"## {title}")
            lines.append("")
            rows = by_section.get(name, [])
            if not rows:
                lines.append("- No claims generated for this section in current sample.")
                lines.append("")
                continue
            for claim in rows:
                lines.append(f"- {claim.get('claim_text', '')}")
                eids = claim.get("evidence_ids", [])
                if isinstance(eids, list) and eids:
                    lines.append(f"  - evidence_ids: {', '.join(str(x) for x in eids)}")
                lines.append(f"  - confidence: {float(claim.get('confidence', 0.0)):.2f}")
            lines.append("")

        body = json.dumps({"text": "\n".join(lines)}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        del fmt, args


def _build_remote_sim_config(backend_config_path: Path, host: str, port: int, model_name: str) -> Path:
    payload = yaml.safe_load(backend_config_path.read_text(encoding="utf-8")) or {}
    writer_backend = dict(payload.get("writer_backend", {}))
    backends = dict(writer_backend.get("backends", {}))
    remote = dict(backends.get("remote", {}))
    remote["base_url"] = f"http://{host}:{port}/generate"
    remote["model_name"] = model_name
    remote["base_url_env"] = ""
    remote["api_key_env"] = ""
    remote["model_name_env"] = ""
    backends["remote"] = remote
    writer_backend["backends"] = backends
    payload["writer_backend"] = writer_backend

    fd, path = tempfile.mkstemp(prefix="stage12a_backend_", suffix=".yaml")
    os.close(fd)
    out_path = Path(path)
    out_path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return out_path


def _start_remote_sim_if_needed(variant: Dict[str, str], writer_cfg: Dict[str, object]) -> RemoteSimContext:
    backend_config_path = Path(str(writer_cfg.get("backend_config_path", "configs/model_backends.yaml")))
    if str(variant.get("writer_backend", "")) != "remote":
        return RemoteSimContext(str(backend_config_path), False, None, None, None)

    sim_cfg = dict(writer_cfg.get("local_remote_simulation", {}))
    if not bool(sim_cfg.get("enabled", False)):
        return RemoteSimContext(str(backend_config_path), False, None, None, None)

    host = str(sim_cfg.get("host", "127.0.0.1"))
    port = int(sim_cfg.get("port", 18081))
    model_name = str(sim_cfg.get("model_name", "stage12a-remote-sim"))
    server = HTTPServer((host, port), _MockRemoteHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    temp_path = _build_remote_sim_config(backend_config_path=backend_config_path, host=host, port=port, model_name=model_name)
    return RemoteSimContext(str(temp_path), True, server, thread, temp_path)


def _stop_remote_sim(ctx: RemoteSimContext) -> None:
    if ctx.server:
        ctx.server.shutdown()
        ctx.server.server_close()
    if ctx.thread:
        ctx.thread.join(timeout=1)
    if ctx.temp_file and ctx.temp_file.exists():
        ctx.temp_file.unlink(missing_ok=True)


def _run_variant(sample: EvalSample, variant: Dict[str, str], paths: Dict[str, Path], eval_cfg: Dict[str, object]) -> Dict[str, object]:
    retrieval_cfg = dict(eval_cfg.get("retrieval", {}))
    writer_cfg = dict(eval_cfg.get("writer", {}))
    verifier_cfg = dict(eval_cfg.get("verifier", {}))

    sim_ctx = _start_remote_sim_if_needed(variant=variant, writer_cfg=writer_cfg)
    try:
        retrieval_query = sample.query or str(retrieval_cfg.get("query", "revenue margin risk"))
        pipeline_result = run_pipeline(
            output_dir=str(paths["outputs_root"]),
            report_dir=str(paths["reports_root"]),
            features_root=str(paths["features_root"]),
            writer_mode=str(variant.get("writer_mode", "template_only")),
            writer_backend=str(variant.get("writer_backend", "mock")),
            writer_backend_config_path=str(sim_ctx.config_path),
            writer_debug_path=str(paths["reports_root"] / "writer_debug.json"),
            retrieval_query=retrieval_query,
            retrieval_topk=int(retrieval_cfg.get("topk", 5)),
            retrieval_curated_dir=str(paths["curated_root"]),
            retrieval_ranking_mode=str(variant.get("ranking_mode", "bm25")),
            reranker_checkpoint_path=str(retrieval_cfg.get("reranker_checkpoint_path", "data/outputs/checkpoints/reranker_checkpoint.json")),
            verifier_checkpoint_path=str(verifier_cfg.get("checkpoint_path", "data/outputs/checkpoints/verifier_checkpoint.json")),
        )
    finally:
        _stop_remote_sim(sim_ctx)

    chart_meta = render_all_charts(
        features_root=str(paths["features_root"]),
        chart_output_dir=str(paths["outputs_root"] / "charts"),
        metadata_path=str(paths["outputs_root"] / "chart_metadata.json"),
    )
    attach_charts_to_report(paths["reports_root"] / "report.md", chart_meta)
    export_reports(
        claim_path=Path(pipeline_result["claim_table"]),
        chart_meta_path=paths["outputs_root"] / "chart_metadata.json",
        report_dir=paths["reports_root"],
    )

    claims = list(_read_json(Path(pipeline_result["claim_table"])))
    report_md = Path(paths["reports_root"] / "report.md").read_text(encoding="utf-8")
    rule_report = dict(_read_json(Path(pipeline_result["verification_report"])))
    verifier_current = verify_claims(
        claims=claims,
        checkpoint_path=str(verifier_cfg.get("checkpoint_path", "data/outputs/checkpoints/verifier_checkpoint.json")),
    )
    writer_debug: Dict[str, object] = {}
    debug_path = paths["reports_root"] / "writer_debug.json"
    if debug_path.exists():
        writer_debug = dict(_read_json(debug_path))

    retrieval_meta = {}
    retrieval_hits: List[Dict[str, object]] = []
    retrieval_used = paths["outputs_root"] / "retrieval_results_used.json"
    if retrieval_used.exists():
        retrieval_payload = dict(_read_json(retrieval_used))
        retrieval_meta = dict(retrieval_payload.get("meta", {}))
        retrieval_hits = list(retrieval_payload.get("hits", []))

    manifest_ids = _read_manifest_ids(paths["curated_root"] / "real_data_manifest.parquet")
    structure = _metric_structure_completeness(report_md, list(eval_cfg.get("required_headers", [])))
    numeric = _metric_numeric_consistency(claims)
    evidence_alignment, evidence_coverage = _metric_evidence_alignment(claims, manifest_ids)
    verifier_current_pass_ratio = float(verifier_current["passed_count"]) / max(
        1, int(verifier_current["passed_count"]) + int(verifier_current["failed_count"])
    )

    return {
        "case_id": sample.case_id,
        "sample_id": f"{sample.symbol}:{sample.period}",
        "symbol": sample.symbol,
        "period": sample.period,
        "query": retrieval_query,
        "task_type": sample.task_type,
        "variant_id": str(variant.get("id", "unknown")),
        "writer_mode": str(variant.get("writer_mode", "")),
        "writer_backend": str(variant.get("writer_backend", "")),
        "ranking_mode": str(variant.get("ranking_mode", "bm25")),
        "structure_completeness": round(structure, 4),
        "numeric_consistency": round(numeric, 4),
        "evidence_alignment": round(evidence_alignment, 4),
        "evidence_coverage": round(evidence_coverage, 4),
        "claim_count": len(claims),
        "report_char_count": len(report_md),
        "rule_verifier_passed": bool(rule_report.get("passed", False)),
        "rule_verifier_error_count": int(rule_report.get("error_count", 0)),
        "current_verifier_pass_ratio": round(verifier_current_pass_ratio, 4),
        "current_verifier_checkpoint_used": bool(verifier_current.get("checkpoint_used", False)),
        "writer_fallback_triggered": bool(writer_debug.get("fallback_triggered", False)),
        "writer_backend_mode": str(writer_debug.get("backend_mode", "")),
        "writer_error_message": str(writer_debug.get("error_message", "")),
        "retrieval_mode_resolved": str(retrieval_meta.get("mode", "")),
        "retrieval_fallback_used": bool(retrieval_meta.get("fallback_used", False)),
        "retrieved_doc_count": len(retrieval_hits),
        "reranked_topk_ids": [str(item.get("sample_id", "")) for item in retrieval_hits if str(item.get("sample_id", "")).strip()],
        "reranked_topk_source_types": [
            str(item.get("source_type", "")) for item in retrieval_hits if str(item.get("source_type", "")).strip()
        ],
        "artifacts": {
            "curated_root": str(paths["curated_root"]),
            "features_root": str(paths["features_root"]),
            "claim_table": str(paths["outputs_root"] / "claim_table.json"),
            "verification_report": str(paths["outputs_root"] / "verification_report.json"),
            "chart_metadata": str(paths["outputs_root"] / "chart_metadata.json"),
            "report_md": str(paths["reports_root"] / "report.md"),
            "report_html": str(paths["reports_root"] / "report.html"),
            "report_json": str(paths["reports_root"] / "report.json"),
        },
    }


def _mean(key: str, rows: List[Dict[str, object]]) -> float:
    if not rows:
        return 0.0
    return round(sum(float(r.get(key, 0.0)) for r in rows) / float(len(rows)), 4)


def _classify_writer_fallback_reason(error_message: str) -> str:
    msg = (error_message or "").lower()
    if not msg:
        return "none"
    if "non-empty base_url" in msg or "base_url" in msg:
        return "missing_config"
    if "timeout" in msg:
        return "timeout_retry"
    if "unable to extract text" in msg:
        return "response_format_incompatible"
    if "empty content" in msg or "empty text" in msg:
        return "empty_output"
    if "http" in msg or "urlopen" in msg:
        return "http_or_network_error"
    if "json" in msg:
        return "structured_parse_failure"
    return "other"


def _extract_metric_from_text(text: str, metric_key: str) -> float | None:
    pattern = _NUMERIC_PATTERNS.get(metric_key)
    if not pattern:
        return None
    match = pattern.search(text or "")
    return float(match.group(1)) if match else None


def _is_exact_match(expected: float, observed: float) -> bool:
    return abs(expected - observed) <= 1e-9


def _is_tolerance_match(expected: float, observed: float, abs_tol: float, rel_tol: float) -> bool:
    diff = abs(expected - observed)
    if diff <= abs_tol:
        return True
    base = max(abs(expected), 1e-9)
    return (diff / base) <= rel_tol


def _metric_status(expected: float | None, observed: float | None, abs_tol: float, rel_tol: float) -> str:
    if expected is None:
        return "missing_coverage"
    if observed is None:
        return "missing_coverage"
    if _is_exact_match(expected, observed):
        return "exact_match"
    if _is_tolerance_match(expected, observed, abs_tol=abs_tol, rel_tol=rel_tol):
        return "tolerance_match"
    return "mismatch"


def _read_claim_metric_value(report_json_path: Path, metric_key: str) -> float | None:
    payload = dict(_read_json(report_json_path))
    claims = list(payload.get("claims", []))
    for claim in claims:
        numeric_values = claim.get("numeric_values") or {}
        if isinstance(numeric_values, dict) and metric_key in numeric_values:
            try:
                return float(numeric_values[metric_key])
            except (TypeError, ValueError):
                continue
    return None


def _read_expected_feature_value(features_root: Path, symbol: str, period: str, metric_key: str) -> float | None:
    path = features_root / "financial_ratios.parquet"
    if not path.exists():
        return None
    df = pd.read_parquet(path)
    rows = df[(df["symbol"].astype(str) == symbol) & (df["period"].astype(str) == period)]
    if rows.empty or metric_key not in rows.columns:
        return None
    series = rows[metric_key].dropna()
    if series.empty:
        return None
    return float(series.iloc[0])


def _read_curated_metric_value(curated_root: Path, metric_key: str) -> float | None:
    path = curated_root / "financials.parquet"
    if not path.exists():
        return None
    df = pd.read_parquet(path)
    if df.empty:
        return None
    return _extract_metric_from_text(str(df.iloc[0].get("content", "")), metric_key)


def _has_chart_coverage(chart_meta_path: Path, metric_key: str) -> bool:
    if not chart_meta_path.exists():
        return False
    meta = list(_read_json(chart_meta_path))
    for row in meta:
        if metric_key in str(row.get("source_fields", "")):
            return True
    return False


def _aggregate(metrics_rows: List[Dict[str, object]], output_root: Path) -> Dict[str, object]:
    by_variant: Dict[str, List[Dict[str, object]]] = {}
    for row in metrics_rows:
        by_variant.setdefault(str(row["variant_id"]), []).append(row)

    variant_summary: Dict[str, Dict[str, object]] = {}
    for variant, rows in by_variant.items():
        variant_summary[variant] = {
            "count": len(rows),
            "structure_completeness_mean": _mean("structure_completeness", rows),
            "numeric_consistency_mean": _mean("numeric_consistency", rows),
            "evidence_alignment_mean": _mean("evidence_alignment", rows),
            "evidence_coverage_mean": _mean("evidence_coverage", rows),
            "current_verifier_pass_ratio_mean": _mean("current_verifier_pass_ratio", rows),
            "rule_verifier_pass_rate": _mean("rule_verifier_passed", rows),
            "writer_fallback_rate": _mean("writer_fallback_triggered", rows),
            "retrieval_fallback_rate": _mean("retrieval_fallback_used", rows),
        }

    comparison = {
        "bm25_vs_reranker": {},
        "template_only_vs_real_writer": {},
        "rule_verifier_vs_current_verifier": {},
    }
    if "bm25_template" in variant_summary and "reranker_template" in variant_summary:
        comparison["bm25_vs_reranker"] = {
            "bm25_structure": variant_summary["bm25_template"]["structure_completeness_mean"],
            "reranker_structure": variant_summary["reranker_template"]["structure_completeness_mean"],
            "bm25_evidence_alignment": variant_summary["bm25_template"]["evidence_alignment_mean"],
            "reranker_evidence_alignment": variant_summary["reranker_template"]["evidence_alignment_mean"],
        }
    if "bm25_template" in variant_summary and "bm25_real_writer" in variant_summary:
        comparison["template_only_vs_real_writer"] = {
            "template_structure": variant_summary["bm25_template"]["structure_completeness_mean"],
            "real_writer_structure": variant_summary["bm25_real_writer"]["structure_completeness_mean"],
            "template_writer_fallback_rate": variant_summary["bm25_template"]["writer_fallback_rate"],
            "real_writer_fallback_rate": variant_summary["bm25_real_writer"]["writer_fallback_rate"],
        }
    if metrics_rows:
        comparison["rule_verifier_vs_current_verifier"] = {
            "rule_verifier_pass_rate_global": round(
                sum(1.0 if bool(r.get("rule_verifier_passed", False)) else 0.0 for r in metrics_rows) / float(len(metrics_rows)),
                4,
            ),
            "current_verifier_pass_ratio_global": round(
                sum(float(r.get("current_verifier_pass_ratio", 0.0)) for r in metrics_rows) / float(len(metrics_rows)),
                4,
            ),
        }

    return {
        "total_reports": len(metrics_rows),
        "variant_count": len(variant_summary),
        "variants": variant_summary,
        "comparison": comparison,
        "outputs": {
            "evaluation_summary_json": str(output_root / "evaluation_summary.json"),
            "per_report_metrics_jsonl": str(output_root / "per_report_metrics.jsonl"),
            "ablation_report_md": str(output_root / "ablation_report.md"),
            "numeric_audit_summary_json": str(output_root / "numeric_audit_summary.json"),
            "per_report_numeric_audit_jsonl": str(output_root / "per_report_numeric_audit.jsonl"),
            "numeric_audit_report_md": str(output_root / "numeric_audit_report.md"),
            "numeric_audit_v1_summary_json": str(output_root / "numeric_audit_v1_summary.json"),
            "per_case_numeric_audit_v1_jsonl": str(output_root / "per_case_numeric_audit_v1.jsonl"),
            "writer_fallback_stats_json": str(output_root / "writer_fallback_stats.json"),
            "writer_backend_diagnosis_md": str(output_root / "writer_backend_diagnosis.md"),
            "writer_trace_jsonl": str(output_root / "writer_trace.jsonl"),
            "writer_trace_csv": str(output_root / "writer_trace.csv"),
            "writer_trace_summary_json": str(output_root / "writer_trace_summary.json"),
        },
    }


def _write_writer_diagnosis(metrics_rows: List[Dict[str, object]], output_root: Path) -> Dict[str, object]:
    reason_counts: Dict[str, int] = {}
    fallback_rows = [r for r in metrics_rows if bool(r.get("writer_fallback_triggered", False))]
    for row in fallback_rows:
        reason = _classify_writer_fallback_reason(str(row.get("writer_error_message", "")))
        reason_counts[reason] = reason_counts.get(reason, 0) + 1

    stats = {
        "total_reports": len(metrics_rows),
        "fallback_count": len(fallback_rows),
        "fallback_rate": round(float(len(fallback_rows)) / float(len(metrics_rows)), 4) if metrics_rows else 0.0,
        "reasons": reason_counts,
    }
    (output_root / "writer_fallback_stats.json").write_text(json.dumps(stats, indent=2), encoding="utf-8")

    lines = [
        "# Writer Backend Diagnosis",
        "",
        f"- total_reports: {stats['total_reports']}",
        f"- fallback_count: {stats['fallback_count']}",
        f"- fallback_rate: {stats['fallback_rate']}",
        "",
        "## Fallback Reason Breakdown",
        "",
    ]
    if not reason_counts:
        lines.append("- none")
    else:
        for k, v in sorted(reason_counts.items(), key=lambda x: x[0]):
            lines.append(f"- {k}: {v}")
    lines.append("")
    lines.append("## Notes")
    lines.append("")
    lines.append("- fallback mechanism remains enabled by design.")
    lines.append("- diagnosis is generated from writer_debug error_message categories.")
    (output_root / "writer_backend_diagnosis.md").write_text("\n".join(lines), encoding="utf-8")
    return stats


def _write_writer_trace_outputs(metrics_rows: List[Dict[str, object]], output_root: Path) -> Dict[str, object]:
    trace_jsonl = output_root / "writer_trace.jsonl"
    if trace_jsonl.exists():
        trace_jsonl.unlink()

    for row in metrics_rows:
        writer_mode = "fallback" if bool(row.get("writer_fallback_triggered", False)) else "normal"
        event = WriterTraceEvent(
            case_id=str(row.get("case_id", row.get("sample_id", ""))),
            query=str(row.get("query", "")),
            task_type=str(row.get("task_type", "unknown")),
            retrieved_doc_count=int(row.get("retrieved_doc_count", 0)),
            reranked_topk_ids=list(row.get("reranked_topk_ids", [])),
            evidence_coverage=float(row.get("evidence_coverage", 0.0)),
            verifier_accept_rate=float(row.get("current_verifier_pass_ratio", 0.0)),
            writer_mode=writer_mode,
            fallback_reason=_classify_writer_fallback_reason(str(row.get("writer_error_message", ""))),
            final_report_path=str(dict(row.get("artifacts", {})).get("report_md", "")),
        )
        append_writer_trace(trace_jsonl, event)

    trace_rows = []
    for line in trace_jsonl.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text:
            continue
        trace_rows.append(dict(json.loads(text)))

    csv_path = export_writer_trace_csv(trace_rows, output_root / "writer_trace.csv")
    by_case = aggregate_writer_trace(trace_rows, group_key="case_id")
    by_task_type = aggregate_writer_trace(trace_rows, group_key="task_type")
    summary = {
        "rows": len(trace_rows),
        "outputs": {
            "writer_trace_jsonl": str(trace_jsonl),
            "writer_trace_csv": str(csv_path),
            "writer_trace_summary_json": str(output_root / "writer_trace_summary.json"),
        },
        "by_case": by_case,
        "by_task_type": by_task_type,
    }
    (output_root / "writer_trace_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def _build_numeric_audit(metrics_rows: List[Dict[str, object]], eval_cfg: Dict[str, object], output_root: Path) -> Dict[str, object]:
    numeric_cfg = dict(eval_cfg.get("numeric_audit", {}))
    metrics_cfg = list(numeric_cfg.get("metrics", []))
    tol_cfg = dict(numeric_cfg.get("tolerance", {}))
    abs_tol = float(tol_cfg.get("absolute", 0.2))
    rel_tol = float(tol_cfg.get("relative", 0.02))

    audit_rows: List[Dict[str, object]] = []
    status_counter = {"exact_match": 0, "tolerance_match": 0, "mismatch": 0, "missing_coverage": 0}
    chart_coverage_hits = 0
    total_metric_checks = 0

    for row in metrics_rows:
        artifacts = dict(row.get("artifacts", {}))
        report_md_path = Path(str(artifacts.get("report_md", "")))
        report_html_path = Path(str(artifacts.get("report_html", "")))
        report_json_path = Path(str(artifacts.get("report_json", "")))
        features_root = Path(str(artifacts.get("features_root", "")))
        curated_root = Path(str(artifacts.get("curated_root", "")))
        chart_meta_path = Path(str(artifacts.get("chart_metadata", "")))
        md_text = report_md_path.read_text(encoding="utf-8") if report_md_path.exists() else ""
        html_text = report_html_path.read_text(encoding="utf-8") if report_html_path.exists() else ""

        for metric in metrics_cfg:
            metric_key = str(metric.get("key", "")).strip()
            if not metric_key:
                continue
            total_metric_checks += 1
            expected = _read_expected_feature_value(features_root, str(row.get("symbol", "")), str(row.get("period", "")), metric_key)
            curated_value = _read_curated_metric_value(curated_root, metric_key)
            observed_json = _read_claim_metric_value(report_json_path, metric_key)
            observed_md = _extract_metric_from_text(md_text, metric_key)
            observed_html = _extract_metric_from_text(html_text, metric_key)
            chart_has_metric = _has_chart_coverage(chart_meta_path, metric_key)
            if chart_has_metric:
                chart_coverage_hits += 1

            observed_best = observed_json if observed_json is not None else observed_md
            if observed_best is None:
                observed_best = observed_html
            status = _metric_status(expected, observed_best, abs_tol=abs_tol, rel_tol=rel_tol)
            status_counter[status] = status_counter.get(status, 0) + 1

            audit_rows.append(
                {
                    "sample_id": row.get("sample_id", ""),
                    "variant_id": row.get("variant_id", ""),
                    "metric_key": metric_key,
                    "metric_name": str(metric.get("display_name", metric_key)),
                    "expected_feature_value": expected,
                    "curated_value": curated_value,
                    "observed_report_json_value": observed_json,
                    "observed_report_md_value": observed_md,
                    "observed_report_html_value": observed_html,
                    "chart_has_metric_field": chart_has_metric,
                    "status": status,
                }
            )

    per_report_numeric = output_root / "per_report_numeric_audit.jsonl"
    with per_report_numeric.open("w", encoding="utf-8") as fh:
        for item in audit_rows:
            fh.write(json.dumps(item, ensure_ascii=False) + "\n")

    summary = {
        "total_checks": total_metric_checks,
        "status_counts": status_counter,
        "status_rates": {
            k: (round(float(v) / float(total_metric_checks), 4) if total_metric_checks else 0.0)
            for k, v in status_counter.items()
        },
        "chart_metric_coverage_rate": round(float(chart_coverage_hits) / float(total_metric_checks), 4) if total_metric_checks else 0.0,
        "outputs": {
            "numeric_audit_summary_json": str(output_root / "numeric_audit_summary.json"),
            "per_report_numeric_audit_jsonl": str(per_report_numeric),
            "numeric_audit_report_md": str(output_root / "numeric_audit_report.md"),
        },
    }
    (output_root / "numeric_audit_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    lines = [
        "# Numeric Audit Report",
        "",
        f"- total_checks: {summary['total_checks']}",
        f"- exact_match_rate: {summary['status_rates']['exact_match']}",
        f"- tolerance_match_rate: {summary['status_rates']['tolerance_match']}",
        f"- mismatch_rate: {summary['status_rates']['mismatch']}",
        f"- missing_coverage_rate: {summary['status_rates']['missing_coverage']}",
        f"- chart_metric_coverage_rate: {summary['chart_metric_coverage_rate']}",
    ]
    (output_root / "numeric_audit_report.md").write_text("\n".join(lines), encoding="utf-8")
    return summary


def _build_numeric_audit_v1(metrics_rows: List[Dict[str, object]], case_lookup: Dict[str, Dict[str, object]], output_root: Path) -> Dict[str, object]:
    results: List[Dict[str, object]] = []
    for row in metrics_rows:
        case_id = str(row.get("case_id", ""))
        case = case_lookup.get(case_id)
        if not case:
            continue
        report_json_path = Path(str(dict(row.get("artifacts", {})).get("report_json", "")))
        if not report_json_path.exists():
            continue
        payload = dict(_read_json(report_json_path))
        claims = list(payload.get("claims", []))
        audit = run_numeric_audit_for_case(case=case, report_claims=claims)
        audit["variant_id"] = str(row.get("variant_id", ""))
        audit["task_type"] = str(row.get("task_type", "unknown"))
        results.append(audit)

    summary = summarize_numeric_audit(results)
    summary["outputs"] = {
        "numeric_audit_v1_summary_json": str(output_root / "numeric_audit_v1_summary.json"),
        "per_case_numeric_audit_v1_jsonl": str(output_root / "per_case_numeric_audit_v1.jsonl"),
    }

    with (output_root / "per_case_numeric_audit_v1.jsonl").open("w", encoding="utf-8") as fh:
        for item in results:
            fh.write(json.dumps(item, ensure_ascii=False) + "\n")
    (output_root / "numeric_audit_v1_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def _write_outputs(metrics_rows: List[Dict[str, object]], summary: Dict[str, object], output_root: Path) -> None:
    output_root.mkdir(parents=True, exist_ok=True)
    per_report_path = output_root / "per_report_metrics.jsonl"
    with per_report_path.open("w", encoding="utf-8") as fh:
        for row in metrics_rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    (output_root / "evaluation_summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

    lines = ["# Stage12A Ablation Report", "", f"- total_reports: {summary['total_reports']}", f"- variant_count: {summary['variant_count']}", "", "## Variant Means", ""]
    for variant, item in dict(summary.get("variants", {})).items():
        lines.append(f"### {variant}")
        lines.append("")
        for key in [
            "structure_completeness_mean",
            "numeric_consistency_mean",
            "evidence_alignment_mean",
            "evidence_coverage_mean",
            "current_verifier_pass_ratio_mean",
            "rule_verifier_pass_rate",
            "writer_fallback_rate",
            "retrieval_fallback_rate",
        ]:
            lines.append(f"- {key}: {item.get(key, 0.0)}")
        lines.append("")
    (output_root / "ablation_report.md").write_text("\n".join(lines), encoding="utf-8")


def run_stage12a_evaluation(config_path: str = "configs/evaluation_stage12a.yaml") -> Dict[str, object]:
    cfg = load_config(config_path)
    eval_cfg = dict(cfg.get("evaluation", {}))
    real_cfg = dict(cfg.get("real_data", {}))
    source_cfg = dict(real_cfg.get("sources", {}))
    raw_root = Path(str(eval_cfg.get("raw_root", real_cfg.get("raw_root", "data/raw/real_data"))))
    output_root = Path(str(eval_cfg.get("output_root", "data/evaluation/stage12a")))
    run_root = output_root / "runs"
    max_samples = int(eval_cfg.get("max_samples", 10))
    variants = list(dict(eval_cfg.get("writer", {})).get("variants", []))
    eval_case_path = Path(str(eval_cfg.get("eval_case_path", "data/eval_v1/cases.jsonl")))
    case_lookup: Dict[str, Dict[str, object]] = {}
    if eval_case_path.exists():
        case_lookup = {item.case_id: item.to_dict() for item in load_eval_cases(eval_case_path)}

    samples = _samples_from_eval_v1(eval_case_path=eval_case_path, max_samples=max_samples)
    if not samples:
        samples = _discover_samples(raw_root=raw_root, configured=list(eval_cfg.get("samples", [])), max_samples=max_samples)
    if not samples:
        raise ValueError(f"No evaluation samples found under {raw_root}")
    if not variants:
        raise ValueError("evaluation.writer.variants is empty")

    metrics_rows: List[Dict[str, object]] = []
    for sample in samples:
        for variant in variants:
            variant_id = str(variant.get("id", "")).strip() or "variant"
            paths = _prepare_data_and_features(sample=sample, variant_id=variant_id, raw_root=raw_root, source_cfg=source_cfg, run_root=run_root)
            metrics_rows.append(_run_variant(sample=sample, variant=variant, paths=paths, eval_cfg=eval_cfg))

    summary = _aggregate(metrics_rows, output_root=output_root)
    summary["numeric_audit"] = _build_numeric_audit(metrics_rows=metrics_rows, eval_cfg=eval_cfg, output_root=output_root)
    summary["numeric_audit_v1"] = _build_numeric_audit_v1(metrics_rows=metrics_rows, case_lookup=case_lookup, output_root=output_root)
    summary["writer_diagnosis"] = _write_writer_diagnosis(metrics_rows=metrics_rows, output_root=output_root)
    summary["writer_trace"] = _write_writer_trace_outputs(metrics_rows=metrics_rows, output_root=output_root)
    _write_outputs(metrics_rows, summary, output_root=output_root)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Stage 12A evaluation harness.")
    parser.add_argument("--config", default="configs/evaluation_stage12a.yaml")
    args = parser.parse_args()
    summary = run_stage12a_evaluation(config_path=args.config)
    print(f"[stage12a] total_reports: {summary['total_reports']}")
    print(f"[stage12a] summary: {summary['outputs']['evaluation_summary_json']}")
    print(f"[stage12a] per-report: {summary['outputs']['per_report_metrics_jsonl']}")
    print(f"[stage12a] ablation: {summary['outputs']['ablation_report_md']}")
    print(f"[stage12a] numeric_audit: {summary['outputs']['numeric_audit_summary_json']}")
    print(f"[stage12a] writer_stats: {summary['outputs']['writer_fallback_stats_json']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
