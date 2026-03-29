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
    replay = replayable[-limit:]
    if len(replay) == limit and replay and replay[0].role == "assistant":
        start_index = len(replayable) - len(replay)
        if start_index > 0 and replayable[start_index - 1].role == "user":
            replay = [replayable[start_index - 1], *replay[:-1]]
    return replay
