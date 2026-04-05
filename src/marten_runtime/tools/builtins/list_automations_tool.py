from __future__ import annotations

from marten_runtime.data_access.adapter import DomainDataAdapter
from marten_runtime.tools.builtins.automation_view import present_automation, sort_presented_automations


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
    presented = sort_presented_automations([present_automation(item) for item in items])
    return {"ok": True, "items": presented, "count": len(presented)}
