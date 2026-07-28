from pathlib import Path
from shutil import copy2, copytree
from tempfile import TemporaryDirectory
import weakref

from marten_runtime.interfaces.http.app import create_app
from marten_runtime.runtime.llm_client import DemoLLMClient
from tests.support.event_loop import close_idle_event_loop


REPO_ROOT = Path(__file__).resolve().parents[1]

def _write_test_repo(root: Path) -> None:
    copytree(REPO_ROOT / "config", root / "config")
    copytree(REPO_ROOT / "agents", root / "agents")
    copytree(REPO_ROOT / "skills", root / "skills")
    if (REPO_ROOT / "mcps.example.json").exists():
        copy2(REPO_ROOT / "mcps.example.json", root / "mcps.example.json")
        copy2(REPO_ROOT / "mcps.example.json", root / "mcps.json")
    (root / "data").mkdir(parents=True, exist_ok=True)


def _cleanup_test_app(runtime, temp_dir: TemporaryDirectory) -> None:  # noqa: ANN001
    worker = getattr(runtime, "compaction_worker", None)
    if worker is not None:
        try:
            worker.stop()
        except Exception:
            pass
    subagent_service = getattr(runtime, "subagent_service", None)
    if subagent_service is not None:
        try:
            subagent_service.shutdown()
        except Exception:
            pass
    close_idle_event_loop()
    temp_dir.cleanup()


def build_test_app(*, emit_explicit_empty_contract: bool = False, env_overrides: dict[str, str] | None = None):
    temp_dir = TemporaryDirectory()
    repo_root = Path(temp_dir.name)
    _write_test_repo(repo_root)
    runtime_env = {
        "OPENAI_API_KEY": "test-key",
        "MINIMAX_API_KEY": "test-key",
        "MARTEN_REPO_SLUG": "tiezhuli001/marten-runtime",
        "MARTEN_REPO_URL": "https://github.com/tiezhuli001/marten-runtime",
        "MARTEN_REPO_BRANCH": "main",
    }
    runtime_env.update(env_overrides or {})
    app = create_app(
        repo_root=repo_root,
        env=runtime_env,
        load_env_file=False,
    )
    app.state._temp_dir = temp_dir
    runtime = app.state.runtime
    app.state._cleanup_finalizer = weakref.finalize(app, _cleanup_test_app, runtime, temp_dir)
    runtime.runtime_loop.llm = DemoLLMClient(
        provider_name="test-demo",
        model_name="test-demo",
        profile_name="test",
        emit_explicit_empty_contract=emit_explicit_empty_contract,
    )
    runtime.llm_client_factory.cache_client("openai_gpt_5_4", runtime.runtime_loop.llm)
    runtime.llm_client_factory.cache_client("minimax_m2_7_highspeed", runtime.runtime_loop.llm)
    runtime.llm_client_factory.cache_client("kimi_k2", runtime.runtime_loop.llm)
    runtime.channels_config = runtime.channels_config.model_copy(
        update={
            "feishu": runtime.channels_config.feishu.model_copy(
                update={"enabled": False, "auto_start": False}
            )
        }
    )
    close_idle_event_loop()
    return app
