from __future__ import annotations

import inspect
import logging
import threading
import time
from dataclasses import dataclass
from uuid import uuid4

from marten_runtime.agents.specs import AgentSpec
from marten_runtime.channels.feishu.delivery import FeishuDeliveryPayload
from marten_runtime.channels.feishu.usage import build_usage_summary_from_history
from marten_runtime.config.models_loader import resolve_model_profile
from marten_runtime.session.models import SessionMessage
from marten_runtime.subagents.store import InMemorySubagentStore
from marten_runtime.subagents.tool_profiles import (
    PROFILE_ORDER,
    normalize_tool_profile_name,
    resolve_child_allowed_tools,
    resolve_effective_tool_profile,
)

VALID_TOOL_PROFILES = set(PROFILE_ORDER)
logger = logging.getLogger(__name__)


@dataclass
class _ExecutionControl:
    cancel_event: threading.Event
    deadline_monotonic: float | None


class SubagentService:
    def __init__(
        self,
        *,
        session_store,
        run_history,
        tool_registry,
        runtime_loop,
        max_concurrent_subagents: int = 5,
        max_queued_subagents: int = 16,
        subagent_timeout_seconds: int = 300,
        store: InMemorySubagentStore | None = None,
        auto_start_background: bool = False,
        feishu_delivery=None,
        agent_registry=None,
        app_runtimes: dict[str, object] | None = None,
        llm_client_factory=None,
        models_config=None,
        terminal_callback=None,
    ) -> None:
        self.session_store = session_store
        self.run_history = run_history
        self.tool_registry = tool_registry
        self.runtime_loop = runtime_loop
        self.max_concurrent_subagents = max_concurrent_subagents
        self.max_queued_subagents = max_queued_subagents
        self.subagent_timeout_seconds = subagent_timeout_seconds
        self.store = store or InMemorySubagentStore()
        self.auto_start_background = auto_start_background
        self.feishu_delivery = feishu_delivery
        self.agent_registry = agent_registry
        self.app_runtimes = dict(app_runtimes or {})
        self.llm_client_factory = llm_client_factory
        self.models_config = models_config
        self.terminal_callback = terminal_callback
        self._running_tasks: set[str] = set()
        self._background_tasks: dict[str, threading.Thread] = {}
        self._execution_threads: dict[str, threading.Thread] = {}
        self._execution_tokens: dict[str, str] = {}
        self._execution_controls: dict[str, _ExecutionControl] = {}
        self._pending_background_starts: set[str] = set()
        self._lock = threading.RLock()

    def spawn(
        self,
        *,
        task: str,
        label: str | None,
        parent_session_id: str,
        parent_run_id: str,
        parent_agent_id: str,
        app_id: str,
        agent_id: str,
        requested_tool_profile: str = "standard",
        parent_allowed_tools: list[str] | None = None,
        origin_channel_id: str | None = None,
        origin_delivery_target: str | None = None,
        context_mode: str = "brief_only",
        notify_on_finish: bool = True,
        include_parent_session_message: bool = True,
    ) -> dict[str, str]:
        if not task.strip():
            raise ValueError("task must not be empty")
        resolved_agent_id = agent_id
        resolved_app_id = app_id
        if self.agent_registry is not None:
            target = self._resolve_registered_agent(
                requested_agent_id=agent_id,
                fallback_agent_id=parent_agent_id,
            )
            resolved_agent_id = target.agent_id
            resolved_app_id = target.app_id or app_id
        normalized_requested_profile = normalize_tool_profile_name(
            requested_tool_profile
        )
        parent_allowed = list(parent_allowed_tools or ["runtime", "skill", "time"])
        effective_tool_profile = self._resolve_effective_tool_profile(
            normalized_requested_profile,
            parent_allowed,
        )
        with self._lock:
            queued_count = len(
                [item for item in self.store.list_tasks() if item.status == "queued"]
            )
            if queued_count >= self.max_queued_subagents:
                raise ValueError("subagent queue is full")
            child_session_id = f"sess_{uuid4().hex[:8]}"
            child = self.session_store.create_child_session(
                parent_session_id=parent_session_id,
                conversation_id=f"subagent:{uuid4().hex[:8]}",
                session_id=child_session_id,
                agent_id=resolved_agent_id,
                active_agent_id=resolved_agent_id,
            )
            task_record = self.store.create(
                label=(label or task[:40]).strip(),
                parent_session_id=parent_session_id,
                parent_run_id=parent_run_id,
                parent_agent_id=parent_agent_id,
                parent_allowed_tools=parent_allowed,
                origin_channel_id=origin_channel_id,
                origin_delivery_target=origin_delivery_target,
                child_session_id=child.session_id,
                app_id=resolved_app_id,
                agent_id=resolved_agent_id,
                tool_profile=normalized_requested_profile,
                effective_tool_profile=effective_tool_profile,
                context_mode=context_mode,
                task_prompt=task,
                notify_on_finish=notify_on_finish,
                include_parent_session_message=include_parent_session_message,
            )
            queue_state = "queued"
            if self.auto_start_background and self.runtime_loop is not None:
                self._pending_background_starts.add(task_record.task_id)
            if len(self._running_tasks) < self.max_concurrent_subagents:
                queue_state = "running"
                self._running_tasks.add(task_record.task_id)
            return {
                "status": "accepted",
                "task_id": task_record.task_id,
                "child_session_id": child.session_id,
                "effective_tool_profile": effective_tool_profile,
                "queue_state": queue_state,
            }

    def run_next_queued_task(self) -> None:
        queued = next(
            (item for item in self.store.list_tasks() if item.status == "queued"),
            None,
        )
        if queued is None:
            return
        self.run_task_by_id(queued.task_id)

    def run_task_by_id(self, task_id: str) -> None:
        queued = self.store.get(task_id)
        if queued.status != "queued":
            return
        with self._lock:
            if queued.task_id in self._execution_threads:
                return
            if queued.task_id not in self._running_tasks:
                if len(self._running_tasks) >= self.max_concurrent_subagents:
                    return
                self._running_tasks.add(queued.task_id)
            execution_token = uuid4().hex
            self._execution_tokens[queued.task_id] = execution_token
            self._execution_controls[queued.task_id] = _ExecutionControl(
                cancel_event=threading.Event(),
                deadline_monotonic=self._deadline_monotonic(),
            )
        self.store.mark_running(queued.task_id)
        worker = threading.Thread(
            target=self._execute_task,
            args=(queued.task_id, execution_token),
            daemon=True,
        )
        with self._lock:
            self._execution_threads[queued.task_id] = worker
        worker.start()
        if self.subagent_timeout_seconds == 0:
            self.complete_task_timeout(queued.task_id, execution_token=execution_token)
            return
        if self.subagent_timeout_seconds > 0:
            worker.join(timeout=self.subagent_timeout_seconds)
            if worker.is_alive():
                self.complete_task_timeout(
                    queued.task_id,
                    execution_token=execution_token,
                )
            return
        worker.join()

    def complete_task_success(self, task_id: str, summary: str) -> None:
        task = self.store.get(task_id)
        if task.status != "running":
            return task
        task = self.store.mark_succeeded(task_id)
        self.store.set_terminal_payload(task_id, result_summary=summary)
        if task.include_parent_session_message:
            self.session_store.append_message(
                task.parent_session_id,
                SessionMessage.system(
                    f"subagent task completed: {task.label}\nsummary: {summary}"
                ),
            )
        self._deliver_channel_notification(task, status="completed", text=summary)
        self._emit_terminal_callback(task)

    def complete_task_failure(self, task_id: str, error_text: str) -> None:
        task = self.store.get(task_id)
        if task.status != "running":
            return
        task = self.store.mark_failed(task_id)
        self.store.set_terminal_payload(task_id, error_text=error_text)
        if task.include_parent_session_message:
            self.session_store.append_message(
                task.parent_session_id,
                SessionMessage.system(
                    f"subagent task failed: {task.label}\nerror: {error_text}"
                ),
            )
        self._deliver_channel_notification(task, status="failed", text=error_text)
        self._emit_terminal_callback(task)

    def complete_task_timeout(
        self,
        task_id: str,
        *,
        execution_token: str | None = None,
    ):
        task = self.store.get(task_id)
        if task.status != "running":
            return
        if execution_token is not None and not self._is_execution_current(
            task_id,
            execution_token,
        ):
            return task
        was_running = task.status == "running"
        self._signal_stop(task_id)
        self._invalidate_execution(task_id)
        task = self.store.mark_timed_out(task_id)
        if task.include_parent_session_message:
            self.session_store.append_message(
                task.parent_session_id,
                SessionMessage.system(f"subagent task timed out: {task.label}"),
            )
        self._deliver_channel_notification(task, status="timed_out", text="subagent task timed out")
        self._emit_terminal_callback(task)
        if not was_running:
            self._release_task_slot(task_id)
        return task

    def cancel_task(
        self,
        task_id: str,
        *,
        requester_session_id: str | None = None,
        requester_run_id: str | None = None,
    ):
        task = self.store.get(task_id)
        if requester_session_id is not None and task.parent_session_id != requester_session_id:
            raise ValueError("subagent task is not owned by current session")
        if requester_run_id is not None and task.parent_run_id != requester_run_id:
            raise ValueError("subagent task is not owned by current run")
        if task.status in {"cancelled", "succeeded", "failed", "timed_out"}:
            return task
        was_running = task.status == "running"
        self._signal_stop(task_id)
        self._invalidate_execution(task_id)
        task = self.store.mark_cancelled(task_id)
        if task.include_parent_session_message:
            self.session_store.append_message(
                task.parent_session_id,
                SessionMessage.system(f"subagent task cancelled: {task.label}"),
            )
        self._deliver_channel_notification(task, status="cancelled", text="subagent task cancelled")
        self._emit_terminal_callback(task)
        if not was_running:
            self._release_task_slot(task_id)
        return task

    def set_terminal_callback(self, callback) -> None:  # noqa: ANN001
        self.terminal_callback = callback

    def shutdown(self) -> None:
        outstanding = [
            item.task_id
            for item in self.store.list_tasks()
            if item.status in {"queued", "running"}
        ]
        for task_id in outstanding:
            self.cancel_task(task_id)
        threads = list(self._background_tasks.values()) + list(
            self._execution_threads.values()
        )
        for thread in threads:
            thread.join(timeout=1.0)
        with self._lock:
            self._running_tasks.clear()
            self._background_tasks.clear()
            self._execution_threads.clear()
            self._execution_tokens.clear()
            self._execution_controls.clear()
            self._pending_background_starts.clear()

    def _resolve_effective_tool_profile(
        self,
        requested_tool_profile: str,
        parent_allowed_tools: list[str],
    ) -> str:
        requested_tool_profile = normalize_tool_profile_name(requested_tool_profile)
        if requested_tool_profile not in VALID_TOOL_PROFILES:
            raise ValueError(f"unknown tool profile: {requested_tool_profile}")
        return resolve_effective_tool_profile(
            requested_profile=requested_tool_profile,
            parent_allowed_tools=parent_allowed_tools,
        )

    def resolve_child_allowed_tools(
        self,
        *,
        requested_tool_profile: str,
        parent_allowed_tools: list[str],
    ) -> list[str]:
        return resolve_child_allowed_tools(
            requested_profile=requested_tool_profile,
            parent_allowed_tools=parent_allowed_tools,
        )

    def _start_background_task(self, task_id: str) -> None:
        with self._lock:
            if task_id in self._background_tasks or task_id in self._execution_threads:
                return
            thread = threading.Thread(target=self.run_task_by_id, args=(task_id,))
            thread.daemon = True
            self._background_tasks[task_id] = thread
        thread.start()

    def release_deferred_background_starts(self) -> int:
        task_ids: list[str] = []
        with self._lock:
            for item in self.store.list_tasks():
                task_id = item.task_id
                if task_id not in self._pending_background_starts:
                    continue
                self._pending_background_starts.discard(task_id)
                if item.status != "queued":
                    continue
                if task_id in self._running_tasks:
                    task_ids.append(task_id)
                    continue
                if len(self._running_tasks) >= self.max_concurrent_subagents:
                    continue
                self._running_tasks.add(task_id)
                task_ids.append(task_id)
        started = 0
        for task_id in task_ids:
            try:
                task = self.store.get(task_id)
            except KeyError:
                continue
            if task.status != "queued":
                continue
            self._start_background_task(task_id)
            started += 1
        return started

    def _start_next_queued_background_task(self) -> None:
        if not self.auto_start_background or self.runtime_loop is None:
            return
        next_task_id = None
        with self._lock:
            if len(self._running_tasks) >= self.max_concurrent_subagents:
                return
            for item in self.store.list_tasks():
                if item.status != "queued":
                    continue
                if item.task_id in self._running_tasks:
                    continue
                if item.task_id in self._pending_background_starts:
                    continue
                next_task_id = item.task_id
                self._running_tasks.add(next_task_id)
                break
        if next_task_id is not None:
            self._start_background_task(next_task_id)

    def _execute_task(self, task_id: str, execution_token: str) -> None:
        task = self.store.get(task_id)
        try:
            parent_session = self.session_store.get(task.parent_session_id)
            compacted = None
            if task.context_mode == "brief_plus_snapshot":
                compacted = parent_session.latest_compacted_context
            execution_agent = self._resolve_execution_agent(task)
            allowed_tools = self.resolve_child_allowed_tools(
                requested_tool_profile=task.effective_tool_profile,
                parent_allowed_tools=task.parent_allowed_tools,
            )
            agent = execution_agent.model_copy(update={"allowed_tools": allowed_tools})
            control = self._execution_controls.get(task.task_id)
            run_kwargs = {
                "trace_id": f"trace_{task.task_id}",
                "agent": agent,
                "session_messages": [],
                "compacted_context": compacted,
                "request_kind": "subagent",
                "parent_run_id": task.parent_run_id,
            }
            if self.llm_client_factory is not None and self.models_config is not None:
                run_kwargs.update(self._runtime_assets_for_agent(agent))
            optional_kwargs = {
                "session_store": self.session_store,
                "stop_event": control.cancel_event if control is not None else None,
                "deadline_monotonic": control.deadline_monotonic if control is not None else None,
                "timeout_seconds_override": self._timeout_seconds_override(task.task_id),
            }
            signature = inspect.signature(self.runtime_loop.run)
            accepts_kwargs = any(
                parameter.kind == inspect.Parameter.VAR_KEYWORD
                for parameter in signature.parameters.values()
            )
            for key, value in optional_kwargs.items():
                if accepts_kwargs or key in signature.parameters:
                    run_kwargs[key] = value
            events = self.runtime_loop.run(
                task.child_session_id,
                task.task_prompt,
                **run_kwargs,
            )
            if not self._is_execution_current(task_id, execution_token):
                return
            if not events:
                self.complete_task_failure(task.task_id, "subagent emitted no events")
                return
            child_run_id = events[-1].run_id
            self.store.attach_child_run(task.task_id, child_run_id)
            self.session_store.mark_run(
                task.child_session_id,
                child_run_id,
                events[-1].created_at,
            )
            try:
                child_run = self.run_history.get(child_run_id)
            except KeyError:
                child_run = None
            if child_run is not None and child_run.latest_actual_usage is not None:
                self.session_store.set_latest_actual_usage(
                    task.child_session_id,
                    child_run.latest_actual_usage,
                )
            if child_run is not None:
                for summary in child_run.tool_outcome_summaries:
                    self.session_store.append_tool_outcome_summary(
                        task.child_session_id,
                        summary,
                    )
            terminal_event = events[-1]
            terminal_text = str(terminal_event.payload.get("text", "")).strip()
            if terminal_event.event_type == "final":
                final_text = terminal_text or "subagent finished"
                self.complete_task_success(task.task_id, final_text)
                return
            if terminal_event.event_type == "error":
                error_code = str(terminal_event.payload.get("code", "")).strip()
                error_text = terminal_text or error_code or "subagent failed"
                self.complete_task_failure(task.task_id, error_text)
                return
            self.complete_task_failure(task.task_id, "subagent emitted no terminal event")
        except Exception as exc:  # pragma: no cover
            if self._is_execution_current(task_id, execution_token):
                self.complete_task_failure(task.task_id, str(exc))
        finally:
            self._release_task_slot(task_id, execution_token=execution_token)

    def _is_execution_current(self, task_id: str, execution_token: str) -> bool:
        with self._lock:
            return self._execution_tokens.get(task_id) == execution_token

    def _invalidate_execution(self, task_id: str) -> None:
        with self._lock:
            self._execution_tokens.pop(task_id, None)

    def _signal_stop(self, task_id: str) -> None:
        with self._lock:
            control = self._execution_controls.get(task_id)
        if control is not None:
            control.cancel_event.set()

    def _release_task_slot(
        self,
        task_id: str,
        *,
        execution_token: str | None = None,
    ) -> None:
        with self._lock:
            if execution_token is None or self._execution_tokens.get(task_id) == execution_token:
                self._execution_tokens.pop(task_id, None)
            self._running_tasks.discard(task_id)
            self._background_tasks.pop(task_id, None)
            self._execution_threads.pop(task_id, None)
            self._execution_controls.pop(task_id, None)
            self._pending_background_starts.discard(task_id)
            should_start_next = (
                self.auto_start_background
                and len(self._running_tasks) < self.max_concurrent_subagents
            )
        if should_start_next:
            self._start_next_queued_background_task()

    def _deadline_monotonic(self) -> float | None:
        if self.subagent_timeout_seconds <= 0:
            return None
        return time.monotonic() + float(self.subagent_timeout_seconds)

    def _timeout_seconds_override(self, task_id: str) -> float | None:
        with self._lock:
            control = self._execution_controls.get(task_id)
        if control is None or control.deadline_monotonic is None:
            return None
        return max(0.05, control.deadline_monotonic - time.monotonic())

    def _resolve_execution_agent(self, task) -> AgentSpec:  # noqa: ANN001
        if self.agent_registry is None:
            return AgentSpec(
                agent_id=task.agent_id,
                role="subagent_worker",
                app_id=task.app_id,
                allowed_tools=[],
                prompt_mode="subagent",
            )
        target = self._resolve_registered_agent(
            requested_agent_id=task.agent_id,
            fallback_agent_id=task.parent_agent_id,
        )
        return target.model_copy(
            update={
                "app_id": target.app_id or task.app_id,
            }
        )

    def _resolve_registered_agent(
        self,
        *,
        requested_agent_id: str,
        fallback_agent_id: str,
    ) -> AgentSpec:
        try:
            return self.agent_registry.get(requested_agent_id)
        except KeyError:
            logger.warning(
                "subagent requested unknown agent_id=%s; falling back to parent agent_id=%s",
                requested_agent_id,
                fallback_agent_id,
            )
        return self.agent_registry.get(fallback_agent_id)

    def _runtime_assets_for_agent(self, agent: AgentSpec) -> dict[str, object]:
        assets = self.app_runtimes.get(agent.app_id)
        if assets is None:
            return {}
        profile_name = getattr(agent, "model_profile", None)
        _, profile = resolve_model_profile(self.models_config, profile_name)
        return {
            "llm_client": self.llm_client_factory.get(
                profile_name,
                default_client=getattr(self.runtime_loop, "llm", None),
            ),
            "system_prompt": assets.system_prompt,
            "bootstrap_manifest_id": assets.manifest.bootstrap_manifest_id,
            "model_profile_name": profile_name,
            "tokenizer_family": profile.tokenizer_family,
        }

    def _deliver_channel_notification(self, task, *, status: str, text: str) -> None:  # noqa: ANN001
        if not task.notify_on_finish:
            return
        if task.origin_channel_id != "feishu":
            return
        if self.feishu_delivery is None:
            return
        chat_id = str(task.origin_delivery_target or "").strip()
        if not chat_id:
            return
        event_type = "final" if status == "completed" else "error"
        run_id = task.child_run_id or task.parent_run_id
        summary = (
            f"后台任务已完成：{task.label}\n{text}"
            if status == "completed"
            else f"后台任务{status}：{task.label}\n{text}"
        )
        self.feishu_delivery.deliver(
            FeishuDeliveryPayload(
                chat_id=chat_id,
                event_type=event_type,
                event_id=f"evt_subagent_{task.task_id}_{status}",
                run_id=run_id,
                trace_id=f"trace_subagent_notify_{task.task_id}",
                sequence=1,
                text=summary,
                dedupe_key=f"subagent:{task.task_id}:{status}",
                usage_summary=build_usage_summary_from_history(self.run_history, run_id),
            )
        )

    def _emit_terminal_callback(self, task) -> None:  # noqa: ANN001
        if self.terminal_callback is None:
            return
        try:
            self.terminal_callback(task)
        except Exception:  # pragma: no cover - defensive logging path
            logger.exception(
                "subagent terminal callback failed",
                extra={"task_id": getattr(task, "task_id", None)},
            )
