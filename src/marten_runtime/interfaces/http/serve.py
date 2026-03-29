import os
from pathlib import Path

import uvicorn

from marten_runtime.config.env_loader import load_repo_env
from marten_runtime.config.platform_loader import PlatformConfig, load_platform_config


def build_server_options(config: PlatformConfig) -> dict[str, int | str]:
    return {
        "host": config.server.host,
        "port": config.server.port,
    }


def main() -> None:
    repo_root = Path(__file__).resolve().parents[4]
    load_repo_env(repo_root)
    config = load_platform_config(str(repo_root / "config/platform.toml"), env=os.environ)
    uvicorn.run(
        "marten_runtime.interfaces.http.app:create_app",
        factory=True,
        **build_server_options(config),
    )


if __name__ == "__main__":
    main()
