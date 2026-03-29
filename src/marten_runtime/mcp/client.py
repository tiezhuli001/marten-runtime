from __future__ import annotations

import json
import os
import asyncio
import threading
from collections.abc import Mapping
from contextlib import asynccontextmanager
from datetime import timedelta

import anyio
import httpx
from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.client.streamable_http import streamable_http_client

from marten_runtime.mcp.models import MCPServerSpec, MCPToolSpec


class MCPClient:
    def __init__(
        self,
        servers: list[MCPServerSpec] | None = None,
        *,
        env: Mapping[str, str] | None = None,
    ) -> None:
        self._servers = {server.server_id: server for server in (servers or [])}
        self._env = dict(os.environ if env is None else env)

    def register_server(self, server: MCPServerSpec) -> None:
        self._servers[server.server_id] = server

    def list_tools(self, server_id: str) -> list[MCPToolSpec]:
        server = self._require_server(server_id)
        if server.transport == "mock":
            return server.tools
        return self._run_async(self._list_tools_async, server)

    def call_tool(self, server_id: str, tool_name: str, payload: dict) -> dict:
        server = self._require_server(server_id)
        if server.transport == "mock":
            query = payload.get("query", "")
            return {
                "server_id": server_id,
                "tool_name": tool_name,
                "payload": payload,
                "result_text": f"{tool_name} result for {query}".strip(),
                "ok": True,
            }
        return self._run_async(self._call_tool_async, server, tool_name, payload)

    def _run_async(self, func, *args):
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return anyio.run(func, *args)

        result: list[object] = []
        error: list[Exception] = []

        def worker() -> None:
            try:
                result.append(anyio.run(func, *args))
            except Exception as exc:
                error.append(exc)

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        thread.join()
        if error:
            raise error[0]
        return result[0]

    def _require_server(self, server_id: str) -> MCPServerSpec:
        try:
            return self._servers[server_id]
        except KeyError as exc:
            raise KeyError(f"MCP_SERVER_NOT_FOUND:{server_id}") from exc

    async def _list_tools_async(self, server: MCPServerSpec) -> list[MCPToolSpec]:
        tools: list[MCPToolSpec] | None = None
        try:
            async with self._open_session(server) as session:
                result = await session.list_tools()
                tools = [
                    MCPToolSpec(name=item.name, description=item.description or "")
                    for item in result.tools
                ]
        except* anyio.BrokenResourceError:
            if tools is None:
                raise
        if tools is None:
            raise RuntimeError(f"MCP_LIST_TOOLS_FAILED:{server.server_id}")
        return tools

    async def _call_tool_async(self, server: MCPServerSpec, tool_name: str, payload: dict) -> dict:
        response_payload: dict | None = None
        try:
            async with self._open_session(server) as session:
                result = await session.call_tool(
                    tool_name,
                    arguments=payload,
                    read_timeout_seconds=timedelta(milliseconds=server.timeout_ms),
                )
                content = []
                text_parts: list[str] = []
                for item in result.content:
                    dumped = item.model_dump(mode="json", by_alias=True)
                    content.append(dumped)
                    if dumped.get("type") == "text":
                        text_parts.append(str(dumped.get("text", "")))
                result_text = "\n".join(part for part in text_parts if part).strip()
                if not result_text and result.structuredContent is not None:
                    result_text = json.dumps(result.structuredContent, ensure_ascii=True)
                response_payload = {
                    "server_id": server.server_id,
                    "tool_name": tool_name,
                    "payload": payload,
                    "content": content,
                    "structured_content": result.structuredContent,
                    "result_text": result_text,
                    "ok": not bool(result.isError),
                    "is_error": bool(result.isError),
                }
        except* anyio.BrokenResourceError:
            if response_payload is None:
                raise
        if response_payload is None:
            raise RuntimeError(f"MCP_CALL_TOOL_FAILED:{server.server_id}:{tool_name}")
        return response_payload

    def _resolve_server_env(self, server: MCPServerSpec) -> dict[str, str]:
        resolved = dict(self._env)
        for key, value in server.env.items():
            if value.startswith("$"):
                source_name = value[1:]
                if source_name not in self._env:
                    raise RuntimeError(f"MCP_ENV_NOT_FOUND:{source_name}")
                resolved[key] = self._env[source_name]
            else:
                resolved[key] = value
        return resolved

    @asynccontextmanager
    async def _open_session(self, server: MCPServerSpec):
        timeout = timedelta(milliseconds=server.timeout_ms)
        if server.transport == "stdio":
            if not server.command:
                raise RuntimeError(f"MCP_STDIO_COMMAND_REQUIRED:{server.server_id}")
            params = StdioServerParameters(
                command=server.command,
                args=server.args,
                env=self._resolve_server_env(server),
                cwd=server.cwd,
            )
            manager = stdio_client(params)
            async with manager as (read_stream, write_stream):
                async with ClientSession(
                    read_stream,
                    write_stream,
                    read_timeout_seconds=timeout,
                ) as session:
                    await session.initialize()
                    yield session
        elif server.transport in {"http", "streamable-http"}:
            if not server.url:
                raise RuntimeError(f"MCP_HTTP_URL_REQUIRED:{server.server_id}")
            async with httpx.AsyncClient(
                headers=server.headers or None,
                timeout=server.timeout_ms / 1000,
            ) as http_client:
                manager = streamable_http_client(server.url, http_client=http_client)
                async with manager as (read_stream, write_stream, get_session_id):
                    del get_session_id
                    async with ClientSession(
                        read_stream,
                        write_stream,
                        read_timeout_seconds=timeout,
                    ) as session:
                        await session.initialize()
                        yield session
        else:
            raise RuntimeError(f"MCP_TRANSPORT_UNSUPPORTED:{server.transport}")
