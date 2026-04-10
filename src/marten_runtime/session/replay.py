from __future__ import annotations

from marten_runtime.session.models import SessionMessage


def replay_session_messages(
    messages: list[SessionMessage],
    *,
    current_message: str | None = None,
    limit: int = 6,
) -> list[SessionMessage]:
    replayable = [message for message in messages if message.role in {"user", "assistant"}]
    if replayable and current_message is not None:
        last = replayable[-1]
        if last.role == "user" and last.content == current_message:
            replayable = replayable[:-1]
    if limit <= 0:
        return []
    replay = _trim_noisy_tail(replayable, limit)
    if len(replay) == limit and replay and replay[0].role == "assistant":
        start_index = len(replayable) - len(replay)
        if start_index > 0 and replayable[start_index - 1].role == "user":
            replay = [replayable[start_index - 1], *replay[:-1]]
    return replay


def _trim_noisy_tail(messages: list[SessionMessage], limit: int) -> list[SessionMessage]:
    replay: list[SessionMessage] = []
    skip_previous_user = False
    for message in reversed(messages):
        if skip_previous_user and message.role == "user":
            skip_previous_user = False
            continue
        if message.role == "assistant" and _is_noisy_assistant_message(message.content):
            skip_previous_user = True
            continue
        skip_previous_user = False
        replay.append(message)
        if len(replay) >= limit:
            break
    return list(reversed(replay))


def _is_noisy_assistant_message(content: str) -> bool:
    normalized = content.strip()
    return (
        len(normalized) > 240
        or normalized.count("步骤;") >= 8
        or normalized.count("\n") >= 8
        or normalized.count("```") >= 2
    )
