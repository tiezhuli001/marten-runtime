from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from typing import Literal, Protocol

import httpx

from pydantic import BaseModel, Field

from marten_runtime.config.models_loader import ModelProfile
from marten_runtime.config.providers_loader import ProvidersConfig
from marten_runtime.runtime.llm_adapters.openai_compat import OpenAICompatLLMClient
from marten_runtime.runtime.llm_message_support import build_openai_chat_payload
from marten_runtime.runtime.provider_registry import resolve_provider_ref
from marten_runtime.runtime.token_estimator import estimate_payload_tokens
from marten_runtime.runtime.finalization_contract_prompt import (
    FinalizationContractDraft,
    extract_finalization_contract_block,
    render_finalization_contract_block,
)
from marten_runtime.runtime.tool_episode_summary_prompt import (
    ToolEpisodeSummaryDraft,
    extract_tool_episode_summary_block,
)
from marten_runtime.tools.registry import ToolSnapshot


class FinalizationEvidenceItem(BaseModel):
    ordinal: int
    tool_name: str
    tool_action: str | None = None
    payload_summary: str | None = None
    result_summary: str
    coverage_tokens: list[str] = Field(default_factory=list)
    required_for_user_request: bool = True
    evidence_source: Literal["tool_result", "loop_meta"] = "tool_result"


class FinalizationEvidenceLedger(BaseModel):
    user_message: str
    tool_call_count: int
    model_request_count: int | None = None
    requires_result_coverage: bool = False
    requires_round_trip_report: bool = False
    items: list[FinalizationEvidenceItem] = Field(default_factory=list)


class LLMRequest(BaseModel):
    session_id: str
    trace_id: str
    message: str
    agent_id: str
    model_name: str | None = None
    tokenizer_family: str | None = None
    system_prompt: str | None = None
    conversation_messages: list["ConversationMessage"] = Field(default_factory=list)
    compact_summary_text: str | None = None
    tool_outcome_summary_text: str | None = None
    memory_text: str | None = None
    working_context: dict[str, object] = Field(default_factory=dict)
    working_context_text: str | None = None
    context_snapshot_id: str | None = None
    skill_snapshot_id: str = "skill_default"
    activated_skill_ids: list[str] = Field(default_factory=list)
    skill_heads_text: str | None = None
    capability_catalog_text: str | None = None
    always_on_skill_text: str | None = None
    channel_protocol_instruction_text: str | None = None
    repository_context_text: str | None = None
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
    finalization_evidence_ledger: FinalizationEvidenceLedger | None = None
    invalid_final_text: str | None = None
    summary_input_text: str | None = None
    timeout_seconds_override: float | None = None
    cooperative_stop_event: object | None = None
    cooperative_deadline_monotonic: float | None = None


class LLMReply(BaseModel):
    final_text: str | None = None
    tool_name: str | None = None
    tool_payload: dict = Field(default_factory=dict)
    tool_episode_summary_draft: ToolEpisodeSummaryDraft | None = None
    finalization_contract_draft: FinalizationContractDraft | None = None
    usage: object | None = None


class ToolFollowupFragment(BaseModel):
    text: str
    source: Literal["tool_result", "loop_meta"]
    tool_name: str | None = None
    safe_for_fallback: bool = True


class ToolFollowupRender(BaseModel):
    terminal_text: str | None = None
    recovery_fragment: ToolFollowupFragment | None = None


class ToolExchange(BaseModel):
    tool_name: str
    tool_payload: dict = Field(default_factory=dict)
    tool_result: dict = Field(default_factory=dict)
    recovery_fragment: ToolFollowupFragment | None = None


class ConversationMessage(BaseModel):
    role: str
    content: str


class LLMClient(Protocol):
    def complete(self, request: LLMRequest) -> LLMReply: ...


class ScriptedLLMClient:
    provider_name: str = "scripted"
    model_name: str = "test-double"

    def __init__(
        self,
        replies: list[LLMReply],
        *,
        session_summary_replies: list[LLMReply] | None = None,
    ) -> None:
        self._replies = list(replies)
        self._session_summary_replies = list(session_summary_replies or [])
        self.requests: list[LLMRequest] = []

    def complete(self, request: LLMRequest) -> LLMReply:
        if request.request_kind == "agent_routing":
            self.requests.append(request)
            return LLMReply(
                tool_name="agent_route",
                tool_payload={"target_agent_id": _test_route_target(request.message)},
            )
        if request.request_kind == "session_summary":
            self.requests.append(request)
            if not self._session_summary_replies:
                raise RuntimeError("scripted session summary llm exhausted")
            return _normalize_reply_contract_metadata(
                request,
                self._session_summary_replies.pop(0),
            )
        self.requests.append(request)
        if not self._replies:
            raise RuntimeError("scripted llm exhausted")
        reply = self._replies.pop(0)
        return _normalize_reply_contract_metadata(request, reply)


