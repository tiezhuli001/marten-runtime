import tomllib

from pydantic import BaseModel, Field

from marten_runtime.config.file_resolver import resolve_config_path


class ChannelConfig(BaseModel):
    enabled: bool


class FeishuWebsocketConfig(BaseModel):
    auto_reconnect: bool = True
    reconnect_count: int = -1
    reconnect_interval_s: int = 5
    ping_interval_s: int = 120


class FeishuChannelConfig(ChannelConfig):
    connection_mode: str = "websocket"
    auto_start: bool = True
    allowed_chat_types: list[str] = Field(default_factory=list)
    allowed_chat_ids: list[str] = Field(default_factory=list)
    websocket: FeishuWebsocketConfig = Field(default_factory=lambda: FeishuWebsocketConfig())
    retry: "FeishuRetryConfig" = Field(default_factory=lambda: FeishuRetryConfig())


class FeishuRetryConfig(BaseModel):
    progress_max_retries: int = 2
    final_max_retries: int = 5
    error_max_retries: int = 5
    base_backoff_seconds: float = 0.25
    max_backoff_seconds: float = 2.0


class ChannelsConfig(BaseModel):
    http: ChannelConfig
    cli: ChannelConfig
    feishu: FeishuChannelConfig


def load_channels_config(path: str) -> ChannelsConfig:
    resolved = resolve_config_path(path)
    if resolved is None:
        data = {
            "http": {"enabled": True},
            "cli": {"enabled": True},
            "feishu": {
                "enabled": False,
                "connection_mode": "websocket",
                "auto_start": False,
                "allowed_chat_types": [],
                "allowed_chat_ids": [],
                "websocket": {},
                "retry": {},
            },
        }
    else:
        data = tomllib.loads(resolved.read_text(encoding="utf-8"))
    feishu = dict(data["feishu"])
    return ChannelsConfig(
        http=ChannelConfig(**data["http"]),
        cli=ChannelConfig(**data["cli"]),
        feishu=FeishuChannelConfig(
            **{key: value for key, value in feishu.items() if key not in {"retry", "websocket"}},
            websocket=FeishuWebsocketConfig(**feishu.get("websocket", {})),
            retry=FeishuRetryConfig(**feishu.get("retry", {})),
        ),
    )
