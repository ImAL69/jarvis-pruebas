from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol


@dataclass(frozen=True)
class MCPServerConfig:
    name: str
    transport: str
    command: str
    args: list[str]


class MCPClientProtocol(Protocol):
    async def list_tools(self, server_name: str) -> list[dict[str, Any]]: ...

    async def call_tool(self, server_name: str, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]: ...


def load_mcp_config(config_path: Path) -> list[MCPServerConfig]:
    if not config_path.exists():
        return []

    raw = json.loads(config_path.read_text(encoding="utf-8"))
    servers = raw.get("servers", [])
    parsed: list[MCPServerConfig] = []
    for server in servers:
        command = str(server.get("command", "")).strip()
        args = [str(item) for item in server.get("args", [])]
        if not command:
            raise ValueError("Cada servidor MCP debe definir command en config local")
        parsed.append(
            MCPServerConfig(
                name=str(server.get("name", "")).strip() or "default",
                transport=str(server.get("transport", "stdio")).strip(),
                command=command,
                args=args,
            )
        )
    return parsed


class MCPClientManager:
    """Capa inicial segura para integrar clientes MCP locales en próximas iteraciones."""

    def __init__(self, config_path: Path) -> None:
        self._config_path = config_path
        self._servers = load_mcp_config(config_path)

    def list_servers(self) -> list[str]:
        return [server.name for server in self._servers]

    async def list_tools(self, server_name: str) -> list[dict[str, Any]]:
        if server_name not in self.list_servers():
            raise ValueError("Servidor MCP no configurado")
        raise NotImplementedError("Pendiente: conectar cliente MCP real de forma segura")

    async def call_tool(self, server_name: str, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if server_name not in self.list_servers():
            raise ValueError("Servidor MCP no configurado")
        raise NotImplementedError("Pendiente: ejecución MCP real en próxima iteración")
