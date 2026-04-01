from __future__ import annotations

from marten_runtime.data_access.adapter import DomainDataAdapter


def run_list_automations_tool(payload: dict, adapter: DomainDataAdapter) -> dict:
    channel = str(payload.get("delivery_channel", "")).strip()
    target = str(payload.get("delivery_target", "")).strip()
    include_disabled = bool(payload.get("include_disabled", False))
    filters: dict[str, object] = {}
    if channel:
        filters["delivery_channel"] = channel
    if target:
        filters["delivery_target"] = target
    if include_disabled:
        filters["include_disabled"] = True
    items = adapter.list_items("automation", filters=filters, limit=100)
    return {"ok": True, "items": items, "count": len(items)}
