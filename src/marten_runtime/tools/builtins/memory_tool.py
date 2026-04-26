from __future__ import annotations

import re

from marten_runtime.memory.service import ThinMemoryService


def run_memory_tool(
    payload: dict,
    *,
    memory_service: ThinMemoryService,
    tool_context: dict | None = None,
) -> dict:
    action = str(payload.get("action", "get")).strip().lower() or "get"
    message = str((tool_context or {}).get("message") or "").strip()
    user_id = str((tool_context or {}).get("user_id") or "").strip()
    if not memory_service.has_stable_user_id(user_id):
        return {
            "action": action,
            "ok": True,
            "available": False,
            "user_id": "",
            "memory_text": "",
            "rendered_memory": None,
        }
    if action == "get":
        document = memory_service.load(user_id)
    elif action == "append":
        _require_explicit_memory_intent(action, message)
        document = memory_service.append(
            user_id,
            section=str(payload.get("section", "")).strip(),
            content=str(payload.get("content", "")).strip(),
        )
    elif action == "replace":
        _require_explicit_memory_intent(action, message)
        document = memory_service.replace(
            user_id,
            section=str(payload.get("section", "")).strip(),
            content=str(payload.get("content", "")).strip(),
        )
    elif action == "delete":
        _require_explicit_memory_intent(action, message)
        document = memory_service.delete(
            user_id,
            section=str(payload.get("section", "")).strip(),
            content=(
                str(payload.get("content", "")).strip()
                if str(payload.get("content", "")).strip()
                else None
            ),
        )
    else:
        raise ValueError("unsupported memory action")
    return {
        "action": action,
        "ok": True,
        "available": True,
        "user_id": user_id,
        "memory_text": document.text,
        "rendered_memory": memory_service.render_prompt_memory(user_id),
        "sections": document.sections,
    }


def _require_explicit_memory_intent(action: str, message: str) -> None:
    if _has_explicit_memory_intent(action, message):
        return
    raise ValueError("explicit user memory intent is required for memory writes")


def _has_explicit_memory_intent(action: str, message: str) -> bool:
    normalized = " ".join(str(message).lower().split())
    if not normalized:
        return False
    remember_patterns = (
        r"\bremember (this|that)\b",
        r"\bsave this to memory\b",
        r"\bstore this in memory\b",
        r"\bwrite this into memory\b",
        r"\badd this to memory\b",
        r"\bupdate memory\b",
        r"\breplace memory\b",
        r"^(请)?记住[:：,\s]",
        r"记住这个",
        r"记住这件事",
        r"记住这一点",
        r"写入记忆",
        r"写进记忆",
        r"存到记忆",
        r"保存到记忆",
        r"更新记忆",
        r"修改记忆",
    )
    delete_patterns = (
        r"\bdelete this memory\b",
        r"\bremove this from memory\b",
        r"\bforget this\b",
        r"\bclear memory\b",
        r"\bdelete memory\b",
        r"删除记忆",
        r"移除记忆",
        r"清除记忆",
        r"忘掉这个",
        r"忘记这件事",
        r"^(请)?忘记[:：,\s]",
    )
    if action == "delete":
        return any(re.search(pattern, normalized) for pattern in delete_patterns)
    return any(re.search(pattern, normalized) for pattern in remember_patterns)
