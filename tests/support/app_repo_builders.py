from __future__ import annotations

from pathlib import Path

from marten_runtime.interfaces.http.app import create_app


def write_test_app(
    root: Path,
    app_id: str,
    *,
    prompt_mode: str,
    marker: str,
    default_agent: str = "assistant",
) -> None:
    app_root = root / "apps" / app_id
    app_root.mkdir(parents=True, exist_ok=True)
    (app_root / "app.toml").write_text(
        (
            f'app_id = "{app_id}"\n'
            'app_version = "0.1.0"\n'
            f'default_agent = "{default_agent}"\n'
            f'prompt_mode = "{prompt_mode}"\n'
            'delegation_policy = "isolated_session_only"\n\n'
            '[bootstrap]\n'
            f'root = "apps/{app_id}"\n'
            'agents = "AGENTS.md"\n'
            'identity = "SOUL.md"\n'
            'tools = "TOOLS.md"\n'
            'bootstrap = "BOOTSTRAP.md"\n\n'
            '[skills]\nrequired = []\n\n'
            '[mcp]\nrequired_servers = []\n'
        ),
        encoding="utf-8",
    )
    (app_root / "BOOTSTRAP.md").write_text(f"{marker} bootstrap", encoding="utf-8")
    (app_root / "SOUL.md").write_text(f"{marker} soul", encoding="utf-8")
    (app_root / "AGENTS.md").write_text(f"{marker} agents", encoding="utf-8")
    (app_root / "TOOLS.md").write_text(f"{marker} tools", encoding="utf-8")


def write_test_repo(root: Path) -> None:
    (root / "config").mkdir(parents=True, exist_ok=True)
    (root / "skills").mkdir(parents=True, exist_ok=True)
    (root / "data").mkdir(parents=True, exist_ok=True)
    (root / "config" / "agents.toml").write_text(
        (
            '[agents.assistant]\n'
            'role = "general_assistant"\n'
            'app_id = "example_assistant"\n'
            'allowed_tools = ["automation", "mcp", "runtime", "self_improve", "skill", "time"]\n'
            'prompt_mode = "full"\n'
            'model_profile = "minimax_coding"\n\n'
            '[agents.coding]\n'
            'role = "coding_agent"\n'
            'app_id = "code_assistant"\n'
            'allowed_tools = ["runtime", "skill", "time"]\n'
            'prompt_mode = "child"\n'
            'model_profile = "default"\n'
        ),
        encoding="utf-8",
    )
    (root / "config" / "bindings.toml").write_text(
        (
            '[[bindings]]\n'
            'agent_id = "assistant"\n'
            'channel_id = "http"\n'
            'default = true\n'
        ),
        encoding="utf-8",
    )
    write_test_app(root, "example_assistant", prompt_mode="full", marker="DEFAULT APP", default_agent="assistant")
    write_test_app(root, "code_assistant", prompt_mode="child", marker="CODE APP", default_agent="coding")


def build_repo_backed_test_app(root: Path):
    return create_app(
        repo_root=root,
        env={"MINIMAX_API_KEY": "minimax-test", "OPENAI_API_KEY": "openai-test"},
        load_env_file=False,
        use_compat_json=False,
    )

