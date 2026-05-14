"""A/H share source discovery helpers for Chinese financial evidence."""

from __future__ import annotations

import hashlib
import re
from typing import Any, Dict, List


_SH_PREFIXES = ("600", "601", "603", "605", "688", "689")
_SZ_PREFIXES = ("000", "001", "002", "003", "300", "301")
_BJ_PREFIXES = ("430", "830", "831", "832", "833", "834", "835", "836", "837", "838", "839", "870", "871", "872", "873", "920")


def normalize_china_symbol(identifier: str) -> Dict[str, str]:
    """Normalize common A/H share identifiers into an exchange-aware payload."""

    raw = str(identifier or "").strip().upper()
    compact = raw.replace(" ", "")
    digits = "".join(re.findall(r"\d+", compact))
    market = ""
    exchange = ""
    stock_code = ""
    normalized_symbol = ""
    yahoo_symbol = ""

    if compact.endswith((".HK", ".HKG")) or compact.startswith("HK"):
        stock_code = digits[-5:].zfill(5) if digits else ""
        if stock_code:
            market = "H-share"
            exchange = "HKEX"
            normalized_symbol = f"{stock_code}.HK"
            yahoo_symbol = normalized_symbol
    elif compact.endswith((".SS", ".SH")) or compact.startswith("SH") or (len(digits) >= 6 and digits[-6:].startswith(_SH_PREFIXES)):
        stock_code = digits[-6:] if len(digits) >= 6 else digits
        if stock_code:
            market = "A-share"
            exchange = "SSE"
            normalized_symbol = f"{stock_code}.SH"
            yahoo_symbol = f"{stock_code}.SS"
    elif compact.endswith(".SZ") or compact.startswith("SZ") or (len(digits) >= 6 and digits[-6:].startswith(_SZ_PREFIXES)):
        stock_code = digits[-6:] if len(digits) >= 6 else digits
        if stock_code:
            market = "A-share"
            exchange = "SZSE"
            normalized_symbol = f"{stock_code}.SZ"
            yahoo_symbol = normalized_symbol
    elif compact.endswith(".BJ") or compact.startswith("BJ") or (len(digits) >= 6 and digits[-6:].startswith(_BJ_PREFIXES)):
        stock_code = digits[-6:] if len(digits) >= 6 else digits
        if stock_code:
            market = "A-share"
            exchange = "BSE"
            normalized_symbol = f"{stock_code}.BJ"

    return {
        "input": raw,
        "market": market,
        "exchange": exchange,
        "stock_code": stock_code,
        "normalized_symbol": normalized_symbol,
        "yahoo_symbol": yahoo_symbol,
    }


def china_finance_source_map(
    identifier: str,
    period: str = "latest",
    include_market_sources: bool = True,
) -> List[Dict[str, Any]]:
    """Return evidence-like source candidates for A/H share research.

    This first slice intentionally discovers stable authority entry points instead
    of scraping volatile JavaScript pages. Downstream agents can use these records
    as source constraints and later replace them with structured extractors.
    """

    info = normalize_china_symbol(identifier)
    if not info.get("stock_code"):
        return []

    symbol = info["normalized_symbol"]
    code = info["stock_code"]
    period_label = period or "latest"
    records: List[Dict[str, Any]] = []

    if info["market"] == "A-share":
        records.extend(_a_share_official_sources(info, period_label))
        if include_market_sources:
            records.extend(_a_share_market_sources(info, period_label))
    elif info["market"] == "H-share":
        records.extend(_h_share_official_sources(info, period_label))
        if include_market_sources:
            records.extend(_h_share_market_sources(info, period_label))

    for index, record in enumerate(records, start=1):
        record.setdefault("symbol", symbol)
        record.setdefault("period", period_label)
        record.setdefault("trust_level", "high" if record.get("source_type") in {"filing", "company_page"} else "medium")
        record.setdefault("metadata", {})
        record["metadata"].update(
            {
                "input_symbol": info["input"],
                "normalized_symbol": symbol,
                "stock_code": code,
                "market": info["market"],
                "exchange": info["exchange"],
                "china_finance_layer": "source_discovery_v1",
            }
        )
        record["evidence_id"] = _evidence_id(symbol=symbol, url=str(record.get("source_url", "")), index=index)
        record["sample_id"] = record["evidence_id"]
        record["url"] = record.get("source_url", "")
    return records


