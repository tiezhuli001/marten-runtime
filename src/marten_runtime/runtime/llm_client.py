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
        if request.tool_result is None and "time" in request.available_tools and "time" in request.message.lower():
            return LLMReply(tool_name="time", tool_payload={"timezone": "UTC"})
        if request.tool_result is None and "mock_search" in request.available_tools and "search" in request.message.lower():
            return LLMReply(tool_name="mock_search", tool_payload={"query": request.message})
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
    req = urllib_request.Request(url, data=payload, headers=headers, method="POST")
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
                        "parameters": {"type": "object"},
                    },
                }
                for tool_name in request.available_tools
            ]
            body["tool_choice"] = "auto"
        return body

    def _build_messages(self, request: LLMRequest) -> list[dict]:
        messages: list[dict] = []
        if request.system_prompt:
            messages.append({"role": "system", "content": request.system_prompt})
        if request.skill_heads_text:
            messages.append({"role": "system", "content": request.skill_heads_text})
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
        return messages

    def _parse_reply(self, payload: dict) -> LLMReply:
        message = payload["choices"][0]["message"]
        tool_calls = message.get("tool_calls", [])
        if tool_calls:
            function = tool_calls[0]["function"]
            arguments = function.get("arguments", "{}")
            parsed_arguments = json.loads(arguments) if isinstance(arguments, str) else arguments
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
    if profile.provider == "openai":
        api_key_env = profile.api_key_env or "OPENAI_API_KEY"
        api_key = env.get(api_key_env)
        if api_key:
            return OpenAIChatLLMClient(
                api_key=api_key,
                model=profile.model,
                profile_name=profile_name,
                base_url=_resolve_base_url(profile=profile, env=env),
                transport=transport,
            )
        return DemoLLMClient(
            provider_name="demo-fallback",
            model_name=f"{profile.provider}:{profile.model}",
            profile_name=profile_name,
        )
    return DemoLLMClient(
        provider_name="demo-fallback",
        model_name=f"{profile.provider}:{profile.model}",
        profile_name=profile_name,
    )
