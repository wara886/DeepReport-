"""Search manager for financial research agents."""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from logging import getLogger
import re
import socket
from pathlib import Path
from typing import Any, Callable, Dict, List
from urllib import error, parse, request

import pandas as pd

from src.data.company_universe import resolve_company_identifier, resolve_symbol
from src.data.independent_sources import fetch_macro_evidence, fetch_sec_companyfacts_evidence
from src.data.source_quality import apply_source_quality
from src.data.yahoo_finance import yahoo_financials_to_evidence, yahoo_snapshot_to_evidence

logger = getLogger(__name__)
from src.retrieval.chunking import chunk_records
from src.retrieval.retrieve import retrieve_evidence_with_mode
from src.utils.config import load_config
from src.utils.env import load_env_files, resolve_config_value


SearchHandler = Callable[..., Dict[str, Any]]


@dataclass
class SearchResult:
    """Normalized search hit returned by SearchManager."""

    result_id: str
    engine: str
    title: str = ""
    snippet: str = ""
    url: str = ""
    score: float = 0.0
    source_type: str = ""
    source_authority: str = ""
    authority_level: str = ""
    source_document_type: str = ""
    authority_score: float = 0.0
    raw: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "result_id": self.result_id,
            "engine": self.engine,
            "title": self.title,
            "snippet": self.snippet,
            "url": self.url,
            "score": self.score,
            "source_type": self.source_type,
            "source_authority": self.source_authority,
            "authority_level": self.authority_level,
            "source_document_type": self.source_document_type,
            "authority_score": self.authority_score,
            "raw": dict(self.raw),
        }


