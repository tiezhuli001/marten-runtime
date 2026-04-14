from pathlib import Path

from marten_runtime.automation.store import AutomationStore
from marten_runtime.interfaces.http.app import create_app
from marten_runtime.runtime.llm_client import DemoLLMClient
from tests.support.event_loop import close_idle_event_loop


REPO_ROOT = Path(__file__).resolve().parents[1]


def build_test_app():
    app = create_app(
        repo_root=REPO_ROOT,
        env={"MINIMAX_API_KEY": "test-key"},
        load_env_file=False,
        use_compat_json=False,
    )
    runtime = app.state.runtime
    runtime.runtime_loop.llm = DemoLLMClient(provider_name="test-demo", model_name="test-demo", profile_name="test")
    runtime.llm_client_factory.cache_client("default", runtime.runtime_loop.llm)
    runtime.llm_client_factory.cache_client("minimax_coding", runtime.runtime_loop.llm)
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
