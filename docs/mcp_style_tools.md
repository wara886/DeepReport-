# MCP-Style Tools Boundary

FinSight exposes financial capabilities through a small local MCP-style boundary. It is a practical tool discovery and invocation surface, not a complete production MCP platform.

## HTTP JSON-RPC Surface

| Method | Status | Behavior |
| --- | --- | --- |
| `initialize` | Supported | Returns `FinSightMCPStyle` and `local-mcp-v1`. |
| `tools/list` | Supported | Returns available tool schemas. |
| `tools/call` | Supported | Invokes one registered tool and returns structured content. |
| `resources/list` | Empty by design | Returns an empty resource collection. |
| `prompts/list` | Empty by design | Returns an empty prompt collection. |

The implementation lives in `src/utils/mcp_http_server.py` and `src/utils/mcp_manager.py`. Qualified manifest names use `finance.<tool_name>`; function schemas use `finance__<tool_name>`.

## Registered Financial Tools

| Tool | Purpose |
| --- | --- |
| `retrieve_local_evidence` | Search evidence with BM25 or configured ranking modes. |
| `calculate_financial_ratios` | Extract revenue, margin, ROE/ROA and cash-flow features. |
| `build_trend_features` | Summarize evidence coverage and trends. |
| `build_three_statement_view` | Normalize evidence into financial statement rows. |
| `build_peer_comparison` | Build peer context for a company and period. |
| `perform_company_valuation` | Produce first-pass valuation artifacts. |
| `fetch_yahoo_market_snapshot` | Convert a market snapshot into evidence. |
| `render_all_charts` | Render report charts and metadata. |
| `attach_charts_to_report` | Attach chart references to Markdown output. |

## Boundary

Tool execution does not bypass evidence and verifier rules. A model may select a tool, but material report claims still require evidence IDs, citations and quality-gate checks.