class SearchManager:
    """Aggregate local and remote search engines behind one contract."""

    def __init__(self):
        self._engines: Dict[str, SearchHandler] = {}

    @classmethod
    def with_local_evidence(cls) -> "SearchManager":
        manager = cls()
        manager.register_engine("local_evidence", local_evidence_search)
        return manager

    @classmethod
    def with_local_sources(cls) -> "SearchManager":
        load_env_files(config_path="configs/data_sources.yaml")
        manager = cls()
        manager.register_engine("local_real_data", local_real_data_search)
        manager.register_engine("independent_macro", independent_macro_search)
        manager.register_engine("sec_edgar", sec_edgar_search)
        manager.register_engine("yahoo_finance", yahoo_finance_search)
        manager.register_engine("eastmoney", eastmoney_search)
        manager.register_engine("cninfo_announcements", cninfo_announcement_search)
        manager.register_engine("exchange_announcements", exchange_announcement_search)
        manager.register_engine("eastmoney_financials", eastmoney_financials_search)
        manager.register_engine("hkex_announcements", hkex_announcement_search)
        manager.register_engine("serper", serper_search)
        manager.register_engine("tavily", tavily_search)
        manager.register_engine("metaso", metaso_search)
        manager.register_engine("sogou", sogou_search)
        manager.register_engine("local_evidence", local_evidence_search)
        return manager

    def register_engine(self, name: str, handler: SearchHandler) -> None:
        if name in self._engines:
            raise ValueError(f"search engine already registered: {name}")
        self._engines[name] = handler

    def engine_names(self) -> List[str]:
        return sorted(self._engines.keys())

    def search(
        self,
        query: str,
        topk: int = 5,
        engines: List[str] | None = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        selected = engines or self.engine_names()
        all_hits: List[SearchResult] = []
        engine_meta: Dict[str, Any] = {}

        for engine in selected:
            if engine not in self._engines:
                engine_meta[engine] = {"error": f"engine not registered: {engine}"}
                continue
            try:
                payload = self._engines[engine](query=query, topk=topk, **kwargs)
                raw_hits = payload.get("hits", [])
                engine_meta[engine] = payload.get("meta", {})
                all_hits.extend(_normalize_hits(engine, raw_hits))
            except Exception as exc:
                engine_meta[engine] = {"error": str(exc)}

        hits = _dedupe_and_rank(all_hits, topk=topk)
        return {
            "query": query,
            "hits": [hit.to_dict() for hit in hits],
            "meta": {
                "engines": selected,
                "engine_meta": engine_meta,
                "total_hits_before_dedupe": len(all_hits),
                "returned_hits": len(hits),
            },
        }


def local_evidence_search(
    query: str,
    topk: int = 5,
    symbol: str | None = None,
    period: str | None = None,
    curated_dir: str = "data/curated",
    ranking_mode: str = "bm25",
    reranker_checkpoint_path: str = "data/outputs/checkpoints/reranker_checkpoint.json",
    use_chunks: bool = True,
    raw_data_root: str = "data/raw/real_data",
    **_: Any,
) -> Dict[str, Any]:
    query_info = adapt_financial_query(query=query, symbol=symbol, period=period, raw_data_root=raw_data_root)
    hits, meta = retrieve_evidence_with_mode(
        query=query_info["adapted_query"],
        topk=topk,
        symbol=symbol,
        period=period,
        curated_dir=curated_dir,
        ranking_mode=ranking_mode,
        reranker_checkpoint_path=reranker_checkpoint_path,
        use_chunks=use_chunks,
        log=False,
    )
    meta.update(query_info)
    return {"hits": hits, "meta": meta}


def local_real_data_search(
    query: str,
    topk: int = 5,
    symbol: str | None = None,
    period: str | None = None,
    raw_data_root: str = "data/raw/real_data",
    use_chunks: bool = True,
    **_: Any,
) -> Dict[str, Any]:
    resolved_symbol = resolve_symbol(symbol or query, raw_data_root=raw_data_root, default=symbol or "")
    query_info = adapt_financial_query(query=query, symbol=resolved_symbol or symbol, period=period, raw_data_root=raw_data_root)
    records = _load_real_data_records(raw_data_root=raw_data_root, symbol=resolved_symbol or symbol, period=period)
    if use_chunks:
        records = [chunk.to_dict() for chunk in chunk_records(records)]
    scored = []
    for item in records:
        row = dict(item)
        row["score"] = _score_record(query=query_info["adapted_query"], item=row)
        scored.append(row)
    scored.sort(key=lambda item: float(item.get("score", 0.0)), reverse=True)
    returned = scored[:topk]
    return {
        "hits": returned,
        "meta": {
            "mode": "local_real_data",
            "raw_data_root": raw_data_root,
            "symbol": resolved_symbol or symbol or "",
            "period": period or "",
            "record_count": len(records),
            "returned_hit_count": len(returned),
            "failure_reason": _local_search_failure_reason(records=records, hits=returned, symbol=resolved_symbol or symbol, period=period),
            "chunking_enabled": use_chunks,
            **query_info,
        },
    }


def tavily_search(
    query: str,
    topk: int = 5,
    data_source_config_path: str = "configs/data_sources.yaml",
    symbol: str | None = None,
    period: str | None = None,
    raw_data_root: str = "data/raw/real_data",
    **_: Any,
) -> Dict[str, Any]:
    config = load_config(data_source_config_path)
    tavily_cfg = dict(config.get("search", {}).get("tavily", {}))
    load_env_files(config_path=data_source_config_path)

    api_key = str(resolve_config_value(tavily_cfg, "api_key", "")).strip()
    if not api_key:
        return {"hits": [], "meta": {"mode": "tavily", "query": query, "failure_reason": "missing_api_key"}}

    base_url = str(tavily_cfg.get("base_url") or "https://api.tavily.com/search").rstrip("/")
    search_depth = str(tavily_cfg.get("default_depth") or "basic")
    max_results = int(tavily_cfg.get("max_results") or topk)
    max_results = min(max(topk, 1), max_results) if max_results > 0 else topk

    payload = {
        "query": query,
        "search_depth": search_depth,
        "max_results": max_results,
        "include_answer": False,
        "include_raw_content": False,
    }
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = request.Request(base_url, data=body, headers=headers, method="POST")

    try:
        with request.urlopen(req, timeout=20) as resp:
            raw = resp.read().decode("utf-8")
    except (TimeoutError, socket.timeout) as exc:
        raise RuntimeError("Tavily search timed out") from exc
    except error.HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Tavily HTTP {exc.code}: {error_body}") from exc
    except error.URLError as exc:
        raise RuntimeError(f"Tavily URL error: {exc.reason}") from exc

    parsed = json.loads(raw)
    results = parsed.get("results", [])
    if not isinstance(results, list):
        results = []
    resolved_symbol = resolve_symbol(symbol or query, raw_data_root=raw_data_root, default=symbol or _extract_symbol_from_query(query) or "")
    resolved_profile = resolve_company_identifier(resolved_symbol or query, raw_data_root=raw_data_root)
    hits = []
    for index, item in enumerate(results, start=1):
        if not isinstance(item, dict):
            continue
        url = str(item.get("url", ""))
        title = str(item.get("title") or url or f"tavily_result_{index}")
        content = str(item.get("content") or "")
        hits.append(
            {
                "evidence_id": f"tavily_{hashlib.sha1(url.encode('utf-8')).hexdigest()[:10]}",
                "source_type": "web_search",
                "title": title,
                "content": content,
                "source_url": url,
                "url": url,
                "symbol": resolved_symbol,
                "period": str(period or ""),
                "publish_time": "",
                "trust_level": "medium",
                "score": _safe_float(item.get("score", 0.0)),
                "metadata": {
                    "engine": "tavily",
                    "company_name": str(resolved_profile.get("company_name", "")),
                    "favicon": item.get("favicon"),
                    "raw_content_present": item.get("raw_content") is not None,
                },
            }
        )
    hits = [apply_source_quality(hit) for hit in hits]
    return {
        "hits": hits[:topk],
        "meta": {
            "mode": "tavily",
            "search_depth": search_depth,
            "request_id": parsed.get("request_id", ""),
            "response_time": parsed.get("response_time", ""),
            "result_count": len(hits),
        },
    }


def hkex_announcement_search(
    query: str,
    topk: int = 5,
    data_source_config_path: str = "configs/data_sources.yaml",
    symbol: str | None = None,
    period: str | None = None,
    raw_data_root: str = "data/raw/real_data",
    **kwargs: Any,
) -> Dict[str, Any]:
    """Best-effort free HKEX disclosure search via configured public search."""

    hk_query = f"site:hkexnews.hk {symbol or ''} {period or ''} annual report announcement {query}".strip()
    payload = tavily_search(
        query=hk_query,
        topk=topk,
        data_source_config_path=data_source_config_path,
        symbol=symbol,
        period=period,
        raw_data_root=raw_data_root,
        **kwargs,
    )
    hits = []
    rejected_identity_count = 0
    for item in payload.get("hits", []) if isinstance(payload, dict) else []:
        if not isinstance(item, dict):
            continue
        row = dict(item)
        row["source_type"] = "hkex_announcement"
        row["trust_level"] = "high"
        row.setdefault("metadata", {})
        if isinstance(row["metadata"], dict):
            row["metadata"]["engine"] = "hkex_announcements"
        if not _record_matches_requested_company(row, symbol=symbol, raw_data_root=raw_data_root):
            rejected_identity_count += 1
            continue
        hits.append(apply_source_quality(row))
    meta = dict(payload.get("meta", {})) if isinstance(payload, dict) else {}
    original_mode = meta.get("mode", "tavily")
    meta["mode"] = "hkex_announcements"
    meta["via"] = original_mode
    meta["result_count"] = len(hits)
    meta["identity_rejected_count"] = rejected_identity_count
    return {"hits": hits[:topk], "meta": meta}


def serper_search(
    query: str,
    topk: int = 5,
    data_source_config_path: str = "configs/data_sources.yaml",
    symbol: str | None = None,
    period: str | None = None,
    raw_data_root: str = "data/raw/real_data",
    **_: Any,
) -> Dict[str, Any]:
    config = load_config(data_source_config_path)
    serper_cfg = dict(config.get("search", {}).get("serper", {}))
    load_env_files(config_path=data_source_config_path)

    api_key = str(resolve_config_value(serper_cfg, "api_key", "")).strip()
    if not api_key:
        raise RuntimeError("missing Serper API key: set SERPER_API_KEY in .env")

    base_url = str(serper_cfg.get("base_url") or "https://google.serper.dev/search").rstrip("/")
    max_results = int(serper_cfg.get("max_results") or topk)
    max_results = min(max(topk, 1), max_results) if max_results > 0 else topk
    payload = {
        "q": query,
        "num": max_results,
        "gl": str(serper_cfg.get("gl") or "us"),
        "hl": str(serper_cfg.get("hl") or "en"),
    }
    headers = {
        "Content-Type": "application/json",
        "X-API-KEY": api_key,
    }
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = request.Request(base_url, data=body, headers=headers, method="POST")

    try:
        with request.urlopen(req, timeout=20) as resp:
            raw = resp.read().decode("utf-8")
    except (TimeoutError, socket.timeout) as exc:
        raise RuntimeError("Serper search timed out") from exc
    except error.HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Serper HTTP {exc.code}: {error_body}") from exc
    except error.URLError as exc:
        raise RuntimeError(f"Serper URL error: {exc.reason}") from exc

    parsed = json.loads(raw)
    organic = parsed.get("organic", [])
    if not isinstance(organic, list):
        organic = []
    resolved_symbol = resolve_symbol(symbol or query, raw_data_root=raw_data_root, default=symbol or _extract_symbol_from_query(query) or "")
    hits = []
    for index, item in enumerate(organic, start=1):
        if not isinstance(item, dict):
            continue
        url = str(item.get("link") or "")
        title = str(item.get("title") or url or f"serper_result_{index}")
        snippet = str(item.get("snippet") or "")
        hits.append(
            {
                "evidence_id": f"serper_{hashlib.sha1(url.encode('utf-8')).hexdigest()[:10]}",
                "source_type": "web_search",
                "title": title,
                "content": snippet,
                "source_url": url,
                "url": url,
                "symbol": resolved_symbol,
                "period": str(period or ""),
                "publish_time": str(item.get("date") or ""),
                "trust_level": "medium",
                "score": max(0.0, float(max_results - index + 1)) / max(max_results, 1),
                "metadata": {
                    "engine": "serper",
                    "position": item.get("position", index),
                    "sitelinks": item.get("sitelinks", []),
                },
            }
        )
    hits = [apply_source_quality(hit) for hit in hits]
    return {
        "hits": hits[:topk],
        "meta": {
            "mode": "serper",
            "result_count": len(hits),
            "search_parameters": parsed.get("searchParameters", {}),
        },
    }


def metaso_search(
    query: str,
    topk: int = 5,
    data_source_config_path: str = "configs/data_sources.yaml",
    symbol: str | None = None,
    period: str | None = None,
    raw_data_root: str = "data/raw/real_data",
    **_: Any,
) -> Dict[str, Any]:
    config = load_config(data_source_config_path)
    metaso_cfg = dict(config.get("search", {}).get("metaso", {}))
    load_env_files(config_path=data_source_config_path)

    api_key = str(resolve_config_value(metaso_cfg, "api_key", "")).strip()
    if not api_key:
        raise RuntimeError("missing Metaso API key: set METASO_API_KEY in .env")

    max_results = int(metaso_cfg.get("max_results") or topk)
    max_results = min(max(topk, 1), max_results) if max_results > 0 else topk
    payload = {
        "query": query,
        "limit": max_results,
        "offset": 0,
        "language": str(metaso_cfg.get("language") or "zh-cn"),
        "region": str(metaso_cfg.get("region") or "cn"),
    }
    parsed = _post_json_search(
        base_url=str(metaso_cfg.get("base_url") or "https://api.metaso.com/v1/search").rstrip("/"),
        payload=payload,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        timeout=float(metaso_cfg.get("timeout", 20)),
        engine="metaso",
    )
    items = _coerce_search_items(parsed, keys=["results", "data", "items"])
    resolved_symbol = resolve_symbol(symbol or query, raw_data_root=raw_data_root, default=symbol or _extract_symbol_from_query(query) or "")
    hits = []
    for index, item in enumerate(items[:max_results], start=1):
        url = str(item.get("url") or item.get("link") or "")
        title = str(item.get("title") or url or f"metaso_result_{index}")
        snippet = str(item.get("description") or item.get("snippet") or item.get("abstract") or item.get("content") or "")
        hits.append(
            {
                "evidence_id": _search_evidence_id("metaso", url, title, index),
                "source_type": "web_search",
                "title": title,
                "content": snippet,
                "source_url": url,
                "url": url,
                "symbol": resolved_symbol,
                "period": str(period or ""),
                "publish_time": str(item.get("publishedDate") or item.get("published_date") or item.get("date") or ""),
                "trust_level": "medium",
                "score": _safe_float(item.get("score", max_results - index + 1)),
                "metadata": {
                    "engine": "metaso",
                    "position": item.get("rank", index),
                    "author": item.get("author", ""),
                    "categories": item.get("categories", []),
                },
            }
        )
    hits = [apply_source_quality(hit) for hit in hits]
    return {
        "hits": hits[:topk],
        "meta": {"mode": "metaso", "result_count": len(hits)},
    }


def sogou_search(
    query: str,
    topk: int = 5,
    data_source_config_path: str = "configs/data_sources.yaml",
    symbol: str | None = None,
    period: str | None = None,
    raw_data_root: str = "data/raw/real_data",
    **_: Any,
) -> Dict[str, Any]:
    config = load_config(data_source_config_path)
    sogou_cfg = dict(config.get("search", {}).get("sogou", {}))
    load_env_files(config_path=data_source_config_path)

    api_key = str(resolve_config_value(sogou_cfg, "api_key", "")).strip()
    if not api_key:
        raise RuntimeError("missing Sogou API key: set SOGOU_API_KEY in .env")

    max_results = int(sogou_cfg.get("max_results") or topk)
    max_results = min(max(topk, 1), max_results) if max_results > 0 else topk
    payload = {
        "query": query,
        "count": max_results,
        "start": 0,
        "language": str(sogou_cfg.get("language") or "zh-cn"),
    }
    parsed = _post_json_search(
        base_url=str(sogou_cfg.get("base_url") or "https://api.sogou.com/v1/search").rstrip("/"),
        payload=payload,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        timeout=float(sogou_cfg.get("timeout", 20)),
        engine="sogou",
    )
    items = _coerce_search_items(parsed, keys=["items", "results", "data"])
    resolved_symbol = resolve_symbol(symbol or query, raw_data_root=raw_data_root, default=symbol or _extract_symbol_from_query(query) or "")
    hits = []
    for index, item in enumerate(items[:max_results], start=1):
        url = str(item.get("url") or item.get("link") or "")
        title = str(item.get("title") or item.get("name") or url or f"sogou_result_{index}")
        snippet = str(item.get("abstract") or item.get("snippet") or item.get("description") or item.get("content") or "")
        hits.append(
            {
                "evidence_id": _search_evidence_id("sogou", url, title, index),
                "source_type": "web_search",
                "title": title,
                "content": snippet,
                "source_url": url,
                "url": url,
                "symbol": resolved_symbol,
                "period": str(period or ""),
                "publish_time": str(item.get("date") or item.get("publishedDate") or ""),
                "trust_level": "medium",
                "score": _safe_float(item.get("score", max_results - index + 1)),
                "metadata": {
                    "engine": "sogou",
                    "position": item.get("rank", item.get("position", index)),
                    "display_url": item.get("displayUrl", item.get("display_url", "")),
                },
            }
        )
    return {
        "hits": hits[:topk],
        "meta": {"mode": "sogou", "result_count": len(hits)},
    }


def yahoo_finance_search(
    query: str,
    topk: int = 5,
    symbol: str | None = None,
    period: str | None = None,
    range_: str = "1mo",
    interval: str = "1d",
    raw_data_root: str = "data/raw/real_data",
    **_: Any,
) -> Dict[str, Any]:
    resolved_symbol = resolve_symbol(symbol or query, raw_data_root=raw_data_root, default=symbol or _extract_symbol_from_query(query) or "")
    resolved_symbol = resolved_symbol.strip().upper()
    if not resolved_symbol:
        return {
            "hits": [],
            "meta": {"mode": "yahoo_finance", "error": "symbol is required for Yahoo Finance search"},
        }
    snapshot = yahoo_snapshot_to_evidence(
        symbol=resolved_symbol,
        period=period or "",
        range_=range_,
        interval=interval,
    )
    hits = [snapshot]
    try:
        financials = yahoo_financials_to_evidence(symbol=resolved_symbol, period=period or "")
        if financials:
            hits.append(financials)
        else:
            logger.warning("yahoo_financials_to_evidence returned None for %s", resolved_symbol)
    except Exception as exc:
        logger.warning("yahoo_financials_to_evidence failed for %s: %s", resolved_symbol, exc)
    return {
        "hits": hits[:topk],
        "meta": {
            "mode": "yahoo_finance",
            "symbol": resolved_symbol,
            "range": range_,
            "interval": interval,
            "result_count": len(hits),
            "has_financials": len(hits) > 1,
        },
    }


def eastmoney_search(
    query: str,
    topk: int = 5,
    symbol: str | None = None,
    period: str | None = None,
    raw_data_root: str = "data/raw/real_data",
    **_: Any,
) -> Dict[str, Any]:
    resolved_symbol = resolve_symbol(symbol or query, raw_data_root=raw_data_root, default=symbol or _extract_symbol_from_query(query) or "")
    secid = _eastmoney_secid(resolved_symbol)
    if not secid:
        return {
            "hits": [],
            "meta": {"mode": "eastmoney", "symbol": resolved_symbol or "", "record_count": 0, "failure_reason": "unsupported_symbol"},
        }
    fields = "f57,f58,f43,f44,f45,f46,f47,f48,f60,f116,f117,f162,f167,f168,f170,f173"
    url = f"https://push2.eastmoney.com/api/qt/stock/get?{parse.urlencode({'secid': secid, 'fields': fields})}"
    headers = {
        "User-Agent": "Mozilla/5.0 DeepReportPlus/0.1",
        "Accept": "application/json,text/plain,*/*",
        "Referer": "https://quote.eastmoney.com/",
    }
    raw = ""
    last_error = ""
    for _attempt in range(2):
        req = request.Request(url, headers=headers, method="GET")
        try:
            with request.urlopen(req, timeout=12) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
            break
        except (TimeoutError, socket.timeout):
            last_error = "Eastmoney quote timed out"
        except error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            last_error = f"Eastmoney HTTP {exc.code}: {body[:300]}"
        except error.URLError as exc:
            last_error = f"Eastmoney URL error: {exc.reason}"
        except Exception as exc:
            last_error = f"Eastmoney request error: {exc}"
    if not raw:
        return {
            "hits": [],
            "meta": {"mode": "eastmoney", "symbol": resolved_symbol or "", "record_count": 0, "failure_reason": "fetch_error", "error": last_error or "Eastmoney quote failed"},
        }
    parsed = json.loads(raw)
    data = parsed.get("data") if isinstance(parsed, dict) else {}
    if not isinstance(data, dict) or not data:
        return {
            "hits": [],
            "meta": {"mode": "eastmoney", "symbol": resolved_symbol or "", "record_count": 0, "failure_reason": "no_quote_data"},
        }
    code = str(data.get("f57") or resolved_symbol or "")
    name = str(data.get("f58") or code)
    price = _eastmoney_scaled(data.get("f43"))
    prev_close = _eastmoney_scaled(data.get("f60"))
    change_pct = _eastmoney_scaled(data.get("f170"))
    volume = _safe_float(data.get("f47"))
    market_cap = _eastmoney_scaled(data.get("f116"), scale=100000000.0)
    pe_ttm = _eastmoney_scaled(data.get("f162"))
    pb = _eastmoney_scaled(data.get("f167"))
    ps = _eastmoney_scaled(data.get("f168"))
    content = (
        f"Eastmoney A-share quote for {name} ({code}): latest price {price}, previous close {prev_close}, "
        f"change_pct {change_pct}%, volume {volume}, market_cap_billion_cny {market_cap}, "
        f"pe_ttm {pe_ttm}, pb {pb}, ps {ps}."
    )
    digest = hashlib.sha1(f"{code}|{period}|{content}".encode("utf-8")).hexdigest()[:10]
    hit = {
        "evidence_id": f"{code}_{period or 'latest'}_eastmoney_{digest}",
        "sample_id": f"{code}_{period or 'latest'}_eastmoney_{digest}",
        "symbol": resolved_symbol or code,
        "period": str(period or ""),
        "source_type": "market_api",
        "title": f"{name} Eastmoney A-share quote",
        "content": content,
        "source_url": f"https://quote.eastmoney.com/{code}.html",
        "publish_time": "",
        "trust_level": "medium",
        "score": 5.8,
        "metadata": {
            "provider": "Eastmoney",
            "secid": secid,
            "code": code,
            "company_name": name,
            "market_cap_billion_cny": market_cap,
            "pe_ttm": pe_ttm,
            "pb": pb,
            "ps": ps,
            "raw": data,
        },
    }
    return {"hits": [hit][:topk], "meta": {"mode": "eastmoney", "symbol": resolved_symbol or code, "record_count": 1, "failure_reason": ""}}


def cninfo_announcement_search(
    query: str,
    topk: int = 5,
    symbol: str | None = None,
    period: str | None = None,
    raw_data_root: str = "data/raw/real_data",
    data_source_config_path: str = "configs/data_sources.yaml",
    enable_remote: bool = False,
    **_: Any,
) -> Dict[str, Any]:
    if not enable_remote:
        return {
            "hits": [],
            "meta": {"mode": "cninfo_announcements", "query": query, "record_count": 0, "failure_reason": "remote_sources_disabled"},
        }
    config = load_config(data_source_config_path)
    cninfo_cfg = dict(config.get("independent_sources", {}).get("company", {}).get("cninfo", {}))
    resolved_symbol = resolve_symbol(symbol or query, raw_data_root=raw_data_root, default=symbol or _extract_symbol_from_query(query) or _extract_cn_symbol(query))
    code = _cn_stock_code(resolved_symbol)
    if not code:
        return {"hits": [], "meta": {"mode": "cninfo_announcements", "query": query, "record_count": 0, "failure_reason": "unsupported_symbol"}}
    query_url = str(cninfo_cfg.get("announcement_query_url") or "http://www.cninfo.com.cn/new/hisAnnouncement/query")
    static_base = str(cninfo_cfg.get("static_base_url") or "http://static.cninfo.com.cn/")
    page_size = int(cninfo_cfg.get("page_size", max(topk, 10)) or max(topk, 10))
    timeout = float(cninfo_cfg.get("timeout", 15) or 15)
    org_id = _cninfo_org_id(code=code, config=cninfo_cfg, timeout=timeout)
    column = "sse" if _is_sh_symbol(resolved_symbol or code) else "szse"
    start_date, end_date = _announcement_date_range(period)
    categories = ";".join(_cninfo_categories_for_period(period, cninfo_cfg))
    form = {
        "stock": f"{code},{org_id}" if org_id else code,
        "searchkey": "",
        "plate": "",
        "category": categories,
        "trade": "",
        "column": column,
        "pageNum": "1",
        "pageSize": str(max(page_size, topk)),
        "tabName": "fulltext",
        "sortName": "",
        "sortType": "",
        "limit": "",
        "showTitle": "",
        "seDate": f"{start_date}~{end_date}" if start_date and end_date else "",
        "isHLtitle": "true",
    }
    headers = {
        "User-Agent": "Mozilla/5.0 DeepReportPlus/0.1",
        "Accept": "application/json,text/plain,*/*",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": "http://www.cninfo.com.cn/new/commonUrl/pageOfSearch",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    }
    try:
        parsed = _post_form_json(query_url, form, headers=headers, timeout=timeout, engine="cninfo")
    except Exception as exc:
        return {"hits": [], "meta": {"mode": "cninfo_announcements", "symbol": resolved_symbol or code, "record_count": 0, "failure_reason": "fetch_error", "error": str(exc)}}
    announcements = parsed.get("announcements")
    if not isinstance(announcements, list):
        announcements = []
    hits: List[Dict[str, Any]] = []
    for item in announcements:
        if not isinstance(item, dict):
            continue
        title = _strip_html(str(item.get("announcementTitle") or item.get("title") or ""))
        adjunct = str(item.get("adjunctUrl") or "")
        source_url = parse.urljoin(static_base, adjunct) if adjunct else ""
        sec_code = str(item.get("secCode") or code)
        sec_name = str(item.get("secName") or item.get("securityName") or sec_code)
        publish_time = str(item.get("announcementTime") or item.get("announcementDate") or "")
        content = f"CNINFO official announcement for {sec_name} ({sec_code}): {title}. PDF/source: {source_url}"
        digest = hashlib.sha1(f"{sec_code}|{title}|{source_url}".encode("utf-8")).hexdigest()[:10]
        hits.append(
            {
                "evidence_id": f"{sec_code}_{period or 'latest'}_cninfo_{digest}",
                "sample_id": f"{sec_code}_{period or 'latest'}_cninfo_{digest}",
                "symbol": resolved_symbol or sec_code,
                "period": str(period or ""),
                "source_type": "cninfo_announcement",
                "title": title or f"{sec_name} CNINFO announcement",
                "content": content,
                "source_url": source_url or f"http://www.cninfo.com.cn/new/disclosure/stock?stockCode={sec_code}",
                "publish_time": publish_time,
                "trust_level": "high",
                "score": 7.2,
                "metadata": {"provider": "CNINFO", "sec_code": sec_code, "sec_name": sec_name, "raw": item},
            }
        )
    hits = _filter_period_announcement_hits([apply_source_quality(hit) for hit in hits], period)
    return {
        "hits": hits[:topk],
        "meta": {
            "mode": "cninfo_announcements",
            "symbol": resolved_symbol or code,
            "record_count": len(hits),
            "failure_reason": "" if hits else "no_announcements",
            "query": query,
        },
    }


def exchange_announcement_search(
    query: str,
    topk: int = 5,
    symbol: str | None = None,
    period: str | None = None,
    raw_data_root: str = "data/raw/real_data",
    data_source_config_path: str = "configs/data_sources.yaml",
    enable_remote: bool = False,
    **_: Any,
) -> Dict[str, Any]:
    if not enable_remote:
        return {
            "hits": [],
            "meta": {"mode": "exchange_announcements", "query": query, "record_count": 0, "failure_reason": "remote_sources_disabled"},
        }
    config = load_config(data_source_config_path)
    exchange_cfg = dict(config.get("independent_sources", {}).get("company", {}).get("exchange_announcements", {}))
    resolved_symbol = resolve_symbol(symbol or query, raw_data_root=raw_data_root, default=symbol or _extract_symbol_from_query(query) or _extract_cn_symbol(query))
    code = _cn_stock_code(resolved_symbol)
    if not code:
        return {"hits": [], "meta": {"mode": "exchange_announcements", "query": query, "record_count": 0, "failure_reason": "unsupported_symbol"}}
    if _is_sh_symbol(resolved_symbol or code):
        return _sse_announcement_search(code=code, period=period or "", topk=topk, query=query, config=exchange_cfg)
    return _szse_announcement_search(code=code, period=period or "", topk=topk, query=query, config=exchange_cfg)


def eastmoney_financials_search(
    query: str,
    topk: int = 5,
    symbol: str | None = None,
    period: str | None = None,
    raw_data_root: str = "data/raw/real_data",
    data_source_config_path: str = "configs/data_sources.yaml",
    enable_remote: bool = False,
    **_: Any,
) -> Dict[str, Any]:
    if not enable_remote:
        return {
            "hits": [],
            "meta": {"mode": "eastmoney_financials", "query": query, "record_count": 0, "failure_reason": "remote_sources_disabled"},
        }
    config = load_config(data_source_config_path)
    em_cfg = dict(config.get("independent_sources", {}).get("company", {}).get("eastmoney_financials", {}))
    resolved_symbol = resolve_symbol(symbol or query, raw_data_root=raw_data_root, default=symbol or _extract_symbol_from_query(query) or _extract_cn_symbol(query))
    code = _cn_stock_code(resolved_symbol)
    if not code:
        return {"hits": [], "meta": {"mode": "eastmoney_financials", "query": query, "record_count": 0, "failure_reason": "unsupported_symbol"}}
    base_url = str(em_cfg.get("base_url") or "https://datacenter-web.eastmoney.com/api/data/v1/get")
    timeout = float(em_cfg.get("timeout", 15) or 15)
    reports = em_cfg.get("reports", {}) if isinstance(em_cfg.get("reports"), dict) else {}
    report_map = {
        "income": str(reports.get("income") or "RPT_DMSK_FN_INCOME"),
        "balance": str(reports.get("balance") or "RPT_DMSK_FN_BALANCE"),
        "cashflow": str(reports.get("cashflow") or "RPT_DMSK_FN_CASHFLOW"),
    }
    hits: List[Dict[str, Any]] = []
    metas: Dict[str, Any] = {}
    for table_type, report_name in report_map.items():
        params = {
            "sortColumns": "REPORT_DATE",
            "sortTypes": "-1",
            "pageSize": str(em_cfg.get("page_size", 20) or 20),
            "pageNumber": "1",
            "reportName": report_name,
            "columns": "ALL",
            "filter": f'(SECURITY_CODE="{code}")',
        }
        url = f"{base_url}?{parse.urlencode(params)}"
        headers = {
            "User-Agent": "Mozilla/5.0 DeepReportPlus/0.1",
            "Accept": "application/json,text/plain,*/*",
            "Referer": "https://data.eastmoney.com/",
        }
        try:
            parsed = _get_json(url, headers=headers, timeout=timeout, engine="eastmoney_financials")
        except Exception as exc:
            metas[table_type] = {"failure_reason": "fetch_error", "error": str(exc)}
            continue
        rows = _coerce_search_items(parsed, keys=["data", "result", "items", "records"])
        if rows and isinstance(rows[0].get("SECURITY_CODE"), (str, int, float)):
            records = rows
        elif rows and isinstance(rows[0].get("data"), list):
            records = rows[0]["data"]
        else:
            result = parsed.get("result") if isinstance(parsed.get("result"), dict) else {}
            data = result.get("data") if isinstance(result, dict) else []
            records = data if isinstance(data, list) else []
        metas[table_type] = {"record_count": len(records), "report_name": report_name}
        if not records:
            continue
        row = _select_financial_row_for_period(records, period) or (records[0] if isinstance(records[0], dict) else {})
        title = f"{code} Eastmoney {table_type} financial table"
        summary = _summarize_eastmoney_financial_row(table_type, row)
        digest = hashlib.sha1(f"{code}|{table_type}|{json.dumps(row, ensure_ascii=False, sort_keys=True, default=str)}".encode("utf-8")).hexdigest()[:10]
        hits.append(
            {
                "evidence_id": f"{code}_{period or 'latest'}_eastmoney_financials_{table_type}_{digest}",
                "sample_id": f"{code}_{period or 'latest'}_eastmoney_financials_{table_type}_{digest}",
                "symbol": resolved_symbol or code,
                "period": str(period or row.get("REPORT_DATE") or ""),
                "source_type": "eastmoney_financials",
                "title": title,
                "content": summary,
                "source_url": f"https://data.eastmoney.com/bbsj/{code}.html",
                "publish_time": str(row.get("NOTICE_DATE") or row.get("REPORT_DATE") or ""),
                "trust_level": "high",
                "score": 8.6,
                "metadata": {"provider": "Eastmoney", "table_type": table_type, "report_name": report_name, "raw": row},
            }
        )
    hits = [apply_source_quality(hit) for hit in hits]
    return {
        "hits": hits[:topk],
        "meta": {
            "mode": "eastmoney_financials",
            "symbol": resolved_symbol or code,
            "record_count": len(hits),
            "failure_reason": "" if hits else "no_financial_table_rows",
            "tables": metas,
            "query": query,
        },
    }


def independent_macro_search(
    query: str,
    topk: int = 5,
    period: str | None = None,
    data_source_config_path: str = "configs/data_sources.yaml",
    enable_remote: bool = False,
    **_: Any,
) -> Dict[str, Any]:
    if not enable_remote:
        return {
            "hits": [],
            "meta": {"mode": "independent_macro", "query": query, "record_count": 0, "failure_reason": "remote_sources_disabled"},
        }
    payload = fetch_macro_evidence(period=period or "", config_path=data_source_config_path, topk=topk).to_dict()
    payload["meta"]["query"] = query
    return payload


def sec_edgar_search(
    query: str,
    topk: int = 5,
    symbol: str | None = None,
    period: str | None = None,
    data_source_config_path: str = "configs/data_sources.yaml",
    raw_data_root: str = "data/raw/real_data",
    enable_remote: bool = False,
    **_: Any,
) -> Dict[str, Any]:
    if not enable_remote:
        return {
            "hits": [],
            "meta": {"mode": "sec_companyfacts", "query": query, "record_count": 0, "failure_reason": "remote_sources_disabled"},
        }
    resolved_symbol = resolve_symbol(symbol or query, raw_data_root=raw_data_root, default=symbol or _extract_symbol_from_query(query) or "")
    payload = fetch_sec_companyfacts_evidence(
        symbol=resolved_symbol,
        period=period or "",
        config_path=data_source_config_path,
        raw_data_root=raw_data_root,
    ).to_dict()
    payload["hits"] = payload.get("hits", [])[:topk]
    payload["meta"]["query"] = query
    return payload


def _eastmoney_secid(symbol: str | None) -> str:
    text = str(symbol or "").strip().upper()
    if not text:
        return ""
    code = text.split(".")[0]
    if text.endswith(".SS") or text.startswith("SH"):
        return f"1.{code[-6:]}"
    if text.endswith(".SZ") or text.startswith("SZ"):
        return f"0.{code[-6:]}"
    if len(code) == 6 and code.isdigit():
        return f"{'1' if code.startswith('6') else '0'}.{code}"
    return ""


def _eastmoney_scaled(value: Any, scale: float = 100.0) -> float | None:
    number = _safe_float(value)
    if number is None:
        return None
    if number <= -1e8:
        return None
    return round(number / scale, 4)


def _cn_stock_code(symbol: str | None) -> str:
    text = str(symbol or "").strip().upper()
    if not text:
        return ""
    if "." in text:
        text = text.split(".")[0]
    if text.startswith(("SH", "SZ")):
        text = text[2:]
    return text[-6:] if len(text) >= 6 and text[-6:].isdigit() else ""


def _extract_cn_symbol(query: str) -> str:
    match = re_search_cn_symbol(query)
    return match or ""


def re_search_cn_symbol(text: str) -> str:
    import re

    match = re.search(r"(?<!\d)([036]\d{5})(?:\.(?:SS|SH|SZ))?(?!\d)", str(text or ""), flags=re.IGNORECASE)
    if not match:
        return ""
    code = match.group(1)
    suffix = ".SS" if code.startswith("6") else ".SZ"
    return f"{code}{suffix}"


def _is_sh_symbol(symbol: str) -> bool:
    text = str(symbol or "").upper()
    code = _cn_stock_code(text)
    return text.endswith(".SS") or text.startswith("SH") or code.startswith("6")


def _announcement_date_range(period: str | None) -> tuple[str, str]:
    text = str(period or "").strip().upper()
    year = _period_year(text)
    if not year:
        return "", ""
    next_year = str(int(year) + 1)
    if "Q1" in text:
        return f"{year}-03-01", f"{year}-06-30"
    if "Q2" in text or "H1" in text:
        return f"{year}-06-01", f"{year}-10-31"
    if "Q3" in text:
        return f"{year}-09-01", f"{year}-12-31"
    return f"{year}-01-01", f"{next_year}-12-31"


def _cninfo_categories_for_period(period: str | None, config: Dict[str, Any]) -> List[str]:
    text = str(period or "").strip().upper()
    if "Q4" in text or "FY" in text or "ANNUAL" in text:
        return ["category_ndbg_szsh"]
    configured = [str(item) for item in config.get("categories", []) if str(item).strip()]
    return configured or ["category_ndbg_szsh", "category_bndbg_szsh", "category_yjdbg_szsh", "category_sjdbg_szsh"]


def _filter_period_announcement_hits(hits: List[Dict[str, Any]], period: str | None) -> List[Dict[str, Any]]:
    text = str(period or "").strip().upper()
    if not hits or not ("Q4" in text or "FY" in text or "ANNUAL" in text):
        return hits
    year = _period_year(text)
    annual_terms = ("年度报告", "年报")
    exclude_terms = ("第一季度", "半年度", "第三季度", "一季度", "半年报", "三季度")
    filtered = [
        hit
        for hit in hits
        if any(term in str(hit.get("title") or "") for term in annual_terms)
        and not any(term in str(hit.get("title") or "") for term in exclude_terms)
        and (not year or year in str(hit.get("title") or ""))
    ]
    return filtered or hits


def _record_matches_requested_company(record: Dict[str, Any], symbol: str | None, raw_data_root: str = "data/raw/real_data") -> bool:
    requested = str(symbol or record.get("symbol") or "").strip()
    if not requested:
        return True
    profile = resolve_company_identifier(requested, raw_data_root=raw_data_root) or {}
    terms = _company_identity_terms(requested, str(profile.get("company_name") or ""))
    if not terms:
        return True
    text = " ".join(
        [
            str(record.get("title") or ""),
            str(record.get("content") or ""),
            str(record.get("source_url") or ""),
        ]
    ).lower()
    return any(term in text for term in terms)


def _company_identity_terms(symbol: str, company_name: str) -> List[str]:
    terms: List[str] = []
    symbol_text = str(symbol or "").strip().lower()
    if symbol_text:
        terms.append(symbol_text)
        if "." in symbol_text:
            terms.append(symbol_text.split(".", 1)[0].lstrip("0") or symbol_text.split(".", 1)[0])
    name = str(company_name or "").strip().lower()
    if name:
        terms.append(name)
        simplified = re.sub(r"\b(holdings|holding|limited|ltd|inc|corp|corporation|company|co)\b\.?", "", name, flags=re.I)
        simplified = " ".join(simplified.split())
        if len(simplified) >= 4:
            terms.append(simplified)
        for token in re.split(r"[^a-z0-9]+", name):
            if len(token) >= 5:
                terms.append(token)
    return list(dict.fromkeys(term for term in terms if len(term) >= 3))


def _target_report_date(period: str | None) -> str:
    text = str(period or "").strip().upper()
    year = _period_year(text)
    if not year:
        return ""
    if "Q1" in text:
        return f"{year}-03-31"
    if "Q2" in text or "H1" in text:
        return f"{year}-06-30"
    if "Q3" in text:
        return f"{year}-09-30"
    if "Q4" in text or "FY" in text or "ANNUAL" in text:
        return f"{year}-12-31"
    return ""


def _period_year(period: str | None) -> str:
    text = str(period or "").strip().upper()
    match = re.search(r"20\d{2}", text)
    return match.group(0) if match else ""


def _select_financial_row_for_period(records: List[Any], period: str | None) -> Dict[str, Any]:
    target = _target_report_date(period)
    candidates = [item for item in records if isinstance(item, dict)]
    if not candidates:
        return {}
    if not target:
        return candidates[0]
    for row in candidates:
        report_date = str(row.get("REPORT_DATE") or row.get("REPORTDATE") or "")
        if report_date.startswith(target):
            return row
    year = target[:4]
    if target.endswith("12-31"):
        for row in candidates:
            report_date = str(row.get("REPORT_DATE") or row.get("REPORTDATE") or "")
            if report_date.startswith(f"{year}-12"):
                return row
    return candidates[0]


def _cninfo_org_id(code: str, config: Dict[str, Any], timeout: float) -> str:
    url = str(config.get("stock_list_url") or "")
    if not url:
        return ""
    headers = {"User-Agent": "Mozilla/5.0 DeepReportPlus/0.1", "Accept": "application/json,text/plain,*/*"}
    try:
        payload = _get_json(url, headers=headers, timeout=timeout, engine="cninfo_stock_list")
    except Exception:
        return ""
    stock_list = payload.get("stockList", []) if isinstance(payload, dict) else []
    if not isinstance(stock_list, list):
        return ""
    for item in stock_list:
        if isinstance(item, dict) and str(item.get("code") or "") == code:
            return str(item.get("orgId") or "")
    return ""


def _sse_announcement_search(code: str, period: str, topk: int, query: str, config: Dict[str, Any]) -> Dict[str, Any]:
    base_url = str(config.get("sse_query_url") or "https://query.sse.com.cn/security/stock/queryCompanyBulletin.do")
    timeout = float(config.get("timeout", 15) or 15)
    start_date, end_date = _announcement_date_range(period)
    params = {
        "isPagination": "true",
        "productId": code,
        "securityType": "0101,120100,020100,020200,120200",
        "reportType2": "DQBG",
        "beginDate": start_date,
        "endDate": end_date,
        "pageHelp.pageSize": str(max(topk, int(config.get("page_size", 10) or 10))),
        "pageHelp.pageNo": "1",
        "pageHelp.beginPage": "1",
        "pageHelp.cacheSize": "1",
        "pageHelp.endPage": "1",
    }
    url = f"{base_url}?{parse.urlencode(params)}"
    headers = {
        "User-Agent": "Mozilla/5.0 DeepReportPlus/0.1",
        "Accept": "application/json,text/plain,*/*",
        "Referer": "https://www.sse.com.cn/",
    }
    try:
        parsed = _get_json(url, headers=headers, timeout=timeout, engine="sse_announcements")
    except Exception as exc:
        return {"hits": [], "meta": {"mode": "exchange_announcements", "exchange": "sse", "symbol": code, "record_count": 0, "failure_reason": "fetch_error", "error": str(exc), "query": query}}
    rows = _coerce_search_items(parsed, keys=["result", "data", "items", "list"])
    hits = []
    for row in rows:
        title = str(row.get("TITLE") or row.get("title") or row.get("bulletinTitle") or "")
        url_path = str(row.get("URL") or row.get("url") or row.get("bulletinUrl") or "")
        source_url = parse.urljoin("https://www.sse.com.cn/", url_path)
        date = str(row.get("SSEDATE") or row.get("date") or row.get("BULLETIN_DATE") or "")
        digest = hashlib.sha1(f"{code}|{title}|{source_url}".encode("utf-8")).hexdigest()[:10]
        hits.append(
            {
                "evidence_id": f"{code}_{period or 'latest'}_sse_announcement_{digest}",
                "sample_id": f"{code}_{period or 'latest'}_sse_announcement_{digest}",
                "symbol": f"{code}.SS",
                "period": period,
                "source_type": "exchange_announcement",
                "title": title or f"{code} SSE announcement",
                "content": f"SSE official announcement for {code}: {title}.",
                "source_url": source_url,
                "publish_time": date,
                "trust_level": "high",
                "score": 7.0,
                "metadata": {"provider": "SSE", "raw": row},
            }
        )
    hits = _filter_period_announcement_hits([apply_source_quality(hit) for hit in hits], period)
    return {"hits": hits[:topk], "meta": {"mode": "exchange_announcements", "exchange": "sse", "symbol": code, "record_count": len(hits), "failure_reason": "" if hits else "no_announcements", "query": query}}


def _szse_announcement_search(code: str, period: str, topk: int, query: str, config: Dict[str, Any]) -> Dict[str, Any]:
    base_url = str(config.get("szse_announcement_url") or "https://www.szse.cn/api/disc/announcement/annList")
    timeout = float(config.get("timeout", 15) or 15)
    start_date, end_date = _announcement_date_range(period)
    payload = {
        "seDate": [start_date, end_date] if start_date and end_date else [],
        "stock": [code],
        "channelCode": ["listedNotice_disc"],
        "pageSize": max(topk, int(config.get("page_size", 10) or 10)),
        "pageNum": 1,
    }
    headers = {
        "User-Agent": "Mozilla/5.0 DeepReportPlus/0.1",
        "Accept": "application/json,text/plain,*/*",
        "Content-Type": "application/json",
        "Referer": "https://www.szse.cn/disclosure/listed/notice/",
    }
    try:
        parsed = _post_json_search(base_url, payload, headers=headers, timeout=timeout, engine="szse_announcements")
    except Exception as exc:
        return {"hits": [], "meta": {"mode": "exchange_announcements", "exchange": "szse", "symbol": code, "record_count": 0, "failure_reason": "fetch_error", "error": str(exc), "query": query}}
    rows = _coerce_search_items(parsed, keys=["data", "items", "announcements", "list"])
    hits = []
    for row in rows:
        title = str(row.get("title") or row.get("announcementTitle") or row.get("discTitle") or "")
        url_path = str(row.get("attachPath") or row.get("url") or row.get("href") or "")
        source_url = parse.urljoin("https://www.szse.cn/", url_path)
        date = str(row.get("publishTime") or row.get("date") or row.get("publishDate") or "")
        digest = hashlib.sha1(f"{code}|{title}|{source_url}".encode("utf-8")).hexdigest()[:10]
        hits.append(
            {
                "evidence_id": f"{code}_{period or 'latest'}_szse_announcement_{digest}",
                "sample_id": f"{code}_{period or 'latest'}_szse_announcement_{digest}",
                "symbol": f"{code}.SZ",
                "period": period,
                "source_type": "exchange_announcement",
                "title": title or f"{code} SZSE announcement",
                "content": f"SZSE official announcement for {code}: {title}.",
                "source_url": source_url,
                "publish_time": date,
                "trust_level": "high",
                "score": 7.0,
                "metadata": {"provider": "SZSE", "raw": row},
            }
        )
    hits = _filter_period_announcement_hits([apply_source_quality(hit) for hit in hits], period)
    return {"hits": hits[:topk], "meta": {"mode": "exchange_announcements", "exchange": "szse", "symbol": code, "record_count": len(hits), "failure_reason": "" if hits else "no_announcements", "query": query}}


def _summarize_eastmoney_financial_row(table_type: str, row: Dict[str, Any]) -> str:
    labels = {
        "OPERATE_INCOME": "operating revenue",
        "TOTAL_OPERATE_INCOME": "total operating revenue",
        "NETPROFIT": "net profit",
        "PARENT_NETPROFIT": "parent net profit",
        "TOTAL_ASSETS": "total assets",
        "TOTAL_LIABILITIES": "total liabilities",
        "TOTAL_EQUITY": "total equity",
        "MONETARYFUNDS": "cash and equivalents",
        "NETCASH_OPERATE": "net operating cash flow",
        "NETCASH_INVEST": "net investing cash flow",
        "NETCASH_FINANCE": "net financing cash flow",
    }
    parts = [f"report_date {row.get('REPORT_DATE') or row.get('REPORTDATE') or 'unknown'}"]
    for key, label in labels.items():
        if key in row and row.get(key) not in {None, ""}:
            parts.append(f"{label} {row.get(key)}")
    if len(parts) == 1:
        for key, value in list(row.items())[:8]:
            if value not in {None, ""}:
                parts.append(f"{key} {value}")
    return f"Eastmoney {table_type} financial table: " + "; ".join(str(part) for part in parts) + "."


def _strip_html(text: str) -> str:
    import re

    return re.sub(r"<[^>]+>", "", str(text or "")).replace("&nbsp;", " ").strip()


def _normalize_hits(engine: str, hits: Any) -> List[SearchResult]:
    if not isinstance(hits, list):
        return []
    normalized: List[SearchResult] = []
    for index, item in enumerate(hits, start=1):
        if not isinstance(item, dict):
            continue
        item = apply_source_quality(item)
        result_id = str(
            item.get("evidence_id")
            or item.get("sample_id")
            or item.get("id")
            or item.get("url")
            or f"{engine}_{index}"
        )
        title = str(item.get("title") or item.get("headline") or item.get("source_type") or result_id)
        snippet = str(item.get("snippet") or item.get("content") or item.get("text") or "")
        url = str(item.get("url") or item.get("source_url") or "")
        score = _safe_float(item.get("rerank_score", item.get("score", 0.0)))
        source_type = str(item.get("source_type") or item.get("source") or engine)
        normalized.append(
            SearchResult(
                result_id=result_id,
                engine=engine,
                title=title,
                snippet=snippet,
                url=url,
                score=score,
                source_type=source_type,
                source_authority=str(item.get("source_authority", "")),
                authority_level=str(item.get("authority_level", "")),
                source_document_type=str(item.get("source_document_type", "")),
                authority_score=_safe_float(item.get("authority_score", 0.0)),
                raw=dict(item),
            )
        )
    return normalized


def _dedupe_and_rank(hits: List[SearchResult], topk: int) -> List[SearchResult]:
    deduped: Dict[str, SearchResult] = {}
    for hit in hits:
        raw = hit.raw if isinstance(hit.raw, dict) else {}
        if str(raw.get("source_type") or "") == "eastmoney_financials":
            key = str(hit.result_id)
        else:
            key = str(raw.get("chunk_id") or hit.url or hit.result_id or f"{hit.engine}:{hit.title}:{hit.snippet[:80]}")
        existing = deduped.get(key)
        if existing is None or hit.score > existing.score:
            deduped[key] = hit
    ranked = sorted(deduped.values(), key=lambda item: (item.score + item.authority_score * 0.05), reverse=True)
    selected: List[SearchResult] = []
    source_counts: Dict[str, int] = {}
    default_diversity_cap = 4
    source_diversity_caps = {"eastmoney_financials": 3}
    for hit in ranked:
        source_key = hit.source_type or hit.engine
        diversity_cap = source_diversity_caps.get(source_key, default_diversity_cap)
        if source_counts.get(source_key, 0) >= diversity_cap:
            continue
        selected.append(hit)
        source_counts[source_key] = source_counts.get(source_key, 0) + 1
        if len(selected) >= topk:
            return selected
    for hit in ranked:
        if hit in selected:
            continue
        selected.append(hit)
        if len(selected) >= topk:
            break
    return selected


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _post_json_search(
    base_url: str,
    payload: Dict[str, Any],
    headers: Dict[str, str],
    timeout: float,
    engine: str,
) -> Dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = request.Request(base_url, data=body, headers=headers, method="POST")
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
    except (TimeoutError, socket.timeout) as exc:
        raise RuntimeError(f"{engine} search timed out") from exc
    except error.HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{engine} HTTP {exc.code}: {error_body}") from exc
    except error.URLError as exc:
        raise RuntimeError(f"{engine} URL error: {exc.reason}") from exc
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise RuntimeError(f"{engine} returned non-object JSON")
    return parsed


def _post_form_json(
    base_url: str,
    payload: Dict[str, Any],
    headers: Dict[str, str],
    timeout: float,
    engine: str,
) -> Dict[str, Any]:
    body = parse.urlencode(payload).encode("utf-8")
    req = request.Request(base_url, data=body, headers=headers, method="POST")
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except (TimeoutError, socket.timeout) as exc:
        raise RuntimeError(f"{engine} search timed out") from exc
    except error.HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{engine} HTTP {exc.code}: {error_body}") from exc
    except error.URLError as exc:
        raise RuntimeError(f"{engine} URL error: {exc.reason}") from exc
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise RuntimeError(f"{engine} returned non-object JSON")
    return parsed


def _get_json(url: str, headers: Dict[str, str], timeout: float, engine: str) -> Dict[str, Any]:
    req = request.Request(url, headers=headers, method="GET")
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except (TimeoutError, socket.timeout) as exc:
        raise RuntimeError(f"{engine} request timed out") from exc
    except error.HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{engine} HTTP {exc.code}: {error_body}") from exc
    except error.URLError as exc:
        raise RuntimeError(f"{engine} URL error: {exc.reason}") from exc
    if raw.strip().startswith(("jsonp", "jQuery")):
        start = raw.find("(")
        end = raw.rfind(")")
        if start >= 0 and end > start:
            raw = raw[start + 1 : end]
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise RuntimeError(f"{engine} returned non-object JSON")
    return parsed


def _coerce_search_items(payload: Dict[str, Any], keys: List[str]) -> List[Dict[str, Any]]:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
        if isinstance(value, dict):
            nested = _coerce_search_items(value, keys=["items", "results", "records", "list"])
            if nested:
                return nested
    return []


def _search_evidence_id(engine: str, url: str, title: str, index: int) -> str:
    seed = url or title or str(index)
    return f"{engine}_{hashlib.sha1(seed.encode('utf-8')).hexdigest()[:10]}"


def _load_real_data_records(raw_data_root: str, symbol: str | None, period: str | None) -> List[Dict[str, Any]]:
    root = Path(raw_data_root)
    if not root.exists():
        return []

    symbols = [symbol] if symbol else [path.name for path in root.iterdir() if path.is_dir()]
    records: List[Dict[str, Any]] = []
    for current_symbol in symbols:
        symbol_dir = root / str(current_symbol)
        if not symbol_dir.exists():
            continue
        periods = [period] if period else [path.name for path in symbol_dir.iterdir() if path.is_dir()]
        for current_period in periods:
            period_dir = symbol_dir / str(current_period)
            if not period_dir.exists():
                continue
            records.extend(_load_period_records(period_dir=period_dir, symbol=str(current_symbol), period=str(current_period)))
    return records


def _load_period_records(period_dir: Path, symbol: str, period: str) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    profile_path = period_dir / "company_profile.json"
    if profile_path.exists():
        profile = json.loads(profile_path.read_text(encoding="utf-8"))
        records.append(
            _record(
                symbol=symbol,
                period=period,
                source_type="company_profile",
                title=f"{symbol} company profile",
                content=str(profile.get("description", "")),
                source_url=str(profile.get("source_url", "")),
                publish_time=str(profile.get("as_of_date", "")),
                trust_level=str(profile.get("trust_level", "medium")),
                metadata=profile,
            )
        )

    financials_path = period_dir / "financials.csv"
    if financials_path.exists():
        for _, row in pd.read_csv(financials_path).iterrows():
            content = (
                f"Revenue {row.get('revenue_billion')}B, revenue growth {row.get('revenue_growth_pct')}%, "
                f"gross margin {row.get('gross_margin_pct')}%, net margin {row.get('net_margin_pct')}%, "
                f"ROE {row.get('roe_pct')}%, ROA {row.get('roa_pct')}%, "
                f"operating cash flow {row.get('operating_cash_flow_billion')}B, "
                f"free cash flow {row.get('free_cash_flow_billion')}B. {row.get('notes', '')}"
            )
            records.append(
                _record(
                    symbol=symbol,
                    period=period,
                    source_type="financials",
                    title=f"{symbol} {period} financial summary",
                    content=content,
                    source_url=str(row.get("source_url", "")),
                    publish_time=str(row.get("publish_time", "")),
                    trust_level=str(row.get("trust_level", "high")),
                    metadata=row.to_dict(),
                )
            )

    market_path = period_dir / "market.csv"
    if market_path.exists():
        for _, row in pd.read_csv(market_path).iterrows():
            content = f"Close {row.get('close')}, volume {row.get('volume')}."
            records.append(
                _record(
                    symbol=symbol,
                    period=period,
                    source_type="market",
                    title=f"{symbol} {period} market snapshot",
                    content=content,
                    source_url=str(row.get("source_url", "")),
                    publish_time=str(row.get("publish_time", "")),
                    trust_level=str(row.get("trust_level", "medium")),
                    metadata=row.to_dict(),
                )
            )

    for file_name, source_type in [("filings.jsonl", "filing"), ("news.jsonl", "news")]:
        path = period_dir / file_name
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            item = json.loads(line)
            records.append(
                _record(
                    symbol=symbol,
                    period=period,
                    source_type=source_type,
                    title=str(item.get("title", f"{symbol} {source_type}")),
                    content=str(item.get("content", "")),
                    source_url=str(item.get("source_url", "")),
                    publish_time=str(item.get("publish_time", "")),
                    trust_level=str(item.get("trust_level", "medium")),
                    metadata=item,
                )
            )
    return records


def _record(
    symbol: str,
    period: str,
    source_type: str,
    title: str,
    content: str,
    source_url: str,
    publish_time: str,
    trust_level: str,
    metadata: Dict[str, Any],
) -> Dict[str, Any]:
    digest = hashlib.sha1(f"{title}|{source_url}|{content}".encode("utf-8")).hexdigest()[:8]
    evidence_id = f"{symbol}_{period}_{source_type}_{digest}"
    return {
        "evidence_id": evidence_id,
        "sample_id": evidence_id,
        "symbol": symbol,
        "period": period,
        "source_type": source_type,
        "title": title,
        "content": content,
        "source_url": source_url,
        "publish_time": publish_time,
        "trust_level": trust_level,
        "metadata": metadata,
    }


def _score_record(query: str, item: Dict[str, Any]) -> float:
    query_terms = {part.lower() for part in query.replace("/", " ").replace("-", " ").split() if len(part) > 1}
    text = " ".join(
        [
            str(item.get("symbol", "")),
            str(item.get("period", "")),
            str(item.get("source_type", "")),
            str(item.get("title", "")),
            str(item.get("content", "")),
        ]
    ).lower()
    overlap = sum(1 for term in query_terms if term in text)
    trust_bonus = {"high": 1.0, "medium": 0.5, "low": 0.1}.get(str(item.get("trust_level", "")).lower(), 0.0)
    return float(overlap) + trust_bonus


def adapt_financial_query(
    query: str,
    symbol: str | None = None,
    period: str | None = None,
    raw_data_root: str = "data/raw/real_data",
) -> Dict[str, Any]:
    """Expand Chinese/alias-heavy finance queries into retrieval-friendly terms."""

    original = str(query or "").strip()
    resolved_symbol = resolve_symbol(symbol or original, raw_data_root=raw_data_root, default=symbol or "")
    profile = resolve_company_identifier(resolved_symbol or original, raw_data_root=raw_data_root)
    additions: List[str] = []
    if resolved_symbol:
        additions.append(resolved_symbol)
    if period:
        additions.append(str(period))
    for key in ["company_name", "industry", "sector"]:
        value = str(profile.get(key, "")).strip() if profile else ""
        if value:
            additions.append(value)
    additions.extend(_finance_query_synonyms(original))

    deduped: List[str] = []
    seen: set[str] = set()
    for item in additions:
        text = str(item).strip()
        key = text.lower()
        if text and key not in seen and key not in original.lower():
            deduped.append(text)
            seen.add(key)
    adapted = " ".join([original] + deduped).strip()
    return {
        "query_original": original,
        "query_adapted": adapted,
        "adapted_query": adapted,
        "query_terms_added": deduped,
        "query_expansion_version": "finance_query_expansion_v1",
    }


def _finance_query_synonyms(query: str) -> List[str]:
    text = str(query or "").lower()
    mapping = {
        "营收": ["revenue", "sales"],
        "收入": ["revenue", "sales"],
        "毛利率": ["gross margin", "gross_margin_pct"],
        "净利率": ["net margin", "net_margin_pct"],
        "利润": ["profit", "net income", "net_margin_pct"],
        "现金流": ["cash flow", "operating cash flow", "free cash flow"],
        "经营现金流": ["operating cash flow", "operating_cash_flow_billion"],
        "自由现金流": ["free cash flow", "free_cash_flow_billion"],
        "估值": ["valuation", "P/E", "P/S", "DCF"],
        "风险": ["risk", "risk assessment"],
        "同行": ["peer comparison", "sector", "industry"],
        "股权": ["ownership", "shareholding"],
        "治理": ["governance", "management"],
        "战略": ["strategy", "business model"],
        "三表": ["income statement", "balance sheet", "cash flow statement"],
        "财务": ["financials", "revenue", "margin", "cash flow"],
    }
    additions: List[str] = []
    for needle, terms in mapping.items():
        if needle in text:
            additions.extend(terms)
    return additions


def _local_search_failure_reason(
    records: List[Dict[str, Any]],
    hits: List[Dict[str, Any]],
    symbol: str | None,
    period: str | None,
) -> str:
    if not records:
        if symbol and period:
            return "no_records_for_symbol_period"
        if symbol:
            return "no_records_for_symbol"
        return "no_records"
    if not hits:
        return "no_hits_after_scoring"
    return ""


def _extract_symbol_from_query(query: str) -> str:
    for token in query.replace("/", " ").replace("-", " ").split():
        cleaned = "".join(ch for ch in token if ch.isalpha()).upper()
        if 1 <= len(cleaned) <= 6 and cleaned not in {"THE", "AND", "FOR", "WITH"}:
            return cleaned
    return ""
