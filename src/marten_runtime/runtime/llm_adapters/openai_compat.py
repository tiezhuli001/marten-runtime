from __future__ import annotations

import json
import math
from collections.abc import Callable, Mapping

import httpx

from marten_runtime.config.providers_loader import ProviderConfig
from marten_runtime.runtime.llm_message_support import (
    build_openai_messages,
    build_tool_definitions,
)
from marten_runtime.runtime.llm_provider_support import (
    extract_openai_usage as _extract_openai_usage,
    parse_tool_arguments as _parse_tool_arguments,
    resolve_base_url as _resolve_base_url,
    strip_hidden_reasoning as _strip_hidden_reasoning,
)
from marten_runtime.runtime.llm_request_instructions import (
    is_tool_followup_request as _is_tool_followup_request,
    should_use_wider_interactive_timeout as _should_use_wider_interactive_timeout,
)
from marten_runtime.runtime.llm_transport_support import (
    invoke_transport as _invoke_transport,
)
from marten_runtime.runtime.provider_retry import (
    ProviderTransportError,
    RetryPolicy,
    normalize_provider_error,
    with_retry,
)
from marten_runtime.runtime.tool_episode_summary_prompt import (
    extract_tool_episode_summary_block,
)
from marten_runtime.runtime.usage_models import (
    ProviderCallAttempt,
    ProviderCallDiagnostics,
)

Transport = Callable[..., dict]


def _default_transport() -> Transport:
    from marten_runtime.runtime.llm_client import _default_transport as transport

    return transport


def _llm_reply(**kwargs):
    from marten_runtime.runtime.llm_client import LLMReply

    return LLMReply(**kwargs)


