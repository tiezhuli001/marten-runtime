from __future__ import annotations

from marten_runtime.runtime.history import InMemoryRunHistory
from marten_runtime.runtime.llm_client import LLMReply, ScriptedLLMClient
from marten_runtime.runtime.loop import RuntimeLoop
from marten_runtime.tools.registry import ToolRegistry


def build_scripted_runtime_loop(
    replies: list[LLMReply] | None = None,
) -> tuple[RuntimeLoop, InMemoryRunHistory]:
    history = InMemoryRunHistory()
    runtime = RuntimeLoop(ScriptedLLMClient(list(replies or [])), ToolRegistry(), history)
    return runtime, history
