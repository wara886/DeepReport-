"""Deterministic pre-write enrichment backed by canonical metrics."""

from __future__ import annotations

import hashlib
from statistics import median
from typing import Any


def enrich_prewrite_inputs(
    *,
    analysis_artifacts: Any,
    claims: Any,
    evidence_records: Any,
    canonical_metrics: Any,
    tables: Any,
    symbol: str,
    period: str,
) -> dict[str, Any]:
    """Align metrics, analysis artifacts, claims, and peer evidence before writing."""

    artifacts = dict(analysis_artifacts) if isinstance(analysis_artifacts, dict) else {}
    claim_rows = [dict(item) for item in claims if isinstance(item, dict)] if isinstance(claims, list) else []
    evidence = [dict(item) for item in evidence_records if isinstance(item, dict)] if isinstance(evidence_records, list) else []
    metric_artifact = canonical_metrics if isinstance(canonical_metrics, dict) else {}
    canonical = metric_artifact.get("canonical_metrics") if isinstance(metric_artifact.get("canonical_metrics"), dict) else {}
    table_rows = [dict(item) for item in tables if isinstance(item, dict)] if isinstance(tables, list) else []

    artifacts["canonical_metrics"] = metric_artifact
    artifacts["tables"] = table_rows
    artifacts["symbol"] = str(symbol or "").upper()
    artifacts["period"] = str(period or "").upper()

    financial_claim = _financial_snapshot_claim(
        canonical,
        evidence_records=evidence,
        symbol=symbol,
        period=period,
    )
    if financial_claim:
        claim_rows = [item for item in claim_rows if item.get("claim_id") != financial_claim["claim_id"]]
        claim_rows.append(financial_claim)

    qualitative_claims = _official_qualitative_claims(evidence, symbol=symbol, period=period)
    if qualitative_claims:
        replaced_sections = {str(item.get("section_name") or "") for item in qualitative_claims}
        claim_rows = [item for item in claim_rows if str(item.get("section_name") or "") not in replaced_sections]
        claim_rows.extend(qualitative_claims)

    peer_payload = _restore_current_peer_comparison(artifacts, symbol=symbol, period=period)
    peer_claim = peer_payload.get("claim")
    peer_evidence = peer_payload.get("evidence_records")
    if isinstance(peer_claim, dict):
        claim_rows = [item for item in claim_rows if str(item.get("section_name") or "") != "peer_compare"]
        claim_rows.append(peer_claim)
    if isinstance(peer_evidence, list):
        evidence = _merge_evidence(evidence, peer_evidence)

    valuation = _build_relative_valuation(
        canonical=canonical,
        evidence_records=evidence,
        symbol=symbol,
        period=period,
    )
    if valuation:
        artifacts["valuation_model"] = valuation["valuation_model"]
        artifacts["valuation_assumptions"] = valuation["valuation_assumptions"]
        artifacts["valuation_sensitivity"] = valuation["valuation_sensitivity"]
        claim_rows = [
            item for item in claim_rows
            if str(item.get("section_name") or "") not in {"valuation", "valuation_sensitivity"}
        ]
        claim_rows.extend([valuation["valuation_claim"], valuation["sensitivity_claim"]])
        evidence = _merge_evidence(evidence, [valuation["evidence_record"]])

    artifacts["claims"] = claim_rows
    return {
        "analysis_artifacts": artifacts,
        "claims": claim_rows,
        "evidence_records": evidence,
    }


