"""Lightweight MCP-style manager for local financial tools.

This module does not start an MCP server. It provides the same project-level
boundary: discover tools, expose schemas, call tools, and export a manifest.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any, Callable, Dict, List


ToolCallable = Callable[..., Any]


@dataclass
class MCPTool:
    """Tool metadata exposed through the local MCP-style manager."""

    name: str
    description: str
    parameters: Dict[str, Any]
    handler: ToolCallable = field(repr=False)
    namespace: str = "local"

    @property
    def qualified_name(self) -> str:
        return f"{self.namespace}.{self.name}" if self.namespace else self.name

    def to_manifest_item(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "qualified_name": self.qualified_name,
            "namespace": self.namespace,
            "description": self.description,
            "parameters": self.parameters,
        }

    def to_tool_schema(self) -> Dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.qualified_name.replace(".", "__"),
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class MCPManager:
    """Register, discover, and call local tools through an MCP-like boundary."""

    def __init__(self):
        self._tools: Dict[str, MCPTool] = {}

    @classmethod
    def from_tool_registry(cls, registry: Any, namespace: str = "finance") -> "MCPManager":
        manager = cls()
        for name in registry.names():
            spec = registry.get(name)
            manager.register_tool(
                name=spec.name,
                description=spec.description,
                parameters=spec.parameters,
                handler=spec.handler,
                namespace=namespace,
            )
        return manager

    def register_tool(
        self,
        name: str,
        description: str,
        parameters: Dict[str, Any],
        handler: ToolCallable,
        namespace: str = "local",
    ) -> None:
        tool = MCPTool(
            name=name,
            description=description,
            parameters=parameters,
            handler=handler,
            namespace=namespace,
        )
        if tool.qualified_name in self._tools:
            raise ValueError(f"MCP tool already registered: {tool.qualified_name}")
        self._tools[tool.qualified_name] = tool

    def list_tools(self) -> List[Dict[str, Any]]:
        return [self._tools[name].to_manifest_item() for name in sorted(self._tools)]

    def tool_schemas(self) -> List[Dict[str, Any]]:
        return [self._tools[name].to_tool_schema() for name in sorted(self._tools)]

    def call_tool(self, name: str, **kwargs: Any) -> Any:
        resolved = self._resolve_name(name)
        return self._tools[resolved].handler(**kwargs)

    def export_manifest(self, output_path: str | Path) -> Path:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "protocol": "local-mcp-v1",
            "tool_count": len(self._tools),
            "tools": self.list_tools(),
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def _resolve_name(self, name: str) -> str:
        if name in self._tools:
            return name
        matches = [key for key in self._tools if key.endswith(f".{name}")]
        if len(matches) == 1:
            return matches[0]
        if not matches:
            raise KeyError(f"MCP tool not found: {name}")
        raise KeyError(f"Ambiguous MCP tool name: {name}; matches={matches}")
