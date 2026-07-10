from src.db.init_db import init_db
from src.services.dictionary_service import DictionaryService, DictionaryTermNotFound
from src.services.report_task_service import ReportTaskService


def build_service(tmp_path):
    engine = init_db(f"sqlite:///{tmp_path / 'company_alias.db'}")
    report_service = ReportTaskService(
        engine=engine,
        output_root=tmp_path / "outputs",
        report_root=tmp_path / "reports",
        memory_root=tmp_path / "memory",
    )
    return DictionaryService(session_factory=report_service.session)


def test_company_alias_resolution_normalizes_chinese_english_and_symbol(tmp_path):
    service = build_service(tmp_path)
    service.create_term(
        {
            "term_type": "company",
            "canonical_name": "腾讯控股",
            "symbol": "0700.HK",
            "market": "HK",
            "aliases": ["腾讯", "Tencent", "Tencent Holdings Limited", "0700.HK"],
        }
    )

    by_symbol = service.resolve_company("0700.HK", market="HK")
    by_chinese = service.resolve_company("腾讯", market="HK")
    by_english = service.resolve_company("Tencent Holdings Limited")

    assert by_symbol["canonical_name"] == "腾讯控股"
    assert by_chinese["symbol"] == "0700.HK"
    assert by_english["market"] == "HK"


def test_company_alias_resolution_rejects_unknown_alias(tmp_path):
    service = build_service(tmp_path)

    try:
        service.resolve_company("不存在公司")
    except DictionaryTermNotFound as exc:
        assert "不存在公司" in str(exc)
    else:
        raise AssertionError("Expected DictionaryTermNotFound")
