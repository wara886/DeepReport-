"""SEC CompanyFacts adapter for real-time structured financial evidence."""

from __future__ import annotations

from datetime import date, datetime
from functools import lru_cache
import hashlib
import json
import os
from typing import Any, Dict, Iterable, List
from urllib import error, request


SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_COMPANYFACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"

REVENUE_CONCEPTS = (
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "Revenues",
    "SalesRevenueNet",
    # Bank / financial institution revenue concepts
    "RevenuesNetOfInterestExpense",
    "NoninterestIncome",
    "InterestAndDividendIncomeOperating",
)
GROSS_PROFIT_CONCEPTS = ("GrossProfit",)
OPERATING_INCOME_CONCEPTS = ("OperatingIncomeLoss",)
NET_INCOME_CONCEPTS = ("NetIncomeLoss", "ProfitLoss")
OPERATING_CASH_FLOW_CONCEPTS = ("NetCashProvidedByUsedInOperatingActivities",)
CAPEX_CONCEPTS = ("PaymentsToAcquirePropertyPlantAndEquipment",)
# Finance lease principal payments are part of the official FCF definition used by many companies
# (e.g. Meta, Alphabet). Deducting them aligns with company-disclosed FCF.
FINANCE_LEASE_CONCEPTS = (
    "FinanceLeasePrincipalPayments",
    "RepaymentsOfFinanceLeaseLiabilities",
)
# Non-recurring / one-time item concepts for earnings quality analysis
INCOME_TAX_BENEFIT_CONCEPTS = (
    "IncomeTaxExpenseBenefit",  # negative value = benefit
)
RESTRUCTURING_CONCEPTS = (
    "RestructuringCharges",
    "RestructuringAndRelatedCostIncurredCost",
)
ASSET_IMPAIRMENT_CONCEPTS = (
    "GoodwillImpairmentLoss",
    "AssetImpairmentCharges",
    "ImpairmentOfIntangibleAssetsExcludingGoodwill",
)
ASSETS_CONCEPTS = ("Assets",)
LIABILITIES_CONCEPTS = ("Liabilities",)
EQUITY_CONCEPTS = ("StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest")
DILUTED_SHARES_CONCEPTS = ("WeightedAverageNumberOfDilutedSharesOutstanding",)
DILUTED_EPS_CONCEPTS = ("EarningsPerShareDiluted",)


def fetch_sec_companyfacts_evidence(
    symbol: str,
    period: str = "latest",
    timeout: int = 20,
    user_agent: str | None = None,
) -> Dict[str, Any]:
    """Fetch SEC CompanyFacts and convert the latest filing facts into one evidence record."""

    symbol = str(symbol or "").strip().upper()
    if not symbol:
        raise ValueError("symbol is required")

    user_agent = user_agent or _sec_user_agent()
    ticker_payload = _cached_sec_tickers(timeout=timeout, user_agent=user_agent)
    cik, company_name = cik_for_symbol(symbol=symbol, ticker_payload=ticker_payload)
    if not cik:
        raise RuntimeError(f"SEC ticker mapping not found for symbol: {symbol}")

    facts_payload = _get_json(
        SEC_COMPANYFACTS_URL.format(cik=str(cik).zfill(10)),
        timeout=timeout,
        user_agent=user_agent,
    )
    return companyfacts_to_evidence(
        symbol=symbol,
        cik=str(cik).zfill(10),
        company_name=company_name or str(facts_payload.get("entityName") or symbol),
        facts_payload=facts_payload,
        requested_period=period,
    )


def cik_for_symbol(symbol: str, ticker_payload: Dict[str, Any]) -> tuple[str, str]:
    symbol = str(symbol or "").strip().upper()
    for item in ticker_payload.values():
        if not isinstance(item, dict):
            continue
        if str(item.get("ticker") or "").upper() == symbol:
            cik = str(item.get("cik_str") or "").strip()
            return cik.zfill(10), str(item.get("title") or "")
    return "", ""


