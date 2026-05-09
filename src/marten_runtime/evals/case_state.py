from __future__ import annotations

from pathlib import Path

from marten_runtime.evals.models import EvalCaseSpec
from marten_runtime.config.models_loader import resolve_model_profile
from marten_runtime.session.compacted_context import CompactedContext
from marten_runtime.session.models import SessionMessage


def seed_case_state(  # noqa: ANN001
    runtime,
    case: EvalCaseSpec,
    *,
    effective_profile_name: str | None = None,
) -> dict[str, object]:
    case_context: dict[str, object] = {}
    conversation_id = f"eval-{case.case_id}"
    user_id = "eval-user"
    if case.case_id == "session_catalog_cn":
        current = runtime.session_store.create(
            session_id="sess_catalog_current",
            conversation_id=conversation_id,
            config_snapshot_id=runtime.config_snapshot.config_snapshot_id,
            bootstrap_manifest_id=runtime.app_manifest.bootstrap_manifest_id,
            channel_id="http",
            user_id=user_id,
        )
        runtime.session_store.set_catalog_metadata(
            current.session_id,
            user_id=user_id,
            agent_id=case.agent_id,
            session_title="当前评测会话",
            session_preview="当前评测会话预览",
        )
        other = runtime.session_store.create(
            session_id="sess_catalog_other",
            conversation_id="eval-session-catalog-other",
            config_snapshot_id=runtime.config_snapshot.config_snapshot_id,
            bootstrap_manifest_id=runtime.app_manifest.bootstrap_manifest_id,
            channel_id="http",
            user_id=user_id,
        )
        runtime.session_store.set_catalog_metadata(
            other.session_id,
            user_id=user_id,
            agent_id=case.agent_id,
            session_title="另一个历史会话",
            session_preview="另一个历史会话预览",
        )
    if case.case_id == "session_resume_continuity_cn":
        current = runtime.session_store.create(
            session_id="sess_resume_current",
            conversation_id=conversation_id,
            config_snapshot_id=runtime.config_snapshot.config_snapshot_id,
            bootstrap_manifest_id=runtime.app_manifest.bootstrap_manifest_id,
            channel_id="http",
            user_id=user_id,
        )
        runtime.session_store.set_catalog_metadata(
            current.session_id,
            user_id=user_id,
            agent_id=case.agent_id,
            session_title="当前会话",
            session_preview="当前会话预览",
        )
        target = runtime.session_store.create(
            session_id="sess_resume_target",
            conversation_id="eval-resume-target",
            config_snapshot_id=runtime.config_snapshot.config_snapshot_id,
            bootstrap_manifest_id=runtime.app_manifest.bootstrap_manifest_id,
            channel_id="http",
            user_id=user_id,
        )
        runtime.session_store.set_catalog_metadata(
            target.session_id,
            user_id=user_id,
            agent_id=case.agent_id,
            session_title="旧会话",
            session_preview="旧会话预览",
        )
        runtime.session_store.append_message(target.session_id, SessionMessage.user("旧会话背景"))
        runtime.session_store.append_message(target.session_id, SessionMessage.assistant("target-marker 已完成"))
        case_context["target_session_id"] = target.session_id
        case_context["target_marker"] = "旧会话"
    if case.case_id in {"context_compaction_continuity_cn", "proactive_compaction_cn", "session_new_continuity_cn"}:
        _seed_long_history_session(
            runtime,
            case,
            conversation_id,
            user_id,
            effective_profile_name=effective_profile_name,
        )
    _seed_memory_fixture(runtime, case, user_id)
    return case_context


def _seed_long_history_session(  # noqa: ANN001
    runtime,
    case: EvalCaseSpec,
    conversation_id: str,
    user_id: str,
    *,
    effective_profile_name: str | None = None,
) -> None:
    session_id = f"seed_{case.case_id}"
    session = runtime.session_store.create(
        session_id=session_id,
        conversation_id=conversation_id,
        config_snapshot_id=runtime.config_snapshot.config_snapshot_id,
        bootstrap_manifest_id=runtime.app_manifest.bootstrap_manifest_id,
        channel_id="http",
        user_id=user_id,
    )
    runtime.session_store.set_catalog_metadata(
        session.session_id,
        user_id=user_id,
        agent_id=case.agent_id,
        session_title="长线程会话",
        session_preview="长线程会话预览",
    )
    history_items = load_history_fixture(case)
    for item in history_items:
        runtime.session_store.append_message(session.session_id, item)
    if case.case_id == "proactive_compaction_cn":
        target_profile_name, _ = resolve_model_profile(
            runtime.models_config,
            effective_profile_name or case.profile_name,
        )
        profile = runtime.models_config.profiles[target_profile_name]
        runtime.models_config.profiles[target_profile_name] = profile.model_copy(
            update={
                "context_window_tokens": 400,
                "reserve_output_tokens": 50,
                "compact_trigger_ratio": 0.5,
            }
        )
    if case.case_id == "context_compaction_continuity_cn":
        runtime.session_store.set_compacted_context(
            session.session_id,
            CompactedContext(
                compact_id="cmp_eval_context_continuity",
                session_id=session.session_id,
                summary_text=(
                    "当前任务：日报同步告警排查。\n"
                    "当前未完成事项：补失败摘要、核对卡片渲染差异、写出下一步动作。\n"
                    "当前判断：主链路卡片发送正常，失败场景下卡片正文仍缺少失败步骤、调用链位置、受影响模块、回退状态。\n"
                    "继续时直接沿着这三步推进，不要要求用户重复任务名。"
                ),
                source_message_range=[0, max(0, len(history_items) - 1)],
                preserved_tail_user_turns=1,
                trigger_kind="context_pressure_proactive",
            ),
        )


def _seed_memory(runtime, user_id: str, section: str, content: str) -> None:  # noqa: ANN001
    runtime.memory_service.replace(user_id, section=section, content=content)


def _seed_memory_fixture(runtime, case: EvalCaseSpec, user_id: str) -> None:  # noqa: ANN001
    fixture_path = case.resolved_fixtures.get("memory_fixture")
    if not fixture_path:
        return
    current_section = "preferences"
    current_lines: list[str] = []
    for raw_line in Path(fixture_path).read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("# "):
            continue
        if line.startswith("## "):
            if current_lines:
                _seed_memory(runtime, user_id, current_section, "\n".join(current_lines))
            current_section = line[3:].strip() or "preferences"
            current_lines = []
            continue
        if line.startswith("- "):
            current_lines.append(line[2:].strip())
    if current_lines:
        _seed_memory(runtime, user_id, current_section, "\n".join(current_lines))


def load_history_fixture(case: EvalCaseSpec) -> list[SessionMessage]:
    fixture_path = case.resolved_fixtures.get("session_history_fixture")
    if not fixture_path:
        return []
    items: list[SessionMessage] = []
    for raw_line in Path(fixture_path).read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            continue
        role, content = line.split(":", 1)
        normalized_role = role.strip().lower()
        text = content.strip()
        if normalized_role == "user":
            items.append(SessionMessage.user(text))
        elif normalized_role == "assistant":
            items.append(SessionMessage.assistant(text))
        elif normalized_role == "system":
            items.append(SessionMessage.system(text))
    return items
