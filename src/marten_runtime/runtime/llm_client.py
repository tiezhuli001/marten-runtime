from __future__ import annotations

import json
import math
import os
import re
from collections.abc import Callable, Mapping
from typing import Protocol
from urllib import error, request as urllib_request

from pydantic import BaseModel, Field

from marten_runtime.config.models_loader import ModelProfile
from marten_runtime.runtime.llm_request_instructions import (
    is_tool_followup_request as _is_tool_followup_request,
    request_specific_instruction as _request_specific_instruction,
    tool_followup_instruction as _tool_followup_instruction,
)
from marten_runtime.runtime.llm_provider_support import (
    collapse_system_messages as _collapse_system_messages,
    elapsed_ms as _elapsed_ms,
    extract_openai_usage as _extract_openai_usage,
    parse_tool_arguments as _parse_tool_arguments,
    resolve_base_url as _resolve_base_url,
    resolve_parameters_schema as _resolve_parameters_schema,
    strip_hidden_reasoning as _strip_hidden_reasoning,
)
from marten_runtime.runtime.provider_retry import (
    ProviderTransportError,
    RetryPolicy,
    normalize_provider_error,
    with_retry,
)
from marten_runtime.runtime.llm_message_support import build_openai_chat_payload
from marten_runtime.runtime.llm_transport_support import (
    invoke_transport as _invoke_transport,
)
from marten_runtime.runtime.token_estimator import estimate_payload_tokens
from marten_runtime.runtime.tool_episode_summary_prompt import (
    ToolEpisodeSummaryDraft,
    extract_tool_episode_summary_block,
)
from marten_runtime.runtime.usage_models import NormalizedUsage
from marten_runtime.runtime.usage_models import (
    ProviderCallAttempt,
    ProviderCallDiagnostics,
)
from marten_runtime.tools.registry import ToolSnapshot


class LLMRequest(BaseModel):
    session_id: str
    trace_id: str
    message: str
    agent_id: str
    app_id: str
    model_name: str | None = None
    tokenizer_family: str | None = None
    system_prompt: str | None = None
    conversation_messages: list["ConversationMessage"] = Field(default_factory=list)
    compact_summary_text: str | None = None
    tool_outcome_summary_text: str | None = None
    working_context: dict[str, object] = Field(default_factory=dict)
    working_context_text: str | None = None
    context_snapshot_id: str | None = None
    skill_snapshot_id: str = "skill_default"
    activated_skill_ids: list[str] = Field(default_factory=list)
    skill_heads_text: str | None = None
    capability_catalog_text: str | None = None
    always_on_skill_text: str | None = None
    channel_protocol_instruction_text: str | None = None
    activated_skill_bodies: list[str] = Field(default_factory=list)
    prompt_mode: str = "full"
    bootstrap_manifest_id: str = "boot_default"
    available_tools: list[str] = Field(default_factory=list)
    tool_snapshot: ToolSnapshot = Field(
        default_factory=lambda: ToolSnapshot(tool_snapshot_id="tool_empty")
    )
    tool_history: list["ToolExchange"] = Field(default_factory=list)
    tool_result: dict | None = None
    requested_tool_name: str | None = None
    requested_tool_payload: dict = Field(default_factory=dict)
    request_kind: str = "conversation"
    summary_input_text: str | None = None
    timeout_seconds_override: float | None = None
    cooperative_stop_event: object | None = None
    cooperative_deadline_monotonic: float | None = None


class LLMReply(BaseModel):
    final_text: str | None = None
    tool_name: str | None = None
    tool_payload: dict = Field(default_factory=dict)
    tool_episode_summary_draft: ToolEpisodeSummaryDraft | None = None
    usage: NormalizedUsage | None = None


class ToolExchange(BaseModel):
    tool_name: str
    tool_payload: dict = Field(default_factory=dict)
    tool_result: dict = Field(default_factory=dict)


class ConversationMessage(BaseModel):
    role: str
    content: str


