from src.schemas.chart import ChartSpec
from src.schemas.claim import ClaimItem
from src.schemas.evidence import EvidenceItem
from src.schemas.report import ReportDocument, ReportSection
from src.schemas.task import ReportTask


def test_evidence_round_trip():
    raw = {
        "evidence_id": "ev_001",
        "source_type": "news",
        "title": "Quarterly update",
        "source_url": "https://example.com/news/quarterly",
        "publish_time": "2026-04-16T10:00:00Z",
        "content": "Revenue grew 12%.",
        "symbol": "AAPL",
        "period": "2025Q4",
        "trust_level": "high",
        "metadata": {"lang": "en"},
    }
    obj = EvidenceItem.from_dict(raw)
    assert obj.to_dict() == raw


def test_claim_round_trip():
    raw = {
        "claim_id": "cl_001",
        "section_name": "financial_analysis",
        "claim_text": "Gross margin improved.",
        "evidence_ids": ["ev_001"],
        "numeric_values": {"gross_margin_pct": 42.3},
        "risk_level": "low",
        "confidence": 0.91,
        "notes": "Backed by filing.",
    }
    obj = ClaimItem.from_dict(raw)
    assert obj.to_dict() == raw


def test_chart_round_trip():
    raw = {
        "chart_id": "ch_001",
        "chart_type": "line",
        "title": "Revenue Trend",
        "source_tables": ["income_statement"],
        "source_fields": ["revenue"],
        "output_path": "data/outputs/revenue_trend.png",
        "caption": "Quarterly revenue trend.",
    }
    obj = ChartSpec.from_dict(raw)
    assert obj.to_dict() == raw


def test_report_round_trip():
    raw = {
        "report_id": "rp_001",
        "symbol": "AAPL",
        "period": "2025Q4",
        "report_type": "company",
        "sections": [
            {
                "section_name": "executive_summary",
                "section_title": "Executive Summary",
                "claims": [
                    {
                        "claim_id": "cl_001",
                        "section_name": "executive_summary",
                        "claim_text": "Revenue increased year over year.",
                        "evidence_ids": ["ev_001"],
                        "numeric_values": {"revenue_yoy_pct": 11.4},
                        "risk_level": "medium",
                        "confidence": 0.88,
                        "notes": "",
                    }
                ],
                "charts": [
                    {
                        "chart_id": "ch_001",
                        "chart_type": "bar",
                        "title": "YoY Growth",
                        "source_tables": ["income_statement"],
                        "source_fields": ["revenue_yoy_pct"],
                        "output_path": "data/outputs/yoy_growth.png",
                        "caption": "YoY growth by quarter.",
                    }
                ],
                "body_markdown": "Revenue trend remains stable.",
                "citations": ["ev_001"],
            }
        ],
        "generated_at": "2026-04-16T12:00:00Z",
        "export_paths": {"markdown": "data/reports/report.md"},
    }
    obj = ReportDocument.from_dict(raw)
    assert obj.to_dict() == raw
    assert isinstance(obj.sections[0], ReportSection)
    assert isinstance(obj.sections[0].claims[0], ClaimItem)
    assert isinstance(obj.sections[0].charts[0], ChartSpec)


def test_task_round_trip():
    raw = {
        "task_id": "task_001",
        "symbol": "AAPL",
        "period": "2025Q4",
        "report_type": "company",
        "stage_name": "stage1_schema",
        "requirements": ["claim-first", "strict-schema"],
        "metadata": {"owner": "local"},
    }
    obj = ReportTask.from_dict(raw)
    assert obj.to_dict() == raw