def companyfacts_to_evidence(
    symbol: str,
    cik: str,
    company_name: str,
    facts_payload: Dict[str, Any],
    requested_period: str = "latest",
) -> Dict[str, Any]:
    facts = facts_payload.get("facts", {}) if isinstance(facts_payload, dict) else {}
    us_gaap = facts.get("us-gaap", {}) if isinstance(facts.get("us-gaap"), dict) else {}
    anchor = _latest_duration_fact(us_gaap, REVENUE_CONCEPTS)
    if not anchor:
        raise RuntimeError(f"SEC CompanyFacts revenue facts not found for {symbol}")

    end = str(anchor.get("end") or "")
    fy = str(anchor.get("fy") or "")
    fp = str(anchor.get("fp") or "")
    form = str(anchor.get("form") or "")
    filed = str(anchor.get("filed") or "")
    accession = str(anchor.get("accn") or "")
    period_label = _period_label(fy=fy, fp=fp, fallback=requested_period)

    revenue = _fact_value(anchor)
    previous_revenue = _matching_prior_year_fact_value(us_gaap, REVENUE_CONCEPTS, anchor)
    revenue_growth = ((revenue - previous_revenue) / previous_revenue * 100) if revenue is not None and previous_revenue else None
    gross_profit = _fact_value(_matching_duration_fact(us_gaap, GROSS_PROFIT_CONCEPTS, anchor))
    operating_income = _fact_value(_matching_duration_fact(us_gaap, OPERATING_INCOME_CONCEPTS, anchor))
    net_income = _fact_value(_matching_duration_fact(us_gaap, NET_INCOME_CONCEPTS, anchor))
    operating_cash_flow = _fact_value(_matching_duration_fact(us_gaap, OPERATING_CASH_FLOW_CONCEPTS, anchor, allow_ytd=True))
    capex = _fact_value(_matching_duration_fact(us_gaap, CAPEX_CONCEPTS, anchor, allow_ytd=True))
    finance_lease_payments = _fact_value(_matching_duration_fact(us_gaap, FINANCE_LEASE_CONCEPTS, anchor, allow_ytd=True))
    income_tax = _fact_value(_matching_duration_fact(us_gaap, INCOME_TAX_BENEFIT_CONCEPTS, anchor, allow_ytd=True))
    restructuring = _fact_value(_matching_duration_fact(us_gaap, RESTRUCTURING_CONCEPTS, anchor, allow_ytd=True))
    asset_impairment = _fact_value(_matching_duration_fact(us_gaap, ASSET_IMPAIRMENT_CONCEPTS, anchor, allow_ytd=True))
    assets = _fact_value(_matching_instant_fact(us_gaap, ASSETS_CONCEPTS, end=end))
    liabilities = _fact_value(_matching_instant_fact(us_gaap, LIABILITIES_CONCEPTS, end=end))
    equity = _fact_value(_matching_instant_fact(us_gaap, EQUITY_CONCEPTS, end=end))
    diluted_shares = _fact_value(_matching_duration_fact(us_gaap, DILUTED_SHARES_CONCEPTS, anchor), units=("shares",))
    diluted_eps = _fact_value(_matching_duration_fact(us_gaap, DILUTED_EPS_CONCEPTS, anchor), units=("USD/shares", "USD/shares"))

    free_cash_flow = None
    fcf_methodology = None
    if operating_cash_flow is not None and capex is not None:
        if finance_lease_payments is not None:
            # Align with company-disclosed FCF: OCF - CapEx - finance lease principal payments
            free_cash_flow = operating_cash_flow - abs(capex) - abs(finance_lease_payments)
            fcf_methodology = "OCF - CapEx - finance lease payments (company-disclosed definition)"
        else:
            # Fallback: OCF - CapEx only; may differ from company-disclosed FCF if finance leases exist
            free_cash_flow = operating_cash_flow - abs(capex)
            fcf_methodology = "OCF - CapEx (simplified; finance lease payments not available in XBRL)"

    # Determine period scope for cash flow metrics (YTD vs quarter)
    anchor_days = _duration_days(anchor)
    ocf_fact = _matching_duration_fact(us_gaap, OPERATING_CASH_FLOW_CONCEPTS, anchor, allow_ytd=True)
    ocf_days = _duration_days(ocf_fact) if ocf_fact else anchor_days
    # YTD if duration is more than 1.5x a single quarter (~135 days)
    ocf_period_type = "YTD" if ocf_days > 135 else "quarter"

    # Annualization factor: quarterly filings (10-Q, ~60-135 days) need ×4 for flow metrics used in ratios.
    # Annual filings (10-K, ~300+ days) are already full-year, factor = 1.
    is_quarterly = anchor_days < 135
    annualization_factor = 4 if is_quarterly else 1

    # Annualized net income for ratio purposes (ROE, ROA).
    # We keep net_income_billion as the raw reported period value for transparency;
    # ratios that require annual figures use the annualized version.
    net_income_annualized = (net_income * annualization_factor) if net_income is not None else None
    roa_pct = _pct(net_income_annualized, assets)
    roe_pct = _pct(net_income_annualized, equity)

    metrics = {
        "symbol": symbol,
        "period": period_label,
        "revenue_billion": _billions(revenue),
        "revenue_growth_pct": _round(revenue_growth),
        "gross_profit_billion": _billions(gross_profit),
        "gross_margin_pct": _pct(gross_profit, revenue),
        "operating_income_billion": _billions(operating_income),
        "operating_margin_pct": _pct(operating_income, revenue),
        "net_income_billion": _billions(net_income),
        "net_margin_pct": _pct(net_income, revenue),
        "operating_cash_flow_billion": _billions(operating_cash_flow),
        "operating_cash_flow_period_type": ocf_period_type,
        "capital_expenditure_billion": _billions(abs(capex) if capex is not None else None),
        "finance_lease_payments_billion": _billions(abs(finance_lease_payments) if finance_lease_payments is not None else None),
        "free_cash_flow_billion": _billions(free_cash_flow),
        "free_cash_flow_period_type": ocf_period_type,
        "free_cash_flow_methodology": fcf_methodology,
        # Non-recurring items (negative income_tax = tax benefit)
        "income_tax_billion": _billions(income_tax),
        "income_tax_benefit_billion": _billions(-income_tax if income_tax is not None and income_tax < 0 else None),
        "restructuring_charges_billion": _billions(restructuring),
        "asset_impairment_billion": _billions(asset_impairment),
        "total_assets_billion": _billions(assets),
        "total_liabilities_billion": _billions(liabilities),
        "shareholder_equity_billion": _billions(equity),
        "is_quarterly": is_quarterly,
        "annualization_factor": annualization_factor,
        "roa_pct": roa_pct,
        "roe_pct": roe_pct,
        "diluted_shares_billion": _billions(diluted_shares),
        "diluted_eps": _round(diluted_eps),
    }
    metrics = {key: value for key, value in metrics.items() if value is not None}
    content = _metrics_content(symbol=symbol, period=period_label, metrics=metrics)
    digest = hashlib.sha1(f"{symbol}|{cik}|{period_label}|{filed}|{content}".encode("utf-8")).hexdigest()[:10]
    source_url = _filing_url(cik=cik, accession=accession)
    evidence_id = f"{symbol}_{period_label.replace(' ', '')}_sec_companyfacts_{digest}"
    return {
        "evidence_id": evidence_id,
        "sample_id": evidence_id,
        "symbol": symbol,
        "period": period_label,
        "source_type": "financials",
        "title": f"{symbol} {period_label} SEC CompanyFacts financial statement facts",
        "content": content,
        "source_url": source_url or SEC_COMPANYFACTS_URL.format(cik=str(cik).zfill(10)),
        "publish_time": filed,
        "trust_level": "high",
        "score": 12.0,
        "metadata": {
            **metrics,
            "provider": "sec_companyfacts",
            "company_name": company_name,
            "cik": str(cik).zfill(10),
            "form": form,
            "filed": filed,
            "end_date": end,
            "accession": accession,
            "source_table_id": f"{symbol.lower()}_{period_label.lower().replace(' ', '_')}_sec_companyfacts",
            "statement_source": "SEC XBRL CompanyFacts API",
            "requested_period": requested_period,
        },
    }


