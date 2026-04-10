from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel

from marten_runtime.config.models_loader import ModelProfile


class CompactionDecision(StrEnum):
    NONE = "none"
    ADVISORY = "advisory"
    PROACTIVE = "proactive"
    REACTIVE = "reactive"


class CompactionSettings(BaseModel):
    context_window_tokens: int = 200_000
    reserve_output_tokens: int = 16_000
    compact_trigger_ratio: float = 0.8

    @property
    def effective_window(self) -> int:
        return max(1, self.context_window_tokens - self.reserve_output_tokens)

    @property
    def advisory_threshold(self) -> int:
        return int(self.effective_window * 0.6)

    @property
    def proactive_threshold(self) -> int:
        return int(self.effective_window * self.compact_trigger_ratio)


def build_compaction_settings(profile: ModelProfile) -> CompactionSettings:
    return CompactionSettings(
        context_window_tokens=(profile.context_window_tokens if profile.context_window_tokens is not None else 200_000),
        reserve_output_tokens=(profile.reserve_output_tokens if profile.reserve_output_tokens is not None else 16_000),
        compact_trigger_ratio=(profile.compact_trigger_ratio if profile.compact_trigger_ratio is not None else 0.8),
    )


def decide_compaction(
    *,
    estimated_tokens: int,
    settings: CompactionSettings,
    has_follow_up_work: bool,
) -> CompactionDecision:
    if estimated_tokens < settings.advisory_threshold:
        return CompactionDecision.NONE
    if estimated_tokens < settings.proactive_threshold:
        return CompactionDecision.ADVISORY
    if has_follow_up_work:
        return CompactionDecision.PROACTIVE
    return CompactionDecision.ADVISORY


def is_reactive_compaction_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return any(
        pattern in message
        for pattern in (
            "prompt too long",
            "maximum context length",
            "context window",
            "context length",
            "too many tokens",
        )
    )


_TERMINAL_KEYWORDS = (
    "已完成",
    "完成了",
    "可以结束",
    "结束吧",
    "thanks",
    "thank you",
    "resolved",
    "done",
    "finished",
)

_CONTINUATION_KEYWORDS = (
    "todo",
    "待办",
    "下一步",
    "接下来",
    "继续",
    "follow-up",
    "remaining",
    "风险",
    "注意",
    "risk",
    "blocker",
)


def has_continuation_demand(*, current_message: str, recent_messages: list[str] | None = None) -> bool:
    lowered = current_message.lower()
    recent = [item.strip() for item in (recent_messages or []) if item and item.strip()]
    haystack = [lowered] + [item.lower() for item in recent]
    if any(keyword in lowered for keyword in _CONTINUATION_KEYWORDS):
        return True
    if any(any(keyword in item for keyword in _CONTINUATION_KEYWORDS) for item in haystack):
        return True
    if any(keyword in lowered for keyword in _TERMINAL_KEYWORDS):
        return False
    return bool(recent)