class LLMClient(Protocol):
    def complete(self, request: LLMRequest) -> LLMReply: ...


class ScriptedLLMClient:
    provider_name: str = "scripted"
    model_name: str = "test-double"

    def __init__(self, replies: list[LLMReply]) -> None:
        self._replies = list(replies)
        self.requests: list[LLMRequest] = []

    def complete(self, request: LLMRequest) -> LLMReply:
        self.requests.append(request)
        if not self._replies:
            raise RuntimeError("scripted llm exhausted")
        reply = self._replies.pop(0)
        if reply.final_text and reply.tool_episode_summary_draft is None:
            parsed = extract_tool_episode_summary_block(reply.final_text)
            return reply.model_copy(
                update={
                    "final_text": parsed.final_text,
                    "tool_episode_summary_draft": parsed.summary_draft,
                }
            )
        return reply


class DemoLLMClient:
    def __init__(
        self,
        *,
        provider_name: str = "demo",
        model_name: str = "demo-local",
        profile_name: str = "demo",
    ) -> None:
        self.provider_name = provider_name
        self.model_name = model_name
        self.profile_name = profile_name

    def complete(self, request: LLMRequest) -> LLMReply:
        if request.tool_result is not None:
            if "iso_time" in request.tool_result:
                return LLMReply(final_text=f"time={request.tool_result['iso_time']}")
            return LLMReply(
                final_text=f"{request.tool_result['tool_name']}={request.tool_result['result_text']}"
            )
        return LLMReply(final_text=request.message)


Transport = Callable[..., dict]




def _default_transport(
    url: str,
    headers: dict[str, str],
    body: dict,
    timeout_seconds: float = 30,
    *,
    stop_event=None,
    deadline_monotonic: float | None = None,
) -> dict:
    del stop_event, deadline_monotonic
    payload = json.dumps(body).encode("utf-8")
    request_headers = dict(headers)
    request_headers.setdefault("User-Agent", "marten-runtime/0.1")
    req = urllib_request.Request(
        url, data=payload, headers=request_headers, method="POST"
    )
    try:
        with urllib_request.urlopen(req, timeout=timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8"))
    except (
        error.HTTPError
    ) as exc:  # pragma: no cover - exercised through integration later
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"provider_http_error:{exc.code}:{detail}") from exc
    except (
        error.URLError
    ) as exc:  # pragma: no cover - exercised through integration later
        raise RuntimeError(f"provider_transport_error:{exc.reason}") from exc


