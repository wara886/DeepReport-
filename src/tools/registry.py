"""Tool registry used by LLM agents and future MCP adapters."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List

import pandas as pd

from src.charts.render import attach_charts_to_report, render_all_charts
from src.data.yahoo_finance import yahoo_snapshot_to_evidence
from src.features.company_valuation import build_peer_comparison, perform_company_valuation
from src.features.financial_ratios import build_financial_ratios
from src.features.financial_statements import build_three_statement_view
from src.features.trend_analysis import build_trend_features
from src.retrieval.retrieve import retrieve_evidence_with_mode


ToolCallable = Callable[..., Any]


@dataclass
class ToolSpec:
    """A callable tool plus the JSON schema exposed to LLM tool calling."""

    name: str
    description: str
    parameters: Dict[str, Any]
    handler: ToolCallable = field(repr=False)

    def to_tool_schema(self) -> Dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class ToolRegistry:
    """Register, inspect, and call local financial tools."""

    def __init__(self):
        self._tools: Dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        if spec.name in self._tools:
            raise ValueError(f"tool already registered: {spec.name}")
        self._tools[spec.name] = spec

    def names(self) -> List[str]:
        return sorted(self._tools.keys())

    def get(self, name: str) -> ToolSpec:
        if name not in self._tools:
            raise KeyError(f"tool not found: {name}")
        return self._tools[name]

    def tool_schemas(self) -> List[Dict[str, Any]]:
        return [self._tools[name].to_tool_schema() for name in self.names()]

    def handlers(self) -> Dict[str, ToolCallable]:
        return {name: self._tools[name].handler for name in self.names()}

    def call(self, name: str, **kwargs: Any) -> Any:
        return self.get(name).handler(**kwargs)


def build_core_tool_registry() -> ToolRegistry:
    """Build the first local tool set for financial multi-agent v1."""

    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            name="retrieve_local_evidence",
            description="Search the local evidence store with BM25 or reranker mode.",
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query."},
                    "topk": {"type": "integer", "description": "Maximum number of hits."},
                    "symbol": {"type": "string", "description": "Optional ticker symbol."},
                    "period": {"type": "string", "description": "Optional fiscal period."},
                    "curated_dir": {"type": "string", "description": "Curated evidence directory."},
                    "ranking_mode": {"type": "string", "enum": ["bm25", "vector", "hybrid", "reranker", "hybrid_rerank"]},
                    "use_chunks": {"type": "boolean", "description": "Retrieve paragraph/table/metric chunks instead of whole records."},
                },
                "required": ["query"],
            },
            handler=retrieve_local_evidence_tool,
        )
    )
    registry.register(
        ToolSpec(
            name="calculate_financial_ratios",
            description="Extract revenue, margin, ROE/ROA, and cash-flow features from evidence records.",
            parameters={
                "type": "object",
                "properties": {
                    "records": {
                        "type": "array",
                        "items": {"type": "object"},
                        "description": "Evidence-like records with content, symbol, period, source_type, and sample_id.",
                    }
                },
                "required": ["records"],
            },
            handler=calculate_financial_ratios_tool,
        )
    )
    registry.register(
        ToolSpec(
            name="build_trend_features",
            description="Build evidence coverage and trend summary features from records.",
            parameters={
                "type": "object",
                "properties": {
                    "records": {
                        "type": "array",
                        "items": {"type": "object"},
                        "description": "Evidence-like records with sample_id, symbol, period, source_type, publish_time.",
                    }
                },
                "required": ["records"],
            },
            handler=build_trend_features_tool,
        )
    )
    registry.register(
        ToolSpec(
            name="build_three_statement_view",
            description="Normalize available company evidence into income statement, cash-flow statement, and balance-sheet rows.",
            parameters={
                "type": "object",
                "properties": {
                    "records": {"type": "array", "items": {"type": "object"}},
                },
                "required": ["records"],
            },
            handler=build_three_statement_view_tool,
        )
    )
    registry.register(
        ToolSpec(
            name="build_peer_comparison",
            description="Build a local sector peer table and target ranking for a company and period.",
            parameters={
                "type": "object",
                "properties": {
                    "symbol": {"type": "string"},
                    "period": {"type": "string"},
                    "raw_data_root": {"type": "string"},
                    "allow_external_discovery": {"type": "boolean"},
                },
                "required": ["symbol", "period"],
            },
            handler=build_peer_comparison_tool,
        )
    )
    registry.register(
        ToolSpec(
            name="perform_company_valuation",
            description="Run a first-pass P/E, P/S, and DCF valuation with peer context.",
            parameters={
                "type": "object",
                "properties": {
                    "symbol": {"type": "string"},
                    "period": {"type": "string"},
                    "records": {"type": "array", "items": {"type": "object"}},
                    "raw_data_root": {"type": "string"},
                },
                "required": ["symbol", "period"],
            },
            handler=perform_company_valuation_tool,
        )
    )
    registry.register(
        ToolSpec(
            name="fetch_yahoo_market_snapshot",
            description="Fetch a real keyless Yahoo Finance market snapshot and return it as evidence.",
            parameters={
                "type": "object",
                "properties": {
                    "symbol": {"type": "string", "description": "Ticker symbol, for example AAPL."},
                    "period": {"type": "string", "description": "Optional fiscal/report period label."},
                    "range_": {"type": "string", "description": "Yahoo chart range, for example 1mo, 3mo, 1y."},
                    "interval": {"type": "string", "description": "Yahoo chart interval, for example 1d, 1wk."},
                },
                "required": ["symbol"],
            },
            handler=fetch_yahoo_market_snapshot_tool,
        )
    )
    registry.register(
        ToolSpec(
            name="render_all_charts",
            description="Render report charts from generated feature parquet files.",
            parameters={
                "type": "object",
                "properties": {
                    "features_root": {"type": "string"},
                    "chart_output_dir": {"type": "string"},
                    "metadata_path": {"type": "string"},
                },
            },
            handler=render_all_charts_tool,
        )
    )
    registry.register(
        ToolSpec(
            name="attach_charts_to_report",
            description="Attach rendered chart metadata to an existing Markdown report.",
            parameters={
                "type": "object",
                "properties": {
                    "report_path": {"type": "string"},
                    "metadata": {"type": "array", "items": {"type": "object"}},
                },
                "required": ["report_path", "metadata"],
            },
            handler=attach_charts_to_report_tool,
        )
    )
    return registry


def retrieve_local_evidence_tool(
    query: str,
    topk: int = 5,
    symbol: str | None = None,
    period: str | None = None,
    curated_dir: str = "data/curated",
    ranking_mode: str = "bm25",
    use_chunks: bool = True,
) -> Dict[str, Any]:
    hits, meta = retrieve_evidence_with_mode(
        query=query,
        topk=topk,
        symbol=symbol or None,
        period=period or None,
        curated_dir=curated_dir,
        ranking_mode=ranking_mode,
        use_chunks=use_chunks,
        log=False,
    )
    return {"hits": hits, "meta": meta}


def calculate_financial_ratios_tool(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    df = pd.DataFrame(records)
    result = build_financial_ratios(df)
    return {"rows": result.to_dict(orient="records")}


def build_trend_features_tool(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    df = pd.DataFrame([_backfill_record_metadata(item) for item in records])
    result = build_trend_features(df)
    return {"rows": result.to_dict(orient="records")}


def build_three_statement_view_tool(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    return build_three_statement_view(records=records)


def build_peer_comparison_tool(
    symbol: str,
    period: str,
    raw_data_root: str = "data/raw/real_data",
    allow_external_discovery: bool = False,
) -> Dict[str, Any]:
    return build_peer_comparison(
        symbol=symbol,
        period=period,
        raw_data_root=raw_data_root,
        allow_external_discovery=allow_external_discovery,
    )


def perform_company_valuation_tool(
    symbol: str,
    period: str,
    records: List[Dict[str, Any]] | None = None,
    raw_data_root: str = "data/raw/real_data",
) -> Dict[str, Any]:
    return perform_company_valuation(
        symbol=symbol,
        period=period,
        records=records or [],
        raw_data_root=raw_data_root,
    )


def fetch_yahoo_market_snapshot_tool(
    symbol: str,
    period: str = "",
    range_: str = "1mo",
    interval: str = "1d",
) -> Dict[str, Any]:
    evidence = yahoo_snapshot_to_evidence(symbol=symbol, period=period, range_=range_, interval=interval)
    return {"evidence": evidence}


def render_all_charts_tool(
    features_root: str = "data/features",
    chart_output_dir: str = "data/outputs/charts",
    metadata_path: str = "data/outputs/chart_metadata.json",
) -> Dict[str, Any]:
    metadata = render_all_charts(
        features_root=features_root,
        chart_output_dir=chart_output_dir,
        metadata_path=metadata_path,
    )
    return {"metadata": metadata, "metadata_path": str(Path(metadata_path))}


def attach_charts_to_report_tool(report_path: str, metadata: List[Dict[str, str]]) -> Dict[str, str]:
    path = attach_charts_to_report(report_path=report_path, metadata=metadata)
    return {"report_path": str(path)}


def _backfill_record_metadata(record: Dict[str, Any]) -> Dict[str, Any]:
    row = dict(record)
    metadata = row.get("metadata", {}) if isinstance(row.get("metadata"), dict) else {}
    for key in ["symbol", "period", "source_type", "publish_time", "sample_id"]:
        if row.get(key) in (None, "") and metadata.get(key) not in (None, ""):
            row[key] = metadata.get(key)
    if row.get("sample_id") in (None, "") and row.get("evidence_id") not in (None, ""):
        row["sample_id"] = row.get("evidence_id")
    return row
