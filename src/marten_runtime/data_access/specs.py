from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EntitySpec:
    entity: str
    item_id_field: str
    allowed_filters: tuple[str, ...]
    deletable: bool
    creatable_fields: tuple[str, ...] = ()
    updatable_fields: tuple[str, ...] = ()


LESSON_CANDIDATE_SPEC = EntitySpec(
    entity="lesson_candidate",
    item_id_field="candidate_id",
    allowed_filters=("agent_id", "status"),
    creatable_fields=(),
    updatable_fields=(),
    deletable=True,
)

AUTOMATION_SPEC = EntitySpec(
    entity="automation",
    item_id_field="automation_id",
    allowed_filters=(
        "delivery_channel",
        "delivery_target",
        "enabled",
        "include_disabled",
        "skill_id",
    ),
    creatable_fields=(
        "automation_id",
        "name",
        "app_id",
        "agent_id",
        "prompt_template",
        "schedule_kind",
        "schedule_expr",
        "timezone",
        "session_target",
        "delivery_channel",
        "delivery_target",
        "skill_id",
        "enabled",
        "internal",
    ),
    updatable_fields=(
        "name",
        "prompt_template",
        "schedule_kind",
        "schedule_expr",
        "timezone",
        "session_target",
        "delivery_channel",
        "delivery_target",
        "skill_id",
        "enabled",
    ),
    deletable=True,
)


ENTITY_SPECS: dict[str, EntitySpec] = {
    LESSON_CANDIDATE_SPEC.entity: LESSON_CANDIDATE_SPEC,
    AUTOMATION_SPEC.entity: AUTOMATION_SPEC,
}
