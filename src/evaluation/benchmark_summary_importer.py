"""Read-only importer for benchmark output summaries used by the evaluation center."""

from __future__ import annotations

import csv
import os
from pathlib import Path
from typing import Any


DEFAULT_BENCHMARK_SUMMARY_ROOTS = (
    Path("data/evaluation"),
    Path("data/benchmarks"),
    Path("data/benchmark_results"),
    Path("data/outputs_dev"),
    Path("data/outputs_user"),
)

METRIC_LABELS = {
    "Delivery Pass Rate": "delivery_pass_rate",
    "Objective Quality Score": "objective_quality_score",
    "Traceable Claim Rate (Artifact-Derived)": "traceable_claim_rate",
    "Traceable Claim Rate": "traceable_claim_rate",
}

SUITE_NAME_HINTS = (
    ("quick9", "Quick-9 多市场跑批"),
    ("quick-9", "Quick-9 多市场跑批"),
    ("formal18", "Formal-18 正式评测"),
    ("formal-18", "Formal-18 正式评测"),
    ("regression", "回归集评测"),
)


def load_benchmark_summaries(
    roots: list[str | Path] | tuple[str | Path, ...] | None = None,
    *,
    max_suites: int = 12,
) -> list[dict[str, Any]]:
    """Load benchmark suites from existing CSV artifacts.

    The benchmark runners write CSV/Markdown artifacts. This importer only reads
    those artifacts and keeps the evaluation center independent from live runs.
    """

    summaries: list[dict[str, Any]] = []
    seen: set[Path] = set()
    for root in _summary_roots(roots):
        if not root.exists():
            continue
        for summary_path in sorted(root.rglob("benchmark_summary.csv"), key=_path_mtime, reverse=True):
            resolved = summary_path.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            suite = _load_suite(summary_path)
            if suite:
                summaries.append(suite)
            if len(summaries) >= max_suites:
                return summaries
    return summaries


def _summary_roots(roots: list[str | Path] | tuple[str | Path, ...] | None) -> list[Path]:
    if roots is None:
        env_value = os.environ.get("FINSIGHT_BENCHMARK_SUMMARY_ROOTS", "")
        roots = [item for item in env_value.split(os.pathsep) if item] or DEFAULT_BENCHMARK_SUMMARY_ROOTS
    return [Path(root) for root in roots]


def _load_suite(summary_path: Path) -> dict[str, Any] | None:
    summary_rows = _read_csv(summary_path)
    if not summary_rows:
        return None
    metric_rows = _parse_metric_rows(summary_rows)
    if not metric_rows:
        return None
    directory = summary_path.parent
    market_breakdown = _load_market_breakdown(directory / "market_breakdown.csv") or _market_rows_from_summary(metric_rows)
    records = _load_jsonl_count(directory / "benchmark_runs.jsonl")
    failures = _read_csv(directory / "benchmark_failures.csv")
    overall = _market_metric(metric_rows, "overall")
    updated_at = max(_path_mtime(path) for path in _existing_artifacts(directory))
    return {
        "suite_id": _suite_id(directory),
        "suite_name": _suite_name(directory),
        "suite_type": _suite_type(directory),
        "artifact_dir": str(directory),
        "last_updated_at": updated_at,
        "metrics": overall,
        "case_count": _case_count(market_breakdown=market_breakdown, records=records),
        "evaluated_count": _evaluated_count(market_breakdown=market_breakdown, records=records),
        "failure_count": len(failures),
        "market_breakdown": market_breakdown,
        "artifacts": _artifact_links(directory),
    }


def _parse_metric_rows(rows: list[dict[str, str]]) -> dict[str, dict[str, float | None]]:
    metrics: dict[str, dict[str, float | None]] = {}
    for row in rows:
        metric_key = METRIC_LABELS.get((row.get("metric") or "").strip())
        if not metric_key:
            continue
        metrics[metric_key] = {
            market: _to_float(row.get(column))
            for market, column in (("overall", "overall"), ("US", "US"), ("HK", "HK"), ("CN-A", "CN-A"))
        }
    return metrics


def _market_metric(metric_rows: dict[str, dict[str, float | None]], market: str) -> dict[str, float | None]:
    return {
        "delivery_pass_rate": metric_rows.get("delivery_pass_rate", {}).get(market),
        "objective_quality_score": metric_rows.get("objective_quality_score", {}).get(market),
        "traceable_claim_rate": metric_rows.get("traceable_claim_rate", {}).get(market),
    }


def _load_market_breakdown(path: Path) -> list[dict[str, Any]]:
    rows = _read_csv(path)
    if not rows:
        return []
    result = []
    for row in rows:
        market = (row.get("market") or "").strip()
        if not market:
            continue
        result.append(
            {
                "market": market,
                "case_count": _to_int(row.get("case_count")),
                "evaluated_count": _to_int(row.get("quality_evaluable_count")),
                "delivery_pass_rate": _to_float(row.get("delivery_pass_rate")),
                "objective_quality_score": _to_float(row.get("objective_quality_score")),
                "traceable_claim_rate": _to_float(row.get("traceable_claim_rate_artifact_derived")),
            }
        )
    return result


def _market_rows_from_summary(metric_rows: dict[str, dict[str, float | None]]) -> list[dict[str, Any]]:
    rows = []
    for market in ("Overall", "US", "HK", "CN-A"):
        key = "overall" if market == "Overall" else market
        rows.append({"market": market, **_market_metric(metric_rows, key), "case_count": None, "evaluated_count": None})
    return rows


def _existing_artifacts(directory: Path) -> list[Path]:
    names = ("benchmark_summary.csv", "benchmark_runs.jsonl", "benchmark_failures.csv", "market_breakdown.csv", "benchmark_report.md")
    return [directory / name for name in names if (directory / name).exists()]


def _artifact_links(directory: Path) -> dict[str, str]:
    labels = {
        "benchmark_summary.csv": "summary_csv",
        "benchmark_runs.jsonl": "runs_jsonl",
        "benchmark_failures.csv": "failures_csv",
        "market_breakdown.csv": "market_csv",
        "benchmark_report.md": "report_md",
    }
    return {label: str(directory / name) for name, label in labels.items() if (directory / name).exists()}


def _case_count(*, market_breakdown: list[dict[str, Any]], records: int | None) -> int | None:
    overall = next((row for row in market_breakdown if row.get("market") == "Overall"), None)
    if overall and overall.get("case_count") is not None:
        return overall["case_count"]
    return records


def _evaluated_count(*, market_breakdown: list[dict[str, Any]], records: int | None) -> int | None:
    overall = next((row for row in market_breakdown if row.get("market") == "Overall"), None)
    if overall and overall.get("evaluated_count") is not None:
        return overall["evaluated_count"]
    return records


def _suite_name(directory: Path) -> str:
    lowered = str(directory).lower()
    for hint, label in SUITE_NAME_HINTS:
        if hint in lowered:
            return label
    return f"基准评测：{directory.name}"


def _suite_type(directory: Path) -> str:
    lowered = str(directory).lower()
    if "quick" in lowered:
        return "quick9"
    if "formal" in lowered:
        return "formal18"
    if "regression" in lowered:
        return "regression"
    return "benchmark"


def _suite_id(directory: Path) -> str:
    return directory.name or directory.resolve().name


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as fh:
        return [dict(row) for row in csv.DictReader(fh)]


def _load_jsonl_count(path: Path) -> int | None:
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as fh:
        return sum(1 for line in fh if line.strip())


def _path_mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def _to_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return round(float(value), 4)
    except (TypeError, ValueError):
        return None


def _to_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None
