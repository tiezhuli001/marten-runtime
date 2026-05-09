from __future__ import annotations

from collections.abc import Mapping

MEMORY_INTENT_FIELD = "intent"
MEMORY_WRITE_INTENT = "durable_write"
MEMORY_DELETE_INTENT = "durable_delete"
MEMORY_SOURCE_EXCERPT_FIELD = "source_excerpt"


def normalize_memory_intent_value(value: object) -> str:
    normalized = " ".join(str(value or "").split()).strip().lower()
    return normalized.replace("-", "_")


def _payload_action(payload: Mapping[str, object] | None) -> str:
    return str((payload or {}).get("action") or "").strip().lower()


def has_explicit_memory_write_intent(value: object) -> bool:
    if isinstance(value, Mapping):
        return _payload_action(value) in {"append", "replace"} and normalize_memory_intent_value(
            value.get(MEMORY_INTENT_FIELD)
        ) == MEMORY_WRITE_INTENT
    return normalize_memory_intent_value(value) == MEMORY_WRITE_INTENT


def has_explicit_memory_delete_intent(value: object) -> bool:
    if isinstance(value, Mapping):
        return _payload_action(value) == "delete" and normalize_memory_intent_value(
            value.get(MEMORY_INTENT_FIELD)
        ) == MEMORY_DELETE_INTENT
    return normalize_memory_intent_value(value) == MEMORY_DELETE_INTENT
