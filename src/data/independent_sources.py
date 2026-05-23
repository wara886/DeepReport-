"""Independent company, macro, and policy data-source adapters."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
import hashlib
import json
import os
import socket
from typing import Any, Dict, Iterable, List
from urllib import error, parse, request

from src.data.company_universe import resolve_company_identifier
from src.data.source_quality import apply_source_quality
from src.utils.config import load_config
from src.utils.env import load_env_files, resolve_config_value


DEFAULT_CIK_MAP = {
    "AAPL": "0000320193",
    "GOOGL": "0001652044",
    "MSFT": "0000789019",
    "NVDA": "0001045810",
    "TSLA": "0001318605",
    "AMD": "0000002488",
}
DEFAULT_FRED_SERIES = {
    "FEDFUNDS": "Effective Federal Funds Rate",
    "DGS10": "10-Year Treasury Constant Maturity Rate",
    "CPIAUCSL": "Consumer Price Index for All Urban Consumers",
    "UNRATE": "Unemployment Rate",
}
DEFAULT_BLS_SERIES = {
    "CUUR0000SA0": "Consumer Price Index for All Urban Consumers",
    "LNS14000000": "Unemployment Rate",
}
DEFAULT_COMPANY_FACTS = [
    "Revenues",
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "NetIncomeLoss",
    "Assets",
    "CashAndCashEquivalentsAtCarryingValue",
    "NetCashProvidedByUsedInOperatingActivities",
    "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
    "PaymentsToAcquirePropertyPlantAndEquipment",
    "PaymentsToAcquireProductiveAssets",
]


@dataclass(frozen=True)
class SourcePayload:
    hits: List[Dict[str, Any]]
    meta: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {"hits": list(self.hits), "meta": dict(self.meta)}


def fetch_independent_evidence_bundle(
    symbol: str,
    period: str = "",
    sector: str = "",
    industry: str = "",
    config_path: str = "configs/data_sources.yaml",
    enable_remote: bool = False,
    topk: int = 8,
) -> Dict[str, Any]:
    """Fetch independent evidence records without making remote calls unless requested."""

    records: List[Dict[str, Any]] = []
    meta: Dict[str, Any] = {
        "enabled": bool(enable_remote),
        "mode": "remote" if enable_remote else "metadata_only",
        "sources": {},
    }
    if not enable_remote:
        meta["failure_reason"] = "remote_sources_disabled"
        return {"records": records, "meta": meta}

    macro = fetch_macro_evidence(period=period, config_path=config_path, topk=topk)
    company = fetch_sec_companyfacts_evidence(symbol=symbol, period=period, config_path=config_path)
    policy = fetch_federal_reserve_policy_evidence(config_path=config_path)
    records.extend(macro.hits)
    records.extend(company.hits)
    records.extend(policy.hits)
    meta["sources"]["macro"] = macro.meta
    meta["sources"]["sec_companyfacts"] = company.meta
    meta["sources"]["federal_reserve"] = policy.meta
    meta["record_count"] = len(records)
    meta["sector"] = sector
    meta["industry"] = industry
    return {"records": records[:topk], "meta": meta}


def fetch_macro_evidence(
    period: str = "",
    config_path: str = "configs/data_sources.yaml",
    topk: int = 8,
) -> SourcePayload:
    """Fetch macro evidence from FRED, BLS, and BEA when credentials are available."""

    config = _load_data_source_config(config_path)
    macro_cfg = dict(config.get("independent_sources", {}).get("macro", {}))
    hits: List[Dict[str, Any]] = []
    source_meta: Dict[str, Any] = {}

    fred_payload = fetch_fred_series_evidence(
        series=_series_map(macro_cfg.get("fred", {}), DEFAULT_FRED_SERIES),
        config_path=config_path,
        topk=max(topk, 1),
    )
    hits.extend(fred_payload.hits)
    source_meta["fred"] = fred_payload.meta

    bls_payload = fetch_bls_series_evidence(
        series=_series_map(macro_cfg.get("bls", {}), DEFAULT_BLS_SERIES),
        config_path=config_path,
        topk=max(1, min(topk, 4)),
    )
    hits.extend(bls_payload.hits)
    source_meta["bls"] = bls_payload.meta

    bea_payload = fetch_bea_indicator_evidence(config_path=config_path)
    hits.extend(bea_payload.hits)
    source_meta["bea"] = bea_payload.meta

    deduped = _dedupe_records(hits)[:topk]
    return SourcePayload(
        hits=deduped,
        meta={
            "mode": "independent_macro",
            "period": period,
            "source_meta": source_meta,
            "record_count": len(deduped),
            "failure_reason": _combined_failure_reason(source_meta),
        },
    )


def fetch_fred_series_evidence(
    series: Dict[str, str] | None = None,
    config_path: str = "configs/data_sources.yaml",
    topk: int = 8,
) -> SourcePayload:
    config = _load_data_source_config(config_path)
    fred_cfg = dict(config.get("independent_sources", {}).get("macro", {}).get("fred", {}))
    api_key = _resolve_api_key(fred_cfg, "api_key", "FRED_API_KEY")
    if not api_key:
        return _skipped("fred", "missing_api_key", "FRED_API_KEY")

    base_url = str(fred_cfg.get("base_url") or "https://api.stlouisfed.org/fred/series/observations")
    timeout = float(fred_cfg.get("timeout", 20))
    hits: List[Dict[str, Any]] = []
    errors: List[str] = []
    for series_id, label in list((series or DEFAULT_FRED_SERIES).items())[:topk]:
        query = parse.urlencode(
            {
                "series_id": series_id,
                "api_key": api_key,
                "file_type": "json",
                "sort_order": "desc",
                "limit": 4,
            }
        )
        try:
            payload = _get_json(f"{base_url}?{query}", timeout=timeout)
            observations = payload.get("observations", [])
            latest = _latest_observation(observations)
            if not latest:
                continue
            obs_date = str(latest.get("date", ""))
            value = str(latest.get("value", ""))
            hits.append(
                _record(
                    evidence_id=f"fred_{series_id.lower()}_{obs_date.replace('-', '')}",
                    source_type="fred_series",
                    title=f"FRED {series_id}: {label}",
                    content=f"{label} latest FRED observation is {value} for {obs_date}.",
                    source_url=f"https://fred.stlouisfed.org/series/{series_id}",
                    publish_time=obs_date,
                    metadata={"provider": "FRED", "series_id": series_id, "series_name": label, "observation_date": obs_date, "value": value},
                )
            )
        except Exception as exc:
            errors.append(f"{series_id}: {exc}")
    return SourcePayload(
        hits=hits,
        meta={"mode": "fred", "record_count": len(hits), "errors": errors, "failure_reason": "fetch_error" if errors and not hits else ""},
    )


def fetch_bls_series_evidence(
    series: Dict[str, str] | None = None,
    config_path: str = "configs/data_sources.yaml",
    topk: int = 4,
) -> SourcePayload:
    config = _load_data_source_config(config_path)
    bls_cfg = dict(config.get("independent_sources", {}).get("macro", {}).get("bls", {}))
    base_url = str(bls_cfg.get("base_url") or "https://api.bls.gov/publicAPI/v2/timeseries/data/")
    timeout = float(bls_cfg.get("timeout", 20))
    api_key = _resolve_api_key(bls_cfg, "api_key", "BLS_API_KEY")
    start_year = str(bls_cfg.get("start_year") or max(date.today().year - 2, 2000))
    end_year = str(bls_cfg.get("end_year") or date.today().year)
    series_map = dict(list((series or DEFAULT_BLS_SERIES).items())[:topk])
    payload: Dict[str, Any] = {"seriesid": list(series_map.keys()), "startyear": start_year, "endyear": end_year}
    if api_key:
        payload["registrationkey"] = api_key
    try:
        parsed = _post_json(base_url, payload=payload, headers={"Content-Type": "application/json"}, timeout=timeout)
    except Exception as exc:
        return SourcePayload(hits=[], meta={"mode": "bls", "record_count": 0, "failure_reason": "fetch_error", "error": str(exc)})

    hits: List[Dict[str, Any]] = []
    for item in parsed.get("Results", {}).get("series", []):
        if not isinstance(item, dict):
            continue
        series_id = str(item.get("seriesID") or "")
        rows = item.get("data", [])
        latest = rows[0] if isinstance(rows, list) and rows and isinstance(rows[0], dict) else {}
        if not latest:
            continue
        year = str(latest.get("year", ""))
        period = str(latest.get("period", ""))
        obs_date = f"{year}-{period}" if year or period else ""
        value = str(latest.get("value", ""))
        label = series_map.get(series_id, series_id)
        hits.append(
            _record(
                evidence_id=f"bls_{series_id.lower()}_{year}_{period}",
                source_type="bls_series",
                title=f"BLS {series_id}: {label}",
                content=f"{label} latest BLS observation is {value} for {obs_date}.",
                source_url="https://www.bls.gov/developers/api_signature_v2.htm",
                publish_time=f"{year}-01-01" if year else "",
                metadata={"provider": "BLS", "series_id": series_id, "series_name": label, "observation_date": obs_date, "value": value},
            )
        )
    return SourcePayload(hits=hits, meta={"mode": "bls", "record_count": len(hits), "failure_reason": "" if hits else "no_observations"})


def fetch_bea_indicator_evidence(config_path: str = "configs/data_sources.yaml") -> SourcePayload:
    config = _load_data_source_config(config_path)
    bea_cfg = dict(config.get("independent_sources", {}).get("macro", {}).get("bea", {}))
    api_key = _resolve_api_key(bea_cfg, "api_key", "BEA_API_KEY")
    if not api_key:
        return _skipped("bea", "missing_api_key", "BEA_API_KEY")

    base_url = str(bea_cfg.get("base_url") or "https://apps.bea.gov/api/data/")
    timeout = float(bea_cfg.get("timeout", 20))
    params = {
        "UserID": api_key,
        "method": "GetData",
        "datasetname": str(bea_cfg.get("datasetname") or "NIPA"),
        "TableName": str(bea_cfg.get("table_name") or "T10101"),
        "Frequency": str(bea_cfg.get("frequency") or "Q"),
        "Year": str(bea_cfg.get("year") or "X"),
        "ResultFormat": "JSON",
    }
    try:
        payload = _get_json(f"{base_url}?{parse.urlencode(params)}", timeout=timeout)
    except Exception as exc:
        return SourcePayload(hits=[], meta={"mode": "bea", "record_count": 0, "failure_reason": "fetch_error", "error": str(exc)})
    rows = payload.get("BEAAPI", {}).get("Results", {}).get("Data", [])
    latest = rows[0] if isinstance(rows, list) and rows and isinstance(rows[0], dict) else {}
    if not latest:
        return SourcePayload(hits=[], meta={"mode": "bea", "record_count": 0, "failure_reason": "no_data"})
    time_period = str(latest.get("TimePeriod", ""))
    line_desc = str(latest.get("LineDescription") or "BEA NIPA indicator")
    value = str(latest.get("DataValue", ""))
    return SourcePayload(
        hits=[
            _record(
                evidence_id=f"bea_{hashlib.sha1((line_desc + time_period).encode('utf-8')).hexdigest()[:10]}",
                source_type="bea_series",
                title=f"BEA NIPA: {line_desc}",
                content=f"{line_desc} latest BEA observation is {value} for {time_period}.",
                source_url="https://www.bea.gov/open-data",
                publish_time="",
                metadata={"provider": "BEA", "time_period": time_period, "value": value, "raw": latest},
            )
        ],
        meta={"mode": "bea", "record_count": 1, "failure_reason": ""},
    )


def fetch_federal_reserve_policy_evidence(config_path: str = "configs/data_sources.yaml") -> SourcePayload:
    config = _load_data_source_config(config_path)
    fed_cfg = dict(config.get("independent_sources", {}).get("macro", {}).get("federal_reserve", {}))
    url = str(fed_cfg.get("url") or "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm")
    timeout = float(fed_cfg.get("timeout", 12))
    try:
        text = _get_text(url, timeout=timeout)
    except Exception as exc:
        return SourcePayload(hits=[], meta={"mode": "federal_reserve", "record_count": 0, "failure_reason": "fetch_error", "error": str(exc)})
    content = " ".join(text.split())[:1200]
    today = date.today().isoformat()
    return SourcePayload(
        hits=[
            _record(
                evidence_id=f"fed_policy_{today.replace('-', '')}",
                source_type="policy_release",
                title="Federal Reserve FOMC policy materials",
                content=content,
                source_url=url,
                publish_time=today,
                metadata={"provider": "Federal Reserve", "fetched_at": today},
            )
        ],
        meta={"mode": "federal_reserve", "record_count": 1, "failure_reason": ""},
    )


def fetch_sec_companyfacts_evidence(
    symbol: str,
    period: str = "",
    config_path: str = "configs/data_sources.yaml",
    raw_data_root: str = "data/raw/real_data",
) -> SourcePayload:
    symbol = str(symbol or "").upper()
    if not symbol:
        return SourcePayload(hits=[], meta={"mode": "sec_companyfacts", "record_count": 0, "failure_reason": "missing_symbol"})

    config = _load_data_source_config(config_path)
    sec_cfg = dict(config.get("independent_sources", {}).get("company", {}).get("sec_edgar", {}))
    cik = _resolve_cik(symbol=symbol, raw_data_root=raw_data_root, config=sec_cfg)
    if not cik:
        return SourcePayload(hits=[], meta={"mode": "sec_companyfacts", "symbol": symbol, "record_count": 0, "failure_reason": "missing_cik"})
    cik = cik.zfill(10)
    base_url = str(sec_cfg.get("companyfacts_base_url") or "https://data.sec.gov/api/xbrl/companyfacts")
    timeout = float(sec_cfg.get("timeout", 20))
    url = f"{base_url}/CIK{cik}.json"
    headers = {"User-Agent": _sec_user_agent(sec_cfg), "Host": "data.sec.gov"}
    try:
        payload = _get_json(url, headers=headers, timeout=timeout)
    except Exception as exc:
        return SourcePayload(
            hits=[],
            meta={"mode": "sec_companyfacts", "symbol": symbol, "cik": cik, "record_count": 0, "failure_reason": "fetch_error", "error": str(exc)},
        )

    facts = payload.get("facts", {}).get("us-gaap", {})
    metrics = _latest_sec_metrics(facts=facts, period=period)
    if not metrics:
        return SourcePayload(hits=[], meta={"mode": "sec_companyfacts", "symbol": symbol, "cik": cik, "record_count": 0, "failure_reason": "no_supported_facts"})
    latest_dates = [str(item.get("filed") or item.get("end") or "") for item in metrics.values() if isinstance(item, dict)]
    publish_time = max([item for item in latest_dates if item] or [""])
    metric_text = "; ".join(f"{name}: {item.get('value')} ({item.get('unit')}, {item.get('end')})" for name, item in metrics.items())
    hit = _record(
        evidence_id=f"sec_companyfacts_{symbol.lower()}_{hashlib.sha1(metric_text.encode('utf-8')).hexdigest()[:10]}",
        source_type="sec_companyfacts",
        title=f"{symbol} SEC company facts",
        content=f"SEC companyfacts latest supported metrics for {symbol}: {metric_text}.",
        source_url=url,
        publish_time=publish_time,
        symbol=symbol,
        period=period,
        metadata={"provider": "SEC EDGAR", "cik": cik, "metrics": metrics, "data_cutoff": publish_time},
    )
    return SourcePayload(hits=[hit], meta={"mode": "sec_companyfacts", "symbol": symbol, "cik": cik, "record_count": 1, "failure_reason": ""})


def _latest_sec_metrics(facts: Dict[str, Any], period: str = "") -> Dict[str, Dict[str, Any]]:
    output: Dict[str, Dict[str, Any]] = {}
    for metric in DEFAULT_COMPANY_FACTS:
        item = facts.get(metric)
        if not isinstance(item, dict):
            continue
        units = item.get("units", {})
        if not isinstance(units, dict):
            continue
        rows: List[Dict[str, Any]] = []
        for unit, values in units.items():
            if isinstance(values, list):
                for value in values:
                    if isinstance(value, dict) and value.get("val") is not None:
                        row = dict(value)
                        row["unit"] = unit
                        rows.append(row)
        if not rows:
            continue
        latest = _select_sec_metric_row(rows, period=period)
        output[metric] = {
            "value": latest.get("val"),
            "unit": latest.get("unit", ""),
            "end": latest.get("end", ""),
            "filed": latest.get("filed", ""),
            "form": latest.get("form", ""),
            "frame": latest.get("frame", ""),
        }
    output = _drop_stale_duplicate_revenue_metric(output)
    return output


def _drop_stale_duplicate_revenue_metric(metrics: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    legacy = metrics.get("Revenues")
    contract = metrics.get("RevenueFromContractWithCustomerExcludingAssessedTax")
    if not legacy or not contract:
        return metrics
    legacy_end = _parse_iso_date(legacy.get("end"))
    contract_end = _parse_iso_date(contract.get("end"))
    if legacy_end and contract_end and (contract_end - legacy_end).days > 370:
        metrics = dict(metrics)
        metrics.pop("Revenues", None)
    elif legacy_end and contract_end and (legacy_end - contract_end).days > 370:
        metrics = dict(metrics)
        metrics.pop("RevenueFromContractWithCustomerExcludingAssessedTax", None)
    return metrics


def _select_sec_metric_row(rows: List[Dict[str, Any]], period: str = "") -> Dict[str, Any]:
    target = _period_target_date(period)
    if not target:
        rows.sort(key=lambda row: str(row.get("filed") or row.get("end") or ""), reverse=True)
        return rows[0]

    upper_bound = target + timedelta(days=10)
    usable = []
    for row in rows:
        end_date = _parse_iso_date(row.get("end"))
        if not end_date or end_date > upper_bound:
            continue
        usable.append((row, end_date))
    if not usable:
        rows.sort(key=lambda row: str(row.get("filed") or row.get("end") or ""), reverse=True)
        return rows[0]

    prefer_annual = "Q4" in str(period or "").upper()
    usable.sort(
        key=lambda pair: (
            abs((pair[1] - target).days),
            0 if (prefer_annual and str(pair[0].get("form") or "").upper() == "10-K") else 1,
            str(pair[0].get("filed") or ""),
        )
    )
    return usable[0][0]


def _period_target_date(period: str | None) -> date | None:
    text = str(period or "").strip().upper()
    if len(text) < 6 or not text[:4].isdigit():
        return None
    year = int(text[:4])
    if "Q1" in text:
        return date(year, 3, 31)
    if "Q2" in text:
        return date(year, 6, 30)
    if "Q3" in text:
        return date(year, 9, 30)
    if "Q4" in text or "FY" in text or "ANNUAL" in text:
        return date(year, 12, 31)
    return None


def _parse_iso_date(raw: Any) -> date | None:
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        return datetime.strptime(text[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _record(
    evidence_id: str,
    source_type: str,
    title: str,
    content: str,
    source_url: str,
    publish_time: str,
    metadata: Dict[str, Any],
    symbol: str = "",
    period: str = "",
) -> Dict[str, Any]:
    record = {
        "evidence_id": evidence_id,
        "sample_id": evidence_id,
        "symbol": symbol,
        "period": period,
        "source_type": source_type,
        "title": title,
        "content": content,
        "source_url": source_url,
        "publish_time": publish_time,
        "source_timestamp": publish_time,
        "data_cutoff": str(metadata.get("data_cutoff") or metadata.get("observation_date") or publish_time),
        "trust_level": "high",
        "score": 1.0,
        "metadata": metadata,
    }
    return apply_source_quality(record)


def _load_data_source_config(config_path: str) -> Dict[str, Any]:
    load_env_files(config_path=config_path)
    return load_config(config_path) if config_path else {}


def _series_map(config: Dict[str, Any], default: Dict[str, str]) -> Dict[str, str]:
    raw = config.get("series") if isinstance(config, dict) else None
    if isinstance(raw, dict):
        return {str(key): str(value) for key, value in raw.items()}
    if isinstance(raw, list):
        return {str(item): str(item) for item in raw}
    return dict(default)


def _resolve_api_key(config: Dict[str, Any], key: str, default_env: str) -> str:
    cfg = dict(config or {})
    cfg.setdefault(f"{key}_env", default_env)
    return str(resolve_config_value(cfg, key, "")).strip()


def _sec_user_agent(config: Dict[str, Any]) -> str:
    env_name = str(config.get("user_agent_env") or "SEC_USER_AGENT")
    configured = os.environ.get(env_name, "").strip()
    return configured or str(config.get("user_agent") or "DeepReportPlus/0.1 contact@example.com")


def _resolve_cik(symbol: str, raw_data_root: str, config: Dict[str, Any]) -> str:
    cik_map = dict(DEFAULT_CIK_MAP)
    configured = config.get("cik_map")
    if isinstance(configured, dict):
        cik_map.update({str(key).upper(): str(value) for key, value in configured.items()})
    profile = resolve_company_identifier(symbol, raw_data_root=raw_data_root)
    profile_cik = str(profile.get("cik") or profile.get("CIK") or "").strip()
    return profile_cik or str(cik_map.get(symbol.upper(), ""))


def _latest_observation(observations: Any) -> Dict[str, Any]:
    if not isinstance(observations, list):
        return {}
    for item in observations:
        if not isinstance(item, dict):
            continue
        value = str(item.get("value", "")).strip()
        if value and value != ".":
            return item
    return {}


def _get_json(url: str, headers: Dict[str, str] | None = None, timeout: float = 20) -> Dict[str, Any]:
    req = request.Request(url, headers=headers or {"User-Agent": "DeepReportPlus/0.1"}, method="GET")
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except (TimeoutError, socket.timeout) as exc:
        raise RuntimeError("request timed out") from exc
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {body[:300]}") from exc
    except error.URLError as exc:
        raise RuntimeError(f"URL error: {exc.reason}") from exc
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise RuntimeError("expected object JSON response")
    return parsed


def _post_json(url: str, payload: Dict[str, Any], headers: Dict[str, str], timeout: float = 20) -> Dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = request.Request(url, data=body, headers=headers, method="POST")
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except (TimeoutError, socket.timeout) as exc:
        raise RuntimeError("request timed out") from exc
    except error.HTTPError as exc:
        body_text = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {body_text[:300]}") from exc
    except error.URLError as exc:
        raise RuntimeError(f"URL error: {exc.reason}") from exc
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise RuntimeError("expected object JSON response")
    return parsed


def _get_text(url: str, timeout: float = 12) -> str:
    req = request.Request(url, headers={"User-Agent": "DeepReportPlus/0.1"}, method="GET")
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except (TimeoutError, socket.timeout) as exc:
        raise RuntimeError("request timed out") from exc
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {body[:300]}") from exc
    except error.URLError as exc:
        raise RuntimeError(f"URL error: {exc.reason}") from exc


def _dedupe_records(records: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    deduped: Dict[str, Dict[str, Any]] = {}
    for record in records:
        key = str(record.get("evidence_id") or record.get("source_url") or record.get("title") or "")
        if key and key not in deduped:
            deduped[key] = dict(record)
    return list(deduped.values())


def _skipped(mode: str, reason: str, env_name: str) -> SourcePayload:
    return SourcePayload(hits=[], meta={"mode": mode, "record_count": 0, "failure_reason": reason, "api_key_env": env_name})


def _combined_failure_reason(source_meta: Dict[str, Any]) -> str:
    reasons = []
    for meta in source_meta.values():
        if isinstance(meta, dict) and meta.get("failure_reason"):
            reasons.append(str(meta["failure_reason"]))
    if not reasons:
        return ""
    if all(reason == "missing_api_key" for reason in reasons):
        return "missing_api_key"
    return "partial_source_failures"
