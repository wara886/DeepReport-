"""Normalize structured statement evidence into canonical financial metrics."""

from __future__ import annotations

from datetime import date
import re
from typing import Any, Dict, Iterable, List

from src.data.company_universe import infer_market_from_symbol
from src.market.currency_rules import infer_statement_currency
from src.utils.money import UNKNOWN_CURRENCY, normalize_currency_code
from src.utils.periods import parse_iso_date, parse_quarter, period_match, period_target_date
from src.data.financial_quality import build_net_income_quality_fields


CORE_METRICS = ("revenue", "net_income", "gross_margin", "free_cash_flow")


def build_standard_financial_metrics(records: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    """Build canonical metric rows from local summaries and structured filings."""

    metrics: List[Dict[str, Any]] = []
    rejected_metrics: List[Dict[str, Any]] = []
    for record in [item for item in records if isinstance(item, dict)]:
        source_type = str(record.get("source_type", "")).lower()
        if source_type == "eastmoney_financials":
            rows, rejected = _partition_period_rows(_eastmoney_metric_rows(record), record)
            metrics.extend(rows)
            rejected_metrics.extend(rejected)
        elif source_type == "sec_companyfacts":
            rows, rejected = _partition_period_rows(_sec_companyfacts_metric_rows(record), record)
            metrics.extend(rows)
            rejected_metrics.extend(rejected)
        elif source_type == "pdf_statement_table":
            rows, rejected = _partition_period_rows(_pdf_statement_metric_rows(record), record)
            metrics.extend(rows)
            rejected_metrics.extend(rejected)
        elif source_type in {"market_api", "market_data"}:
            rows, rejected = _partition_period_rows(_market_api_metric_rows(record), record)
            metrics.extend(rows)
            rejected_metrics.extend(rejected)
        elif source_type == "financials":
            rows, rejected = _partition_period_rows(_local_financial_metric_rows(record), record)
            metrics.extend(rows)
            rejected_metrics.extend(rejected)
        elif source_type == "hk_financials":
            rows, rejected = _partition_period_rows(_hk_financials_metric_rows(record), record)
            metrics.extend(rows)
            rejected_metrics.extend(rejected)

    # Deduplicate: for same metric_name, keep the highest-confidence entry,
    # preferring structured sources (eastmoney, local financials) over
    # PDF-extracted tables which may have scale/unit errors.
    deduped: Dict[str, Dict[str, Any]] = {}
    for item in metrics:
        name = str(item.get("metric_name", ""))
        if not name:
            continue
        source_id = str(item.get("source_evidence_id") or "")
        is_pdf = "pdf_" in source_id.lower() or "pdf" in str(item.get("calculation_formula") or "").lower()
        existing = deduped.get(name)
        if existing is None:
            deduped[name] = item
            continue
        existing_conf = float(existing.get("confidence", 0) or 0)
        current_conf = float(item.get("confidence", 0) or 0)
        existing_pdf = "pdf_" in str(existing.get("source_evidence_id") or "").lower() or "pdf" in str(existing.get("calculation_formula") or "").lower()
        # If current is PDF and existing is not, skip current (PDF loses to structured)
        if is_pdf and not existing_pdf:
            continue
        # If existing is PDF and current is not, replace with structured
        if existing_pdf and not is_pdf:
            deduped[name] = item
            continue
        # Both same class: keep the higher-confidence one
        if current_conf > existing_conf:
            deduped[name] = item
    deduped_metrics = list(deduped.values())

    present = {str(item.get("metric_name", "")) for item in deduped_metrics}
    return {
        "metrics": deduped_metrics,
        "metric_count": len(deduped_metrics),
        "rejected_metrics": rejected_metrics,
        "rejected_metric_count": len(rejected_metrics),
        "coverage": {
            "required_metrics": list(CORE_METRICS),
            "present_metrics": sorted(present),
            "has_core_metric_lineage": set(CORE_METRICS).issubset(present),
            "rejected_metric_count": len(rejected_metrics),
        },
    }


def build_standard_statement_rows(records: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Build normalized income, balance-sheet, and cash-flow rows."""

    rows: List[Dict[str, Any]] = []
    for record in [item for item in records if isinstance(item, dict)]:
        source_type = str(record.get("source_type", "")).lower()
        if source_type == "eastmoney_financials":
            accepted, _rejected = _partition_period_rows(_eastmoney_statement_rows(record), record)
            rows.extend(accepted)
        elif source_type == "sec_companyfacts":
            accepted, _rejected = _partition_period_rows(_sec_companyfacts_statement_rows(record), record)
            rows.extend(accepted)
        elif source_type == "pdf_statement_table":
            accepted, _rejected = _partition_period_rows(_pdf_statement_rows(record), record)
            rows.extend(accepted)
        elif source_type in {"market_api", "market_data"}:
            accepted, _rejected = _partition_period_rows(_market_api_statement_rows(record), record)
            rows.extend(accepted)
        elif source_type == "hk_financials":
            accepted, _rejected = _partition_period_rows(_hk_financials_statement_rows(record), record)
            rows.extend(accepted)
    priority = {"sec_companyfacts": 0, "sec_filing": 1, "eastmoney_financials": 2, "pdf_statement_table": 3, "hk_financials": 4, "market_api": 5, "market_data": 5}
    rows.sort(key=lambda row: priority.get(str(row.get("source_type") or "").lower(), 99))
    # Deduplicate: keep first row per line_item (most authoritative source wins)
    seen: Dict[str, Dict[str, Any]] = {}
    deduped_rows: List[Dict[str, Any]] = []
    for row in rows:
        key = str(row.get("line_item") or "")
        if not key or key in seen:
            continue
        seen[key] = row
        deduped_rows.append(row)
    return deduped_rows


def build_standard_table_artifacts(records: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Group normalized rows into table artifacts with source lineage."""

    rows = build_standard_statement_rows(records)
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for row in rows:
        table_id = str(row.get("source_table_id") or "")
        if table_id:
            grouped.setdefault(table_id, []).append(row)

    tables: List[Dict[str, Any]] = []
    for table_id, table_rows in grouped.items():
        first = table_rows[0] if table_rows else {}
        tables.append(
            {
                "table_id": table_id,
                "table_type": str(first.get("statement", "financial_statement")),
                "rows": table_rows,
                "columns": sorted({key for row in table_rows for key in row.keys()}),
                "source_evidence_id": str(first.get("evidence_id", "")),
                "period": str(first.get("period", "")),
                "currency": normalize_currency_code(first.get("currency") or first.get("unit")),
                "unit": str(first.get("scale") or "raw"),
                "extraction_method": "structured_statement_api_normalization",
                "confidence": 0.86,
                "metadata": {"provider": str(first.get("provider", ""))},
            }
        )
    return tables


def _eastmoney_metric_rows(record: Dict[str, Any]) -> List[Dict[str, Any]]:
    metadata = _dict(record.get("metadata"))
    raw = _dict(metadata.get("raw"))
    table_type = str(metadata.get("table_type") or "")
    evidence_id = _evidence_id(record)
    symbol = str(record.get("symbol") or raw.get("SECURITY_CODE") or "")
    period = str(record.get("period") or "")
    report_date = str(raw.get("REPORT_DATE") or raw.get("REPORTDATE") or "")
    notice_date = str(raw.get("NOTICE_DATE") or record.get("publish_time") or "")
    table_id = _table_id(symbol, period, evidence_id, table_type or "eastmoney")

    rows: List[Dict[str, Any]] = []
    if table_type == "income":
        revenue = _first_number(raw, ["TOTAL_OPERATE_INCOME", "OPERATE_INCOME"])
        net_income = _first_number(raw, ["PARENT_NETPROFIT", "NETPROFIT"])
        cost = _first_number(raw, ["TOTAL_OPERATE_COST", "OPERATE_COST"])
        if revenue is not None:
            rows.append(_metric_row("revenue", revenue, "CNY", period, table_id, evidence_id, "reported total operating revenue", 0.9, symbol, report_date, notice_date, raw))
        if net_income is not None:
            rows.append(_metric_row("net_income", net_income, "CNY", period, table_id, evidence_id, "reported parent net profit", 0.9, symbol, report_date, notice_date, raw))
        if revenue not in (None, 0) and cost is not None:
            rows.append(_metric_row("gross_margin", (revenue - cost) / revenue * 100.0, "pct", period, table_id, evidence_id, "(revenue - operating cost) / revenue", 0.72, symbol, report_date, notice_date, raw))
    elif table_type == "balance":
        for name, keys in [
            ("total_assets", ["TOTAL_ASSETS"]),
            ("total_liabilities", ["TOTAL_LIABILITIES"]),
            ("equity", ["TOTAL_EQUITY", "TOTAL_PARENT_EQUITY"]),
        ]:
            value = _first_number(raw, keys)
            if value is not None:
                rows.append(_metric_row(name, value, "CNY", period, table_id, evidence_id, f"reported {name}", 0.88, symbol, report_date, notice_date, raw))
    elif table_type == "cashflow":
        ocf = _first_number(raw, ["NETCASH_OPERATE", "NETCASH_OPERATE_ACT"])
        capex = _first_number(raw, ["CONSTRUCT_LONG_ASSET_PAY_CASH", "PURCHASE_FIX_ASSET"])
        if ocf is not None:
            rows.append(_metric_row("operating_cash_flow", ocf, "CNY", period, table_id, evidence_id, "reported net operating cash flow", 0.88, symbol, report_date, notice_date, raw))
        if capex is not None:
            rows.append(_metric_row("capex", capex, "CNY", period, table_id, evidence_id, "reported cash paid for long-term assets", 0.72, symbol, report_date, notice_date, raw))
        if ocf is not None and capex is not None:
            rows.append(_metric_row("free_cash_flow", ocf - capex, "CNY", period, table_id, evidence_id, "operating_cash_flow - capex", 0.68, symbol, report_date, notice_date, raw))
    return rows


def _sec_companyfacts_metric_rows(record: Dict[str, Any]) -> List[Dict[str, Any]]:
    metadata = _dict(record.get("metadata"))
    facts = _dict(metadata.get("metrics"))
    evidence_id = _evidence_id(record)
    symbol = str(record.get("symbol") or "")
    period = str(record.get("period") or "")
    table_id = _table_id(symbol, period, evidence_id, "sec_companyfacts")
    rows: List[Dict[str, Any]] = []

    # ── 30+ GAAP 指标映射 ──────────────────────────
    # (metric_name, [SEC taxonomy concept names...], formula label)
    mapping = [
        # ── 利润表 (Income Statement) ──
        ("revenue", ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues"], "GAAP revenue"),
        ("net_income", ["NetIncomeLoss"], "GAAP net income"),
        ("gross_profit", ["GrossProfit"], "GAAP gross profit"),
        ("cost_of_revenue", ["CostOfRevenue"], "GAAP cost of revenue"),
        ("operating_income", ["OperatingIncomeLoss"], "GAAP operating income"),
        ("operating_expense", ["OperatingExpenses"], "GAAP operating expenses"),
        ("research_development", ["ResearchAndDevelopmentExpense"], "GAAP R&D expense"),
        ("selling_general_admin", ["SellingGeneralAndAdministrativeExpense"], "GAAP SG&A expense"),
        ("interest_expense", ["InterestExpense", "InterestExpenseNonoperating"], "GAAP interest expense"),
        ("interest_income", ["InterestIncome", "InterestIncomeNonoperating"], "GAAP interest income"),
        ("other_income_expense", ["OtherNonoperatingIncomeExpense", "OtherNonoperatingIncome"], "GAAP other income/expense"),
        ("income_tax_expense", ["IncomeTaxExpenseProvisionBenefit"], "GAAP income tax expense"),
        ("income_from_continuing", ["IncomeLossFromContinuingOperations"], "GAAP income from continuing ops"),
        ("net_income_attributable", ["NetIncomeLossAttributableToParent"], "GAAP net income attributable to parent"),
        ("eps_basic", ["EarningsPerShareBasic"], "GAAP EPS basic"),
        ("eps_diluted", ["EarningsPerShareDiluted"], "GAAP EPS diluted"),
        ("weighted_avg_shares_basic", ["WeightedAverageNumberOfSharesOutstandingBasic"], "GAAP weighted avg shares basic"),
        ("weighted_avg_shares_diluted", ["WeightedAverageNumberOfSharesOutstandingDiluted"], "GAAP weighted avg shares diluted"),
        # ── 资产负债表 (Balance Sheet) ──
        ("total_assets", ["Assets"], "GAAP total assets"),
        ("current_assets", ["AssetsCurrent", "CurrentAssets"], "GAAP current assets"),
        ("cash_and_equivalents", ["CashAndCashEquivalentsAtCarryingValue"], "GAAP cash and equivalents"),
        ("accounts_receivable", ["AccountsReceivableNetCurrent", "AccountsReceivableNet"], "GAAP accounts receivable"),
        ("inventory", ["InventoryNet", "Inventory"], "GAAP inventory"),
        ("property_plant_equipment", ["PropertyPlantAndEquipmentNet"], "GAAP PP&E net"),
        ("goodwill", ["Goodwill"], "GAAP goodwill"),
        ("intangible_assets", ["IntangibleAssetsNetExcludingGoodwill", "IntangibleAssetsNet"], "GAAP intangible assets"),
        ("total_liabilities", ["Liabilities"], "GAAP total liabilities"),
        ("current_liabilities", ["LiabilitiesCurrent", "CurrentLiabilities"], "GAAP current liabilities"),
        ("short_term_debt", ["ShortTermBorrowings"], "GAAP short-term borrowings"),
        ("long_term_debt", ["LongTermDebtNoncurrent", "LongTermDebt"], "GAAP long-term debt"),
        ("accounts_payable", ["AccountsPayableCurrent", "AccountsPayable"], "GAAP accounts payable"),
        ("stockholders_equity", ["StockholdersEquity"], "GAAP stockholders equity"),
        ("retained_earnings", ["RetainedEarningsAccumulatedDeficit"], "GAAP retained earnings"),
        ("accum_other_comprehensive", ["AccumulatedOtherComprehensiveIncomeLossNetOfTax"], "GAAP AOCI"),
        # ── 现金流量表 (Cash Flow) ──
        ("operating_cash_flow",
         ["NetCashProvidedByUsedInOperatingActivities",
          "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"],
         "GAAP operating cash flow"),
        ("investing_cash_flow", ["NetCashProvidedByUsedInInvestingActivities"], "GAAP investing cash flow"),
        ("financing_cash_flow", ["NetCashProvidedByUsedInFinancingActivities"], "GAAP financing cash flow"),
        ("capex",
         ["PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets"],
         "GAAP capital expenditure"),
        ("depreciation_amortization",
         ["DepreciationDepletionAndAmortization", "DepreciationAndAmortization"],
         "GAAP depreciation & amortization"),
        ("stock_based_compensation", ["ShareBasedCompensation"], "GAAP stock-based compensation"),
        ("dividends_paid", ["DividendsPaid", "PaymentsOfDividends"], "GAAP dividends paid"),
    ]
    for metric_name, keys, formula in mapping:
        fact = _first_fact(facts, keys)
        value = _safe_float(fact.get("value")) if fact else None
        if value is None:
            continue
        rows.append(
            _metric_row(
                metric_name=metric_name,
                value=value,
                unit=str(fact.get("unit") or "USD"),
                period=period,
                source_table_id=table_id,
                source_evidence_id=evidence_id,
                calculation_formula=formula,
                confidence=0.92,
                symbol=symbol,
                report_date=str(fact.get("end") or ""),
                notice_date=str(fact.get("filed") or record.get("publish_time") or ""),
                raw=fact,
            )
        )

    # ── 派生指标 ──
    # 自由现金流 = OCF - capex
    ocf = _first_fact(facts, ["NetCashProvidedByUsedInOperatingActivities",
                               "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"])
    capex = _first_fact(facts, ["PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets"])
    ocf_value = _safe_float(ocf.get("value")) if ocf else None
    capex_value = _safe_float(capex.get("value")) if capex else None
    if ocf_value is not None and capex_value is not None:
        raw = dict(ocf)
        raw["capex_value"] = capex_value
        rows.append(
            _metric_row(
                metric_name="free_cash_flow",
                value=ocf_value - capex_value,
                unit=str(ocf.get("unit") or "USD"),
                period=period,
                source_table_id=table_id,
                source_evidence_id=evidence_id,
                calculation_formula="operating_cash_flow - capex",
                confidence=0.72,
                symbol=symbol,
                report_date=str(ocf.get("end") or ""),
                notice_date=str(ocf.get("filed") or record.get("publish_time") or ""),
                raw=raw,
            )
        )

    # EBIT = operating_income (or net_income + tax + interest)
    op_inc = _first_fact(facts, ["OperatingIncomeLoss"])
    op_inc_val = _safe_float(op_inc.get("value")) if op_inc else None
    if op_inc_val is not None:
        rows.append(
            _metric_row(
                metric_name="ebit",
                value=op_inc_val,
                unit=str(op_inc.get("unit") or "USD"),
                period=period,
                source_table_id=table_id,
                source_evidence_id=evidence_id,
                calculation_formula="OperatingIncomeLoss (GAAP EBIT)",
                confidence=0.88,
                symbol=symbol,
                report_date=str(op_inc.get("end") or ""),
                notice_date=str(op_inc.get("filed") or record.get("publish_time") or ""),
                raw=op_inc,
            )
        )

    # gross_margin = gross_profit / revenue (计算逻辑在 coverage 层已完成)
    rev = _first_fact(facts, ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues"])
    gp = _first_fact(facts, ["GrossProfit"])
    rev_val = _safe_float(rev.get("value")) if rev else None
    gp_val = _safe_float(gp.get("value")) if gp else None
    if rev_val and gp_val:
        rows.append(
            _metric_row(
                metric_name="gross_margin",
                value=gp_val / rev_val * 100.0,
                unit="pct",
                period=period,
                source_table_id=table_id,
                source_evidence_id=evidence_id,
                calculation_formula="gross_profit / revenue * 100",
                confidence=0.85,
                symbol=symbol,
                report_date=str(rev.get("end") or ""),
                notice_date=str(rev.get("filed") or record.get("publish_time") or ""),
                raw={"revenue": rev_val, "gross_profit": gp_val},
            )
        )
    return rows


def _sec_companyfacts_statement_rows(record: Dict[str, Any]) -> List[Dict[str, Any]]:
    metadata = _dict(record.get("metadata"))
    facts = _dict(metadata.get("metrics"))
    evidence_id = _evidence_id(record)
    symbol = str(record.get("symbol") or "")
    period = str(record.get("period") or "")
    table_id = _table_id(symbol, period, evidence_id, "sec_companyfacts")
    mapping = [
        # 利润表
        ("income_statement", "revenue", ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues"]),
        ("income_statement", "net_income", ["NetIncomeLoss"]),
        ("income_statement", "gross_profit", ["GrossProfit"]),
        ("income_statement", "cost_of_revenue", ["CostOfRevenue"]),
        ("income_statement", "operating_income", ["OperatingIncomeLoss"]),
        ("income_statement", "operating_expense", ["OperatingExpenses"]),
        ("income_statement", "research_development", ["ResearchAndDevelopmentExpense"]),
        ("income_statement", "selling_general_admin", ["SellingGeneralAndAdministrativeExpense"]),
        ("income_statement", "interest_expense", ["InterestExpense", "InterestExpenseNonoperating"]),
        ("income_statement", "income_tax_expense", ["IncomeTaxExpenseProvisionBenefit"]),
        ("income_statement", "eps_basic", ["EarningsPerShareBasic"]),
        ("income_statement", "eps_diluted", ["EarningsPerShareDiluted"]),
        # 资产负债表
        ("balance_sheet", "total_assets", ["Assets"]),
        ("balance_sheet", "current_assets", ["AssetsCurrent", "CurrentAssets"]),
        ("balance_sheet", "cash_and_equivalents", ["CashAndCashEquivalentsAtCarryingValue"]),
        ("balance_sheet", "accounts_receivable", ["AccountsReceivableNetCurrent", "AccountsReceivableNet"]),
        ("balance_sheet", "inventory", ["InventoryNet", "Inventory"]),
        ("balance_sheet", "property_plant_equipment", ["PropertyPlantAndEquipmentNet"]),
        ("balance_sheet", "goodwill", ["Goodwill"]),
        ("balance_sheet", "intangible_assets", ["IntangibleAssetsNetExcludingGoodwill", "IntangibleAssetsNet"]),
        ("balance_sheet", "total_liabilities", ["Liabilities"]),
        ("balance_sheet", "current_liabilities", ["LiabilitiesCurrent", "CurrentLiabilities"]),
        ("balance_sheet", "long_term_debt", ["LongTermDebtNoncurrent", "LongTermDebt"]),
        ("balance_sheet", "stockholders_equity", ["StockholdersEquity"]),
        ("balance_sheet", "retained_earnings", ["RetainedEarningsAccumulatedDeficit"]),
        # 现金流量表
        ("cash_flow_statement", "operating_cash_flow", ["NetCashProvidedByUsedInOperatingActivities",
                                                          "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"]),
        ("cash_flow_statement", "investing_cash_flow", ["NetCashProvidedByUsedInInvestingActivities"]),
        ("cash_flow_statement", "financing_cash_flow", ["NetCashProvidedByUsedInFinancingActivities"]),
        ("cash_flow_statement", "capex", ["PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets"]),
        ("cash_flow_statement", "depreciation_amortization", ["DepreciationDepletionAndAmortization", "DepreciationAndAmortization"]),
        ("cash_flow_statement", "stock_based_compensation", ["ShareBasedCompensation"]),
        ("cash_flow_statement", "dividends_paid", ["DividendsPaid", "PaymentsOfDividends"]),
    ]
    rows: List[Dict[str, Any]] = []
    for statement, line_item, keys in mapping:
        fact = _first_fact(facts, keys)
        value = _safe_float(fact.get("value")) if fact else None
        if value is None:
            continue
        rows.append(
            {
                "symbol": symbol,
                "period": period,
                "statement": statement,
                "line_item": line_item,
                "value": value,
                "unit": str(fact.get("unit") or "USD"),
                "estimated": False,
                "evidence_id": evidence_id,
                "source_evidence_id": evidence_id,
                "source_table_id": table_id,
                "report_date": str(fact.get("end") or ""),
                "notice_date": str(fact.get("filed") or record.get("publish_time") or ""),
                "source_period": str(fact.get("fy") or fact.get("fp") or period),
                "period_match": _period_match(period=period, report_date=str(fact.get("end") or ""), raw=fact),
                "source_type": "sec_companyfacts",
                "provider": "SEC EDGAR",
            }
        )
    ocf = _first_fact(facts, ["NetCashProvidedByUsedInOperatingActivities", "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"])
    capex = _first_fact(facts, ["PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets"])
    ocf_value = _safe_float(ocf.get("value")) if ocf else None
    capex_value = _safe_float(capex.get("value")) if capex else None
    if ocf_value is not None and capex_value is not None:
        rows.append(
            {
                "symbol": symbol,
                "period": period,
                "statement": "cash_flow_statement",
                "line_item": "free_cash_flow",
                "value": ocf_value - capex_value,
                "unit": str(ocf.get("unit") or "USD"),
                "estimated": False,
                "evidence_id": evidence_id,
                "source_evidence_id": evidence_id,
                "source_table_id": table_id,
                "report_date": str(ocf.get("end") or ""),
                "notice_date": str(ocf.get("filed") or record.get("publish_time") or ""),
                "source_period": str(ocf.get("fy") or ocf.get("fp") or period),
                "period_match": _period_match(period=period, report_date=str(ocf.get("end") or ""), raw=ocf),
                "source_type": "sec_companyfacts",
                "provider": "SEC EDGAR",
                "calculation_formula": "operating_cash_flow - capex",
            }
        )
    return rows


def _eastmoney_statement_rows(record: Dict[str, Any]) -> List[Dict[str, Any]]:
    metadata = _dict(record.get("metadata"))
    raw = _dict(metadata.get("raw"))
    table_type = str(metadata.get("table_type") or "")
    evidence_id = _evidence_id(record)
    symbol = str(record.get("symbol") or raw.get("SECURITY_CODE") or "")
    period = str(record.get("period") or "")
    report_date = str(raw.get("REPORT_DATE") or raw.get("REPORTDATE") or "")
    table_id = _table_id(symbol, period, evidence_id, table_type or "eastmoney")
    mapping = {
        "income": (
            "income_statement",
            [
                ("revenue", ["TOTAL_OPERATE_INCOME", "OPERATE_INCOME"]),
                ("operating_cost", ["TOTAL_OPERATE_COST", "OPERATE_COST"]),
                ("operating_profit", ["OPERATE_PROFIT"]),
                ("total_profit", ["TOTAL_PROFIT"]),
                ("net_income", ["PARENT_NETPROFIT", "NETPROFIT"]),
            ],
        ),
        "balance": (
            "balance_sheet",
            [
                ("total_assets", ["TOTAL_ASSETS"]),
                ("total_liabilities", ["TOTAL_LIABILITIES"]),
                ("equity", ["TOTAL_EQUITY", "TOTAL_PARENT_EQUITY"]),
            ],
        ),
        "cashflow": (
            "cash_flow_statement",
            [
                ("operating_cash_flow", ["NETCASH_OPERATE", "NETCASH_OPERATE_ACT"]),
                ("investing_cash_flow", ["NETCASH_INVEST"]),
                ("financing_cash_flow", ["NETCASH_FINANCE"]),
                ("capex", ["CONSTRUCT_LONG_ASSET_PAY_CASH", "PURCHASE_FIX_ASSET"]),
            ],
        ),
    }
    if table_type not in mapping:
        return []
    statement, items = mapping[table_type]
    rows: List[Dict[str, Any]] = []
    for line_item, keys in items:
        value = _first_number(raw, keys)
        if value is None:
            continue
        rows.append(
            {
                "symbol": symbol,
                "period": period,
                "statement": statement,
                "line_item": line_item,
                "value": value,
                "unit": "CNY",
                "estimated": False,
                "evidence_id": evidence_id,
                "source_evidence_id": evidence_id,
                "source_table_id": table_id,
                "report_date": report_date,
                "period_match": _period_match(period=period, report_date=report_date, raw={"period": period, "end": report_date}),
                "source_type": "eastmoney_financials",
                "provider": "Eastmoney",
            }
        )
    return rows


def _local_financial_metric_rows(record: Dict[str, Any]) -> List[Dict[str, Any]]:
    metadata = _dict(record.get("metadata"))
    evidence_id = _evidence_id(record)
    symbol = str(record.get("symbol") or metadata.get("symbol") or "")
    period = str(record.get("period") or metadata.get("period") or "")
    table_id = _table_id(symbol, period, evidence_id, "financial_metrics")
    metric_map = [
        ("revenue", "revenue_billion", "USD_billion", "reported revenue"),
        ("net_income", "net_income_billion", "USD_billion", "reported net income"),
        ("adjusted_net_income", "adjusted_net_income_billion", "USD_billion", "adjusted or normalized net income"),
        ("non_recurring_gain", "non_recurring_gain_billion", "USD_billion", "non-recurring gain"),
        ("gross_margin", "gross_margin_pct", "pct", "reported gross margin"),
        ("free_cash_flow", "free_cash_flow_billion", "USD_billion", "reported free cash flow"),
    ]
    rows: List[Dict[str, Any]] = []
    for metric_name, key, unit, formula in metric_map:
        value = _first_number({**metadata, **record}, [key])
        if value is not None:
            rows.append(_metric_row(metric_name, value, unit, period, table_id, evidence_id, formula, 0.95, symbol, "", str(record.get("publish_time") or ""), metadata))
    return rows


def _hk_financials_metric_rows(record: Dict[str, Any]) -> List[Dict[str, Any]]:
    """从 hk_financials 引擎的 metadata.rows 中提取 metric rows。"""
    metadata = _dict(record.get("metadata"))
    evidence_id = _evidence_id(record)
    symbol = str(record.get("symbol") or "")
    period = str(record.get("period") or "")
    table_type = str(metadata.get("table_type") or "")
    currency_meta = _statement_currency_meta_for_record(record)
    currency = currency_meta.statement_currency
    unit = _pdf_unit(currency, "raw")  # reuse: returns base currency code
    table_id = str(metadata.get("table_id") or _table_id(symbol, period, evidence_id, "hk_financials"))
    report_date = ""
    notice_date = ""

    rows_raw = metadata.get("rows") if isinstance(metadata.get("rows"), list) else []
    if not rows_raw:
        # Try financials_raw fallback
        fin_raw = _dict(metadata.get("financials_raw"))
        fin_rows = fin_raw.get(table_type, []) if isinstance(fin_raw.get(table_type), list) else []
        rows_raw = fin_rows

    by_item: Dict[str, float] = {}
    for row in rows_raw:
        if not isinstance(row, dict):
            continue
        item = str(row.get("line_item") or "").strip()
        val = _safe_float(row.get("value"))
        if item and val is not None:
            if item not in by_item:
                by_item[item] = val
            if not report_date:
                report_date = str(row.get("end_date") or "")
    if not rows_raw:
        return []

    output: List[Dict[str, Any]] = []
    # Map common yfinance line_item names to metric names
    yf_mapping = [
        ("revenue", "Total Revenue", "yfinance HK revenue"),
        ("net_income", "Net Income", "yfinance HK net income"),
        ("gross_profit", "Gross Profit", "yfinance HK gross profit"),
        ("cost_of_revenue", "Cost Of Revenue", "yfinance HK cost of revenue"),
        ("operating_income", "Operating Income", "yfinance HK operating income"),
        ("research_development", "Research And Development", "yfinance HK R&D"),
        ("selling_general_admin", "Selling General And Administrative", "yfinance HK SG&A"),
        ("interest_expense", "Interest Expense", "yfinance HK interest expense"),
        ("income_tax_expense", "Income Tax Expense", "yfinance HK income tax"),
        ("total_assets", "Total Assets", "yfinance HK total assets"),
        ("current_assets", "Current Assets", "yfinance HK current assets"),
        ("cash_and_equivalents", "Cash And Cash Equivalents", "yfinance HK cash"),
        ("accounts_receivable", "Accounts Receivable", "yfinance HK AR"),
        ("inventory", "Inventory", "yfinance HK inventory"),
        ("property_plant_equipment", "Property Plant And Equipment", "yfinance HK PP&E"),
        ("goodwill", "Goodwill", "yfinance HK goodwill"),
        ("intangible_assets", "Intangible Assets", "yfinance HK intangible assets"),
        ("total_liabilities", "Total Liabilities", "yfinance HK total liabilities"),
        ("current_liabilities", "Current Liabilities", "yfinance HK current liabilities"),
        ("long_term_debt", "Long Term Debt", "yfinance HK long-term debt"),
        ("accounts_payable", "Accounts Payable", "yfinance HK AP"),
        ("stockholders_equity", "Stockholders Equity", "yfinance HK equity"),
        ("retained_earnings", "Retained Earnings", "yfinance HK retained earnings"),
        ("operating_cash_flow", "Operating Cash Flow", "yfinance HK OCF"),
        ("capex", "Capital Expenditure", "yfinance HK capex"),
        ("free_cash_flow", "Free Cash Flow", "yfinance HK FCF"),
        ("depreciation_amortization", "Depreciation And Amortization", "yfinance HK D&A"),
        ("dividends_paid", "Dividends Paid", "yfinance HK dividends"),
    ]
    for metric_name, yf_key, formula in yf_mapping:
        if yf_key in by_item:
            output.append(
                _metric_row(
                    metric_name=metric_name,
                    value=by_item[yf_key],
                    unit=unit,
                    period=period,
                    source_table_id=table_id,
                    source_evidence_id=evidence_id,
                    calculation_formula=formula,
                    confidence=0.72,
                    symbol=symbol,
                    report_date=report_date,
                    notice_date=notice_date,
                    raw={
                        "period": period,
                        "source_type": "hk_financials",
                        "currency_basis": currency_meta.currency_basis,
                        "currency_confidence": currency_meta.confidence,
                        "inferred_from": currency_meta.inferred_from,
                    },
                )
            )
    return output


def _hk_financials_statement_rows(record: Dict[str, Any]) -> List[Dict[str, Any]]:
    """从 hk_financials 引擎的 metadata.rows 中提取 statement rows。"""
    metadata = _dict(record.get("metadata"))
    evidence_id = _evidence_id(record)
    symbol = str(record.get("symbol") or "")
    period = str(record.get("period") or "")
    table_type = str(metadata.get("table_type") or "")
    currency_meta = _statement_currency_meta_for_record(record)
    currency = currency_meta.statement_currency
    table_id = str(metadata.get("table_id") or _table_id(symbol, period, evidence_id, "hk_financials"))

    rows_raw = metadata.get("rows") if isinstance(metadata.get("rows"), list) else []
    if not rows_raw:
        fin_raw = _dict(metadata.get("financials_raw"))
        fin_rows = fin_raw.get(table_type, []) if isinstance(fin_raw.get(table_type), list) else []
        rows_raw = fin_rows
    if not rows_raw:
        return []

    statement_map = {
        "income": "income_statement",
        "balance": "balance_sheet",
        "cashflow": "cash_flow_statement",
    }
    statement = statement_map.get(table_type, "income_statement")

    output: List[Dict[str, Any]] = []
    for row in rows_raw:
        if not isinstance(row, dict):
            continue
        line_item = str(row.get("line_item") or "").strip()
        value = _safe_float(row.get("value"))
        if not line_item or value is None:
            continue
        output.append({
            "symbol": symbol,
            "period": period,
            "statement": statement,
            "line_item": line_item,
            "value": value,
            "unit": currency,
            "currency": currency,
            "scale": "unit",
            "currency_basis": currency_meta.currency_basis,
            "currency_confidence": currency_meta.confidence,
            "inferred_from": currency_meta.inferred_from,
            "evidence_id": evidence_id,
            "source_evidence_id": evidence_id,
            "source_table_id": table_id,
            "report_date": str(row.get("end_date") or ""),
            "source_period": period,
            "period_match": _period_match(period=period, report_date=str(row.get("end_date") or ""), raw={"period": period}),
            "source_type": "hk_financials",
            "provider": "Yahoo Finance",
        })
    return output


def _market_api_metric_rows(record: Dict[str, Any]) -> List[Dict[str, Any]]:
    metadata = _dict(record.get("metadata"))
    financials = _dict(metadata.get("financials"))
    evidence_id = _evidence_id(record)
    symbol = str(record.get("symbol") or "")
    period = str(record.get("period") or "")
    currency_meta = _currency_meta_for_record(record)
    currency = currency_meta.statement_currency
    confidence = 0.62 if currency != UNKNOWN_CURRENCY else 0.46
    table_id = _table_id(symbol, period, evidence_id, "yahoo_financials")
    income = _latest_statement_row(financials, "income", period)
    balance = _latest_statement_row(financials, "balance", period)
    cashflow = _latest_statement_row(financials, "cashflow", period)
    rows: List[Dict[str, Any]] = []

    revenue = _first_number(income, ["Total Revenue", "totalRevenue", "Operating Revenue"])
    net_income = _first_number(income, ["Net Income", "netIncome", "Net Income Common Stockholders"])
    quality = build_net_income_quality_fields(financials, income, net_income=net_income, revenue=revenue)
    adjusted_net_income = quality.get("adjusted_net_income")
    gross_profit = _first_number(income, ["Gross Profit", "grossProfit"])
    total_assets = _first_number(balance, ["Total Assets", "totalAssets"])
    total_liabilities = _first_number(balance, ["Total Liabilities Net Minority Interest", "totalLiabilities", "Total Liabilities"])
    equity = _first_number(balance, ["Total Equity Gross Minority Interest", "Stockholders Equity", "totalStockholderEquity"])
    operating_cash_flow = _first_number(cashflow, ["Operating Cash Flow", "totalCashFromOperatingActivities", "Cash Flow From Continuing Operating Activities"])
    capex = _first_number(cashflow, ["Capital Expenditure", "capitalExpenditures"])
    free_cash_flow = _first_number(cashflow, ["Free Cash Flow", "freeCashFlow"])
    # 银行/保险等不直接披露 FCF 的行业：用 OCF + capex（capex 为负数）计算
    if free_cash_flow is None and operating_cash_flow is not None and capex is not None:
        free_cash_flow = operating_cash_flow + capex

    report_date = str(income.get("end_date") or balance.get("end_date") or cashflow.get("end_date") or "")
    raw = {
        "period": period,
        "end": report_date,
        "source_type": str(record.get("source_type") or "market_api"),
        "net_income_quality_flag": quality.get("net_income_quality_flag"),
        "valuation_input_usable": quality.get("valuation_input_usable"),
        "valuation_input_rejection_reason": quality.get("valuation_input_rejection_reason"),
        "non_recurring_gain_ratio": quality.get("non_recurring_gain_ratio"),
    }
    for metric_name, value, formula in [
        ("revenue", revenue, "Yahoo Finance reported revenue"),
        (
            "net_income",
            adjusted_net_income if adjusted_net_income is not None else net_income,
            "Yahoo Finance adjusted/normalized net income"
            if adjusted_net_income is not None and adjusted_net_income != net_income
            else "Yahoo Finance reported net income",
        ),
        ("adjusted_net_income", adjusted_net_income, "Yahoo Finance normalized income or net income less non-recurring gain"),
        ("non_recurring_gain", quality.get("non_recurring_gain"), "Yahoo Finance unusual item or gain on sale of securities"),
        ("total_assets", total_assets, "Yahoo Finance reported total assets"),
        ("total_liabilities", total_liabilities, "Yahoo Finance reported total liabilities"),
        ("equity", equity, "Yahoo Finance reported equity"),
        ("operating_cash_flow", operating_cash_flow, "Yahoo Finance reported operating cash flow"),
        ("capex", abs(capex) if capex is not None else None, "Yahoo Finance reported capital expenditure"),
        ("free_cash_flow", free_cash_flow, "Yahoo Finance reported free cash flow"),
    ]:
        if value is None:
            continue
        rows.append(_metric_row(metric_name, value, currency, period, table_id, evidence_id, formula, confidence, symbol, report_date, str(record.get("publish_time") or ""), {**raw, "currency_basis": currency_meta.currency_basis, "inferred_from": currency_meta.inferred_from}))
    if gross_profit is not None and revenue not in (None, 0):
        rows.append(_metric_row("gross_margin", float(gross_profit) / float(revenue) * 100.0, "pct", period, table_id, evidence_id, "gross_profit / revenue", 0.62, symbol, report_date, str(record.get("publish_time") or ""), raw))
    return rows


def _market_api_statement_rows(record: Dict[str, Any]) -> List[Dict[str, Any]]:
    metadata = _dict(record.get("metadata"))
    financials = _dict(metadata.get("financials"))
    evidence_id = _evidence_id(record)
    symbol = str(record.get("symbol") or "")
    period = str(record.get("period") or "")
    currency_meta = _currency_meta_for_record(record)
    currency = currency_meta.statement_currency
    table_id = _table_id(symbol, period, evidence_id, "yahoo_financials")
    income = _latest_statement_row(financials, "income", period)
    balance = _latest_statement_row(financials, "balance", period)
    cashflow = _latest_statement_row(financials, "cashflow", period)
    specs = [
        ("income_statement", "revenue", _first_number(income, ["Total Revenue", "totalRevenue", "Operating Revenue"]), income),
        (
            "income_statement",
            "net_income",
            build_net_income_quality_fields(
                financials,
                income,
                net_income=_first_number(income, ["Net Income", "netIncome", "Net Income Common Stockholders"]),
                revenue=_first_number(income, ["Total Revenue", "totalRevenue", "Operating Revenue"]),
            ).get("adjusted_net_income")
            or _first_number(income, ["Net Income", "netIncome", "Net Income Common Stockholders"]),
            income,
        ),
        (
            "income_statement",
            "adjusted_net_income",
            build_net_income_quality_fields(
                financials,
                income,
                net_income=_first_number(income, ["Net Income", "netIncome", "Net Income Common Stockholders"]),
                revenue=_first_number(income, ["Total Revenue", "totalRevenue", "Operating Revenue"]),
            ).get("adjusted_net_income"),
            income,
        ),
        (
            "income_statement",
            "non_recurring_gain",
            build_net_income_quality_fields(
                financials,
                income,
                net_income=_first_number(income, ["Net Income", "netIncome", "Net Income Common Stockholders"]),
                revenue=_first_number(income, ["Total Revenue", "totalRevenue", "Operating Revenue"]),
            ).get("non_recurring_gain"),
            income,
        ),
        ("balance_sheet", "total_assets", _first_number(balance, ["Total Assets", "totalAssets"]), balance),
        ("balance_sheet", "total_liabilities", _first_number(balance, ["Total Liabilities Net Minority Interest", "totalLiabilities", "Total Liabilities"]), balance),
        ("balance_sheet", "equity", _first_number(balance, ["Total Equity Gross Minority Interest", "Stockholders Equity", "totalStockholderEquity"]), balance),
        ("cash_flow_statement", "operating_cash_flow", _first_number(cashflow, ["Operating Cash Flow", "totalCashFromOperatingActivities", "Cash Flow From Continuing Operating Activities"]), cashflow),
        ("cash_flow_statement", "capex", _abs_or_none(_first_number(cashflow, ["Capital Expenditure", "capitalExpenditures"])), cashflow),
        ("cash_flow_statement", "free_cash_flow", _first_number(cashflow, ["Free Cash Flow", "freeCashFlow"]), cashflow),
    ]
    rows: List[Dict[str, Any]] = []
    for statement, line_item, value, source_row in specs:
        if value is None:
            continue
        report_date = str(source_row.get("end_date") or "")
        rows.append(
            {
                "symbol": symbol,
                "period": period,
                "statement": statement,
                "line_item": line_item,
                "value": value,
                "unit": currency,
                "currency": currency,
                "scale": "unit",
                "currency_basis": currency_meta.currency_basis,
                "currency_confidence": currency_meta.confidence,
                "inferred_from": currency_meta.inferred_from,
                "estimated": False,
                "evidence_id": evidence_id,
                "source_evidence_id": evidence_id,
                "source_table_id": table_id,
                "report_date": report_date,
                "notice_date": str(record.get("publish_time") or ""),
                "source_period": period,
                "period_match": _period_match(period=period, report_date=report_date, raw={"period": period, "end": report_date}),
                "source_type": str(record.get("source_type") or "market_api"),
                "provider": "Yahoo Finance",
            }
        )
    return rows


def _pdf_statement_metric_rows(record: Dict[str, Any]) -> List[Dict[str, Any]]:
    metadata = _dict(record.get("metadata"))
    evidence_id = _evidence_id(record)
    symbol = str(record.get("symbol") or "")
    period = str(record.get("period") or "")
    table_type = str(metadata.get("table_type") or "")
    table_id = str(metadata.get("table_id") or _table_id(symbol, period, evidence_id, table_type or "pdf_statement_table"))
    currency = str(metadata.get("currency") or "")
    if not currency:
        currency = _currency_meta_for_record(record).statement_currency
    unit = _pdf_unit_from_metadata(currency, metadata)
    report_date = str(metadata.get("report_date") or record.get("publish_time") or "")
    notice_date = str(metadata.get("notice_date") or record.get("publish_time") or "")
    rows = metadata.get("rows") if isinstance(metadata.get("rows"), list) else []
    by_item = {
        str(row.get("line_item") or ""): _safe_float(row.get("value"))
        for row in rows
        if isinstance(row, dict) and _safe_float(row.get("value")) is not None
    }
    output: List[Dict[str, Any]] = []
    mapping = {
        "revenue": ("revenue", "reported PDF revenue"),
        "net_income": ("net_income", "reported PDF net income"),
        "gross_profit": ("gross_profit", "reported PDF gross profit"),
        "operating_cash_flow": ("operating_cash_flow", "reported PDF operating cash flow"),
        "free_cash_flow": ("free_cash_flow", "reported PDF free cash flow"),
        "total_assets": ("total_assets", "reported PDF total assets"),
        "total_liabilities": ("total_liabilities", "reported PDF total liabilities"),
        "equity": ("equity", "reported PDF equity"),
    }
    for source_item, (metric_name, formula) in mapping.items():
        value = by_item.get(source_item)
        if value is None:
            continue
        output.append(_metric_row(metric_name, value, unit, period, table_id, evidence_id, formula, 0.86, symbol, report_date, notice_date, {"period": period}))
    if by_item.get("gross_profit") is not None and by_item.get("revenue") not in (None, 0):
        output.append(
            _metric_row(
                "gross_margin",
                float(by_item["gross_profit"]) / float(by_item["revenue"]) * 100.0,
                "pct",
                period,
                table_id,
                evidence_id,
                "gross_profit / revenue",
                0.78,
                symbol,
                report_date,
                notice_date,
                {"period": period},
            )
        )
    return output


def _pdf_statement_rows(record: Dict[str, Any]) -> List[Dict[str, Any]]:
    metadata = _dict(record.get("metadata"))
    evidence_id = _evidence_id(record)
    symbol = str(record.get("symbol") or "")
    period = str(record.get("period") or "")
    table_type = str(metadata.get("table_type") or "financial_statement")
    table_id = str(metadata.get("table_id") or _table_id(symbol, period, evidence_id, table_type))
    currency = str(metadata.get("currency") or "")
    if not currency:
        currency = _currency_meta_for_record(record).statement_currency
    unit = _pdf_unit_from_metadata(currency, metadata)
    report_date = str(metadata.get("report_date") or record.get("publish_time") or "")
    rows = metadata.get("rows") if isinstance(metadata.get("rows"), list) else []
    output: List[Dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        value = _safe_float(row.get("value"))
        line_item = str(row.get("line_item") or "")
        if value is None or not line_item:
            continue
        output.append(
            {
                "symbol": symbol,
                "period": period,
                "statement": table_type,
                "line_item": line_item,
                "value": value,
                "unit": unit,
                "estimated": False,
                "evidence_id": evidence_id,
                "source_evidence_id": evidence_id,
                "source_table_id": table_id,
                "report_date": report_date,
                "notice_date": str(record.get("publish_time") or ""),
                "source_period": period,
                "period_match": _period_match(period=period, report_date=report_date, raw={"period": period, "end": report_date}),
                "source_type": "pdf_statement_table",
                "provider": "PDF",
            }
        )
    return output


def _pdf_unit(currency: str, unit: str) -> str:
    base = normalize_currency_code(currency)
    normalized_unit = str(unit or "").strip().lower()
    if normalized_unit in {"million", "millions"}:
        return f"{base}_million"
    if normalized_unit in {"thousand", "thousands"}:
        return f"{base}_thousand"
    if normalized_unit in {"billion", "billions"}:
        return f"{base}_billion"
    return base


def _pdf_unit_from_metadata(currency: str, metadata: Dict[str, Any]) -> str:
    """Resolve scale from explicit metadata, falling back to extracted table headers."""

    explicit = str(metadata.get("unit") or "raw").strip().lower()
    if explicit not in {"", "raw", "unit", "units"}:
        return _pdf_unit(currency, explicit)
    header_text = " ".join(_flatten_text(metadata.get("raw_rows"))).lower()
    if re.search(r"\b(?:in\s+)?billions?\b", header_text):
        return _pdf_unit(currency, "billions")
    if re.search(r"\b(?:in\s+)?millions?\b", header_text):
        return _pdf_unit(currency, "millions")
    if re.search(r"\b(?:in\s+)?thousands?\b", header_text):
        return _pdf_unit(currency, "thousands")
    return _pdf_unit(currency, explicit)


def _flatten_text(value: Any) -> List[str]:
    if isinstance(value, dict):
        output: List[str] = []
        for item in value.values():
            output.extend(_flatten_text(item))
        return output
    if isinstance(value, (list, tuple)):
        output = []
        for item in value:
            output.extend(_flatten_text(item))
        return output
    return [str(value)] if value is not None else []


def _metric_row(
    metric_name: str,
    value: float,
    unit: str,
    period: str,
    source_table_id: str,
    source_evidence_id: str,
    calculation_formula: str,
    confidence: float,
    symbol: str,
    report_date: str,
    notice_date: str,
    raw: Dict[str, Any],
) -> Dict[str, Any]:
    currency = _currency_from_unit(unit)
    scale = _scale_from_unit(unit)
    return {
        "metric_key": metric_name,
        "metric_lineage_id": _metric_lineage_id(symbol, period, metric_name, source_table_id, source_evidence_id, report_date),
        "metric_name": metric_name,
        "value": round(float(value), 6),
        "unit": unit,
        "currency": currency,
        "scale": scale,
        "source_id": source_evidence_id,
        "source_type": str(raw.get("source_type") or ""),
        "currency_basis": str(raw.get("currency_basis") or ("unknown" if currency == UNKNOWN_CURRENCY else "source_or_rule")),
        "currency_confidence": str(raw.get("currency_confidence") or ("unknown" if currency == UNKNOWN_CURRENCY else "medium")),
        "inferred_from": str(raw.get("inferred_from") or ""),
        "period": period,
        "source_period": str(raw.get("fy") or raw.get("fp") or raw.get("period") or period),
        "period_match": _period_match(period=period, report_date=report_date, raw=raw),
        "source_table_id": source_table_id,
        "source_evidence_id": source_evidence_id,
        "calculation_formula": calculation_formula,
        "confidence": confidence,
        "symbol": symbol,
        "report_date": report_date,
        "notice_date": notice_date,
        "raw_field_keys": sorted(str(key) for key in raw.keys()),
    }


def _currency_meta_for_record(record: Dict[str, Any]):
    symbol = str(record.get("symbol") or "")
    market = infer_market_from_symbol(symbol).get("market", "")
    if market == "hk":
        issuer_meta = infer_statement_currency(symbol=symbol, market=market)
        if issuer_meta.statement_currency != UNKNOWN_CURRENCY:
            return issuer_meta
    return infer_statement_currency(symbol=symbol, market=market, source=record)


def _statement_currency_meta_for_record(record: Dict[str, Any]):
    """Prefer issuer statement-currency rules over HK trading-currency metadata."""

    return _currency_meta_for_record(record)


def _currency_from_unit(unit: Any) -> str:
    text = str(unit or "")
    if "_" in text:
        text = text.split("_", 1)[0]
    return normalize_currency_code(text)


def _scale_from_unit(unit: Any) -> str:
    text = str(unit or "").lower()
    if "billion" in text:
        return "billion"
    if "million" in text:
        return "million"
    if "thousand" in text:
        return "thousand"
    return "unit"


def _partition_period_rows(rows: List[Dict[str, Any]], record: Dict[str, Any]) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    accepted: List[Dict[str, Any]] = []
    rejected: List[Dict[str, Any]] = []
    for row in rows:
        if row.get("period_match") is False:
            rejected.append(
                {
                    "metric_name": row.get("metric_name") or row.get("line_item"),
                    "value": row.get("value"),
                    "unit": row.get("unit"),
                    "target_period": row.get("period") or record.get("period"),
                    "source_period": row.get("source_period", ""),
                    "report_date": row.get("report_date", ""),
                    "notice_date": row.get("notice_date", record.get("publish_time", "")),
                    "source_table_id": row.get("source_table_id", ""),
                    "source_evidence_id": row.get("source_evidence_id") or row.get("evidence_id", ""),
                    "reason": "period_mismatch",
                }
            )
            continue
        accepted.append(row)
    return accepted, rejected


def _period_match(period: str, report_date: str, raw: Dict[str, Any]) -> bool | None:
    return period_match(period=period, report_date=report_date, raw=raw)


def _parse_quarter(value: str) -> tuple[str, str] | None:
    return parse_quarter(value)


def _quarter_from_date(value: str) -> tuple[str, str] | None:
    import re

    match = re.match(r"(\d{4})-(\d{1,2})-\d{1,2}", str(value or ""))
    if not match:
        return None
    month = int(match.group(2))
    quarter = ((month - 1) // 3) + 1
    return match.group(1), f"Q{quarter}"


def _period_target_date(period: str) -> date | None:
    return period_target_date(period)


def _parse_iso_date(raw: Any) -> date | None:
    return parse_iso_date(raw)


def _metric_lineage_id(symbol: str, period: str, metric_name: str, table_id: str, evidence_id: str, report_date: str) -> str:
    parts = [symbol or "unknown", period or "unknown", metric_name, table_id or evidence_id or "noev", report_date or "nodate"]
    return "_".join(str(part).lower().replace(" ", "_").replace("/", "_") for part in parts if str(part).strip())


def _first_number(raw: Dict[str, Any], keys: List[str]) -> float | None:
    for key in keys:
        value = raw.get(key)
        number = _safe_float(value)
        if number is not None:
            return number
    return None


def _latest_statement_row(financials: Dict[str, Any], statement: str, period: str) -> Dict[str, Any]:
    quarterly = {
        "income": "quarterly_income_history",
        "balance": "quarterly_balance_history",
        "cashflow": "quarterly_cashflow_history",
    }
    annual = {
        "income": "income_history",
        "balance": "balance_history",
        "cashflow": "cashflow_history",
    }
    prefer_quarter = _parse_quarter(period) is not None
    keys = [quarterly[statement]] if prefer_quarter else [annual[statement], quarterly[statement]]
    for key in keys:
        rows = financials.get(key)
        if not (isinstance(rows, list) and rows and isinstance(rows[0], dict)):
            continue
        target_row = _statement_row_for_period(rows, period)
        if target_row:
            return target_row
        if not prefer_quarter:
            return rows[0]
    return {}


def _statement_row_for_period(rows: List[Any], period: str) -> Dict[str, Any]:
    for row in rows:
        if not isinstance(row, dict):
            continue
        report_date = str(row.get("end_date") or row.get("report_date") or row.get("date") or row.get("asOfDate") or "")
        if _period_match(period=period, report_date=report_date, raw={"period": period, "end": report_date}) is True:
            return row
    return {}


def _abs_or_none(value: float | None) -> float | None:
    return abs(float(value)) if value is not None else None


def _first_fact(raw: Dict[str, Any], keys: List[str]) -> Dict[str, Any]:
    candidates: List[Dict[str, Any]] = []
    for key in keys:
        value = raw.get(key)
        if isinstance(value, dict) and _safe_float(value.get("value")) is not None:
            candidates.append(value)
    if not candidates:
        return {}
    candidates.sort(key=lambda item: str(item.get("end") or item.get("filed") or ""), reverse=True)
    return candidates[0]


def _safe_float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        output = float(value)
        if output != output:
            return None
        return output
    except (TypeError, ValueError):
        return None


def _dict(value: Any) -> Dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _evidence_id(record: Dict[str, Any]) -> str:
    return str(record.get("evidence_id") or record.get("sample_id") or "")


def _table_id(symbol: str, period: str, evidence_id: str, table_type: str) -> str:
    parts = [symbol or "unknown", period or "unknown", table_type or "table", evidence_id or "noev"]
    return "_".join(str(part).lower().replace(" ", "_") for part in parts if str(part).strip())
