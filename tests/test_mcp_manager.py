import json

from src.tools import build_core_tool_registry
from src.utils import MCPManager


def test_mcp_manager_wraps_tool_registry_and_exports_manifest(tmp_path):
    registry = build_core_tool_registry()
    manager = MCPManager.from_tool_registry(registry, namespace="finance")

    tools = manager.list_tools()
    assert any(item["qualified_name"] == "finance.calculate_financial_ratios" for item in tools)
    assert any(schema["function"]["name"] == "finance__calculate_financial_ratios" for schema in manager.tool_schemas())

    result = manager.call_tool(
        "calculate_financial_ratios",
        records=[
            {
                "sample_id": "ev_1",
                "symbol": "AAPL",
                "period": "2025Q4",
                "source_type": "filing",
                "content": "Revenue 120.0B, gross margin 45.0%.",
            }
        ],
    )
    assert result["rows"][0]["revenue_billion"] == 120.0

    manifest_path = manager.export_manifest(tmp_path / "mcp_manifest.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["protocol"] == "local-mcp-v1"
    assert manifest["tool_count"] == len(tools)
