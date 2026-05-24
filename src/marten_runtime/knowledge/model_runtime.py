from __future__ import annotations

import gc
from datetime import datetime, timezone
from typing import Any


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_or_none(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()


class LazyModelState:
    def __init__(self, *, model_id: str, enabled: bool) -> None:
        self.model_id = model_id
        self.enabled = enabled
        self.loaded_at: datetime | None = None
        self.last_used_at: datetime | None = None

    def mark_loaded(self) -> None:
        now = utc_now()
        if self.loaded_at is None:
            self.loaded_at = now
        self.last_used_at = now

    def mark_used(self) -> None:
        self.last_used_at = utc_now()

    def mark_unloaded(self) -> None:
        self.loaded_at = None
        self.last_used_at = None

    def snapshot(self, *, loaded: bool, idle_ttl_seconds: float | None) -> dict[str, object]:
        return {
            "model_id": self.model_id,
            "enabled": self.enabled,
            "status": "loaded" if loaded else "not_loaded",
            "loaded_at": iso_or_none(self.loaded_at if loaded else None),
            "last_used_at": iso_or_none(self.last_used_at if loaded else None),
            "idle_ttl_seconds": idle_ttl_seconds,
        }


def unload_model_object(owner: Any, attr_name: str = "_model") -> bool:
    if getattr(owner, attr_name, None) is None:
        return False
    setattr(owner, attr_name, None)
    gc.collect()
    _clear_accelerator_caches()
    return True


def _clear_accelerator_caches() -> None:
    try:
        import torch  # type: ignore[import-not-found]
    except Exception:
        return
    try:
        if getattr(torch, "cuda", None) is not None and torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        pass
    try:
        mps = getattr(torch, "mps", None)
        if mps is not None and hasattr(mps, "empty_cache"):
            mps.empty_cache()
    except Exception:
        pass
