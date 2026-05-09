from __future__ import annotations

import json
import re
from typing import Literal

from pydantic import BaseModel, Field

FINALIZATION_CONTRACT_BLOCK_MARKER = "finalization_contract"
_FINALIZATION_CONTRACT_BLOCK_RE = re.compile(
    r"\n*```finalization_contract\s*\n(?P<body>[\s\S]*?)\n```\s*$"
)

_RUNTIME_NUMERIC_KINDS = (
    "estimated_usage",
    "effective_window",
    "context_window",
    "usage_percent",
    "replay_budget",
    "remaining_context",
    "remaining_effective",
)


class LiveTimeClaimDraft(BaseModel):
    facets: list[Literal["time", "date", "weekday"]] = Field(default_factory=list)
    year: int | None = None
    month: int | None = None
    day: int | None = None
    weekday: int | None = None
    hour: int | None = None
    minute: int | None = None
    second: int | None = None
    requires_second_precision: bool = False


class RuntimeNumericClaimDraft(BaseModel):
    kind: Literal[
        "estimated_usage",
        "effective_window",
        "context_window",
        "usage_percent",
        "replay_budget",
        "remaining_context",
        "remaining_effective",
    ]
    value: int


class LiveRuntimeContextClaimDraft(BaseModel):
    numeric_claims: list[RuntimeNumericClaimDraft] = Field(default_factory=list)
    status: str | None = None


class SessionSwitchClaimDraft(BaseModel):
    kind: Literal["new", "resume_switch", "resume_noop"]
    session_id: str | None = None


class CurrentSessionIdentityClaimDraft(BaseModel):
    session_id: str


class SpawnSubagentAcceptanceClaimDraft(BaseModel):
    queue_state: Literal["queued", "running"] | None = None
    notify_phrase: Literal["after_start", "after_finish"] | None = None


class MemoryMutationClaimDraft(BaseModel):
    content: str | None = None


class FinalizationContractDraft(BaseModel):
    requires_result_coverage: bool = False
    requires_round_trip_report: bool = False
    live_time: LiveTimeClaimDraft | None = None
    live_runtime_context: LiveRuntimeContextClaimDraft | None = None
    session_switch: SessionSwitchClaimDraft | None = None
    current_session_identity: CurrentSessionIdentityClaimDraft | None = None
    spawn_subagent_acceptance: SpawnSubagentAcceptanceClaimDraft | None = None
    memory_write: MemoryMutationClaimDraft | None = None
    memory_delete: MemoryMutationClaimDraft | None = None


class FinalizationContractRender(BaseModel):
    final_text: str
    contract_draft: FinalizationContractDraft | None = None


def render_finalization_contract_instruction() -> str:
    empty_block = (
        "```finalization_contract\n"
        "{\"requires_result_coverage\": false, \"requires_round_trip_report\": false, \"live_time\": null, "
        "\"live_runtime_context\": null, \"session_switch\": null, \"current_session_identity\": null, "
        "\"spawn_subagent_acceptance\": null, \"memory_write\": null, \"memory_delete\": null}\n```"
    )
    return (
        "Every model-authored final answer must end with a ```finalization_contract``` code block containing JSON. "
        "Put the normal user-visible answer first, then append the code block. "
        "Completion rule: A reply without this block is incomplete, even when the visible answer is only one short sentence. "
        "Short direct answers still need the exact empty block when they make no contract-sensitive claim. "
        "This includes greetings, acknowledgements, and self-introductions. "
        "这也包括首轮直接回答、问候、自我介绍和简短确认句。 "
        f"Example: 你好。\n{empty_block} "
        f"Example: 我是 marten-runtime 中的主执行代理。\n{empty_block} "
        "If the visible answer is only an example/template/copy/reference, keep every claim field null and both requires_* flags false. "
        "If the visible answer claims any current-turn fact or successful action that the host verifies, encode the exact claimed semantics in JSON instead of relying on free text parsing. "
        "Supported claim fields: live_time, live_runtime_context, session_switch, current_session_identity, spawn_subagent_acceptance, memory_write, memory_delete. "
        "For live_time, set facets from [time,date,weekday] and include the exact claimed values; set requires_second_precision=true when the current turn explicitly asked for second-level precision. "
        "For live_runtime_context, encode claimed numeric facts as numeric_claims with kinds from "
        "[estimated_usage,effective_window,context_window,usage_percent,replay_budget,remaining_context,remaining_effective] and set status when claiming a runtime state. "
        "For memory_write/memory_delete, set content to the exact preference or memory content that the visible answer says was written or deleted. "
        "Set requires_result_coverage=true only when the visible answer is explicitly summarizing or covering the current-turn tool results. "
        "Set requires_round_trip_report=true only when the visible answer explicitly reports this turn as a multi-request or multi-tool round trip. "
        "Use this exact empty shape when no contract-sensitive claim is being made: "
        f"{empty_block} "
        "If you also need to append a ```tool_episode_summary``` block, place ```finalization_contract``` before ```tool_episode_summary``` so the summary block stays last."
    )


def parse_finalization_contract_response(text: str) -> FinalizationContractDraft:
    parsed = json.loads(text)
    normalized = {
        "requires_result_coverage": bool(parsed.get("requires_result_coverage", False)),
        "requires_round_trip_report": bool(parsed.get("requires_round_trip_report", False)),
        "live_time": parsed.get("live_time"),
        "live_runtime_context": parsed.get("live_runtime_context"),
        "session_switch": parsed.get("session_switch"),
        "current_session_identity": parsed.get("current_session_identity"),
        "spawn_subagent_acceptance": parsed.get("spawn_subagent_acceptance"),
        "memory_write": parsed.get("memory_write"),
        "memory_delete": parsed.get("memory_delete"),
    }
    return FinalizationContractDraft.model_validate(normalized)


def extract_finalization_contract_block(text: str) -> FinalizationContractRender:
    normalized = str(text or "").strip()
    match = _FINALIZATION_CONTRACT_BLOCK_RE.search(normalized)
    if not match:
        return FinalizationContractRender(final_text=normalized, contract_draft=None)
    visible_text = normalized[: match.start()].rstrip()
    try:
        draft = parse_finalization_contract_response(match.group("body"))
    except Exception:
        draft = None
    return FinalizationContractRender(final_text=visible_text.strip(), contract_draft=draft)


def render_finalization_contract_block(draft: FinalizationContractDraft | None = None) -> str:
    payload = (draft or FinalizationContractDraft()).model_dump(mode="json", exclude_none=False)
    return "```finalization_contract\n" + json.dumps(payload, ensure_ascii=False) + "\n```"