class OpenAICompatLLMClient:
    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        profile_name: str,
        provider_name: str = "openai",
        provider: ProviderConfig | None = None,
        env: Mapping[str, str] | None = None,
        transport: Transport | None = None,
    ) -> None:
        self.api_key = api_key
        self.model_name = model
        self.profile_name = profile_name
        self.provider_name = provider_name
        self.provider = provider or ProviderConfig(
            adapter="openai_compat",
            base_url="https://api.openai.com/v1",
            api_key_env="OPENAI_API_KEY",
            supports_responses_api=True,
            supports_responses_streaming=True,
            supports_chat_completions=True,
        )
        self.env = dict(env or {})
        self.base_url = (
            _resolve_base_url(provider=self.provider, env=self.env)
            or self.provider.base_url
        ).rstrip("/")
        self.transport = transport or _default_transport()
        self._uses_default_transport = transport is None
        self.retry_policy = RetryPolicy()
        self.interactive_retry_policy = RetryPolicy(
            max_attempts=2, base_backoff_seconds=0.25, max_backoff_seconds=1.0
        )
        self.default_timeout_seconds = 30
        self.interactive_timeout_seconds = 20
        self.interactive_tool_followup_timeout_seconds = 20
        self.last_call_diagnostics: ProviderCallDiagnostics | None = None

    def complete(self, request) -> object:
        timeout_seconds = self._timeout_seconds_for(request)
        retry_policy = self._retry_policy_for(request)
        attempts: list[ProviderCallAttempt] = []
        self.last_call_diagnostics = None
        use_responses_api = self._should_use_responses_api()
        try:
            payload = with_retry(
                lambda: (
                    self._invoke_responses_transport(
                        request=request,
                        timeout_seconds=timeout_seconds,
                        attempts=attempts,
                    )
                    if use_responses_api
                    else self._invoke_chat_transport(
                        request=request,
                        timeout_seconds=timeout_seconds,
                        attempts=attempts,
                    )
                ),
                policy=retry_policy,
                stop_event=request.cooperative_stop_event,
                deadline_monotonic=request.cooperative_deadline_monotonic,
            )
        except Exception as exc:
            normalized = exc if isinstance(exc, ProviderTransportError) else None
            if normalized is None:
                normalized = normalize_provider_error(exc)
            self.last_call_diagnostics = ProviderCallDiagnostics(
                request_kind=request.request_kind,
                timeout_seconds=timeout_seconds,
                max_attempts=retry_policy.max_attempts,
                completed=False,
                final_error_code=normalized.error_code,
                attempts=list(attempts),
            )
            raise normalized
        try:
            reply = (
                self._parse_responses_reply(payload)
                if use_responses_api
                else self._parse_reply(payload)
            )
            self.last_call_diagnostics = ProviderCallDiagnostics(
                request_kind=request.request_kind,
                timeout_seconds=timeout_seconds,
                max_attempts=retry_policy.max_attempts,
                completed=True,
                final_error_code=None,
                attempts=list(attempts),
            )
            return reply
        except ProviderTransportError as exc:
            self.last_call_diagnostics = ProviderCallDiagnostics(
                request_kind=request.request_kind,
                timeout_seconds=timeout_seconds,
                max_attempts=retry_policy.max_attempts,
                completed=False,
                final_error_code=exc.error_code,
                attempts=list(attempts),
            )
            raise
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ProviderTransportError(
                "PROVIDER_RESPONSE_INVALID",
                f"provider_response_invalid:{exc}",
            ) from exc

    def _timeout_seconds_for(self, request) -> int:
        if request.timeout_seconds_override is not None:
            return max(1, int(math.ceil(request.timeout_seconds_override)))
        if _is_tool_followup_request(request):
            return self.interactive_tool_followup_timeout_seconds
        if request.request_kind == "interactive" and _should_use_wider_interactive_timeout(request):
            return self.default_timeout_seconds
        if request.request_kind == "interactive":
            return self.interactive_timeout_seconds
        return self.default_timeout_seconds

    def _retry_policy_for(self, request) -> RetryPolicy:
        if request.request_kind == "interactive":
            return self.interactive_retry_policy
        return self.retry_policy

    def _should_use_responses_api(self) -> bool:
        if str(self.model_name or "").lower().startswith("gpt-5"):
            if not self.provider.supports_responses_api:
                raise ValueError(
                    f"provider_missing_responses_api_support:{self.provider_name}"
                )
            return True
        if not self.provider.supports_chat_completions:
            raise ValueError(
                f"provider_missing_chat_completions_support:{self.provider_name}"
            )
        return False

    def _request_headers(self) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        headers.update(self.provider.extra_headers)
        for header_name, env_name in self.provider.header_env_map.items():
            value = self.env.get(env_name)
            if value:
                headers[header_name] = value
        return headers

    def _invoke_chat_transport(
        self,
        *,
        request,
        timeout_seconds: int,
        attempts: list[ProviderCallAttempt],
    ) -> dict:
        from marten_runtime.runtime.llm_message_support import build_openai_chat_payload

        return _invoke_transport(
            transport=self.transport,
            url=f"{self.base_url}/chat/completions",
            headers=self._request_headers(),
            body=build_openai_chat_payload(self.model_name, request),
            timeout_seconds=timeout_seconds,
            attempts=attempts,
            stop_event=request.cooperative_stop_event,
            deadline_monotonic=request.cooperative_deadline_monotonic,
        )

    def _invoke_responses_transport(
        self,
        *,
        request,
        timeout_seconds: int,
        attempts: list[ProviderCallAttempt],
    ) -> dict:
        body = self._build_responses_payload(
            request,
            stream=self.provider.supports_responses_streaming,
        )
        transport = self.transport
        if self.provider.supports_responses_streaming and self._uses_default_transport:
            transport = _responses_stream_transport
        return _invoke_transport(
            transport=transport,
            url=f"{self.base_url}/responses",
            headers=self._request_headers(),
            body=body,
            timeout_seconds=timeout_seconds,
            attempts=attempts,
            stop_event=request.cooperative_stop_event,
            deadline_monotonic=request.cooperative_deadline_monotonic,
        )

    def _parse_reply(self, payload: dict):
        message = payload["choices"][0]["message"]
        usage = _extract_openai_usage(
            payload,
            provider_name=self.provider_name,
            model_name=self.model_name,
        )
        tool_calls = message.get("tool_calls", [])
        if tool_calls:
            function = tool_calls[0]["function"]
            return _llm_reply(
                tool_name=function["name"],
                tool_payload=_parse_tool_arguments(function.get("arguments", "{}")),
                usage=usage,
            )
        content = message.get("content", "")
        if isinstance(content, list):
            final_text = "".join(
                str(item.get("text") or "") for item in content if isinstance(item, dict)
            )
            parsed = extract_tool_episode_summary_block(
                _strip_hidden_reasoning(final_text)
            )
            return _llm_reply(
                final_text=parsed.final_text,
                tool_episode_summary_draft=parsed.summary_draft,
                usage=usage,
            )
        visible_text = "" if content is None else str(content)
        parsed = extract_tool_episode_summary_block(
            _strip_hidden_reasoning(visible_text)
        )
        return _llm_reply(
            final_text=parsed.final_text,
            tool_episode_summary_draft=parsed.summary_draft,
            usage=usage,
        )

    def _build_responses_payload(self, request, *, stream: bool) -> dict[str, object]:
        instructions, input_items = _build_responses_instructions_and_input(request)
        body: dict[str, object] = {
            "model": self.model_name,
            "store": False,
            "input": input_items,
            "text": {"format": {"type": "text"}, "verbosity": "medium"},
        }
        if stream:
            body["stream"] = True
        if instructions:
            body["instructions"] = instructions
        tool_definitions = _build_responses_tool_definitions(request)
        if tool_definitions:
            body["tools"] = tool_definitions
            body["tool_choice"] = "auto"
        return body

    def _parse_responses_reply(self, payload: dict):
        _raise_for_responses_error(payload)
        usage = _extract_openai_usage(
            payload,
            provider_name=self.provider_name,
            model_name=self.model_name,
        )
        function_calls = _extract_responses_function_calls(payload)
        if len(function_calls) > 1:
            raise ProviderTransportError(
                "PROVIDER_RESPONSE_INVALID",
                "provider_response_invalid:multiple_function_calls_not_supported",
            )
        if function_calls:
            function = function_calls[0]
            return _llm_reply(
                tool_name=str(function.get("name") or ""),
                tool_payload=_parse_tool_arguments(function.get("arguments", "{}")),
                usage=usage,
            )
        output = payload.get("output")
        if isinstance(output, list):
            text = _extract_responses_output_text(output)
            if text:
                parsed = extract_tool_episode_summary_block(
                    _strip_hidden_reasoning(text)
                )
                return _llm_reply(
                    final_text=parsed.final_text,
                    tool_episode_summary_draft=parsed.summary_draft,
                    usage=usage,
                )
        output_text = _extract_responses_payload_text(payload)
        parsed = extract_tool_episode_summary_block(
            _strip_hidden_reasoning("" if output_text is None else str(output_text))
        )
        if not parsed.final_text and payload.get("status") == "completed" and payload.get("error") is None:
            raise ProviderTransportError(
                "PROVIDER_RESPONSE_INVALID",
                "provider_response_invalid:completed_response_without_visible_output",
            )
        return _llm_reply(
            final_text=parsed.final_text,
            tool_episode_summary_draft=parsed.summary_draft,
            usage=usage,
        )


