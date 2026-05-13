from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from marten_runtime.agents.specs import AgentSpec


@dataclass(frozen=True)
class AgentRuntimeAssets:
    agent_id: str
    asset_root: str
    prompt_manifest_id: str
    system_prompt: str


def load_agent_runtime_assets(*, repo_root: Path, spec: AgentSpec) -> AgentRuntimeAssets:
    return AgentRuntimeAssets(
        agent_id=spec.agent_id,
        asset_root=spec.asset_root,
        prompt_manifest_id=spec.prompt_manifest_id,
        system_prompt=load_agent_system_prompt(repo_root=repo_root, spec=spec),
    )


def load_agent_system_prompt(*, repo_root: Path, spec: AgentSpec) -> str:
    agent_root = repo_root / spec.asset_root
    sections: list[str] = [
        "[Runtime]",
        (
            f"你是 `{spec.agent_id}`，运行在 `marten-runtime` 中。"
            " 你必须以当前 runtime 助手身份回答，不要自称 Cursor、Claude、ChatGPT 或 Codex。"
            " 当用户问你是谁时，直接说明你是运行在 marten-runtime 中的助手。"
        ),
        "[Behavior Contract]",
        (
            "- 回答要认真、克制、偏工程化表达\n"
            "- 优先根据 runtime 已知事实、已注册工具、已加载配置来回答\n"
            "- 如果问题需要实时 GitHub / MCP / channel 信息，优先通过工具确认，不要编造\n"
            "- 不要把内部事件序号、trace id、run id、底层实现细节直接暴露给终端用户"
        ),
        "[Progressive Disclosure Rules]",
        (
            "- 先阅读当前可见的 skill summaries，再决定是否需要更多展开\n"
            "- 只在某个 skill 明显适用且 summary 不足时，再调用 `skill` 加载该 skill 正文\n"
            "- 不要一次加载多个 skill 正文，也不要预先展开所有 skill\n"
            "- 只有在 server、tool 或参数仍不明确时，才先用 `mcp` 查看 list/detail\n"
            "- 如果 capability catalog 已经暴露了精确的 server_id、tool_name 和参数形状，并且用户目标对象已经足够明确，可以直接使用匹配的 `mcp` 调用\n"
            "- 不要假设所有 MCP 工具细节已经默认展开；但也不要在 exact server/tool surface 已经明确时，先做无意义的 list/detail 试探"
        ),
    ]
    for title, relative_path in (
        ("Bootstrap", spec.bootstrap_file),
        ("Identity", spec.identity_file),
        ("Agents", spec.agents_file),
        ("Tools", spec.tools_file),
    ):
        if not relative_path:
            continue
        path = agent_root / relative_path
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8").strip()
        if not text:
            continue
        sections.append(f"[{title}]\n{text}")
    lessons_path = agent_root / "SYSTEM_LESSONS.md"
    if lessons_path.exists():
        lessons_text = lessons_path.read_text(encoding="utf-8").strip()
        if lessons_text:
            sections.append(f"[Runtime Learned Lessons]\n{lessons_text}")
    return "\n\n".join(sections).strip()
