from __future__ import annotations

import json
import inspect
import os
import asyncio
import threading
import time
from concurrent.futures import TimeoutError as FutureTimeoutError
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
        self._persistent_stdio_sessions: dict[str, _PersistentStdioSession] = {}
        self._persistent_stdio_lock = threading.RLock()

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
        if server.transport == "stdio" and self._should_use_persistent_stdio_list():
            session = self._persistent_stdio_session(server)
            try:
                return session.run_list_tools(
                    stop_event=stop_event,
                    deadline_monotonic=deadline_monotonic,
                    timeout_seconds_override=timeout_seconds_override,
                )
            except BaseException:
                self._discard_persistent_stdio_session(server.server_id, session)
                raise
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
        if server.transport == "stdio" and self._should_use_persistent_stdio_call():
            session = self._persistent_stdio_session(server)
            try:
                return session.run_call_tool(
                    tool_name,
                    payload,
                    stop_event=stop_event,
                    deadline_monotonic=deadline_monotonic,
                    timeout_seconds_override=timeout_seconds_override,
                )
            except BaseException:
                self._discard_persistent_stdio_session(server.server_id, session)
                raise
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


    def shutdown(self) -> None:
        with self._persistent_stdio_lock:
            sessions = list(self._persistent_stdio_sessions.values())
            self._persistent_stdio_sessions.clear()
        for session in sessions:
            session.close()

    def _should_use_persistent_stdio_list(self) -> bool:
        return (
            type(self)._list_tools_async is MCPClient._list_tools_async
            and type(self)._open_session is MCPClient._open_session
        )

    def _should_use_persistent_stdio_call(self) -> bool:
        return (
            type(self)._call_tool_async is MCPClient._call_tool_async
            and type(self)._open_session is MCPClient._open_session
        )

    def _persistent_stdio_session(self, server: MCPServerSpec) -> "_PersistentStdioSession":
        if server.transport != "stdio":
            raise RuntimeError(f"MCP_PERSISTENT_STDIO_UNSUPPORTED:{server.transport}")
        with self._persistent_stdio_lock:
            existing = self._persistent_stdio_sessions.get(server.server_id)
            if existing is not None:
                if not existing.is_closed():
                    return existing
                self._persistent_stdio_sessions.pop(server.server_id, None)
            session = _PersistentStdioSession(self, server)
            self._persistent_stdio_sessions[server.server_id] = session
            return session

    def _discard_persistent_stdio_session(self, server_id: str, session: "_PersistentStdioSession") -> None:
        with self._persistent_stdio_lock:
            if self._persistent_stdio_sessions.get(server_id) is not session:
                return
            self._persistent_stdio_sessions.pop(server_id, None)
        session.close()

    def _stdio_client_manager(self, params: StdioServerParameters):
        return stdio_client(params)

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
            manager = self._stdio_client_manager(params)
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
                trust_env=False,
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


