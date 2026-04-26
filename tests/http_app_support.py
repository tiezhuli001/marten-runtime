from pathlib import Path
from shutil import copy2, copytree
from tempfile import TemporaryDirectory

from marten_runtime.automation.store import AutomationStore
from marten_runtime.interfaces.http.app import create_app
from marten_runtime.runtime.llm_client import DemoLLMClient
from tests.support.event_loop import close_idle_event_loop


REPO_ROOT = Path(__file__).resolve().parents[1]


def _write_test_repo(root: Path) -> None:
    copytree(REPO_ROOT / "config", root / "config")
    copytree(REPO_ROOT / "apps", root / "apps")
    copytree(REPO_ROOT / "skills", root / "skills")
    if (REPO_ROOT / "mcps.example.json").exists():
        copy2(REPO_ROOT / "mcps.example.json", root / "mcps.example.json")
        copy2(REPO_ROOT / "mcps.example.json", root / "mcps.json")
    (root / "data").mkdir(parents=True, exist_ok=True)


def build_test_app():
    temp_dir = TemporaryDirectory()
    repo_root = Path(temp_dir.name)
    _write_test_repo(repo_root)
    app = create_app(
        repo_root=repo_root,
        env={"OPENAI_API_KEY": "test-key", "MINIMAX_API_KEY": "test-key"},
        load_env_file=False,
    )
    app.state._temp_dir = temp_dir
    runtime = app.state.runtime
    runtime.runtime_loop.llm = DemoLLMClient(provider_name="test-demo", model_name="test-demo", profile_name="test")
    runtime.llm_client_factory.cache_client("openai_gpt5", runtime.runtime_loop.llm)
    runtime.llm_client_factory.cache_client("minimax_m25", runtime.runtime_loop.llm)
    runtime.llm_client_factory.cache_client("kimi_k2", runtime.runtime_loop.llm)
    runtime.automation_store = AutomationStore()
    runtime.channels_config = runtime.channels_config.model_copy(
        update={
            "feishu": runtime.channels_config.feishu.model_copy(
                update={"enabled": False, "auto_start": False}
            )
        }
    )
    close_idle_event_loop()
    return app