def _financial_snapshot_claim(
    canonical: dict[str, Any],
    *,
    evidence_records: list[dict[str, Any]],
    symbol: str,
    period: str,
) -> dict[str, Any] | None:
    specs = (
        ("revenue", "revenue_billion", "收入"),
        ("net_income", "net_income_billion", "净利润"),
        ("total_assets", "total_assets_billion", "总资产"),
        ("total_liabilities", "total_liabilities_billion", "总负债"),
        ("operating_cash_flow", "operating_cash_flow_billion", "经营现金流"),
        ("free_cash_flow", "free_cash_flow_billion", "自由现金流"),
    )
    numeric: dict[str, float] = {}
    descriptions: list[str] = []
    evidence_ids: list[str] = []
    for metric_name, numeric_key, label in specs:
        row = canonical.get(metric_name)
        value = _number(row.get("value")) if isinstance(row, dict) else None
        if value is None:
            continue
        numeric[numeric_key] = value
        descriptions.append(f"{label}{value:.2f}")
        evidence_id = str(row.get("source_evidence_id") or "")
        if evidence_id:
            evidence_ids.append(evidence_id)
    if len(numeric) < 4:
        return None
    official_ids = _primary_financial_evidence_ids(evidence_records, period=period)
    evidence_ids = _dedupe([*official_ids[:2], *evidence_ids])
    return {
        "claim_id": "cl_prewrite_financial_snapshot",
        "section_name": "financial_analysis",
        "claim_text": (
            f"{str(symbol or '').upper()} {str(period or '').upper()} 的正式指标快照为："
            + "、".join(descriptions)
            + "；收入、利润、资产负债与现金流均来自同一版 Canonical Metrics。"
        ),
        "evidence_ids": _dedupe(evidence_ids),
        "citation_evidence_ids": _dedupe(evidence_ids)[:4],
        "numeric_values": numeric,
        "risk_level": "low",
        "confidence": 0.88,
        "notes": "canonical pre-write financial snapshot",
        "metric_lineage_ids": [str(canonical[name].get("metric_id") or name) for name, _, _ in specs if name in canonical],
    }


def _official_qualitative_claims(
    evidence_records: list[dict[str, Any]],
    *,
    symbol: str,
    period: str,
) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = {"business_overview": [], "strategy_business": []}
    for record in evidence_records:
        if str(record.get("source_type") or "").lower() != "sec_10k_section":
            continue
        identity = " ".join(
            str(record.get(key) or "").lower()
            for key in ("evidence_id", "title")
        )
        if "business" in identity:
            groups["business_overview"].append(record)
        if any(token in identity for token in ("mda", "management discussion", "competition", "segments")):
            groups["strategy_business"].append(record)

    output: list[dict[str, Any]] = []
    for section, records in groups.items():
        if not records:
            continue
        selected = records[:3]
        evidence_ids = _dedupe(str(item.get("evidence_id") or "") for item in selected)
        excerpts = [_evidence_excerpt(item.get("content"), limit=520) for item in selected]
        excerpts = [item for item in excerpts if item]
        if not excerpts:
            continue
        description = "；".join(excerpts[:2])
        title = "Item 1 业务披露" if section == "business_overview" else "Item 7 管理层讨论"
        output.append(
            {
                "claim_id": f"cl_prewrite_{section}",
                "section_name": section,
                "claim_text": (
                    f"{str(symbol or '').upper()} {str(period or '').upper()} 10-K {title}显示：{description}"
                ),
                "evidence_ids": evidence_ids,
                "citation_evidence_ids": evidence_ids,
                "numeric_values": {},
                "risk_level": "low",
                "confidence": 0.9,
                "notes": "official SEC 10-K qualitative disclosure",
            }
        )
    return output