def _get_json(url: str, timeout: int, user_agent: str) -> Dict[str, Any]:
    req = request.Request(
        url,
        headers={
            "User-Agent": user_agent,
            "Accept": "application/json",
            "Accept-Encoding": "identity",
        },
        method="GET",
    )
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"SEC HTTP {exc.code}: {body[:300]}") from exc
    except error.URLError as exc:
        raise RuntimeError(f"SEC URL error: {exc.reason}") from exc


@lru_cache(maxsize=8)
def _cached_sec_tickers(timeout: int, user_agent: str) -> Dict[str, Any]:
    return _get_json(SEC_TICKERS_URL, timeout=timeout, user_agent=user_agent)


def _sec_user_agent() -> str:
    return os.environ.get("SEC_USER_AGENT", "OpenDeepReportPlus/0.1 contact noreply@example.com").strip()


def _latest_duration_fact(us_gaap: Dict[str, Any], concepts: Iterable[str]) -> Dict[str, Any]:
    candidates = _facts_for_concepts(us_gaap, concepts, units=("USD",))
    forms = {"10-Q", "10-K"}
    candidates = [item for item in candidates if str(item.get("form") or "") in forms and _fact_value(item) is not None]
    quarterly = [item for item in candidates if _duration_days(item) in range(60, 121)]
    if quarterly:
        return _latest_by_filed_end(quarterly)
    # Fallback: prefer the most recent annual (10-K) filing over arbitrary old data
    annual = [item for item in candidates if str(item.get("form") or "") == "10-K"]
    pool = annual or candidates
    return _latest_by_filed_end(pool)


