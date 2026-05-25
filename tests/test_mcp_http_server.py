from src.tools import build_core_tool_registry
from src.utils import MCPManager
from src.utils.mcp_http_server import dispatch_jsonrpc


def _manager():
    return MCPManager.from_tool_registry(build_core_tool_registry(), namespace="finance")


def test_mcp_jsonrpc_initialize_and_tools_list():
    manager = _manager()

    init = dispatch_jsonrpc({"jsonrpc": "2.0", "id": 1, "method": "initialize"}, manager)
    tools = dispatch_jsonrpc({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, manager)

    assert init["result"]["serverInfo"]["name"] == "FinSightMCPStyle"
    assert tools["result"]["tools"]
    assert any(item["name"] == "finance__fetch_yahoo_market_snapshot" for item in tools["result"]["tools"])
    assert all("inputSchema" in item for item in tools["result"]["tools"])


def test_mcp_jsonrpc_calls_registered_tool():
    manager = _manager()

    result = dispatch_jsonrpc(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "calculate_financial_ratios",
                "arguments": {
                    "records": [
                        {
                            "sample_id": "ev_1",
                            "symbol": "AAPL",
                            "period": "2025Q4",
                            "source_type": "filing",
                            "content": "Revenue 120.0B, gross margin 45.0%.",
                        }
                    ]
                },
            },
        },
        manager,
    )

    assert result["result"]["structuredContent"]["rows"][0]["revenue_billion"] == 120.0
    assert result["result"]["content"][0]["type"] == "text"