def _restore_current_peer_comparison(artifacts: dict[str, Any], *, symbol: str, period: str) -> dict[str, Any]:
    peer_context = artifacts.get("peer_context") if isinstance(artifacts.get("peer_context"), dict) else {}
    rows = peer_context.get("peer_rows") if isinstance(peer_context.get("peer_rows"), list) else []
    if not rows:
        rows = peer_context.get("period_mismatch_rows") if isinstance(peer_context.get("period_mismatch_rows"), list) else []
    rows = [dict(item) for item in rows if isinstance(item, dict)]
    target = str(symbol or "").upper()
    target_row = next((item for item in rows if str(item.get("symbol") or "").upper() == target), None)
    peers = [item for item in rows if str(item.get("symbol") or "").upper() != target]
    peers = [item for item in peers if _peer_row_has_metrics(item)]
    if not isinstance(target_row, dict) or len(peers) < 2:
        return {}

    clean_rows = [target_row, *peers[:5]]
    for row in clean_rows:
        row["data_period"] = str(row.get("data_period") or "current_ttm").lower()
        row["target_period"] = str(period or "").upper()
        row["period_match"] = False
        row["comparison_role"] = "target" if str(row.get("symbol") or "").upper() == target else "peer"

    peer_evidence = [_peer_evidence_record(row, target_symbol=target, target_period=period) for row in clean_rows]
    peer_evidence = [item for item in peer_evidence if item]
    evidence_by_symbol = {str(item.get("symbol") or "").upper(): str(item.get("evidence_id") or "") for item in peer_evidence}
    approved = [str(item.get("symbol") or "").upper() for item in peers[:5] if str(item.get("symbol") or "")]
    target_margin = _number(target_row.get("net_margin_pct"))
    target_growth = _number(target_row.get("revenue_growth_pct"))
    peer_margins = [value for value in (_number(item.get("net_margin_pct")) for item in peers[:5]) if value is not None]
    peer_growth = [value for value in (_number(item.get("revenue_growth_pct")) for item in peers[:5]) if value is not None]
    if target_margin is None or not peer_margins:
        return {}
    median_margin = median(peer_margins)
    median_growth = median(peer_growth) if peer_growth else None
    margin_direction = "低于" if target_margin < median_margin else "高于"
    growth_text = ""
    numeric = {
        "target_net_margin_pct": target_margin,
        "peer_median_net_margin_pct": median_margin,
    }
    for row in clean_rows:
        row_symbol = str(row.get("symbol") or "").lower()
        row_margin = _number(row.get("net_margin_pct"))
        if row_symbol and row_margin is not None:
            numeric[f"peer_{row_symbol}_net_margin_pct"] = row_margin
    if target_growth is not None and median_growth is not None:
        growth_direction = "低于" if target_growth < median_growth else "高于"
        growth_text = f"；收入增速{target_growth:.1f}%，{growth_direction}可比组中位数{median_growth:.1f}%"
        numeric.update({"target_revenue_growth_pct": target_growth, "peer_median_revenue_growth_pct": median_growth})

    evidence_ids = _dedupe(evidence_by_symbol.values())
    claim = {
        "claim_id": "cl_prewrite_peer_current_ttm",
        "section_name": "peer_compare",
        "claim_text": (
            f"当前 TTM 市场快照中，{target} 净利率为{target_margin:.1f}%，{margin_direction}"
            f"{len(peers[:5])}家可比公司中位数{median_margin:.1f}%{growth_text}。"
            f"该比较只用于当前经营横截面，不替代{str(period or '').upper()}同期间财务比较。"
        ),
        "evidence_ids": evidence_ids,
        "citation_evidence_ids": evidence_ids[:4],
        "numeric_values": numeric,
        "risk_level": "medium",
        "confidence": 0.76,
        "notes": "current TTM peer comparison; target fiscal-period substitution prohibited",
    }
    peer_context = {
        **peer_context,
        "status": "current_ttm_comparison",
        "peer_rows": clean_rows,
        "rows": clean_rows,
        "peer_count": len(peers[:5]),
        "approved_peer_symbols": approved,
        "comparison_period": "CURRENT_TTM",
        "target_period": str(period or "").upper(),
        "period_scope_note": "Current TTM peer snapshot is separate from target fiscal-period statements.",
        "findings": [claim["claim_text"]],
        "missing_inputs": [],
        "impact_on_report": "量化同行横截面可用，但不得与目标财年指标混作同期间比较。",
    }
    artifacts["peer_context"] = peer_context
    artifacts["peer_rows"] = clean_rows
    artifacts["peer_analysis"] = {
        "status": "current_ttm_comparison",
        "confidence": 0.76,
        "source": "yahoo_finance_current_ttm",
        "evidence_ids": evidence_ids,
        "findings": [claim["claim_text"]],
        "approved_peer_symbols": approved,
        "peer_rows": clean_rows,
        "rows": clean_rows,
        "comparison_period": "CURRENT_TTM",
        "target_period": str(period or "").upper(),
        "verified": True,
    }
    return {"claim": claim, "evidence_records": peer_evidence}