def _matching_duration_fact(
    us_gaap: Dict[str, Any],
    concepts: Iterable[str],
    anchor: Dict[str, Any],
    allow_ytd: bool = False,
) -> Dict[str, Any]:
    candidates = _facts_for_concepts(us_gaap, concepts, units=("USD", "shares", "USD/shares"))
    candidates = [item for item in candidates if str(item.get("form") or "") in {"10-Q", "10-K"} and _fact_value(item, units=("USD", "shares", "USD/shares")) is not None]
    end = str(anchor.get("end") or "")
    fy = str(anchor.get("fy") or "")
    fp = str(anchor.get("fp") or "")
    same_period = [item for item in candidates if str(item.get("end") or "") == end and str(item.get("fy") or "") == fy and str(item.get("fp") or "") == fp]
    if not allow_ytd:
        anchor_days = _duration_days(anchor)
        same_period = [item for item in same_period if abs(_duration_days(item) - anchor_days) <= 8]
    if same_period:
        return _latest_by_filed_end(same_period)
    same_end = [item for item in candidates if str(item.get("end") or "") == end]
    if not allow_ytd:
        anchor_days = _duration_days(anchor)
        same_end = [item for item in same_end if abs(_duration_days(item) - anchor_days) <= 8]
    return _latest_by_filed_end(same_end)


def _matching_instant_fact(us_gaap: Dict[str, Any], concepts: Iterable[str], end: str) -> Dict[str, Any]:
    candidates = _facts_for_concepts(us_gaap, concepts, units=("USD",))
    candidates = [item for item in candidates if str(item.get("form") or "") in {"10-Q", "10-K"} and str(item.get("end") or "") == end]
    return _latest_by_filed_end(candidates)


