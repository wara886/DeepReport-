from src.agents.base_agent import AgentTask
from src.agents.deep_analyze_agent import build_rule_claims
from src.agents.final_answer_agent import FinalAnswerAgent, backfill_empty_sections_from_claims
from src.agents.peer_comparison_agent import PeerComparisonAgent
from src.agents.verifier import Verifier
from src.schemas.claim import ClaimItem


def test_backfill_replaces_empty_executive_and_three_statement_sections():
    markdown = (
        "# Report\n\n"
        "## 执行摘要\n\n- 本节暂无可验证结论。\n\n"
        "## 三表摘要\n\n- 本节暂无可验证结论。\n\n"
        "## 风险评估\n\n- ok\n"
    )
    claims = [
        {
            "claim_id": "cl_exec",
            "section_name": "executive_summary",
            "claim_text": "META 执行摘要：营收约 56.3B，净利润约 26.8B。",
            "evidence_ids": ["ev_fin"],
            "numeric_values": {"revenue_billion": 56.3, "net_income_billion": 26.8},
            "confidence": 0.82,
        },
        {
            "claim_id": "cl_stmt",
            "section_name": "financial_statements",
            "claim_text": "三表关键项包括：营收 56.3B；净利润 26.8B；自由现金流 12.4B。",
            "evidence_ids": ["ev_fin"],
            "numeric_values": {"free_cash_flow_billion": 12.4},
            "confidence": 0.80,
        },
    ]

    output = backfill_empty_sections_from_claims(markdown, claims)

    assert "本节暂无可验证结论" not in output
    assert "META 执行摘要" in output
    assert "三表关键项包括" in output


def test_final_answer_backfills_financial_analysis_from_unpacked_claims():
    claims = [
        {
            "claim_id": f"cl_pinned_{idx}",
            "section_name": section,
            "claim_text": f"{section} claim.",
            "evidence_ids": ["ev_fin"],
            "numeric_values": {},
            "confidence": 0.7,
        }
        for idx, section in enumerate(
            [
                "executive_summary",
                "business_overview",
                "financial_statements",
                "peer_compare",
                "valuation",
                "valuation_sensitivity",
                "risks",
                "conclusion",
            ]
        )
    ]
    claims.append(
        {
            "claim_id": "cl_fin",
            "section_name": "financial_analysis",
            "claim_text": "META 财务分析恢复：营收增长、净利率和现金流均有可验证结论。",
            "evidence_ids": ["ev_fin"],
            "numeric_values": {"revenue_billion": 56.3},
            "confidence": 0.95,
        }
    )

    result = FinalAnswerAgent(model=None).execute_task(
        AgentTask(
            task_id="final",
            task_type="final_answer",
            description="final",
            parameters={"research_topic": "META", "claims": claims, "max_claims": 3},
        )
    )

    markdown = result.output["markdown"]
    assert "META 财务分析恢复" in markdown
    assert "## 财务分析" in markdown


def test_verifier_blocks_empty_section_when_claim_exists():
    verifier = Verifier()
    claim = ClaimItem(
        claim_id="cl_stmt",
        section_name="financial_statements",
        claim_text="三表关键项包括：营收 56.3B；净利润 26.8B；自由现金流 12.4B。",
        evidence_ids=["ev_fin"],
        numeric_values={"revenue_billion": 56.3, "net_income_billion": 26.8, "free_cash_flow_billion": 12.4},
        confidence=0.8,
    )

    report = verifier.verify(
        claims=[claim],
        markdown="# Report\n\n## 执行摘要\n\n- ok [ev_fin]\n\n## 三表摘要\n\n- 本节暂无可验证结论。\n\n## 财务分析\n\n- ok [ev_fin]\n\n## 风险评估\n\n- ok\n",
        evidence_records=[
            {
                "evidence_id": "ev_fin",
                "source_type": "financials",
                "source_url": "https://www.sec.gov/",
                "content": "Revenue 56.3B, net income 26.8B, free cash flow 12.4B.",
            }
        ],
    )

    assert report["passed"] is False
    assert any("financial_statements" in item or "三表摘要" in item for item in report["errors"])


