from __future__ import annotations

import json
import inspect
import os
import asyncio
import threading
import time
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

    def list_tools(
        self,
        server_id: str,
        *,
        stop_event=None,
        deadline_monotonic: float | None = None,
        timeout_seconds_override: float | None = None,
    ) -> list[MCPToolSpec]:
        server = self._require_server(server_id)
        if server.transport == "mock":
            return server.tools
        return self._run_async(
            self._list_tools_async,
            server,
            stop_event,
            deadline_monotonic,
            timeout_seconds_override,
            stop_event=stop_event,
            deadline_monotonic=deadline_monotonic,
        )

    def call_tool(
        self,
        server_id: str,
        tool_name: str,
        payload: dict,
        *,
        stop_event=None,
        deadline_monotonic: float | None = None,
        timeout_seconds_override: float | None = None,
    ) -> dict:
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
        return self._run_async(
            self._call_tool_async,
            server,
            tool_name,
            payload,
            stop_event,
            deadline_monotonic,
            timeout_seconds_override,
            stop_event=stop_event,
            deadline_monotonic=deadline_monotonic,
        )

    def _run_async(
        self,
        func,
        *args,
        stop_event=None,
        deadline_monotonic: float | None = None,
    ):
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return anyio.run(func, *args)

        result: list[object] = []
        error: list[BaseException] = []
        worker_loop: list[asyncio.AbstractEventLoop] = []
        worker_task: list[asyncio.Task[object]] = []

        def worker() -> None:
            loop = asyncio.new_event_loop()
            worker_loop.append(loop)
            asyncio.set_event_loop(loop)
            try:
                task = loop.create_task(func(*args))
                worker_task.append(task)
                result.append(loop.run_until_complete(task))
            except BaseException as exc:
                error.append(exc)
            finally:
                pending = [task for task in asyncio.all_tasks(loop) if not task.done()]
                for pending_task in pending:
                    pending_task.cancel()
                if pending:
                    loop.run_until_complete(
                        asyncio.gather(*pending, return_exceptions=True)
                    )
                loop.run_until_complete(loop.shutdown_asyncgens())
                asyncio.set_event_loop(None)
                loop.close()

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        cancellation_error: TimeoutError | None = None
        while thread.is_alive():
            thread.join(timeout=0.05)
            if stop_event is not None and getattr(stop_event, "is_set", lambda: False)():
                cancellation_error = TimeoutError("MCP_CALL_CANCELLED")
                self._cancel_async_worker(worker_loop, worker_task)
                thread.join(timeout=0.5)
                break
            if deadline_monotonic is not None and time.monotonic() >= float(deadline_monotonic):
                cancellation_error = TimeoutError("MCP_CALL_TIMED_OUT")
                self._cancel_async_worker(worker_loop, worker_task)
                thread.join(timeout=0.5)
                break
        if cancellation_error is not None:
            raise cancellation_error
        if error:
            raise error[0]
        if not result:
            raise RuntimeError("MCP_ASYNC_RUN_FAILED")
        return result[0]

    def _require_server(self, server_id: str) -> MCPServerSpec:
        try:
            return self._servers[server_id]
        except KeyError as exc:
            raise KeyError(f"MCP_SERVER_NOT_FOUND:{server_id}") from exc

    async def _list_tools_async(self, server: MCPServerSpec, stop_event=None, deadline_monotonic: float | None = None, timeout_seconds_override: float | None = None) -> list[MCPToolSpec]:
        tools: list[MCPToolSpec] | None = None
        try:
            self._raise_if_interrupted(stop_event, deadline_monotonic)
            async with self._open_session_compat(
                server,
                timeout_seconds_override=timeout_seconds_override,
                deadline_monotonic=deadline_monotonic,
            ) as session:
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

    async def _call_tool_async(self, server: MCPServerSpec, tool_name: str, payload: dict, stop_event=None, deadline_monotonic: float | None = None, timeout_seconds_override: float | None = None) -> dict:
        response_payload: dict | None = None
        try:
            self._raise_if_interrupted(stop_event, deadline_monotonic)
            async with self._open_session_compat(
                server,
                timeout_seconds_override=timeout_seconds_override,
                deadline_monotonic=deadline_monotonic,
            ) as session:
                result = await session.call_tool(
                    tool_name,
                    arguments=payload,
                    read_timeout_seconds=timedelta(seconds=self._effective_timeout_seconds(server, timeout_seconds_override, deadline_monotonic)),
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

    def _open_session_compat(
        self,
        server: MCPServerSpec,
        *,
        timeout_seconds_override: float | None = None,
        deadline_monotonic: float | None = None,
    ):
        return self._open_session(
            server,
            **self._open_session_kwargs(
                timeout_seconds_override=timeout_seconds_override,
                deadline_monotonic=deadline_monotonic,
            ),
        )

    def _open_session_kwargs(
        self,
        *,
        timeout_seconds_override: float | None = None,
        deadline_monotonic: float | None = None,
    ) -> dict[str, float]:
        try:
            signature = inspect.signature(self._open_session)
        except (TypeError, ValueError):
            signature = None
        accepts_kwargs = bool(signature) and any(
            parameter.kind == inspect.Parameter.VAR_KEYWORD
            for parameter in signature.parameters.values()
        )
        candidates = {
            "timeout_seconds_override": timeout_seconds_override,
            "deadline_monotonic": deadline_monotonic,
        }
        return {
            key: value
            for key, value in candidates.items()
            if value is not None and (accepts_kwargs or (signature is not None and key in signature.parameters))
        }

    @asynccontextmanager
    async def _open_session(self, server: MCPServerSpec, *, timeout_seconds_override: float | None = None, deadline_monotonic: float | None = None):
        timeout = timedelta(seconds=self._effective_timeout_seconds(server, timeout_seconds_override, deadline_monotonic))
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
                timeout=self._effective_timeout_seconds(server, timeout_seconds_override, deadline_monotonic),
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


    @staticmethod
    def _raise_if_interrupted(stop_event, deadline_monotonic: float | None) -> None:
        if stop_event is not None and getattr(stop_event, "is_set", lambda: False)():
            raise RuntimeError("MCP_CALL_CANCELLED")
        if deadline_monotonic is not None and time.monotonic() >= deadline_monotonic:
            raise TimeoutError("MCP_CALL_TIMED_OUT")

    @staticmethod
    def _effective_timeout_seconds(server: MCPServerSpec, timeout_seconds_override: float | None, deadline_monotonic: float | None) -> float:
        timeout = float(server.timeout_ms) / 1000.0
        if timeout_seconds_override is not None:
            timeout = min(timeout, float(timeout_seconds_override))
        if deadline_monotonic is not None:
            timeout = min(timeout, max(0.05, deadline_monotonic - time.monotonic()))
        return max(0.05, timeout)

    @staticmethod
    def _cancel_async_worker(
        worker_loop: list[asyncio.AbstractEventLoop],
        worker_task: list[asyncio.Task[object]],
    ) -> None:
        if not worker_loop:
            return
        loop = worker_loop[0]
        if loop.is_closed():
            return

        def cancel_task() -> None:
            if worker_task and not worker_task[0].done():
                worker_task[0].cancel()

        loop.call_soon_threadsafe(cancel_task)
