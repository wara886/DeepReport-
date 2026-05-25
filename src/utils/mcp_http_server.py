"""HTTP surface for the local MCP-style financial tool manager."""

from __future__ import annotations

from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from typing import Any, Dict, Tuple
from urllib.parse import urlparse

from src.tools import build_core_tool_registry
from src.utils import MCPManager


def build_default_mcp_manager() -> MCPManager:
    return MCPManager.from_tool_registry(build_core_tool_registry(), namespace="finance")


def dispatch_jsonrpc(payload: Dict[str, Any], manager: MCPManager) -> Dict[str, Any]:
    request_id = payload.get("id")
    method = str(payload.get("method") or "")
    params = payload.get("params", {}) if isinstance(payload.get("params"), dict) else {}
    try:
        if method == "initialize":
            result = {
                "protocolVersion": "local-mcp-v1",
                "serverInfo": {"name": "FinSightMCPStyle", "version": "0.1.0"},
                "capabilities": {"tools": True},
            }
        elif method in {"tools/list", "list_tools"}:
            result = {"tools": [_to_mcp_tool(item) for item in manager.list_tools()]}
        elif method in {"tools/call", "call_tool"}:
            name = str(params.get("name") or "")
            name = name.replace("__", ".")
            arguments = params.get("arguments", {})
            if not isinstance(arguments, dict):
                raise ValueError("params.arguments must be an object")
            content = manager.call_tool(name, **arguments)
            result = {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(content, ensure_ascii=False, indent=2),
                    }
                ],
                "structuredContent": content,
                "isError": False,
            }
        elif method in {"resources/list", "prompts/list"}:
            result = {"resources": []} if method == "resources/list" else {"prompts": []}
        else:
            raise KeyError(f"unsupported method: {method}")
        return {"jsonrpc": "2.0", "id": request_id, "result": result}
    except Exception as exc:
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": -32000, "message": str(exc)},
        }


def create_mcp_handler(manager: MCPManager | None = None) -> type[BaseHTTPRequestHandler]:
    resolved_manager = manager or build_default_mcp_manager()

    class MCPRequestHandler(BaseHTTPRequestHandler):
        server_version = "FinSightMCPStyle/0.1"

        def do_GET(self) -> None:
            path = urlparse(self.path).path
            if path in {"/", "/health"}:
                self._send_json({"status": "ok", "service": "FinSightMCPStyle"})
            elif path in {"/manifest", "/mcp/manifest", "/tools", "/mcp/tools"}:
                self._send_json(
                    {
                        "protocol": "local-mcp-v1",
                        "tool_count": len(resolved_manager.list_tools()),
                        "tools": resolved_manager.list_tools(),
                    }
                )
            else:
                self._send_json({"error": f"not found: {path}"}, status=HTTPStatus.NOT_FOUND)

        def do_POST(self) -> None:
            path = urlparse(self.path).path
            try:
                payload = self._read_json()
                if path in {"/rpc", "/mcp/rpc"}:
                    self._send_json(dispatch_jsonrpc(payload, resolved_manager))
                elif path in {"/call", "/mcp/call"}:
                    name = str(payload.get("name") or "")
                    arguments = payload.get("arguments", {})
                    if not isinstance(arguments, dict):
                        raise ValueError("arguments must be an object")
                    self._send_json({"result": resolved_manager.call_tool(name, **arguments)})
                else:
                    self._send_json({"error": f"not found: {path}"}, status=HTTPStatus.NOT_FOUND)
            except Exception as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)

        def log_message(self, format: str, *args: Any) -> None:
            return

        def _read_json(self) -> Dict[str, Any]:
            length = int(self.headers.get("Content-Length", "0") or 0)
            raw = self.rfile.read(length).decode("utf-8") if length else "{}"
            payload = json.loads(raw)
            if not isinstance(payload, dict):
                raise ValueError("JSON payload must be an object")
            return payload

        def _send_json(self, payload: Dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
            body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
            self.send_response(int(status))
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(body)

    return MCPRequestHandler


def run_mcp_server(host: str = "127.0.0.1", port: int = 8765) -> Tuple[ThreadingHTTPServer, str]:
    server = ThreadingHTTPServer((host, port), create_mcp_handler())
    url = f"http://{host}:{server.server_address[1]}"
    return server, url


def _to_mcp_tool(item: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "name": str(item.get("qualified_name") or item.get("name") or "").replace(".", "__"),
        "title": str(item.get("qualified_name") or item.get("name") or ""),
        "description": str(item.get("description") or ""),
        "inputSchema": item.get("parameters", {"type": "object", "properties": {}}),
        "annotations": {
            "namespace": item.get("namespace", ""),
            "localName": item.get("name", ""),
        },
    }