def _build_relative_valuation(
    *,
    canonical: dict[str, Any],
    evidence_records: list[dict[str, Any]],
    symbol: str,
    period: str,
) -> dict[str, Any]:
    price_context = _market_price_context(evidence_records, symbol=symbol)
    price = _number(price_context.get("price"))
    shares = _metric_value(canonical, "shares_outstanding")
    net_income = _metric_value(canonical, "net_income")
    revenue = _metric_value(canonical, "revenue")
    equity = _metric_value(canonical, "total_equity")
    if not price or not shares or not net_income or not revenue:
        return {}

    market_cap = price * shares
    eps = net_income / shares
    pe = market_cap / net_income
    ps = market_cap / revenue
    pb = market_cap / equity if equity else None
    financial_ids = _metric_evidence_ids(
        canonical,
        ("shares_outstanding", "net_income", "revenue", "total_equity"),
    )
    market_id = str(price_context.get("evidence_id") or "")
    evidence_ids = _dedupe([*financial_ids, market_id])
    currency = str(price_context.get("currency") or _metric_currency(canonical, "net_income") or "USD").upper()
    market_as_of = str(price_context.get("as_of_date") or "")
    summary_multiples = {"pe": round(pe, 2), "ps": round(ps, 2)}
    if pb is not None:
        summary_multiples["pb"] = round(pb, 2)
    audited_multiples = {
        "pe": {
            "denominator_metric": "net_income",
            "denominator_value": round(net_income, 4),
            "multiple": round(pe, 4),
            "equity_value_billion": round(market_cap, 4),
        },
        "ps": {
            "denominator_metric": "revenue",
            "denominator_value": round(revenue, 4),
            "multiple": round(ps, 4),
            "equity_value_billion": round(market_cap, 4),
        },
    }
    if pb is not None and equity is not None:
        audited_multiples["pb"] = {
            "denominator_metric": "total_equity",
            "denominator_value": round(equity, 4),
            "multiple": round(pb, 4),
            "equity_value_billion": round(market_cap, 4),
        }

    valuation_model = {
        "schema_version": "relative_valuation.v1",
        "symbol": str(symbol or "").upper(),
        "period": str(period or "").upper(),
        "valuation_available": True,
        "valuation_status": "available",
        "method": "current_price_relative_valuation",
        "financial_period": str(period or "").upper(),
        "market_as_of_date": market_as_of,
        "currency": currency,
        "current_price": round(price, 4),
        "shares_outstanding_billion": round(shares, 4),
        "market_cap_billion": round(market_cap, 2),
        "eps": round(eps, 4),
        "relative_valuation": {
            "multiples": audited_multiples,
            "summary_multiples": summary_multiples,
        },
        "input_summary": {
            "revenue_billion": round(revenue, 4),
            "net_income_billion": round(net_income, 4),
            "total_equity_billion": round(equity, 4) if equity is not None else None,
            "shares_outstanding_billion": round(shares, 4),
            "current_price": round(price, 4),
        },
        "source_evidence_ids": evidence_ids,
        "period_basis_note": "Financial inputs use the target fiscal period; price uses the stated current market date.",
    }
    scenarios = []
    for label, earnings_factor, multiple_factor in (
        ("bear", 0.90, 0.80),
        ("base", 1.00, 1.00),
        ("bull", 1.10, 1.20),
    ):
        target_price = eps * earnings_factor * pe * multiple_factor
        scenarios.append(
            {
                "scenario": label,
                "label": {"bear": "悲观情景", "base": "基准情景", "bull": "乐观情景"}[label],
                "earnings_change_pct": round((earnings_factor - 1.0) * 100.0, 1),
                "pe_change_pct": round((multiple_factor - 1.0) * 100.0, 1),
                "pe_multiple": round(pe * multiple_factor, 2),
                "target_price": round(target_price, 2),
            }
        )
    scenario_values = {
        item["scenario"]: {
            **item,
            "equity_value_billion": round(item["target_price"] * shares, 4),
        }
        for item in scenarios
    }
    valuation_sensitivity = {
        "schema_version": "valuation_sensitivity.v1",
        "method": "pe_earnings_scenario",
        "metric": "target_price",
        "currency": currency,
        "financial_period": str(period or "").upper(),
        "market_as_of_date": market_as_of,
        "rows": scenarios,
        "sensitivity": scenarios,
        "scenario_values": scenario_values,
        "source_evidence_ids": evidence_ids,
        "limitations": "Scenario prices are mechanical P/E and earnings sensitivities, not a DCF or investment target price.",
    }
    assumptions = {
        "schema_version": "valuation_assumptions.v1",
        "method": "pe_earnings_scenario",
        "base_eps": round(eps, 4),
        "base_pe": round(pe, 2),
        "base_price": round(price, 4),
        "financial_period": str(period or "").upper(),
        "market_as_of_date": market_as_of,
        "scenario_changes": {
            "bear": {"earnings_pct": -10.0, "pe_pct": -20.0},
            "base": {"earnings_pct": 0.0, "pe_pct": 0.0},
            "bull": {"earnings_pct": 10.0, "pe_pct": 20.0},
        },
    }
    pb_text = f"、P/B {pb:.1f}x" if pb is not None else ""
    derived_evidence_id = f"internal_relative_valuation_{str(symbol or '').lower()}_{str(period or '').lower()}_v1"
    metric_lineage_ids = [
        str(canonical[name].get("metric_id") or name)
        for name in ("shares_outstanding", "net_income", "revenue", "total_equity")
        if isinstance(canonical.get(name), dict)
    ]
    valuation_evidence_ids = _dedupe([*evidence_ids, derived_evidence_id])
    valuation_claim = {
        "claim_id": "cl_prewrite_relative_valuation",
        "section_name": "valuation",
        "claim_text": (
            f"以{str(period or '').upper()}净利润、收入和期末股本，结合{market_as_of or '当前'}股价"
            f"{price:.2f}{currency}计算，{str(symbol or '').upper()}当前市值约{market_cap:.1f}十亿{currency}，"
            f"对应 P/E {pe:.1f}x、P/S {ps:.1f}x{pb_text}。这是历史财务与当前行情的混合时点相对估值。"
        ),
        "evidence_ids": valuation_evidence_ids,
        "citation_evidence_ids": valuation_evidence_ids[:5],
        "numeric_values": {
            "market_cap_billion": market_cap,
            "pe_ratio": pe,
            "ps_ratio": ps,
            **({"pb_ratio": pb} if pb is not None else {}),
        },
        "risk_level": "medium",
        "confidence": 0.82,
        "notes": "relative valuation; target fiscal metrics plus current market price",
        "metric_lineage_ids": metric_lineage_ids,
        "input_metric_lineage_ids": metric_lineage_ids,
    }
    sensitivity_claim = {
        "claim_id": "cl_prewrite_valuation_sensitivity",
        "section_name": "valuation_sensitivity",
        "claim_text": (
            f"机械敏感性以 EPS {eps:.2f}{currency}、当前隐含 P/E {pe:.1f}x 为基准："
            f"悲观情景（盈利-10%、P/E-20%）对应{scenarios[0]['target_price']:.2f}{currency}，"
            f"基准情景对应{scenarios[1]['target_price']:.2f}{currency}，"
            f"乐观情景（盈利+10%、P/E+20%）对应{scenarios[2]['target_price']:.2f}{currency}。"
            "情景结果用于观察盈利与估值倍数的联合弹性，不构成目标价。"
        ),
        "evidence_ids": valuation_evidence_ids,
        "citation_evidence_ids": valuation_evidence_ids[:5],
        "numeric_values": {
            "bear_target_price": scenarios[0]["target_price"],
            "base_target_price": scenarios[1]["target_price"],
            "bull_target_price": scenarios[2]["target_price"],
        },
        "risk_level": "medium",
        "confidence": 0.78,
        "notes": "mechanical P/E and earnings sensitivity; not a target price",
        "metric_lineage_ids": metric_lineage_ids,
        "input_metric_lineage_ids": metric_lineage_ids,
    }
    derived_evidence = {
        "evidence_id": derived_evidence_id,
        "sample_id": derived_evidence_id,
        "symbol": str(symbol or "").upper(),
        "period": str(period or "").upper(),
        "source_period": str(period or "").upper(),
        "period_match": True,
        "source_type": "valuation_model",
        "title": f"{str(symbol or '').upper()} relative valuation and sensitivity model",
        "content": (
            f"Derived valuation model: market_cap_billion={market_cap:.4f}, pe_ratio={pe:.4f}, "
            f"ps_ratio={ps:.4f}, pb_ratio={(pb if pb is not None else 0.0):.4f}; "
            f"bear_target_price={scenarios[0]['target_price']:.2f}, "
            f"base_target_price={scenarios[1]['target_price']:.2f}, "
            f"bull_target_price={scenarios[2]['target_price']:.2f}."
        ),
        "source_url": "",
        "source_evidence_ids": evidence_ids,
        "metadata": {
            "generated_by": "prewrite_enrichment",
            "calculation_method": "current_price_relative_valuation_and_pe_earnings_scenario",
            "financial_period": str(period or "").upper(),
            "market_as_of_date": market_as_of,
            "input_metric_lineage_ids": metric_lineage_ids,
            "source_evidence_ids": evidence_ids,
            "derived": True,
        },
    }
    return {
        "valuation_model": valuation_model,
        "valuation_assumptions": assumptions,
        "valuation_sensitivity": valuation_sensitivity,
        "valuation_claim": valuation_claim,
        "sensitivity_claim": sensitivity_claim,
        "evidence_record": derived_evidence,
    }