def _build_responses_instructions_and_input(request) -> tuple[str | None, list[dict[str, object]]]:
    instructions: list[str] = []
    input_items: list[dict[str, object]] = []
    for item in build_openai_messages(request):
        role = str(item.get("role") or "")
        if role == "system":
            content = str(item.get("content") or "").strip()
            if content:
                instructions.append(content)
            continue
        converted = _convert_message_to_responses_input_items(item)
        input_items.extend(converted)
    merged_instructions = "\n\n".join(part for part in instructions if part).strip() or None
    if not input_items:
        input_items.append(
            {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": request.message}],
            }
        )
    return merged_instructions, input_items


def _convert_message_to_responses_input_items(message: dict[str, object]) -> list[dict[str, object]]:
    role = str(message.get("role") or "")
    if role == "user":
        content = str(message.get("content") or "").strip()
        if not content:
            return []
        return [
            {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": content}],
            }
        ]
    if role == "assistant":
        items: list[dict[str, object]] = []
        content = str(message.get("content") or "").strip()
        if content:
            items.append(
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": content}],
                    "status": "completed",
                }
            )
        for index, tool_call in enumerate(message.get("tool_calls") or [], start=1):
            if not isinstance(tool_call, dict):
                continue
            function = tool_call.get("function")
            if not isinstance(function, dict):
                continue
            call_id = str(tool_call.get("id") or f"call_{index}")
            items.append(
                {
                    "type": "function_call",
                    "id": f"fc_{call_id}",
                    "call_id": call_id,
                    "name": str(function.get("name") or ""),
                    "arguments": str(function.get("arguments") or "{}"),
                }
            )
        return items
    if role == "tool":
        content = str(message.get("content") or "").strip()
        if not content:
            return []
        call_id = str(message.get("tool_call_id") or "call_0")
        return [
            {
                "type": "function_call_output",
                "call_id": call_id,
                "output": content,
            }
        ]
    return []