def test_meta_fcf_claim_preserves_methodology():
    records = [
        {
            "evidence_id": "ev_meta_fin",
            "sample_id": "ev_meta_fin",
            "symbol": "META",
            "period": "FY2026Q1",
            "source_type": "financials",
            "metadata": {
                "symbol": "META",
                "period": "FY2026Q1",
                "free_cash_flow_methodology": "OCF - CapEx - finance lease payments (company-disclosed definition)",
                "finance_lease_payments_billion": 0.017,
            },
            "content": "Meta revenue and cash flow summary.",
        }
    ]
    ratio_rows = [
        {
            "sample_id": "ev_meta_fin",
            "symbol": "META",
            "period": "FY2026Q1",
            "revenue_billion": 56.3,
            "net_income_billion": 26.8,
            "free_cash_flow_billion": 12.386,
            "free_cash_flow_methodology": "OCF - CapEx - finance lease payments (company-disclosed definition)",
            "finance_lease_payments_billion": 0.017,
        }
    ]
    statement_view = {
        "coverage": {"has_three_statement_view": True, "line_item_count": 3},
        "rows": [
            {"symbol": "META", "statement": "income_statement", "line_item": "net_income", "value_billion": 26.8},
            {"symbol": "META", "statement": "cash_flow_statement", "line_item": "free_cash_flow", "value_billion": 12.386},
            {"symbol": "META", "statement": "balance_sheet", "line_item": "shareholder_equity", "value_billion": 244.1},
        ],
    }

    claims = build_rule_claims(records=records, ratio_rows=ratio_rows, trend_rows=[], statement_view=statement_view)
    fcf_claims = [claim for claim in claims if claim.section_name == "financial_statements" and "自由现金流" in claim.claim_text]

    assert fcf_claims
    assert any("finance lease payments" in claim.claim_text or "融资租赁" in claim.claim_text for claim in fcf_claims)


def test_peer_comparison_outputs_core_and_extended_groups(monkeypatch):
    def fake_fetch(symbol, period):
        return {
            "evidence_id": f"ev_{symbol}",
            "symbol": symbol,
            "period": "FY2026Q1",
            "source_type": "financials",
            "metadata": {
                "symbol": symbol,
                "period": "FY2026Q1",
                "revenue_billion": 100.0,
                "revenue_growth_pct": 10.0,
                "net_margin_pct": 30.0,
                "roe_pct": 20.0,
                "free_cash_flow_billion": 10.0,
            },
        }

    monkeypatch.setattr("src.data.sec_companyfacts.fetch_sec_companyfacts_evidence", fake_fetch)
    agent = PeerComparisonAgent(model=None)
    result = agent.run(
        AgentTask(
            task_id="peer",
            task_type="peer",
            description="peer",
            parameters={
                "symbol": "META",
                "period": "latest",
                "sector": "Communication Services",
                "industry": "Internet Content",
                "target_metrics": {
                    "symbol": "META",
                    "period": "FY2026Q1",
                    "revenue_growth_pct": 33.1,
                    "net_margin_pct": 47.5,
                    "roe_pct": 43.9,
                },
                "financial_evidence_ids": ["ev_meta"],
            },
        )
    )

    claim = result.output["claims"][0]
    assert "核心可比组 GOOGL" in claim["claim_text"]
    assert "扩展参考组 NFLX, DIS, T" in claim["claim_text"]
    assert "财期对齐" in claim["claim_text"]
    assert claim["numeric_values"]["core_peer_count"] == 1
    assert claim["numeric_values"]["extended_peer_count"] == 3


def test_peer_comparison_excludes_stale_peer_period_and_aligns_evidence(monkeypatch):
    def fake_fetch(symbol, period):
        peer_period = "FY2025 Q3" if symbol == "C" else "FY2026 Q1"
        return {
            "evidence_id": f"ev_{symbol}",
            "symbol": symbol,
            "period": peer_period,
            "source_type": "financials",
            "metadata": {
                "symbol": symbol,
                "period": peer_period,
                "revenue_billion": 100.0,
                "revenue_growth_pct": 10.0,
                "net_margin_pct": 30.0,
                "roe_pct": 20.0,
                "free_cash_flow_billion": 10.0,
            },
        }

    monkeypatch.setattr("src.data.sec_companyfacts.fetch_sec_companyfacts_evidence", fake_fetch)
    agent = PeerComparisonAgent(model=None)
    result = agent.run(
        AgentTask(
            task_id="peer",
            task_type="peer",
            description="peer",
            parameters={
                "symbol": "JPM",
                "period": "latest",
                "sector": "Financials",
                "industry": "Diversified Banks",
                "target_metrics": {
                    "symbol": "JPM",
                    "period": "FY2026 Q1",
                    "revenue_growth_pct": 10.0,
                    "net_margin_pct": 33.0,
                    "roe_pct": 18.0,
                },
                "financial_evidence_ids": ["ev_jpm"],
            },
        )
    )

    claim = result.output["claims"][0]
    text = claim["claim_text"]
    assert "C(FY2025 Q3)" in text
    assert "核心可比组 BAC, WFC" in text
    assert "核心可比组 BAC, WFC, C" not in text
    assert "MS" in text
    assert "ev_MS" in claim["evidence_ids"]
    assert "ev_C" not in claim["evidence_ids"]
    assert claim["numeric_values"]["excluded_peer_count"] == 1