def _market_price_context(evidence_records: list[dict[str, Any]], *, symbol: str) -> dict[str, Any]:
    expected = str(symbol or "").upper()
    for record in evidence_records:
        if str(record.get("symbol") or "").upper() not in {"", expected}:
            continue
        source_type = str(record.get("source_type") or "").lower()
        if source_type not in {"market", "market_api", "market_data", "eastmoney_quote"}:
            continue
        for metadata in _metadata_objects(record.get("metadata")):
            snapshot = metadata.get("snapshot") if isinstance(metadata.get("snapshot"), dict) else metadata
            price = _first_number(snapshot, ("last_close", "currentPrice", "regularMarketPrice", "price", "close"))
            if price is None:
                continue
            return {
                "price": price,
                "currency": str(snapshot.get("currency") or record.get("currency") or ""),
                "as_of_date": str(snapshot.get("latest_date") or snapshot.get("as_of_date") or metadata.get("as_of_date") or ""),
                "evidence_id": str(record.get("evidence_id") or record.get("sample_id") or ""),
            }
    return {}


def _metadata_objects(value: Any) -> list[dict[str, Any]]:
    pending = [value] if isinstance(value, dict) else []
    output: list[dict[str, Any]] = []
    visited: set[int] = set()
    while pending and len(output) < 64:
        current = pending.pop(0)
        marker = id(current)
        if marker in visited:
            continue
        visited.add(marker)
        output.append(current)
        parent = current.get("parent_metadata")
        if isinstance(parent, dict):
            pending.append(parent)
        raw_record = current.get("raw_artifact_record")
        if isinstance(raw_record, dict) and isinstance(raw_record.get("metadata"), dict):
            pending.append(raw_record["metadata"])
    return output


