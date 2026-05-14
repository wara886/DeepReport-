"""PeerComparisonAgent: generates peer_compare section claims using real-time SEC data for peers."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import csv
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.agents.base_agent import AgentStatus, AgentTask, BaseAgent, TaskResult
from src.features.company_valuation import _safe_float, build_peer_comparison
from src.schemas.claim import ClaimItem


# Default peer sets by sector/industry. Core groups are the main comparable
# companies; extended groups are useful context but should not be presented as
# equally comparable.
_PEER_GROUPS: Dict[str, Dict[str, List[str]]] = {
    "Financials": {
        "core": ["JPM", "BAC", "WFC", "C"],
        "extended": ["GS", "MS"],
        "rationale": "large US money-center/commercial banks are the core group; capital-markets-heavy banks are extended references.",
    },
    "Communication Services": {
        "core": ["META", "GOOGL"],
        "extended": ["NFLX", "DIS", "T"],
        "rationale": "digital advertising platforms are the core group; streaming/media/telecom names are extended references.",
    },
    "Technology": {
        "core": ["AAPL", "MSFT", "NVDA", "ORCL", "CRM"],
        "extended": ["AMZN", "TSM", "INTC"],
        "rationale": "large-cap technology platforms and infrastructure peers are the core group; adjacent hardware/cloud/semi names are extended references.",
    },
    "China Liquor": {
        "core": ["000858.SZ", "000568.SZ", "600809.SH"],
        "extended": ["603369.SH"],
        "rationale": "A 股白酒公司按高端/次高端白酒商业模式、渠道结构和消费属性构成核心可比组。",
    },
    "default": {
        "core": ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA"],
        "extended": [],
        "rationale": "large-cap US listed peers are used as a fallback when sector metadata is limited.",
    },
}

_FINANCIAL_SYMBOLS = frozenset({"JPM", "BAC", "WFC", "GS", "MS", "C", "BRK.B", "AXP", "BLK", "SCHW"})


def _get_peer_groups(symbol: str, sector: str, industry: str, max_core: int = 4, max_extended: int = 3) -> Dict[str, Any]:
    """Return layered peer groups for comparison, excluding the target."""
    if _is_china_liquor_symbol(symbol, sector, industry):
        group = _PEER_GROUPS["China Liquor"]
    elif symbol in _FINANCIAL_SYMBOLS or "bank" in sector.lower() or "financial" in sector.lower():
        group = _PEER_GROUPS["Financials"]
    elif symbol in {"META", "GOOGL", "NFLX", "DIS"}:
        group = _PEER_GROUPS["Communication Services"]
    elif symbol in {"AAPL", "MSFT", "NVDA", "ORCL", "CRM", "INTC", "TSM"}:
        group = _PEER_GROUPS["Technology"]
    elif "tech" in sector.lower() or "software" in industry.lower() or "semiconductor" in industry.lower():
        group = _PEER_GROUPS["Technology"]
    elif "communication" in sector.lower() or "media" in sector.lower():
        group = _PEER_GROUPS["Communication Services"]
    else:
        group = _PEER_GROUPS.get(sector, _PEER_GROUPS["default"])
    core = [s for s in group.get("core", []) if s != symbol][:max_core]
    extended = [s for s in group.get("extended", []) if s != symbol][:max_extended]
    return {
        "core": core,
        "extended": extended,
        "all": _dedupe_symbols(core + extended),
        "rationale": str(group.get("rationale") or ""),
    }


def _dedupe_symbols(symbols: List[str]) -> List[str]:
    output = []
    seen = set()
    for symbol in symbols:
        key = str(symbol).upper()
        if key and key not in seen:
            seen.add(key)
            output.append(key)
    return output


def _is_china_listed_symbol(symbol: str) -> bool:
    text = str(symbol or "").upper()
    return text.endswith((".SS", ".SH", ".SZ", ".BJ", ".HK")) or text[:2] in {"SH", "SZ", "BJ", "HK"}


def _is_china_liquor_symbol(symbol: str, sector: str, industry: str) -> bool:
    text = f"{symbol} {sector} {industry}".upper()
    return any(token in text for token in ["600519", "000858", "000568", "600809", "603369", "白酒", "LIQUOR", "BEVERAGE"])


def _fmt(val: Optional[float], suffix: str = "", decimals: int = 1) -> str:
    if val is None:
        return "N/A"
    return f"{val:.{decimals}f}{suffix}"


def _filter_period_aligned_peers(
    peer_rows: List[Dict[str, Any]],
    peer_evidence_records: List[Dict[str, Any]],
    target_period: str,
) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, str]]]:
    """Keep peer rows on the target fiscal period; report stale peers instead of mixing them."""
    target = str(target_period or "").strip()
    if not target or target.lower() == "latest":
        return peer_rows, peer_evidence_records, []

    evidence_by_symbol = {
        str(record.get("symbol") or record.get("metadata", {}).get("symbol") or "").upper(): record
        for record in peer_evidence_records
        if isinstance(record, dict)
    }
    kept_rows: List[Dict[str, Any]] = []
    kept_symbols: set[str] = set()
    excluded: List[Dict[str, str]] = []
    for row in peer_rows:
        if not isinstance(row, dict):
            continue
        symbol = str(row.get("symbol") or "").upper()
        peer_period = str(row.get("period") or "").strip()
        if _same_fiscal_period(peer_period, target):
            kept_rows.append(row)
            kept_symbols.add(symbol)
        else:
            excluded.append({"symbol": symbol, "period": peer_period or "unknown", "target_period": target})
    kept_evidence = [
        record
        for symbol, record in evidence_by_symbol.items()
        if symbol in kept_symbols
    ]
    return kept_rows, kept_evidence, excluded


def _same_fiscal_period(left: str, right: str) -> bool:
    return _normalize_period(left) == _normalize_period(right)


def _normalize_period(value: str) -> str:
    return " ".join(str(value or "").upper().replace("-", " ").split())


class PeerComparisonAgent(BaseAgent):
    """Generates peer_compare claims by fetching real-time SEC data for peer companies."""

    def __init__(self, model=None, tools=None):
        super().__init__(name="PeerComparisonAgent", model=model, tools=tools or {})

    def get_capabilities(self) -> list:
        return ["peer_comparison", "competitive_analysis", "sector_benchmarking"]

    def execute_task(self, task: AgentTask) -> TaskResult:
        return self.run(task)

    def run(self, task: AgentTask) -> TaskResult:
        params = task.parameters or {}
        symbol: str = str(params.get("symbol", "Company")).upper()
        period: str = str(params.get("period", "latest"))
        sector: str = str(params.get("sector", ""))
        industry: str = str(params.get("industry", ""))
        target_metrics: Dict[str, Any] = params.get("target_metrics", {})
        financial_evidence_ids: List[str] = params.get("financial_evidence_ids", [])
        raw_data_root = str(params.get("raw_data_root") or "data/raw/real_data")
        is_china_symbol = _is_china_listed_symbol(symbol)
        use_sec_fetch = bool(params.get("use_sec_fetch", True)) and not is_china_symbol
        peer_fetch_max_workers = max(1, int(params.get("peer_fetch_max_workers", 4) or 4))

        peer_groups = _get_peer_groups(symbol, sector, industry)
        peer_symbols = list(peer_groups["all"])
        core_symbols = list(peer_groups["core"])
        extended_symbols = list(peer_groups["extended"])

        # Fetch peer metrics via SEC CompanyFacts first. Local peer comparison is a fallback
        # for offline demos and legacy 2025Q4 fixtures.
        peer_rows: List[Dict[str, Any]] = []
        peer_evidence_records: List[Dict[str, Any]] = []
        try:
            from src.data.sec_companyfacts import fetch_sec_companyfacts_evidence
            if use_sec_fetch:
                with ThreadPoolExecutor(max_workers=min(peer_fetch_max_workers, max(1, len(peer_symbols)))) as executor:
                    future_to_symbol = {
                        executor.submit(fetch_sec_companyfacts_evidence, peer_sym, period): peer_sym
                        for peer_sym in peer_symbols
                    }
                    records_by_symbol: Dict[str, Dict[str, Any]] = {}
                    for future in as_completed(future_to_symbol):
                        peer_sym = future_to_symbol[future]
                        try:
                            evidence = future.result()
                        except Exception:
                            continue
                        if isinstance(evidence, dict):
                            records_by_symbol[peer_sym] = evidence
                    for peer_sym in peer_symbols:
                        evidence = records_by_symbol.get(peer_sym)
                        metrics = evidence.get("metadata", {}) if isinstance(evidence, dict) else {}
                        if metrics:
                            peer_rows.append({
                                "symbol": peer_sym,
                                "period": evidence.get("period") or metrics.get("period") or period,
                                **metrics,
                            })
                            peer_evidence_records.append(evidence)
        except Exception:
            pass
        if not peer_rows:
            try:
                local_peer = build_peer_comparison(symbol=symbol, period=period, raw_data_root=raw_data_root)
                peer_rows = [
                    row for row in local_peer.get("peer_rows", [])
                    if isinstance(row, dict) and str(row.get("symbol", "")).upper() != symbol
                ]
                if peer_rows:
                    peer_evidence_records = _load_local_peer_financial_evidence(
                        raw_data_root=raw_data_root,
                        period=period,
                        symbols=[str(row.get("symbol", "")).upper() for row in peer_rows],
                    )
            except Exception:
                peer_rows = []

        target_period = str(target_metrics.get("period") or period)
        peer_rows, peer_evidence_records, excluded_peers = _filter_period_aligned_peers(
            peer_rows=peer_rows,
            peer_evidence_records=peer_evidence_records,
            target_period=target_period,
        )
        available_peer_symbols = {str(row.get("symbol", "")).upper() for row in peer_rows if str(row.get("symbol", "")).strip()}
        available_core_symbols = [peer for peer in core_symbols if peer in available_peer_symbols]
        available_extended_symbols = [peer for peer in extended_symbols if peer in available_peer_symbols]

        # Build comparison table
        all_rows = [{"symbol": symbol, **target_metrics}] + peer_rows
        table_lines = [
            "| 公司 | 营收(B) | 营收增速(%) | 净利率(%) | ROE(%) | FCF(B) |",
            "|------|---------|------------|----------|--------|--------|",
        ]
        for row in all_rows:
            sym = str(row.get("symbol", ""))
            marker = " ◀" if sym == symbol else ""
            rev = _safe_float(row.get("revenue_billion"))
            rev_g = _safe_float(row.get("revenue_growth_pct"))
            nm = _safe_float(row.get("net_margin_pct"))
            roe = _safe_float(row.get("roe_pct"))
            fcf = _safe_float(row.get("free_cash_flow_billion"))
            table_lines.append(
                f"| {sym}{marker} | {_fmt(rev)} | {_fmt(rev_g)} | {_fmt(nm)} | {_fmt(roe)} | {_fmt(fcf)} |"
            )

        # Narrative comparison
        target_rev_g = _safe_float(target_metrics.get("revenue_growth_pct"))
        target_nm = _safe_float(target_metrics.get("net_margin_pct"))
        target_roe = _safe_float(target_metrics.get("roe_pct"))

        peer_rev_gs = [_safe_float(r.get("revenue_growth_pct")) for r in peer_rows if _safe_float(r.get("revenue_growth_pct")) is not None]
        peer_nms = [_safe_float(r.get("net_margin_pct")) for r in peer_rows if _safe_float(r.get("net_margin_pct")) is not None]
        peer_roes = [_safe_float(r.get("roe_pct")) for r in peer_rows if _safe_float(r.get("roe_pct")) is not None]
        peer_periods = sorted({str(r.get("period") or "") for r in peer_rows if str(r.get("period") or "")})
        aligned_periods = not peer_periods or all(p == target_period or p == period for p in peer_periods)
        period_note = (
            f"财期对齐：目标期间 {target_period}；同行期间 {', '.join(peer_periods[:6]) or period}；"
            f"{'基本一致' if aligned_periods else '存在不完全一致，需作为横向比较限制'}。"
        )
        excluded_note = ""
        if excluded_peers:
            excluded_items = [
                f"{item['symbol']}({item['period']})"
                for item in excluded_peers
                if item.get("symbol") and item.get("period")
            ]
            if excluded_items:
                excluded_note = " 已剔除财期不一致或过旧的同行数据：" + ", ".join(excluded_items[:6]) + "。"

        narrative_parts = []
        if target_rev_g is not None and peer_rev_gs:
            avg_peer_rev_g = sum(peer_rev_gs) / len(peer_rev_gs)
            diff = target_rev_g - avg_peer_rev_g
            narrative_parts.append(
                f"营收增速 {target_rev_g:.1f}%，同行均值 {avg_peer_rev_g:.1f}%，"
                f"{'高于' if diff > 0 else '低于'}同行 {abs(diff):.1f}pct"
            )
        if target_nm is not None and peer_nms:
            avg_peer_nm = sum(peer_nms) / len(peer_nms)
            diff = target_nm - avg_peer_nm
            narrative_parts.append(
                f"净利率 {target_nm:.1f}%，同行均值 {avg_peer_nm:.1f}%，"
                f"{'高于' if diff > 0 else '低于'}同行 {abs(diff):.1f}pct"
            )
        if target_roe is not None and peer_roes:
            avg_peer_roe = sum(peer_roes) / len(peer_roes)
            diff = target_roe - avg_peer_roe
            narrative_parts.append(
                f"ROE {target_roe:.1f}%，同行均值 {avg_peer_roe:.1f}%，"
                f"{'高于' if diff > 0 else '低于'}同行 {abs(diff):.1f}pct"
            )

        if not narrative_parts:
            narrative = f"{symbol} 同行对比数据不足，无法生成定量比较。"
        else:
            peer_method = (
                f"同行选择方法：核心可比组 {', '.join(available_core_symbols) or 'N/A'}；"
                f"扩展参考组 {', '.join(available_extended_symbols) or 'N/A'}。"
                f"{peer_groups.get('rationale', '')} {period_note}{excluded_note}"
            )
            narrative = (
                f"{symbol} 同行对比：{peer_method} "
                + "；".join(narrative_parts)
                + "。"
            )

        if is_china_symbol:
            data_source_note = (
                "（A/H 股同行数据优先使用交易所、巨潮资讯和本地结构化财报缓存；"
                "行情源仅用于价格、市值等市场数据，不单独支撑核心财务结论。）"
            )
        else:
            data_source_note = (
                "（同行数据优先通过 SEC EDGAR CompanyFacts API 实时获取；"
                "若实时接口不可用，则回退到本地同业缓存。）"
            )

        claim_text = narrative + "\n\n" + "\n".join(table_lines) + "\n\n" + data_source_note

        peer_evidence_ids = [
            str(item.get("evidence_id") or item.get("sample_id") or "")
            for item in peer_evidence_records
            if isinstance(item, dict) and str(item.get("evidence_id") or item.get("sample_id") or "")
        ]
        claim = ClaimItem(
            claim_id="cl_peer_0001",
            section_name="peer_compare",
            claim_text=claim_text,
            evidence_ids=(financial_evidence_ids[:2] + peer_evidence_ids[:6]) or financial_evidence_ids[:3],
            numeric_values={
                "peer_count": len(peer_rows),
                "core_peer_count": len(available_core_symbols),
                "extended_peer_count": len(available_extended_symbols),
                "excluded_peer_count": len(excluded_peers),
                "target_revenue_growth_pct": target_rev_g or 0.0,
                "target_net_margin_pct": target_nm or 0.0,
            },
            risk_level="low",
            confidence=0.68 if peer_rows else 0.40,
            notes=(
                f"由 PeerComparisonAgent 生成；实时 SEC 数据同行 {len(peer_rows)} 家；"
                f"核心组={','.join(available_core_symbols) or 'N/A'}；扩展组={','.join(available_extended_symbols) or 'N/A'}；"
                f"剔除={','.join(item.get('symbol', '') for item in excluded_peers) or 'N/A'}；"
                f"period_aligned={aligned_periods}。"
            ),
        )

        return TaskResult(
            task_id=task.task_id,
            agent_name=self.name,
            status=AgentStatus.COMPLETED,
            output={
                "claims": [claim.__dict__ if hasattr(claim, "__dict__") else claim],
                "evidence_records": peer_evidence_records,
            },
        )


def _load_local_peer_financial_evidence(
    raw_data_root: str,
    period: str,
    symbols: List[str],
) -> List[Dict[str, Any]]:
    root = Path(raw_data_root)
    wanted = {str(symbol or "").upper() for symbol in symbols if str(symbol or "").strip()}
    records: List[Dict[str, Any]] = []
    if not root.exists() or not wanted:
        return records
    for symbol in wanted:
        symbol_dir = root / symbol
        if not symbol_dir.exists():
            continue
        period_dir = symbol_dir / period
        if not period_dir.exists():
            candidates = sorted([path for path in symbol_dir.iterdir() if path.is_dir()], reverse=True)
            period_dir = candidates[0] if candidates else period_dir
        financials_path = period_dir / "financials.csv"
        if not financials_path.exists():
            continue
        with financials_path.open("r", encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                evidence_id = f"{symbol}_{period_dir.name}_financials_local"
                records.append(
                    {
                        "evidence_id": evidence_id,
                        "sample_id": evidence_id,
                        "symbol": symbol,
                        "period": str(row.get("period") or period_dir.name),
                        "source_type": "financials",
                        "title": f"{symbol} {period_dir.name} structured financial summary",
                        "content": (
                            f"Revenue {row.get('revenue_billion')}B, revenue growth {row.get('revenue_growth_pct')}%, "
                            f"gross margin {row.get('gross_margin_pct')}%, net margin {row.get('net_margin_pct')}%, "
                            f"ROE {row.get('roe_pct')}%, operating cash flow {row.get('operating_cash_flow_billion')}B. "
                            f"{row.get('notes', '')}"
                        ),
                        "source_url": str(row.get("source_url") or ""),
                        "publish_time": str(row.get("publish_time") or ""),
                        "trust_level": str(row.get("trust_level") or "high"),
                        "metadata": dict(row),
                    }
                )
    return records
