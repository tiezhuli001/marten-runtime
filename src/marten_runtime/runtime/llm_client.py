from __future__ import annotations

import json
import os
import re
from collections.abc import Callable, Mapping
from typing import Protocol
from urllib import error, request as urllib_request

from pydantic import BaseModel, Field

from marten_runtime.config.models_loader import ModelProfile
from marten_runtime.runtime.provider_retry import ProviderTransportError, RetryPolicy, with_retry
from marten_runtime.tools.registry import ToolSnapshot


class LLMRequest(BaseModel):
    session_id: str
    trace_id: str
    message: str
    agent_id: str
    app_id: str
    system_prompt: str | None = None
    conversation_messages: list["ConversationMessage"] = Field(default_factory=list)
    working_context: dict[str, object] = Field(default_factory=dict)
    working_context_text: str | None = None
    context_snapshot_id: str | None = None
    skill_snapshot_id: str = "skill_default"
    activated_skill_ids: list[str] = Field(default_factory=list)
    skill_heads_text: str | None = None
    capability_catalog_text: str | None = None
    always_on_skill_text: str | None = None
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


class LLMReply(BaseModel):
    final_text: str | None = None
    tool_name: str | None = None
    tool_payload: dict = Field(default_factory=dict)


class ToolExchange(BaseModel):
    tool_name: str
    tool_payload: dict = Field(default_factory=dict)
    tool_result: dict = Field(default_factory=dict)


class ConversationMessage(BaseModel):
    role: str
    content: str


class LLMClient(Protocol):
    def complete(self, request: LLMRequest) -> LLMReply:
        ...


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
        return self._replies.pop(0)


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


Transport = Callable[[str, dict[str, str], dict], dict]


def _default_transport(url: str, headers: dict[str, str], body: dict) -> dict:
    payload = json.dumps(body).encode("utf-8")
    request_headers = dict(headers)
    request_headers.setdefault("User-Agent", "marten-runtime/0.1")
    req = urllib_request.Request(url, data=payload, headers=request_headers, method="POST")
    try:
        with urllib_request.urlopen(req, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:  # pragma: no cover - exercised through integration later
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"provider_http_error:{exc.code}:{detail}") from exc
    except error.URLError as exc:  # pragma: no cover - exercised through integration later
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

    def complete(self, request: LLMRequest) -> LLMReply:
        payload = with_retry(
            lambda: self.transport(
                f"{self.base_url}/chat/completions",
                {
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                self._build_payload(request),
            ),
            policy=self.retry_policy,
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
        body: dict[str, object] = {
            "model": self.model_name,
            "messages": self._build_messages(request),
        }
        if request.available_tools:
            body["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": tool_name,
                        "description": request.tool_snapshot.tool_metadata.get(tool_name, {}).get("description", ""),
                        "parameters": _tool_parameters_schema(tool_name),
                    },
                }
                for tool_name in request.available_tools
            ]
            body["tool_choice"] = "auto"
        return body

    def _build_messages(self, request: LLMRequest) -> list[dict]:
        messages: list[dict] = []
        is_tool_followup = bool(request.tool_history) or (
            request.tool_result is not None and bool(request.requested_tool_name)
        )
        include_capability_catalog = bool(request.capability_catalog_text) and not is_tool_followup
        if request.system_prompt:
            messages.append({"role": "system", "content": request.system_prompt})
        if request.skill_heads_text and not is_tool_followup:
            messages.append({"role": "system", "content": request.skill_heads_text})
        if include_capability_catalog:
            messages.append({"role": "system", "content": request.capability_catalog_text})
        if request.always_on_skill_text:
            messages.append({"role": "system", "content": request.always_on_skill_text})
        if request.working_context_text:
            messages.append({"role": "system", "content": request.working_context_text})
        for body in request.activated_skill_bodies:
            messages.append({"role": "system", "content": body})
        for item in request.conversation_messages:
            messages.append({"role": item.role, "content": item.content})
        messages.append({"role": "user", "content": request.message})
        tool_history = list(request.tool_history)
        if not tool_history and request.tool_result is not None and request.requested_tool_name:
            tool_history.append(
                ToolExchange(
                    tool_name=request.requested_tool_name,
                    tool_payload=request.requested_tool_payload,
                    tool_result=request.tool_result,
                )
            )
        for index, item in enumerate(tool_history, start=1):
            call_id = f"call_{index}"
            messages.append(
                {
                    "role": "assistant",
                    "tool_calls": [
                        {
                            "id": call_id,
                            "type": "function",
                            "function": {
                                "name": item.tool_name,
                                "arguments": json.dumps(item.tool_payload, ensure_ascii=True),
                            },
                        }
                    ],
                }
            )
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call_id,
                    "content": json.dumps(item.tool_result, ensure_ascii=True),
                }
            )
        return _collapse_system_messages(messages)

    def _parse_reply(self, payload: dict) -> LLMReply:
        message = payload["choices"][0]["message"]
        tool_calls = message.get("tool_calls", [])
        if tool_calls:
            function = tool_calls[0]["function"]
            arguments = function.get("arguments", "{}")
            parsed_arguments = _parse_tool_arguments(arguments)
            return LLMReply(tool_name=function["name"], tool_payload=parsed_arguments)
        content = message.get("content", "")
        if isinstance(content, list):
            final_text = "".join(
                item.get("text", "")
                for item in content
                if isinstance(item, dict)
            )
            return LLMReply(final_text=_strip_hidden_reasoning(final_text))
        return LLMReply(final_text=_strip_hidden_reasoning(str(content)))


