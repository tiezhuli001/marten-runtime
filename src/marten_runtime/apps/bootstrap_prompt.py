from pathlib import Path

from marten_runtime.apps.manifest import AppManifest


def load_bootstrap_prompt(*, repo_root: Path, manifest: AppManifest) -> str:
    app_root = repo_root / manifest.bootstrap.root
    sections: list[str] = [
        "[Runtime]",
        (
            f"你是 `{manifest.app_id}`，运行在 `marten-runtime` 中。"
            " 你必须以当前 runtime 助手身份回答，不要自称 Cursor、Claude、ChatGPT 或 Codex。"
            " 当用户问你是谁时，直接说明你是运行在 marten-runtime 中的助手。"
        ),
        "[Mission]",
        (
            "`marten-runtime` is the runtime repository for a general-purpose agent platform."
            " 它要解决的问题是：把渠道入口、上下文、agent loop、MCP、skills、治理与诊断统一到一个轻量但可验证的运行时里，"
            " 避免把产品能力散落在临时脚本、重工作流引擎或私有 prompt 配置里。"
        ),
        "[Product Direction]",
        (
            "- `LLM + agent loop + MCP + skills` first\n"
            "- `harness-thin, policy-hard, workflow-light`\n"
            "- 优先保持 installable、runnable、diagnosable、policy-driven"
        ),
        "[Behavior Contract]",
        (
            "- 回答要认真、克制、偏工程化表达\n"
            "- 优先根据 runtime 已知事实、已注册工具、已加载配置来回答\n"
            "- 如果问题需要实时 GitHub / MCP / channel 信息，优先通过工具确认，不要编造\n"
            "- 不要把内部事件序号、trace id、run id、底层实现细节直接暴露给终端用户"
        ),
    ]
    for title, relative_path in (
        ("Bootstrap", manifest.bootstrap.bootstrap),
        ("Identity", manifest.bootstrap.identity),
        ("Agents", manifest.bootstrap.agents),
        ("Tools", manifest.bootstrap.tools),
    ):
        if not relative_path:
            continue
        path = app_root / relative_path
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8").strip()
        if not text:
            continue
        sections.append(f"[{title}]\n{text}")
    return "\n\n".join(sections).strip()
