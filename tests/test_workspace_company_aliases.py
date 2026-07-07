from src.db.init_db import init_db
from src.services.report_task_service import ReportTaskService
from src.services.workspace_service import WorkspaceCompanyNotFound, WorkspaceService


def build_service(tmp_path):
    engine = init_db(f"sqlite:///{tmp_path / 'aliases.db'}")
    report_service = ReportTaskService(
        engine=engine,
        output_root=tmp_path / "outputs",
        report_root=tmp_path / "reports",
        memory_root=tmp_path / "memory",
    )
    return WorkspaceService(session_factory=report_service.session)


def test_workspace_company_alias_resolution_matches_symbol_name_and_alias(tmp_path):
    service = build_service(tmp_path)
    workspace = service.create_workspace(
        {
            "name": "跨市场投研空间",
            "slug": "cross-market",
            "market": "HK",
            "focus_metrics": ["revenue", "cash_flow"],
            "risk_types": ["policy", "competition"],
        }
    )
    service.add_company(
        workspace["id"],
        {
            "name": "Tencent Holdings Limited",
            "symbol": "0700.HK",
            "market": "HK",
            "industry": "Internet",
            "aliases": ["腾讯", "腾讯控股", "Tencent"],
        },
    )

    by_symbol = service.resolve_company("cross-market", "0700.HK")
    by_alias = service.resolve_company("cross-market", "腾讯控股")
    by_english = service.resolve_company("cross-market", "Tencent")

    assert by_symbol["symbol"] == "0700.HK"
    assert by_alias["name"] == "Tencent Holdings Limited"
    assert by_english["market"] == "HK"
    assert by_alias["focus_metrics"] == ["revenue", "cash_flow"]
    assert by_alias["risk_types"] == ["policy", "competition"]


def test_workspace_company_alias_resolution_rejects_unknown_company(tmp_path):
    service = build_service(tmp_path)
    service.create_workspace({"name": "默认投研空间", "slug": "default"})

    try:
        service.resolve_company("default", "不存在公司")
    except WorkspaceCompanyNotFound as exc:
        assert "不存在公司" in str(exc)
    else:
        raise AssertionError("Expected WorkspaceCompanyNotFound")