def _strip_hidden_reasoning(text: str) -> str:
    cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE)
    return cleaned.strip()


def _parse_tool_arguments(arguments: object) -> dict:
    if arguments is None:
        return {}
    if isinstance(arguments, dict):
        return arguments
    if not isinstance(arguments, str):
        raise ValueError("tool_arguments_invalid_type")
    normalized = arguments.strip()
    if not normalized:
        return {}
    fenced = re.match(r"^```(?:json)?\s*(.*?)\s*```$", normalized, flags=re.DOTALL | re.IGNORECASE)
    if fenced is not None:
        normalized = fenced.group(1).strip()
    if not normalized:
        return {}
    return json.loads(normalized)


def _collapse_system_messages(messages: list[dict]) -> list[dict]:
    system_chunks: list[str] = []
    collapsed: list[dict] = []
    flushed = False

    for item in messages:
        if item.get("role") == "system":
            content = item.get("content")
            if isinstance(content, str) and content.strip():
                system_chunks.append(content)
            continue
        if system_chunks and not flushed:
            collapsed.append({"role": "system", "content": "\n\n".join(system_chunks)})
            flushed = True
        collapsed.append(item)
    if system_chunks and not flushed:
        collapsed.append({"role": "system", "content": "\n\n".join(system_chunks)})
    return collapsed


def _tool_parameters_schema(tool_name: str) -> dict[str, object]:
    if tool_name == "automation":
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["register", "list", "detail", "update", "delete", "pause", "resume"],
                },
                "automation_id": {"type": "string"},
                "include_disabled": {"type": "boolean"},
            },
            "required": ["action"],
            "additionalProperties": True,
        }
    if tool_name == "mcp":
        return {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["list", "detail", "call"]},
                "server_id": {"type": "string"},
                "tool_name": {"type": "string"},
                "query": {"type": "string"},
                "arguments": {"type": "object"},
            },
            "required": ["action"],
            "additionalProperties": True,
        }
    if tool_name == "self_improve":
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "list_candidates",
                        "candidate_detail",
                        "delete_candidate",
                        "summary",
                        "list_evidence",
                        "list_system_lessons",
                        "save_candidate",
                    ],
                },
                "candidate_id": {"type": "string"},
            },
            "required": ["action"],
            "additionalProperties": True,
        }
    if tool_name == "skill":
        return {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["load"]},
                "skill_id": {"type": "string"},
            },
            "required": ["action", "skill_id"],
            "additionalProperties": False,
        }
    if tool_name == "time":
        return {
            "type": "object",
            "properties": {
                "timezone": {"type": "string"},
                "tz": {"type": "string"},
            },
            "additionalProperties": False,
        }
    return {"type": "object"}


def _resolve_base_url(*, profile: ModelProfile, env: Mapping[str, str]) -> str | None:
    api_key_env = profile.api_key_env or "OPENAI_API_KEY"
    if api_key_env.endswith("_API_KEY"):
        base_env = f"{api_key_env.removesuffix('_API_KEY')}_API_BASE"
        override = env.get(base_env)
        if override:
            return override
    return profile.base_url


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
