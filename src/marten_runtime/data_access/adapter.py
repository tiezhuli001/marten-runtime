from __future__ import annotations

from marten_runtime.automation.skill_ids import canonicalize_automation_skill_id
from marten_runtime.data_access.specs import ENTITY_SPECS, EntitySpec
from marten_runtime.automation.store import AutomationStore
from marten_runtime.self_improve.models import LessonCandidate
from marten_runtime.self_improve.sqlite_store import SQLiteSelfImproveStore


class DomainDataAdapter:
    def __init__(
        self,
        *,
        self_improve_store: SQLiteSelfImproveStore,
        automation_store: AutomationStore | None = None,
    ) -> None:
        self.self_improve_store = self_improve_store
        self.automation_store = automation_store

    def list_items(self, entity: str, *, filters: dict, limit: int) -> list[dict]:
        spec = self._get_spec(entity)
        self._validate_filters(spec, filters)
        if entity == "lesson_candidate":
            items = self.self_improve_store.list_candidates(
                agent_id=str(filters.get("agent_id", "assistant")),
                limit=limit,
                status=str(filters["status"]) if "status" in filters else None,
            )
            return [item.model_dump(mode="json") for item in items]
        if entity == "automation":
            store = self._require_automation_store()
            include_disabled = bool(filters.get("include_disabled", False))
            items = store.list_public(include_disabled=include_disabled)
            if "delivery_channel" in filters:
                expected = str(filters["delivery_channel"])
                items = [item for item in items if item.delivery_channel == expected]
            if "delivery_target" in filters:
                expected = str(filters["delivery_target"])
                items = [item for item in items if item.delivery_target == expected]
            if "skill_id" in filters:
                expected = canonicalize_automation_skill_id(str(filters["skill_id"]))
                items = [
                    item
                    for item in items
                    if canonicalize_automation_skill_id(item.skill_id) == expected
                ]
            if "enabled" in filters:
                expected = bool(filters["enabled"])
                items = [item for item in items if item.enabled is expected]
            return [item.model_dump(mode="json") for item in items[:limit]]
        raise KeyError(entity)

    def get_item(self, entity: str, *, item_id: str) -> dict:
        self._get_spec(entity)
        if entity == "lesson_candidate":
            return self.self_improve_store.get_candidate(item_id).model_dump(mode="json")
        if entity == "automation":
            return self._require_automation_store().get(item_id).model_dump(mode="json")
        raise KeyError(entity)

    def create_item(self, entity: str, *, values: dict) -> dict:
        spec = self._get_spec(entity)
        self._validate_values(spec, values, operation="create")
        if entity == "automation":
            store = self._require_automation_store()
            created = store.create_job(values)
            return created.model_dump(mode="json")
        raise KeyError(entity)

    def update_item(self, entity: str, *, item_id: str, values: dict) -> dict:
        spec = self._get_spec(entity)
        self._validate_values(spec, values, operation="update")
        if entity == "automation":
            updated = self._require_automation_store().update(item_id, values)
            return updated.model_dump(mode="json")
        raise KeyError(entity)

    def delete_item(self, entity: str, *, item_id: str) -> dict:
        spec = self._get_spec(entity)
        if not spec.deletable:
            raise KeyError(entity)
        if entity == "lesson_candidate":
            deleted = self.self_improve_store.delete_candidate(item_id)
            return {"ok": deleted, spec.item_id_field: item_id}
        if entity == "automation":
            deleted = self._require_automation_store().delete(item_id)
            return {"ok": deleted, spec.item_id_field: item_id}
        raise KeyError(entity)

    def _get_spec(self, entity: str) -> EntitySpec:
        try:
            return ENTITY_SPECS[entity]
        except KeyError as exc:
            raise KeyError(entity) from exc

    def _validate_filters(self, spec: EntitySpec, filters: dict) -> None:
        for key in filters:
            if key not in spec.allowed_filters:
                raise KeyError(key)

    def _validate_values(self, spec: EntitySpec, values: dict, *, operation: str) -> None:
        allowed_fields = spec.creatable_fields if operation == "create" else spec.updatable_fields
        if not allowed_fields:
            raise KeyError(spec.entity)
        for key in values:
            if key not in allowed_fields:
                raise KeyError(key)

    def _require_automation_store(self) -> AutomationStore:
        if self.automation_store is None:
            raise KeyError("automation")
        return self.automation_store
