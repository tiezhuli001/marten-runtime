from marten_runtime.runtime.llm_client import LLMReply
from marten_runtime.tools.registry import ToolRegistry, ToolSnapshot


class ToolCallRejected(Exception):
    def __init__(self, error_code: str) -> None:
        super().__init__(error_code)
        self.error_code = error_code


class ToolExecutionFailed(Exception):
    def __init__(self, message: str, *, cause_error_code: str | None = None) -> None:
        super().__init__(message)
        self.error_code = "TOOL_EXECUTION_FAILED"
        self.cause_error_code = str(cause_error_code or "").strip() or None


def resolve_tool_call(
    reply: LLMReply,
    registry: ToolRegistry,
    tool_snapshot: ToolSnapshot,
    *,
    tool_context: dict | None = None,
) -> dict | None:
    if not reply.tool_name:
        return None
    if not tool_snapshot.allows(reply.tool_name):
        raise ToolCallRejected("TOOL_NOT_ALLOWED")
    if reply.tool_name not in registry.list():
        raise ToolCallRejected("TOOL_NOT_FOUND")
    try:
        return registry.call(reply.tool_name, reply.tool_payload, tool_context=tool_context)
    except Exception as exc:  # pragma: no cover - covered through runtime tests
        raise ToolExecutionFailed(
            str(exc),
            cause_error_code=getattr(exc, "error_code", None),
        ) from exc