def _a_share_official_sources(info: Dict[str, str], period: str) -> List[Dict[str, Any]]:
    code = info["stock_code"]
    exchange = info["exchange"]
    symbol = info["normalized_symbol"]
    records = [
        {
            "source_type": "filing",
            "title": f"{symbol} 巨潮资讯公告与定期报告入口",
            "content": (
                f"{symbol} 的 A 股公司公告、定期报告和临时公告应优先通过巨潮资讯等法定信息披露入口核验；"
                f"本记录用于约束后续检索优先使用官方披露来源。"
            ),
            "source_url": "https://www.cninfo.com.cn/new/snapshot/companyListCn",
            "publish_time": "",
            "score": 1.0,
            "metadata": {"period": period, "source_role": "official_disclosure_portal"},
        }
    ]
    if exchange == "SSE":
        records.append(
            {
                "source_type": "company_page",
                "title": f"{symbol} 上交所上市公司资料入口",
                "content": f"{symbol} 属于上交所标的，交易所公司资料页用于核验上市地点、证券简称和官方披露入口。",
                "source_url": f"https://www.sse.com.cn/assortment/stock/list/info/company/index.shtml?COMPANY_CODE={code}",
                "publish_time": "",
                "score": 0.96,
                "metadata": {"period": period, "source_role": "exchange_company_page"},
            }
        )
    elif exchange == "SZSE":
        records.append(
            {
                "source_type": "company_page",
                "title": f"{symbol} 深交所证券资料入口",
                "content": f"{symbol} 属于深交所标的，交易所证券资料入口用于核验上市地点、证券简称和官方披露入口。",
                "source_url": f"https://www.szse.cn/certificate/individual/index.html?code={code}",
                "publish_time": "",
                "score": 0.96,
                "metadata": {"period": period, "source_role": "exchange_company_page"},
            }
        )
    elif exchange == "BSE":
        records.append(
            {
                "source_type": "company_page",
                "title": f"{symbol} 北交所上市公司资料入口",
                "content": f"{symbol} 属于北交所标的，北交所官网和巨潮资讯应作为公告与证券资料核验入口。",
                "source_url": "https://www.bse.cn/",
                "publish_time": "",
                "score": 0.94,
                "metadata": {"period": period, "source_role": "exchange_company_page"},
            }
        )
    return records


def _a_share_market_sources(info: Dict[str, str], period: str) -> List[Dict[str, Any]]:
    code = info["stock_code"]
    exchange_prefix = "sh" if info["exchange"] == "SSE" else "sz" if info["exchange"] == "SZSE" else "bj"
    symbol = info["normalized_symbol"]
    return [
        {
            "source_type": "market_data",
            "title": f"{symbol} 东方财富行情入口",
            "content": f"{symbol} 的最新价、成交量、市值等行情字段可通过东方财富行情页作为市场数据候选源，再与交易所/公告口径区分使用。",
            "source_url": f"https://quote.eastmoney.com/{exchange_prefix}{code}.html",
            "publish_time": "",
            "score": 0.78,
            "metadata": {"period": period, "source_role": "market_snapshot_candidate"},
        },
        {
            "source_type": "market_data",
            "title": f"{symbol} 同花顺行情入口",
            "content": f"{symbol} 的行情和估值字段可通过同花顺个股页作为辅助市场数据源，不能单独支撑核心财务报表结论。",
            "source_url": f"https://stockpage.10jqka.com.cn/{code}/",
            "publish_time": "",
            "score": 0.72,
            "metadata": {"period": period, "source_role": "market_snapshot_candidate"},
        },
    ]


def _h_share_official_sources(info: Dict[str, str], period: str) -> List[Dict[str, Any]]:
    symbol = info["normalized_symbol"]
    return [
        {
            "source_type": "filing",
            "title": f"{symbol} 港交所披露易公告入口",
            "content": f"{symbol} 的港股公告、年报和中期报告应优先通过港交所披露易核验。",
            "source_url": "https://www.hkexnews.hk/index_c.htm",
            "publish_time": "",
            "score": 1.0,
            "metadata": {"period": period, "source_role": "official_disclosure_portal"},
        },
        {
            "source_type": "company_page",
            "title": f"{symbol} 港交所证券资料入口",
            "content": f"{symbol} 的证券简称、上市资料和市场分类应通过港交所官方市场数据入口核验。",
            "source_url": "https://www.hkex.com.hk/Market-Data/Securities-Prices/Equities?sc_lang=zh-HK",
            "publish_time": "",
            "score": 0.94,
            "metadata": {"period": period, "source_role": "exchange_company_page"},
        },
    ]


def _h_share_market_sources(info: Dict[str, str], period: str) -> List[Dict[str, Any]]:
    code = info["stock_code"]
    symbol = info["normalized_symbol"]
    return [
        {
            "source_type": "market_data",
            "title": f"{symbol} 东方财富港股行情入口",
            "content": f"{symbol} 的港股最新价、成交量和市值字段可通过东方财富港股行情页作为辅助市场数据源。",
            "source_url": f"https://quote.eastmoney.com/hk/{code}.html",
            "publish_time": "",
            "score": 0.76,
            "metadata": {"period": period, "source_role": "market_snapshot_candidate"},
        }
    ]


def _evidence_id(symbol: str, url: str, index: int) -> str:
    digest = hashlib.sha1(f"{symbol}|{url}|{index}".encode("utf-8")).hexdigest()[:10]
    safe_symbol = symbol.replace(".", "_").replace("-", "_")
    return f"china_finance_{safe_symbol}_{digest}"