def _peer_evidence_record(row: dict[str, Any], *, target_symbol: str, target_period: str) -> dict[str, Any]:
    peer_symbol = str(row.get("symbol") or row.get("ticker") or "").upper()
    source_url = str(row.get("source_url") or "")
    if not peer_symbol or not source_url:
        return {}
    digest = hashlib.sha1(f"{target_symbol}|{peer_symbol}|CURRENT_TTM|{source_url}".encode("utf-8")).hexdigest()[:12]
    evidence_id = f"peer_current_ttm_{peer_symbol.lower()}_{digest}"
    metrics = []
    for key, label in (
        ("revenue_growth_pct", "收入增速"),
        ("gross_margin_pct", "毛利率"),
        ("net_margin_pct", "净利率"),
        ("roe_pct", "ROE"),
    ):
        value = _number(row.get(key))
        if value is not None:
            metrics.append(f"{label}{value:.2f}%")
    return {
        "evidence_id": evidence_id,
        "sample_id": evidence_id,
        "symbol": peer_symbol,
        "period": "CURRENT_TTM",
        "source_period": "CURRENT_TTM",
        "target_period": str(target_period or "").upper(),
        "period_match": False,
        "source_type": "market_api",
        "title": f"{peer_symbol} current TTM peer snapshot",
        "content": f"{peer_symbol} 当前 TTM 市场快照：" + "、".join(metrics) + "。",
        "source_url": source_url,
        "metadata": {
            "context_type": "peer_current_ttm",
            "comparison_target_symbol": target_symbol,
            "source_period": "CURRENT_TTM",
            "target_period": str(target_period or "").upper(),
            "period_match": False,
            "provider": "yahoo_finance",
            "source_quality": {
                "source_authority": "market_data",
                "authority_level": "market_data",
                "authority_score": 0.78,
                "trust_level": "medium",
                "source_document_type": "market_snapshot",
            },
        },
    }


