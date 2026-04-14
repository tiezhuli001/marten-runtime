from __future__ import annotations

import json
import re
from collections.abc import Mapping

from marten_runtime.config.models_loader import ModelProfile
from marten_runtime.runtime.timing import elapsed_ms
from marten_runtime.runtime.usage_models import NormalizedUsage
from marten_runtime.tools.registry import ToolSnapshot


def strip_hidden_reasoning(text: str) -> str:
    cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE)
    return cleaned.strip()


def extract_openai_usage(
    payload: dict,
    *,
    provider_name: str,
    model_name: str,
) -> NormalizedUsage | None:
    usage = payload.get("usage")
    if not isinstance(usage, dict):
        return None
    prompt_tokens = int(usage.get("prompt_tokens", 0) or 0)
    completion_tokens = int(usage.get("completion_tokens", 0) or 0)
    total_tokens = int(usage.get("total_tokens", prompt_tokens + completion_tokens) or 0)
    prompt_details = usage.get("prompt_tokens_details")
    completion_details = usage.get("completion_tokens_details")
    cached_tokens = None
    if isinstance(prompt_details, dict) and prompt_details.get("cached_tokens") is not None:
        cached_tokens = int(prompt_details.get("cached_tokens", 0) or 0)
    reasoning_tokens = None
    if isinstance(completion_details, dict) and completion_details.get("reasoning_tokens") is not None:
        reasoning_tokens = int(completion_details.get("reasoning_tokens", 0) or 0)
    return NormalizedUsage(
        input_tokens=prompt_tokens,
        output_tokens=completion_tokens,
        total_tokens=total_tokens,
        cached_input_tokens=cached_tokens,
        reasoning_output_tokens=reasoning_tokens,
        provider_name=provider_name,
        model_name=model_name,
        raw_usage_payload=usage,
    )


def parse_tool_arguments(arguments: object) -> dict:
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


def collapse_system_messages(messages: list[dict]) -> list[dict]:
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

def resolve_parameters_schema(tool_name: str, tool_snapshot: ToolSnapshot) -> dict[str, object]:
    schema = tool_snapshot.tool_metadata.get(tool_name, {}).get("parameters_schema")
    if isinstance(schema, dict) and schema:
        return schema
    from marten_runtime.runtime.capabilities import get_capability_declarations

    declarations = get_capability_declarations()
    if tool_name in declarations:
        return dict(declarations[tool_name].parameters_schema)
    return {"type": "object"}


def resolve_base_url(*, profile: ModelProfile, env: Mapping[str, str]) -> str | None:
    api_key_env = profile.api_key_env or "OPENAI_API_KEY"
    if api_key_env.endswith("_API_KEY"):
        base_env = f"{api_key_env.removesuffix('_API_KEY')}_API_BASE"
        override = env.get(base_env)
        if override:
            return override
    return profile.base_url
