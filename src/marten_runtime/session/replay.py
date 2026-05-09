from __future__ import annotations

from marten_runtime.session.models import SessionMessage


def replay_session_messages(
    messages: list[SessionMessage],
    *,
    current_message: str | None = None,
    user_turns: int = 8,
    message_count: int | None = None,
) -> list[SessionMessage]:
    replayable = [
        message
        for message in messages
        if message.role in {"user", "assistant"}
        or (message.role == "system" and _is_replayable_system_message(message.content))
    ]
    if replayable and current_message is not None:
        last = replayable[-1]
        if last.role == "user" and last.content == current_message:
            replayable = replayable[:-1]
    if isinstance(message_count, int):
        if message_count <= 0:
            return []
        window = replayable[-message_count:]
    else:
        if user_turns <= 0:
            return []
        window = _recent_user_turn_window(replayable, user_turns)
    if not window:
        return []
    return _trim_noisy_tail(window, len(window))


def _recent_user_turn_window(
    messages: list[SessionMessage],
    user_turns: int,
) -> list[SessionMessage]:
    if user_turns <= 0:
        return []
    selected_start: int | None = None
    turns = 0
    for index in range(len(messages) - 1, -1, -1):
        if messages[index].role != "user":
            continue
        turns += 1
        selected_start = index
        if turns >= user_turns:
            break
    if selected_start is None:
        return []
    return messages[selected_start:]


def _trim_noisy_tail(messages: list[SessionMessage], limit: int) -> list[SessionMessage]:
    if limit <= 0:
        return []
    return list(messages[-limit:])


def _is_noisy_assistant_message(content: str) -> bool:
    del content
    return False


def _is_replayable_system_message(content: str) -> bool:
    normalized = str(content or "").strip().lower()
    return normalized.startswith("subagent task completed:") or normalized.startswith("subagent task failed:") or normalized.startswith("subagent task timed out:") or normalized.startswith("subagent task cancelled:")
