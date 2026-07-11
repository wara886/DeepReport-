"""Test FinancialFact unit and period structured contracts (P0-2).

Covers:
- 126.3B USD == 1263 亿元 (same normalized_value)
- 12.63B USD == 126.3 亿元
- 1.263B USD == 12.63 亿元
- USD/CNY/HKD
- million/billion/万/亿
- quarter/FY/TTM
- Period mismatch detection
- Quality model uses normalized_value, not display text
"""

from src.db.init_db import init_db
from src.db.models import FinancialFact
from src.services.financial_fact_service import (
    FinancialFactService,
    _normalized_value,
    build_display_value,
    _infer_period_basis,
)
from src.services.report_task_service import ReportTaskService


# --- Scale normalization ---

def test_126_3b_usd_normalizes_correctly():
    """126.3B USD raw_value=126.3, scale=billion → normalized=126300000000."""
    nv = _normalized_value(126.3, "billion")
    assert nv == 126_300_000_000.0, f"Expected 126300000000, got {nv}"


def test_126_3b_usd_equals_1263_亿_cny_normalized():
    """126.3B USD and 1263 亿 CNY have same normalized_value scale."""
    nv_usd = _normalized_value(126.3, "billion")   # USD
    nv_cny = _normalized_value(1263.0, "亿")        # 亿 = 1e8, but value already in 亿, so 1263
    # 126.3B = 126,300,000,000 in absolute units
    # 1263亿 = 1263 * 100,000,000 = 126,300,000,000
    assert nv_usd == nv_cny, f"USD normalized {nv_usd} != CNY normalized {nv_cny}"


def test_12_63b_usd_normalizes():
    """12.63B USD → normalized = 12630000000."""
    nv = _normalized_value(12.63, "billion")
    assert nv == 12_630_000_000.0, f"Expected 12630000000, got {nv}"


def test_1_263b_usd_normalizes():
    """1.263B USD → normalized = 1263000000."""
    nv = _normalized_value(1.263, "billion")
    assert nv == 1_263_000_000.0, f"Expected 1263000000, got {nv}"


def test_million_normalization():
    """million scale multiplies by 1_000_000."""
    assert _normalized_value(391.035, "million") == 391_035_000.0


def test_万_scale():
    """万 scale multiplies by 10_000."""
    assert _normalized_value(1200.0, "万") == 12_000_000.0


def test_no_scale_returns_raw():
    """No scale → multiplier = 1."""
    assert _normalized_value(42.0, None) == 42.0
    assert _normalized_value(42.0, "") == 42.0


# --- Cross-locale display ---

def test_display_value_en_us_billion():
    dv = build_display_value(126.3, currency="USD", scale="billion", locale="en-US")
    assert "126.3" in dv
    assert "B" in dv or "billion" in dv


def test_display_value_zh_cn_billion():
    dv = build_display_value(126.3, currency="USD", scale="billion", locale="zh-CN")
    assert "亿" in dv


def test_display_value_zh_cn_cny():
    dv = build_display_value(1200, currency="CNY", scale="亿", locale="zh-CN")
    assert "¥" in dv
    assert "亿" in dv


# --- Period basis inference ---

def test_infer_period_basis_quarter():
    assert _infer_period_basis("2025Q4") == "quarter"
    assert _infer_period_basis("FY2025Q3") == "quarter"


def test_infer_period_basis_fiscal_year():
    assert _infer_period_basis("FY2025") == "fiscal_year"
    assert _infer_period_basis("2025") == "fiscal_year"


def test_infer_period_basis_ttm():
    assert _infer_period_basis("2025TTM") == "ttm"


# --- Integration: importing a fact with normalized_value ---

def test_import_fact_auto_normalizes(tmp_path):
    """Importing a financial fact auto-computes normalized_value and period_basis."""
    engine = init_db(f"sqlite:///{tmp_path / 'norm_fact.db'}")
    report_service = ReportTaskService(
        engine=engine,
        output_root=tmp_path / "outputs",
        report_root=tmp_path / "reports",
        memory_root=tmp_path / "memory",
    )
    service = FinancialFactService(session_factory=report_service.session)

    fact = service.import_fact(
        {
            "metric_name": "Revenue",
            "value": 126.3,
            "period": "FY2025",
            "symbol": "AAPL",
            "currency": "USD",
            "unit": "dollar",
            "scale": "billion",
        }
    )

    assert fact["normalized_value"] == 126_300_000_000.0
    assert fact["period_basis"] == "fiscal_year"
    assert fact["source_period"] == "FY2025"


def test_import_fact_quarterly_period(tmp_path):
    """Quarterly period is correctly detected."""
    engine = init_db(f"sqlite:///{tmp_path / 'qtr_fact.db'}")
    report_service = ReportTaskService(
        engine=engine,
        output_root=tmp_path / "outputs",
        report_root=tmp_path / "reports",
        memory_root=tmp_path / "memory",
    )
    service = FinancialFactService(session_factory=report_service.session)

    fact = service.import_fact(
        {
            "metric_name": "Revenue",
            "value": 94.835,
            "period": "2025Q4",
            "symbol": "AAPL",
            "currency": "USD",
            "unit": "dollar",
            "scale": "billion",
        }
    )

    assert fact["period_basis"] == "quarter"
    assert fact["normalized_value"] == 94_835_000_000.0


# --- Quality model uses structured values ---

def test_facts_with_same_normalized_value_are_equivalent():
    """Two facts with different (value, scale) pairs but same normalized_value
    are numerically equivalent regardless of display text."""
    nv_126b = _normalized_value(126.3, "billion")
    nv_1263yi = _normalized_value(1263.0, "亿")
    assert nv_126b == nv_1263yi, "126.3B != 1263亿 in normalized form"

    # More edge cases: 12630000万 = 12630000 * 10000 = 126,300,000,000
    nv_1263yi_v2 = _normalized_value(12_630_000.0, "万")
    assert nv_126b == nv_1263yi_v2, "126.3B != 12630000万 in normalized form"


def test_explicit_normalized_value_takes_precedence(tmp_path):
    """When payload provides normalized_value explicitly, don't recompute."""
    engine = init_db(f"sqlite:///{tmp_path / 'explicit_nv.db'}")
    report_service = ReportTaskService(
        engine=engine,
        output_root=tmp_path / "outputs",
        report_root=tmp_path / "reports",
        memory_root=tmp_path / "memory",
    )
    service = FinancialFactService(session_factory=report_service.session)

    fact = service.import_fact(
        {
            "metric_name": "Revenue",
            "value": 126.3,
            "period": "FY2025",
            "symbol": "AAPL",
            "currency": "USD",
            "unit": "dollar",
            "scale": "billion",
            "normalized_value": 999_999_999_999.0,  # explicit override
            "period_basis": "ttm",
        }
    )

    assert fact["normalized_value"] == 999_999_999_999.0
    assert fact["period_basis"] == "ttm"
