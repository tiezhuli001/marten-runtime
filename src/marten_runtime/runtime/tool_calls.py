from marten_runtime.runtime.llm_client import LLMReply
from marten_runtime.tools.registry import ToolRegistry, ToolSnapshot


class ToolCallRejected(Exception):
    def __init__(self, error_code: str) -> None:
        super().__init__(error_code)
        self.error_code = error_code


def resolve_tool_call(reply: LLMReply, registry: ToolRegistry, tool_snapshot: ToolSnapshot) -> dict | None:
    if not reply.tool_name:
        return None
    if not tool_snapshot.allows(reply.tool_name):
        raise ToolCallRejected("TOOL_NOT_ALLOWED")
    if reply.tool_name not in registry.list():
        raise ToolCallRejected("TOOL_NOT_FOUND")
    return registry.call(reply.tool_name, reply.tool_payload)