def _extract_responses_output_text(output: list[object]) -> str:
    chunks: list[str] = []
    for item in output:
        if not isinstance(item, dict):
            continue
        if item.get("type") != "message":
            continue
        content = item.get("content")
        if not isinstance(content, list):
            continue
        for part in content:
            if not isinstance(part, dict):
                continue
            part_type = str(part.get("type") or "")
            if part_type in {"output_text", "text"}:
                text = part.get("text")
                if text:
                    chunks.append(str(text))
    return "".join(chunks).strip()


def _extract_responses_payload_text(payload: dict[str, object]) -> str | None:
    output_text = payload.get("output_text")
    if output_text:
        return str(output_text)

    content = payload.get("content")
    if isinstance(content, str) and content.strip():
        return content
    if isinstance(content, list):
        chunks: list[str] = []
        for item in content:
            if isinstance(item, dict):
                text = item.get("text")
                if text:
                    chunks.append(str(text))
        joined = "".join(chunks).strip()
        if joined:
            return joined

    response = payload.get("response")
    if isinstance(response, dict):
        nested = _extract_responses_payload_text(response)
        if nested:
            return nested

    choices = payload.get("choices")
    if isinstance(choices, list) and choices:
        first = choices[0]
        if isinstance(first, dict):
            message = first.get("message")
            if isinstance(message, dict):
                content = message.get("content")
                if isinstance(content, str) and content.strip():
                    return content
                if isinstance(content, list):
                    chunks: list[str] = []
                    for item in content:
                        if isinstance(item, dict):
                            text = item.get("text")
                            if text:
                                chunks.append(str(text))
                    joined = "".join(chunks).strip()
                    if joined:
                        return joined
    return None


def _extract_responses_function_calls(payload: dict[str, object]) -> list[dict[str, object]]:
    output = payload.get("output")
    if not isinstance(output, list):
        return []
    function_calls: list[dict[str, object]] = []
    for item in output:
        if isinstance(item, dict) and item.get("type") == "function_call":
            function_calls.append(item)
    return function_calls


def _raise_for_responses_error(payload: dict[str, object]) -> None:
    error = payload.get("error")
    if error:
        raise _classify_responses_error(
            detail=error,
            status=str(payload.get("status") or "").strip().lower() or None,
        )
    status = str(payload.get("status") or "").strip().lower()
    if status in {"failed", "incomplete", "cancelled"}:
        raise _classify_responses_error(
            detail=payload.get("incomplete_details"),
            status=status,
        )


def _classify_responses_error(
    *,
    detail: object,
    status: str | None,
) -> ProviderTransportError:
    serialized = json.dumps(detail, ensure_ascii=True) if detail is not None else "null"
    code = _extract_responses_http_code(detail)
    error_type = _extract_responses_error_type(detail)
    if code in {401, 403} or error_type in {"authentication_error", "invalid_api_key"}:
        return ProviderTransportError(
            "PROVIDER_AUTH_ERROR",
            f"provider_responses_error:{status or 'error'}:{serialized}",
        )
    if code == 429 or error_type in {"rate_limit_error", "rate_limit_exceeded"}:
        return ProviderTransportError(
            "PROVIDER_RATE_LIMITED",
            f"provider_responses_error:{status or 'error'}:{serialized}",
            retryable=True,
        )
    if code in {502, 503, 504, 529}:
        return ProviderTransportError(
            "PROVIDER_UPSTREAM_UNAVAILABLE",
            f"provider_responses_error:{status or 'error'}:{serialized}",
            retryable=True,
        )
    if status in {"failed", "incomplete", "cancelled"}:
        return ProviderTransportError(
            "PROVIDER_UPSTREAM_UNAVAILABLE",
            f"provider_responses_error:{status}:{serialized}",
            retryable=True,
        )
    return ProviderTransportError(
        "PROVIDER_RESPONSE_INVALID",
        f"provider_response_invalid:responses_error:{serialized}",
    )


def _extract_responses_http_code(detail: object) -> int | None:
    if not isinstance(detail, dict):
        return None
    for key in ("status_code", "http_status", "code"):
        value = detail.get(key)
        if value is None:
            continue
        try:
            return int(value)
        except (TypeError, ValueError):
            continue
    return None


def _extract_responses_error_type(detail: object) -> str | None:
    if not isinstance(detail, dict):
        return None
    error_type = detail.get("type")
    if isinstance(error_type, str) and error_type.strip():
        return error_type.strip().lower()
    return None


