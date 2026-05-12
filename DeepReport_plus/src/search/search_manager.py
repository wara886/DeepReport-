"""Search manager for financial research agents."""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import socket
from pathlib import Path
from typing import Any, Callable, Dict, List
from urllib import error, request

import pandas as pd

from src.data.company_universe import resolve_company_identifier, resolve_symbol
from src.data.sec_companyfacts import fetch_sec_companyfacts_evidence
from src.data.source_quality import apply_source_quality
from src.data.yahoo_finance import yahoo_snapshot_to_evidence
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
        manager.register_engine("yahoo_finance", yahoo_finance_search)
        manager.register_engine("sec_companyfacts", sec_companyfacts_search)
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
        raise RuntimeError("missing Tavily API key: set TAVILY_API_KEY in DeepReport_plus/.env")

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
        raise RuntimeError("missing Serper API key: set SERPER_API_KEY in DeepReport_plus/.env")

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
        raise RuntimeError("missing Metaso API key: set METASO_API_KEY in DeepReport_plus/.env")

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
        raise RuntimeError("missing Sogou API key: set SOGOU_API_KEY in DeepReport_plus/.env")

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
    evidence = yahoo_snapshot_to_evidence(
        symbol=resolved_symbol,
        period=period or "",
        range_=range_,
        interval=interval,
    )
    return {
        "hits": [evidence][:topk],
        "meta": {
            "mode": "yahoo_finance",
            "symbol": resolved_symbol,
            "range": range_,
            "interval": interval,
            "result_count": 1,
        },
    }


def sec_companyfacts_search(
    query: str,
    topk: int = 5,
    symbol: str | None = None,
    period: str | None = None,
    raw_data_root: str = "data/raw/real_data",
    **_: Any,
) -> Dict[str, Any]:
    resolved_symbol = resolve_symbol(symbol or query, raw_data_root=raw_data_root, default=symbol or _extract_symbol_from_query(query) or "")
    resolved_symbol = resolved_symbol.strip().upper()
    if not resolved_symbol:
        return {
            "hits": [],
            "meta": {"mode": "sec_companyfacts", "error": "symbol is required for SEC CompanyFacts search"},
        }
    evidence = fetch_sec_companyfacts_evidence(symbol=resolved_symbol, period=period or "latest")
    return {
        "hits": [evidence][:topk],
        "meta": {
            "mode": "sec_companyfacts",
            "symbol": resolved_symbol,
            "period": evidence.get("period", period or "latest"),
            "form": evidence.get("metadata", {}).get("form", ""),
            "filed": evidence.get("metadata", {}).get("filed", ""),
            "result_count": 1,
        },
    }


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
        key = str(raw.get("chunk_id") or hit.url or hit.result_id or f"{hit.engine}:{hit.title}:{hit.snippet[:80]}")
        existing = deduped.get(key)
        if existing is None or hit.score > existing.score:
            deduped[key] = hit
    return sorted(deduped.values(), key=lambda item: (item.score + item.authority_score * 0.05), reverse=True)[:topk]


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