class OpenAIChatLLMClient:
    provider_name: str = "openai"

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        profile_name: str,
        base_url: str | None = None,
        transport: Transport | None = None,
    ) -> None:
        self.api_key = api_key
        self.model_name = model
        self.profile_name = profile_name
        self.base_url = (base_url or "https://api.openai.com/v1").rstrip("/")
        self.transport = transport or _default_transport
        self.retry_policy = RetryPolicy()
        self.interactive_retry_policy = RetryPolicy(
            max_attempts=2, base_backoff_seconds=0.25, max_backoff_seconds=1.0
        )
        self.default_timeout_seconds = 30
        self.interactive_timeout_seconds = 20
        self.interactive_tool_followup_timeout_seconds = 20
        self.last_call_diagnostics: ProviderCallDiagnostics | None = None

    def complete(self, request: LLMRequest) -> LLMReply:
        timeout_seconds = self._timeout_seconds_for(request)
        retry_policy = self._retry_policy_for(request)
        attempts: list[ProviderCallAttempt] = []
        self.last_call_diagnostics = None
        try:
            payload = with_retry(
                lambda: self._invoke_transport(
                    request=request,
                    timeout_seconds=timeout_seconds,
                    attempts=attempts,
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
        self.last_call_diagnostics = ProviderCallDiagnostics(
            request_kind=request.request_kind,
            timeout_seconds=timeout_seconds,
            max_attempts=retry_policy.max_attempts,
            completed=True,
            final_error_code=None,
            attempts=list(attempts),
        )
        try:
            return self._parse_reply(payload)
        except ProviderTransportError:
            raise
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ProviderTransportError(
                "PROVIDER_RESPONSE_INVALID",
                f"provider_response_invalid:{exc}",
            ) from exc

    def _build_payload(self, request: LLMRequest) -> dict:
        return build_openai_chat_payload(self.model_name, request)

    def _timeout_seconds_for(self, request: LLMRequest) -> int:
        if request.timeout_seconds_override is not None:
            return max(1, int(math.ceil(request.timeout_seconds_override)))
        if _is_tool_followup_request(request):
            return self.interactive_tool_followup_timeout_seconds
        if request.request_kind == "interactive":
            return self.interactive_timeout_seconds
        return self.default_timeout_seconds

    def _retry_policy_for(self, request: LLMRequest) -> RetryPolicy:
        if request.request_kind == "interactive":
            return self.interactive_retry_policy
        return self.retry_policy

    def _invoke_transport(
        self,
        *,
        request: LLMRequest,
        timeout_seconds: int,
        attempts: list[ProviderCallAttempt],
    ) -> dict:
        return _invoke_transport(
            transport=self.transport,
            url=f"{self.base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            body=self._build_payload(request),
            timeout_seconds=timeout_seconds,
            attempts=attempts,
            stop_event=request.cooperative_stop_event,
            deadline_monotonic=request.cooperative_deadline_monotonic,
        )

    def _parse_reply(self, payload: dict) -> LLMReply:
        message = payload["choices"][0]["message"]
        usage = _extract_openai_usage(
            payload,
            provider_name=self.provider_name,
            model_name=self.model_name,
        )
        tool_calls = message.get("tool_calls", [])
        if tool_calls:
            function = tool_calls[0]["function"]
            arguments = function.get("arguments", "{}")
            parsed_arguments = _parse_tool_arguments(arguments)
            return LLMReply(
                tool_name=function["name"], tool_payload=parsed_arguments, usage=usage
            )
        content = message.get("content", "")
        if isinstance(content, list):
            final_text = "".join(
                item.get("text", "") for item in content if isinstance(item, dict)
            )
            parsed = extract_tool_episode_summary_block(
                _strip_hidden_reasoning(final_text)
            )
            return LLMReply(
                final_text=parsed.final_text,
                tool_episode_summary_draft=parsed.summary_draft,
                usage=usage,
            )
        parsed = extract_tool_episode_summary_block(
            _strip_hidden_reasoning(str(content))
        )
        return LLMReply(
            final_text=parsed.final_text,
            tool_episode_summary_draft=parsed.summary_draft,
            usage=usage,
        )


def estimate_request_tokens(request: LLMRequest) -> int:
    payload = build_openai_chat_payload(request.model_name or "estimate", request)
    return estimate_payload_tokens(
        payload, tokenizer_family=request.tokenizer_family
    ).input_tokens_estimate


def estimate_request_usage(request: LLMRequest):
    payload = build_openai_chat_payload(request.model_name or "estimate", request)
    return estimate_payload_tokens(payload, tokenizer_family=request.tokenizer_family)


def build_llm_client(
    *,
    profile_name: str,
    profile: ModelProfile,
    env: Mapping[str, str] | None = None,
    transport: Transport | None = None,
) -> LLMClient:
    env = os.environ if env is None else env
    if profile.provider != "openai":
        raise ValueError(f"unsupported_llm_provider:{profile.provider}")
    api_key_env = profile.api_key_env or "OPENAI_API_KEY"
    api_key = env.get(api_key_env)
    if not api_key:
        raise ValueError(f"missing_llm_api_key:{api_key_env}")
    return OpenAIChatLLMClient(
        api_key=api_key,
        model=profile.model,
        profile_name=profile_name,
        base_url=_resolve_base_url(profile=profile, env=env),
        transport=transport,
    )