def _peer_row_has_metrics(row: dict[str, Any]) -> bool:
    return sum(
        _number(row.get(key)) is not None
        for key in ("revenue_growth_pct", "gross_margin_pct", "net_margin_pct", "roe_pct")
    ) >= 2


def _primary_financial_evidence_ids(evidence_records: list[dict[str, Any]], *, period: str) -> list[str]:
    target = str(period or "").upper()
    primary_types = {
        "sec_10k_filing",
        "sec_10k_section",
        "sec_companyfacts",
        "cninfo_announcement",
        "hkex_announcement",
        "official_filing",
    }
    ranked: list[tuple[int, str]] = []
    for record in evidence_records:
        source_type = str(record.get("source_type") or "").lower()
        if source_type not in primary_types:
            continue
        record_period = str(record.get("period") or record.get("source_period") or "").upper()
        if target and record_period and record_period != target:
            continue
        identity = " ".join(str(record.get(key) or "").lower() for key in ("evidence_id", "title"))
        score = 0 if any(token in identity for token in ("financial", "companyfacts")) else 1
        evidence_id = str(record.get("evidence_id") or record.get("sample_id") or "")
        if evidence_id:
            ranked.append((score, evidence_id))
    return _dedupe(item[1] for item in sorted(ranked))


def _evidence_excerpt(value: Any, *, limit: int) -> str:
    text = " ".join(str(value or "").split()).strip()
    if len(text) <= limit:
        return text
    head = text[:limit].rstrip()
    end = max(head.rfind(mark) for mark in (".", ";", "。", "；"))
    if end >= limit // 2:
        return head[: end + 1]
    return head + "."


def _metric_value(canonical: dict[str, Any], name: str) -> float | None:
    row = canonical.get(name)
    return _number(row.get("value")) if isinstance(row, dict) else None


def _metric_currency(canonical: dict[str, Any], name: str) -> str:
    row = canonical.get(name)
    return str(row.get("currency") or "") if isinstance(row, dict) else ""


def _metric_evidence_ids(canonical: dict[str, Any], names: tuple[str, ...]) -> list[str]:
    return _dedupe(
        str(canonical[name].get("source_evidence_id") or "")
        for name in names
        if isinstance(canonical.get(name), dict)
    )


def _merge_evidence(existing: list[dict[str, Any]], incoming: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in [*existing, *incoming]:
        evidence_id = str(row.get("evidence_id") or row.get("sample_id") or "")
        if not evidence_id or evidence_id in seen:
            continue
        seen.add(evidence_id)
        output.append(row)
    return output


def _first_number(row: dict[str, Any], keys: tuple[str, ...]) -> float | None:
    for key in keys:
        value = _number(row.get(key))
        if value is not None:
            return value
    return None


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number else None


def _dedupe(values: Any) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        output.append(text)
    return output
