"""Entity resolution for natural-language financial research requests."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any, Dict, List

from src.data.company_universe import resolve_company_identifier_with_diagnostics


@dataclass(frozen=True)
class EntityResolutionResult:
    company_name: str
    symbol: str
    market: str
    confidence: float
    candidates: List[Dict[str, Any]]
    ambiguous: bool = False
    reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "company_name": self.company_name,
            "symbol": self.symbol,
            "market": self.market,
            "confidence": round(float(self.confidence), 3),
            "candidates": list(self.candidates),
            "ambiguous": bool(self.ambiguous),
            "reason": self.reason,
        }


_BUILTIN_ENTITIES: List[Dict[str, Any]] = [
    {"company_name": "NVIDIA Corporation", "symbol": "NVDA", "market": "US", "aliases": ["英伟达", "辉达", "nvidia", "nvda"]},
    {"company_name": "Apple Inc.", "symbol": "AAPL", "market": "US", "aliases": ["苹果公司", "apple inc", "aapl"]},
    {"company_name": "Kweichow Moutai Co., Ltd.", "symbol": "600519.SS", "market": "CN-A", "aliases": ["贵州茅台", "茅台", "kweichow moutai", "600519"]},
    {"company_name": "China Merchants Bank Co., Ltd. A Share", "symbol": "600036.SS", "market": "CN-A", "aliases": ["招商银行", "招行", "cmb", "600036"]},
    {"company_name": "China Merchants Bank Co., Ltd. H Share", "symbol": "3968.HK", "market": "HK", "aliases": ["招商银行", "招行", "cmb", "3968"]},
    {"company_name": "Tencent Holdings Limited", "symbol": "0700.HK", "market": "HK", "aliases": ["腾讯", "腾讯控股", "tencent", "0700"]},
]

_AMBIGUOUS_PRODUCT_TERMS = {
    "苹果": [
        {"company_name": "Apple Inc.", "symbol": "AAPL", "market": "US", "confidence": 0.72},
        {"company_name": "苹果品类/商品", "symbol": "", "market": "commodity_or_product", "confidence": 0.42},
    ]
}


class EntityResolver:
    def __init__(self, raw_data_root: str | Path = "data/raw/real_data"):
        self.raw_data_root = raw_data_root

    def resolve(self, query: str) -> EntityResolutionResult:
        text = str(query or "").strip()
        if not text:
            return EntityResolutionResult("", "", "", 0.0, [], reason="empty_query")

        builtin = self._resolve_builtin(text)
        if builtin:
            return builtin

        diagnostics = resolve_company_identifier_with_diagnostics(text, raw_data_root=self.raw_data_root)
        if diagnostics.get("resolved"):
            symbol = str(diagnostics.get("symbol", "")).upper()
            return EntityResolutionResult(
                company_name=str(diagnostics.get("company_name", "")),
                symbol=symbol,
                market=infer_market(symbol),
                confidence=float(diagnostics.get("confidence", 0.0) or 0.0),
                candidates=[_candidate_from_diagnostics(diagnostics)],
                ambiguous=bool(diagnostics.get("ambiguous", False)),
                reason=str(diagnostics.get("match_type", "company_universe")),
            )

        ticker = _explicit_ticker(text)
        if ticker:
            return EntityResolutionResult(
                company_name=ticker,
                symbol=ticker,
                market=infer_market(ticker),
                confidence=0.86,
                candidates=[{"company_name": ticker, "symbol": ticker, "market": infer_market(ticker), "confidence": 0.86}],
                reason="explicit_ticker",
            )

        return EntityResolutionResult("", "", "", 0.0, [], reason=str(diagnostics.get("reason", "no_match")))

    def _resolve_builtin(self, text: str) -> EntityResolutionResult | None:
        normalized = _normalize(text)
        candidates: List[Dict[str, Any]] = []
        for item in _BUILTIN_ENTITIES:
            aliases = [str(alias) for alias in item.get("aliases", [])]
            if any(_normalize(alias) and _normalize(alias) in normalized for alias in aliases):
                score = _alias_score(text, aliases)
                candidates.append(
                    {
                        "company_name": item["company_name"],
                        "symbol": item["symbol"],
                        "market": item["market"],
                        "confidence": score,
                    }
                )

        if not candidates:
            for term, term_candidates in _AMBIGUOUS_PRODUCT_TERMS.items():
                if term in text:
                    return EntityResolutionResult(
                        company_name="",
                        symbol="",
                        market="",
                        confidence=0.0,
                        candidates=term_candidates,
                        ambiguous=True,
                        reason="product_company_ambiguous",
                    )
            return None

        candidates.sort(key=lambda item: float(item.get("confidence", 0.0)), reverse=True)
        best = candidates[0]
        same_alias_ambiguous = len(candidates) > 1 and float(best.get("confidence", 0.0)) - float(candidates[1].get("confidence", 0.0)) < 0.08
        explicit_market = _explicit_market_hint(text)
        if explicit_market:
            market_matches = [candidate for candidate in candidates if candidate.get("market") == explicit_market]
            if market_matches:
                best = market_matches[0]
                same_alias_ambiguous = False

        return EntityResolutionResult(
            company_name=str(best.get("company_name", "")),
            symbol=str(best.get("symbol", "")).upper(),
            market=str(best.get("market", "")),
            confidence=float(best.get("confidence", 0.0)),
            candidates=candidates,
            ambiguous=same_alias_ambiguous,
            reason="builtin_alias_ambiguous" if same_alias_ambiguous else "builtin_alias",
        )


def infer_market(symbol: str) -> str:
    value = str(symbol or "").upper()
    if value.endswith(".HK") or re.fullmatch(r"\d{4}\.HK", value):
        return "HK"
    if value.endswith(".SS") or value.endswith(".SH") or value.endswith(".SZ") or re.fullmatch(r"[036]\d{5}", value):
        return "CN-A"
    if value:
        return "US"
    return ""


def _candidate_from_diagnostics(payload: Dict[str, Any]) -> Dict[str, Any]:
    symbol = str(payload.get("symbol", "")).upper()
    return {
        "company_name": str(payload.get("company_name", "")),
        "symbol": symbol,
        "market": infer_market(symbol),
        "confidence": float(payload.get("confidence", 0.0) or 0.0),
    }


def _explicit_ticker(text: str) -> str:
    hk = re.search(r"\b(\d{4}\.HK)\b", text, flags=re.I)
    if hk:
        return hk.group(1).upper()
    cn = re.search(r"\b([036]\d{5}\.(?:SS|SH|SZ))\b", text, flags=re.I)
    if cn:
        return cn.group(1).upper()
    us = re.search(r"\b([A-Z]{1,5})\b", text)
    if us and us.group(1) not in {"A", "H", "FY", "TTM"}:
        return us.group(1).upper()
    return ""


def _explicit_market_hint(text: str) -> str:
    lowered = text.lower()
    if "港股" in text or "h股" in lowered or " hk" in lowered:
        return "HK"
    if "a股" in lowered or "上交所" in text or "深交所" in text:
        return "CN-A"
    if "美股" in text or "纳斯达克" in text or "nyse" in lowered or "nasdaq" in lowered:
        return "US"
    return ""


def _alias_score(text: str, aliases: List[str]) -> float:
    normalized = _normalize(text)
    best = 0.0
    for alias in aliases:
        compact = _normalize(alias)
        if not compact:
            continue
        if compact == normalized:
            best = max(best, 1.0)
        elif compact in normalized:
            best = max(best, min(0.96, 0.78 + len(compact) / max(len(normalized), 1) * 0.16))
    return round(best or 0.75, 3)


def _normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9一-鿿]+", "", value.lower())
