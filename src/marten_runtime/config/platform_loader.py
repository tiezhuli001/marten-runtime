import tomllib

from pydantic import BaseModel

from marten_runtime.config.file_resolver import resolve_config_path


class RuntimeConfig(BaseModel):
    mode: str


class ServerConfig(BaseModel):
    host: str
    port: int
    public_base_url: str | None = None


class PlatformConfig(BaseModel):
    runtime: RuntimeConfig
    server: ServerConfig


def load_platform_config(path: str, env: dict[str, str] | None = None) -> PlatformConfig:
    resolved = resolve_config_path(path)
    if resolved is None:
        config = PlatformConfig(
            runtime=RuntimeConfig(mode="rewrite-first"),
            server=ServerConfig(
                host="0.0.0.0",
                port=8000,
                public_base_url="http://127.0.0.1:8000",
            ),
        )
    else:
        data = tomllib.loads(resolved.read_text(encoding="utf-8"))
        config = PlatformConfig(
            runtime=RuntimeConfig(**data["runtime"]),
            server=ServerConfig(**data["server"]),
        )
    overrides = env or {}
    host = overrides.get("SERVER_HOST")
    port = overrides.get("SERVER_PORT")
    public_base_url = overrides.get("SERVER_PUBLIC_BASE_URL")
    return config.model_copy(
        update={
            "server": config.server.model_copy(
                update={
                    "host": host or config.server.host,
                    "port": int(port) if port else config.server.port,
                    "public_base_url": public_base_url or config.server.public_base_url,
                }
            )
        }
    )