def _responses_stream_transport(
    url: str,
    headers: dict[str, str],
    body: dict,
    timeout_seconds: float = 30,
    *,
    stop_event=None,
    deadline_monotonic: float | None = None,
) -> dict:
    del stop_event, deadline_monotonic
    request_headers = dict(headers)
    request_headers.setdefault("User-Agent", "marten-runtime/0.1")
    request_headers.setdefault("Accept", "text/event-stream")
    with httpx.stream(
        "POST",
        url,
        headers=request_headers,
        json=body,
        timeout=timeout_seconds,
    ) as response:
        response.raise_for_status()
        return _consume_responses_sse(response)


def _consume_responses_sse(response: httpx.Response) -> dict:
    payload: dict[str, object] | None = None
    output_items: list[dict[str, object]] = []
    output_text_chunks: list[str] = []
    function_call_buffers: dict[str, dict[str, object]] = {}

    for event in _iter_sse_events(response):
        event_type = str(event.get("type") or "")
        if event_type in {"response.created", "response.in_progress"}:
            candidate = event.get("response")
            if isinstance(candidate, dict):
                payload = dict(candidate)
        elif event_type == "response.output_text.delta":
            delta = event.get("delta")
            if delta:
                output_text_chunks.append(str(delta))
        elif event_type == "response.output_text.done":
            text = event.get("text")
            if text:
                output_text_chunks = [str(text)]
        elif event_type == "response.output_item.added":
            item = event.get("item")
            if isinstance(item, dict) and item.get("type") == "function_call":
                call_id = str(item.get("call_id") or item.get("id") or "")
                if call_id:
                    function_call_buffers[call_id] = dict(item)
        elif event_type == "response.function_call_arguments.delta":
            call_id = str(event.get("call_id") or "")
            if call_id:
                buffer = function_call_buffers.setdefault(call_id, {"call_id": call_id})
                arguments = str(buffer.get("arguments") or "")
                buffer["arguments"] = arguments + str(event.get("delta") or "")
        elif event_type == "response.function_call_arguments.done":
            call_id = str(event.get("call_id") or "")
            if call_id:
                buffer = function_call_buffers.setdefault(call_id, {"call_id": call_id})
                buffer["arguments"] = str(event.get("arguments") or "{}")
        elif event_type == "response.output_item.done":
            item = event.get("item")
            if not isinstance(item, dict):
                continue
            if item.get("type") == "function_call":
                call_id = str(item.get("call_id") or item.get("id") or "")
                merged = dict(item)
                if call_id and call_id in function_call_buffers:
                    merged = {**function_call_buffers[call_id], **merged}
                    merged["arguments"] = str(
                        function_call_buffers[call_id].get("arguments")
                        or item.get("arguments")
                        or "{}"
                    )
                output_items.append(merged)
            else:
                output_items.append(dict(item))
        elif event_type == "response.completed":
            candidate = event.get("response")
            if isinstance(candidate, dict):
                payload = dict(candidate)
        elif event_type in {"response.failed", "error"}:
            raise _classify_responses_error(
                detail=event.get("error") or event,
                status="failed",
            )

    if payload is None:
        raise RuntimeError("provider_response_invalid:responses_stream_missing_completion")
    if output_items:
        payload["output"] = output_items
    if output_text_chunks:
        payload["output_text"] = "".join(output_text_chunks)
    return payload


def _iter_sse_events(response: httpx.Response):
    buffer: list[str] = []
    for raw_line in response.iter_lines():
        line = raw_line.decode("utf-8", "ignore") if isinstance(raw_line, bytes) else str(raw_line)
        if line == "":
            event = _parse_sse_event(buffer)
            buffer = []
            if event is not None:
                yield event
            continue
        buffer.append(line)
    if buffer:
        event = _parse_sse_event(buffer)
        if event is not None:
            yield event


def _parse_sse_event(lines: list[str]) -> dict[str, object] | None:
    data_lines = [line[5:].strip() for line in lines if line.startswith("data:")]
    if not data_lines:
        return None
    data = "\n".join(data_lines).strip()
    if not data or data == "[DONE]":
        return None
    return json.loads(data)


def _build_responses_tool_definitions(request) -> list[dict[str, object]]:
    definitions = build_tool_definitions(request)
    converted: list[dict[str, object]] = []
    for item in definitions:
        function = item.get("function")
        if not isinstance(function, dict):
            continue
        converted.append(
            {
                "type": "function",
                "name": str(function.get("name") or ""),
                "description": str(function.get("description") or ""),
                "parameters": function.get("parameters") or {"type": "object"},
            }
        )
    return converted