def _matching_prior_year_fact_value(us_gaap: Dict[str, Any], concepts: Iterable[str], anchor: Dict[str, Any]) -> float | None:
    try:
        fy = int(anchor.get("fy"))
    except (TypeError, ValueError):
        return None
    fp = str(anchor.get("fp") or "")
    anchor_days = _duration_days(anchor)
    candidates = _facts_for_concepts(us_gaap, concepts, units=("USD",))
    matches = [
        item
        for item in candidates
        if str(item.get("form") or "") in {"10-Q", "10-K"}
        and str(item.get("fp") or "") == fp
        and str(item.get("fy") or "") == str(fy - 1)
        and abs(_duration_days(item) - anchor_days) <= 8
    ]
    return _fact_value(_latest_by_filed_end(matches))


def _facts_for_concepts(us_gaap: Dict[str, Any], concepts: Iterable[str], units: tuple[str, ...]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for concept in concepts:
        payload = us_gaap.get(concept)
        if not isinstance(payload, dict):
            continue
        unit_payload = payload.get("units", {}) if isinstance(payload.get("units"), dict) else {}
        for unit in units:
            values = unit_payload.get(unit)
            if isinstance(values, list):
                for item in values:
                    if isinstance(item, dict):
                        row = dict(item)
                        row["_concept"] = concept
                        row["_unit"] = unit
                        rows.append(row)
    return rows


def _latest_by_filed_end(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not rows:
        return {}
    return sorted(rows, key=lambda item: (_date_key(item.get("filed")), _date_key(item.get("end"))), reverse=True)[0]


def _fact_value(item: Dict[str, Any], units: tuple[str, ...] = ("USD",)) -> float | None:
    if not isinstance(item, dict):
        return None
    if item.get("_unit") not in units:
        return None
    try:
        value = item.get("val")
        if value is None:
            return None
        output = float(value)
        if output != output:
            return None
        return output
    except (TypeError, ValueError):
        return None


def _duration_days(item: Dict[str, Any]) -> int:
    try:
        start = datetime.fromisoformat(str(item.get("start"))).date()
        end = datetime.fromisoformat(str(item.get("end"))).date()
        return max((end - start).days + 1, 0)
    except (TypeError, ValueError):
        return 0


def _date_key(value: Any) -> date:
    try:
        return datetime.fromisoformat(str(value)).date()
    except (TypeError, ValueError):
        return date.min


def _period_label(fy: str, fp: str, fallback: str) -> str:
    if fy and fp:
        return f"FY{fy} {fp}"
    return fallback or "latest"


def _billions(value: float | None) -> float | None:
    return round(float(value) / 1_000_000_000, 6) if value is not None else None


def _pct(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator in (None, 0):
        return None
    return round(float(numerator) / float(denominator) * 100, 6)


def _round(value: float | None) -> float | None:
    return round(float(value), 6) if value is not None else None


def _metrics_content(symbol: str, period: str, metrics: Dict[str, Any]) -> str:
    parts = [
        f"{symbol} {period} SEC CompanyFacts structured financials.",
        f"Revenue {metrics.get('revenue_billion')}B",
        f"revenue growth {metrics.get('revenue_growth_pct')}%",
        f"gross margin {metrics.get('gross_margin_pct')}%",
        f"net margin {metrics.get('net_margin_pct')}%",
        f"ROE {metrics.get('roe_pct')}%",
        f"ROA {metrics.get('roa_pct')}%",
        f"operating cash flow {metrics.get('operating_cash_flow_billion')}B",
        f"free cash flow {metrics.get('free_cash_flow_billion')}B",
        f"net income {metrics.get('net_income_billion')}B",
        f"total assets {metrics.get('total_assets_billion')}B",
        f"total liabilities {metrics.get('total_liabilities_billion')}B",
        f"shareholder equity {metrics.get('shareholder_equity_billion')}B",
    ]
    return ", ".join(part for part in parts if "None" not in part) + "."


def _filing_url(cik: str, accession: str) -> str:
    if not accession:
        return ""
    cik_int = str(int(cik))
    accession_clean = accession.replace("-", "")
    return f"https://www.sec.gov/Archives/edgar/data/{cik_int}/{accession_clean}/"
