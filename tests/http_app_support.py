import asyncio
from pathlib import Path

from marten_runtime.interfaces.http.app import create_app


REPO_ROOT = Path(__file__).resolve().parents[1]


def build_test_app():
    app = create_app(
        repo_root=REPO_ROOT,
        env={},
        load_env_file=False,
        use_compat_json=False,
    )
    runtime = app.state.runtime
    runtime.channels_config = runtime.channels_config.model_copy(
        update={
            "feishu": runtime.channels_config.feishu.model_copy(
                update={"enabled": False, "auto_start": False}
            )
        }
    )
    _close_idle_event_loop()
    return app


def _close_idle_event_loop() -> None:
    policy = asyncio.get_event_loop_policy()
    try:
        loop = policy.get_event_loop()
    except RuntimeError:
        return
    if loop.is_running() or loop.is_closed():
        return
    loop.close()
    try:
        asyncio.set_event_loop(None)
    except RuntimeError:
        pass