class DemoLLMClient:
    def __init__(
        self,
        *,
        provider_name: str = "demo",
        model_name: str = "demo-local",
        profile_name: str = "demo",
        emit_explicit_empty_contract: bool = False,
    ) -> None:
        self.provider_name = provider_name
        self.model_name = model_name
        self.profile_name = profile_name
        self.emit_explicit_empty_contract = emit_explicit_empty_contract

    def complete(self, request: LLMRequest) -> LLMReply:
        if request.request_kind == "agent_routing":
            return LLMReply(
                tool_name="agent_route",
                tool_payload={"target_agent_id": _test_route_target(request.message)},
            )
        if request.tool_result is not None:
            if "iso_time" in request.tool_result:
                return _normalize_reply_contract_metadata(
                    request,
                    LLMReply(
                        final_text=self._render_visible_text(
                            f"time={request.tool_result['iso_time']}"
                        )
                    ),
                )
            return _normalize_reply_contract_metadata(
                request,
                LLMReply(
                    final_text=self._render_visible_text(
                        f"{request.tool_result['tool_name']}={request.tool_result['result_text']}"
                    )
                ),
            )
        return _normalize_reply_contract_metadata(
            request,
            LLMReply(final_text=self._render_visible_text(request.message)),
        )

    def _render_visible_text(self, text: str) -> str:
        if self.emit_explicit_empty_contract:
            return _with_explicit_empty_contract(text)
        return str(text or "").strip()


def _test_route_target(message: str) -> str:
    text = str(message or "").lower()
    bazi_markers = (
        "八字",
        "四柱",
        "农历",
        "子平",
        "盲派",
        "大运",
        "年柱",
        "月柱",
        "日柱",
        "时柱",
    )
    return "bazi" if any(marker in text for marker in bazi_markers) else "main"


def _normalize_reply_contract_metadata(request: LLMRequest, reply: LLMReply) -> LLMReply:
    del request
    if reply.final_text:
        visible_text = str(reply.final_text or "")
        parsed_summary = extract_tool_episode_summary_block(visible_text)
        parsed_contract = extract_finalization_contract_block(parsed_summary.final_text)
        return reply.model_copy(
            update={
                "final_text": parsed_contract.final_text,
                "tool_episode_summary_draft": (
                    reply.tool_episode_summary_draft or parsed_summary.summary_draft
                ),
                "finalization_contract_draft": (
                    parsed_contract.contract_draft or reply.finalization_contract_draft
                ),
            }
        )
    return reply


def _with_explicit_empty_contract(text: str) -> str:
    visible_text = str(text or "").strip()
    if not visible_text:
        return ""
    return f"{visible_text}\n{render_finalization_contract_block()}"


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
    request_headers = dict(headers)
    request_headers.setdefault("User-Agent", "marten-runtime/0.1")
    try:
        response = httpx.post(
            url,
            headers=request_headers,
            json=body,
            timeout=timeout_seconds,
        )
        response.raise_for_status()
        return response.json()
    except httpx.HTTPStatusError as exc:  # pragma: no cover
        detail = exc.response.text
        raise RuntimeError(f"provider_http_error:{exc.response.status_code}:{detail}") from exc
    except httpx.TimeoutException as exc:  # pragma: no cover
        raise TimeoutError(str(exc) or "provider timeout") from exc
    except httpx.HTTPError as exc:  # pragma: no cover
        raise RuntimeError(f"provider_transport_error:{exc}") from exc


OpenAIChatLLMClient = OpenAICompatLLMClient


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
    providers_config: ProvidersConfig,
    env: Mapping[str, str] | None = None,
    transport: Transport | None = None,
) -> LLMClient:
    env = os.environ if env is None else env
    provider = resolve_provider_ref(
        provider_ref=profile.provider_ref,
        providers_config=providers_config,
    )
    if provider.adapter != "openai_compat":
        raise ValueError(f"unsupported_llm_adapter:{provider.adapter}")
    api_key = env.get(provider.api_key_env)
    if not api_key:
        raise ValueError(f"missing_llm_api_key:{provider.api_key_env}")
    return OpenAICompatLLMClient(
        api_key=api_key,
        model=profile.model,
        profile_name=profile_name,
        provider_name=profile.provider_ref,
        provider=provider,
        env=env,
        transport=transport,
    )