class _PersistentStdioSession:
    def __init__(self, client: MCPClient, server: MCPServerSpec) -> None:
        self._client = client
        self._server = server
        self._loop = asyncio.new_event_loop()
        self._ready = threading.Event()
        self._closed = threading.Event()
        self._startup_error: BaseException | None = None
        self._session = None
        self._stop_async: asyncio.Event | None = None
        self._op_lock = threading.RLock()
        self._thread = threading.Thread(
            target=self._thread_main,
            name=f"mcp-stdio-{server.server_id}",
            daemon=True,
        )
        self._thread.start()

    def run_list_tools(
        self,
        *,
        stop_event=None,
        deadline_monotonic: float | None = None,
        timeout_seconds_override: float | None = None,
    ) -> list[MCPToolSpec]:
        result = self._run_coroutine(
            lambda: self._list_tools_async(),
            stop_event=stop_event,
            deadline_monotonic=deadline_monotonic,
            timeout_seconds_override=timeout_seconds_override,
        )
        return [
            MCPToolSpec(name=item.name, description=item.description or "")
            for item in result.tools
        ]

    def run_call_tool(
        self,
        tool_name: str,
        payload: dict,
        *,
        stop_event=None,
        deadline_monotonic: float | None = None,
        timeout_seconds_override: float | None = None,
    ) -> dict:
        result = self._run_coroutine(
            lambda: self._call_tool_async(
                tool_name,
                payload,
                timeout_seconds_override,
                deadline_monotonic,
            ),
            stop_event=stop_event,
            deadline_monotonic=deadline_monotonic,
            timeout_seconds_override=timeout_seconds_override,
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
        return {
            "server_id": self._server.server_id,
            "tool_name": tool_name,
            "payload": payload,
            "content": content,
            "structured_content": result.structuredContent,
            "result_text": result_text,
            "ok": not bool(result.isError),
            "is_error": bool(result.isError),
        }

    def is_closed(self) -> bool:
        return self._closed.is_set()

    def close(self) -> None:
        if self._closed.is_set():
            return
        self._closed.set()
        stop_async = self._stop_async
        if self._ready.is_set() and self._startup_error is None and self._loop.is_running() and stop_async is not None:
            self._loop.call_soon_threadsafe(stop_async.set)
        self._thread.join(timeout=2.0)
        if self._thread.is_alive():
            return
        if not self._loop.is_closed():
            self._loop.close()

    async def _list_tools_async(self):
        session = self._require_ready_session()
        return await session.list_tools()

    async def _call_tool_async(
        self,
        tool_name: str,
        payload: dict,
        timeout_seconds_override: float | None,
        deadline_monotonic: float | None,
    ):
        session = self._require_ready_session()
        return await session.call_tool(
            tool_name,
            arguments=payload,
            read_timeout_seconds=timedelta(
                seconds=self._client._effective_timeout_seconds(
                    self._server,
                    timeout_seconds_override,
                    deadline_monotonic,
                )
            ),
        )

    async def _startup(self) -> None:
        if not self._server.command:
            raise RuntimeError(f"MCP_STDIO_COMMAND_REQUIRED:{self._server.server_id}")
        params = StdioServerParameters(
            command=self._server.command,
            args=self._server.args,
            env=self._client._resolve_server_env(self._server),
            cwd=self._server.cwd,
        )
        try:
            async with self._client._stdio_client_manager(params) as (read_stream, write_stream):
                async with ClientSession(
                    read_stream,
                    write_stream,
                    read_timeout_seconds=timedelta(
                        seconds=self._client._effective_timeout_seconds(self._server, None, None)
                    ),
                ) as session:
                    await session.initialize()
                    self._session = session
                    self._stop_async = asyncio.Event()
                    self._ready.set()
                    if not self._closed.is_set():
                        await self._stop_async.wait()
        except BaseException as exc:
            self._startup_error = exc
            self._ready.set()
        finally:
            self._session = None
            self._stop_async = None

    def _thread_main(self) -> None:
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._startup())
        except BaseException as exc:
            self._startup_error = exc
            self._ready.set()
        finally:
            pending = [task for task in asyncio.all_tasks(self._loop) if not task.done()]
            for task in pending:
                task.cancel()
            if pending:
                self._loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            self._loop.run_until_complete(self._loop.shutdown_asyncgens())
            asyncio.set_event_loop(None)

    def _require_ready_session(self):
        if self._session is None:
            raise RuntimeError(f"MCP_STDIO_SESSION_NOT_READY:{self._server.server_id}")
        return self._session

    def _run_coroutine(
        self,
        coroutine_factory,
        *,
        stop_event=None,
        deadline_monotonic: float | None = None,
        timeout_seconds_override: float | None = None,
    ):
        self._wait_until_ready(stop_event, deadline_monotonic, timeout_seconds_override)
        if self._startup_error is not None:
            raise self._startup_error
        with self._op_lock:
            future = asyncio.run_coroutine_threadsafe(coroutine_factory(), self._loop)
            while True:
                timeout = self._poll_timeout(deadline_monotonic, timeout_seconds_override)
                try:
                    return future.result(timeout=timeout)
                except FutureTimeoutError:
                    if stop_event is not None and getattr(stop_event, "is_set", lambda: False)():
                        future.cancel()
                        raise TimeoutError("MCP_CALL_CANCELLED")
                    if deadline_monotonic is not None and time.monotonic() >= float(deadline_monotonic):
                        future.cancel()
                        raise TimeoutError("MCP_CALL_TIMED_OUT")

    def _wait_until_ready(
        self,
        stop_event,
        deadline_monotonic: float | None,
        timeout_seconds_override: float | None,
    ) -> None:
        started = time.monotonic()
        while not self._ready.is_set():
            if stop_event is not None and getattr(stop_event, "is_set", lambda: False)():
                raise TimeoutError("MCP_CALL_CANCELLED")
            if deadline_monotonic is not None and time.monotonic() >= float(deadline_monotonic):
                raise TimeoutError("MCP_CALL_TIMED_OUT")
            if timeout_seconds_override is not None and time.monotonic() - started >= float(timeout_seconds_override):
                raise TimeoutError("MCP_CALL_TIMED_OUT")
            self._ready.wait(timeout=0.05)

    @staticmethod
    def _poll_timeout(
        deadline_monotonic: float | None,
        timeout_seconds_override: float | None,
    ) -> float:
        timeout = 0.05
        if timeout_seconds_override is not None:
            timeout = min(timeout, max(0.01, float(timeout_seconds_override)))
        if deadline_monotonic is not None:
            timeout = min(timeout, max(0.01, float(deadline_monotonic) - time.monotonic()))
        return timeout
