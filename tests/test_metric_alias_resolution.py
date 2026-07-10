from src.db.init_db import init_db
from src.services.dictionary_service import DictionaryService
from src.services.report_task_service import ReportTaskService


def build_service(tmp_path):
    engine = init_db(f"sqlite:///{tmp_path / 'metric_alias.db'}")
    report_service = ReportTaskService(
        engine=engine,
        output_root=tmp_path / "outputs",
        report_root=tmp_path / "reports",
        memory_root=tmp_path / "memory",
    )
    return DictionaryService(session_factory=report_service.session)


def test_metric_alias_resolution_maps_financial_metric_variants(tmp_path):
    service = build_service(tmp_path)
    service.create_term(
        {
            "term_type": "metric",
            "canonical_name": "营业收入",
            "aliases": ["营收", "收入", "revenue", "total revenue"],
            "description": "利润表收入科目",
            "metadata": {"statement": "income"},
        }
    )

    by_cn = service.resolve_metric("营收")
    by_en = service.resolve_metric("Total Revenue")

    assert by_cn["canonical_name"] == "营业收入"
    assert by_cn["metadata"]["statement"] == "income"
    assert by_en["matched_alias"] == "total revenue"


def test_dictionary_supports_risk_and_exclude_terms(tmp_path):
    service = build_service(tmp_path)
    service.create_term({"term_type": "risk", "canonical_name": "增长放缓", "aliases": ["增速下滑", "growth slowdown"]})
    service.create_term({"term_type": "exclude", "canonical_name": "广告噪声", "aliases": ["推广", "免责声明"]})

    risks = service.list_terms(term_type="risk")
    excludes = service.list_terms(term_type="exclude")

    assert risks["items"][0]["canonical_name"] == "增长放缓"
    assert excludes["items"][0]["aliases"] == ["广告噪声", "推广", "免责声明"]
