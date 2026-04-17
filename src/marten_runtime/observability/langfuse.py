from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Protocol


logger = logging.getLogger(__name__)


class LangfuseClientProtocol(Protocol):
    def create_trace(self, payload: dict[str, Any]) -> dict[str, Any]: ...
    def record_generation(self, payload: dict[str, Any]) -> None: ...
    def record_tool_span(self, payload: dict[str, Any]) -> None: ...
    def finalize_trace(self, payload: dict[str, Any]) -> None: ...
    def flush(self) -> None: ...
    def shutdown(self) -> None: ...


@dataclass(frozen=True)
class LangfuseConfig:
    public_key: str | None = None
    secret_key: str | None = None
    base_url: str | None = None
    configured: bool = False
    reason: str | None = None


@dataclass(frozen=True)
class LangfuseRunHandle:
    trace_id: str
    url: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class LangfuseObserver:
    def __init__(
        self,
        *,
        config: LangfuseConfig,
        client: LangfuseClientProtocol | None = None,
    ) -> None:
        self._config = config
        self._client = client
        self._runtime_reason: str | None = None

    @property
    def base_url(self) -> str | None:
        return self._config.base_url

    def enabled(self) -> bool:
        return self._config.configured and self._client is not None

    def configured(self) -> bool:
        return self._config.configured

    def healthy(self) -> bool:
        return self._client is not None and self._runtime_reason is None

    def config_reason(self) -> str | None:
        return self._runtime_reason or self._config.reason

    def status(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled(),
            "healthy": self.healthy(),
            "configured": self.configured(),
            "base_url": self.base_url,
            "reason": self.config_reason(),
        }

    def start_run_trace(
        self,
        *,
        name: str,
        trace_id: str,
        input_text: str | None = None,
        metadata: dict[str, Any] | None = None,
        tags: list[str] | None = None,
    ) -> LangfuseRunHandle:
        payload = {
            "name": name,
            "trace_id": trace_id,
            "input_text": input_text,
            "metadata": dict(metadata or {}),
            "tags": list(tags or []),
        }
        if not self.enabled():
            return LangfuseRunHandle(
                trace_id=trace_id,
                url=None,
                metadata=dict(metadata or {}),
            )
        assert self._client is not None
        try:
            created = self._client.create_trace(payload)
        except Exception as exc:
            self._mark_client_error("create_trace", exc)
            return LangfuseRunHandle(
                trace_id=trace_id,
                url=None,
                metadata=dict(metadata or {}),
            )
        self._mark_client_success()
        return LangfuseRunHandle(
            trace_id=str(created.get("trace_id") or trace_id),
            url=_normalize_url(created.get("url")),
            metadata=dict(metadata or {}),
        )

    def observe_generation(
        self,
        handle: LangfuseRunHandle,
        *,
        name: str,
        model: str | None = None,
        provider: str | None = None,
        input_payload: dict[str, Any] | None = None,
        output_payload: dict[str, Any] | None = None,
        usage: dict[str, Any] | None = None,
        status: str,
        latency_ms: int,
        metadata: dict[str, Any] | None = None,
        error_code: str | None = None,
    ) -> None:
        if not self.enabled():
            return
        assert self._client is not None
        try:
            self._client.record_generation(
                {
                    "trace_id": handle.trace_id,
                    "name": name,
                    "model": model,
                    "provider": provider,
                    "input_payload": dict(input_payload or {}),
                    "output_payload": dict(output_payload or {}),
                    "usage": dict(usage or {}),
                    "status": status,
                    "latency_ms": int(latency_ms),
                    "metadata": dict(metadata or {}),
                    "error_code": error_code,
                }
            )
            self._mark_client_success()
        except Exception as exc:
            self._mark_client_error("record_generation", exc)

    def observe_tool_call(
        self,
        handle: LangfuseRunHandle,
        *,
        name: str,
        tool_name: str,
        tool_payload: dict[str, Any] | None = None,
        tool_result: dict[str, Any] | None = None,
        status: str,
        latency_ms: int,
        metadata: dict[str, Any] | None = None,
        error_code: str | None = None,
    ) -> None:
        if not self.enabled():
            return
        assert self._client is not None
        try:
            self._client.record_tool_span(
                {
                    "trace_id": handle.trace_id,
                    "name": name,
                    "tool_name": tool_name,
                    "tool_payload": dict(tool_payload or {}),
                    "tool_result": dict(tool_result or {}),
                    "status": status,
                    "latency_ms": int(latency_ms),
                    "metadata": dict(metadata or {}),
                    "error_code": error_code,
                }
            )
            self._mark_client_success()
        except Exception as exc:
            self._mark_client_error("record_tool_span", exc)

    def finalize_run(
        self,
        handle: LangfuseRunHandle,
        *,
        status: str,
        final_text: str | None = None,
        error_code: str | None = None,
        usage: dict[str, Any] | None = None,
        total_ms: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        if not self.enabled():
            return
        assert self._client is not None
        try:
            self._client.finalize_trace(
                {
                    "trace_id": handle.trace_id,
                    "status": status,
                    "final_text": final_text,
                    "error_code": error_code,
                    "usage": dict(usage or {}),
                    "total_ms": total_ms,
                    "metadata": dict(metadata or {}),
                }
            )
            self._mark_client_success()
        except Exception as exc:
            self._mark_client_error("finalize_trace", exc)

    def flush(self) -> None:
        if self._client is None:
            return
        try:
            self._client.flush()
            self._mark_client_success()
        except Exception as exc:
            self._mark_client_error("flush", exc)

    def shutdown(self) -> None:
        if self._client is None:
            return
        try:
            self._client.shutdown()
            self._mark_client_success()
        except Exception as exc:
            self._mark_client_error("shutdown", exc)

    def _mark_client_error(self, operation: str, exc: Exception) -> None:
        self._runtime_reason = "langfuse_client_error"
        logger.warning("langfuse %s failed: %s", operation, exc, exc_info=True)

    def _mark_client_success(self) -> None:
        self._runtime_reason = None


def build_langfuse_observer(
    *,
    env: dict[str, str] | None = None,
    client: LangfuseClientProtocol | None = None,
) -> LangfuseObserver:
    resolved_env = env or {}
    public_key = _normalize_env(resolved_env.get("LANGFUSE_PUBLIC_KEY"))
    secret_key = _normalize_env(resolved_env.get("LANGFUSE_SECRET_KEY"))
    base_url = _normalize_env(resolved_env.get("LANGFUSE_BASE_URL"))
    configured = bool(public_key and secret_key and base_url)
    config_reason = None if configured else "missing_langfuse_config"
    resolved_client = client
    if configured and resolved_client is None:
        resolved_client = _build_sdk_client(
            LangfuseConfig(
                public_key=public_key,
                secret_key=secret_key,
                base_url=base_url,
                configured=True,
                reason=None,
            )
        )
        if resolved_client is None:
            config_reason = "langfuse_sdk_unavailable"
    return LangfuseObserver(
        config=LangfuseConfig(
            public_key=public_key,
            secret_key=secret_key,
            base_url=base_url,
            configured=configured,
            reason=config_reason,
        ),
        client=resolved_client,
    )


def _normalize_env(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _normalize_url(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _build_sdk_client(config: LangfuseConfig) -> LangfuseClientProtocol | None:
    try:
        from langfuse import Langfuse
    except ImportError:
        return None
    try:
        sdk_client = Langfuse(
            public_key=config.public_key,
            secret_key=config.secret_key,
            host=config.base_url,
        )
    except Exception:
        return None
    return _SDKLangfuseClient(sdk_client)


class _SDKLangfuseClient:
    def __init__(self, sdk_client: Any) -> None:
        self._sdk_client = sdk_client
        self._root_observations: dict[str, Any] = {}

    def create_trace(self, payload: dict[str, Any]) -> dict[str, Any]:
        trace_id = self._normalize_trace_id(payload.get("trace_id"))
        root = self._sdk_client.start_observation(
            trace_context={"trace_id": trace_id} if trace_id else None,
            name=str(payload.get("name") or "runtime.turn"),
            as_type="span",
            input=payload.get("input_text"),
            metadata=self._build_metadata(payload),
        )
        resolved_trace_id = str(getattr(root, "trace_id", None) or trace_id)
        self._root_observations[resolved_trace_id] = root
        return {
            "trace_id": resolved_trace_id,
            "url": _normalize_url(
                self._sdk_client.get_trace_url(trace_id=resolved_trace_id)
            ),
        }

    def record_generation(self, payload: dict[str, Any]) -> None:
        parent = self._root_observations.get(str(payload.get("trace_id") or ""))
        creator = parent if parent is not None else self._sdk_client
        observation = creator.start_observation(
            name=str(payload.get("name") or "llm"),
            as_type="generation",
            input=payload.get("input_payload"),
            output=payload.get("output_payload"),
            metadata=self._build_metadata(payload),
            model=_normalize_env(payload.get("model")),
            usage_details=self._normalize_usage(payload.get("usage")),
        )
        observation.end()

    def record_tool_span(self, payload: dict[str, Any]) -> None:
        parent = self._root_observations.get(str(payload.get("trace_id") or ""))
        creator = parent if parent is not None else self._sdk_client
        observation = creator.start_observation(
            name=str(payload.get("name") or "tool.call"),
            as_type="tool",
            input=payload.get("tool_payload"),
            output=payload.get("tool_result"),
            metadata=self._build_metadata(payload),
        )
        observation.end()

    def finalize_trace(self, payload: dict[str, Any]) -> None:
        trace_id = str(payload.get("trace_id") or "")
        root = self._root_observations.pop(trace_id, None)
        if root is None:
            return
        usage_details = self._normalize_usage(payload.get("usage"))
        metadata = self._build_metadata(payload)
        if usage_details is not None:
            metadata["cumulative_usage"] = dict(usage_details)
        root.update(
            output=payload.get("final_text"),
            metadata=metadata,
            usage_details=usage_details,
        )
        root.end()

    def flush(self) -> None:
        self._sdk_client.flush()

    def shutdown(self) -> None:
        self._sdk_client.shutdown()

    def _build_metadata(self, payload: dict[str, Any]) -> dict[str, Any]:
        metadata = dict(payload.get("metadata") or {})
        for key in ("status", "latency_ms", "error_code", "total_ms", "tool_name"):
            value = payload.get(key)
            if value is not None:
                metadata[key] = value
        tags = payload.get("tags")
        if tags:
            metadata["tags"] = list(tags)
        provider = payload.get("provider")
        if provider is not None:
            metadata["provider"] = provider
        return metadata

    def _normalize_usage(self, usage: Any) -> dict[str, int] | None:
        if not isinstance(usage, dict):
            return None
        normalized: dict[str, int] = {}
        for key, value in usage.items():
            if isinstance(value, bool):
                continue
            if isinstance(value, (int, float)):
                normalized[str(key)] = int(value)
        return normalized or None

    def _normalize_trace_id(self, value: Any) -> str:
        trace_id = str(value or "").strip().lower()
        if len(trace_id) == 32 and all(char in "0123456789abcdef" for char in trace_id):
            return trace_id
        create_trace_id = getattr(self._sdk_client, "create_trace_id", None)
        if callable(create_trace_id):
            return str(create_trace_id(seed=str(value or "")))
        return trace_id
