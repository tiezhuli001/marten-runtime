from __future__ import annotations

from datetime import datetime, timezone

from marten_runtime.subagents.models import SUBAGENT_TERMINAL_STATUSES, SubagentTask


class InMemorySubagentStore:
    def __init__(self) -> None:
        self._items: dict[str, SubagentTask] = {}

    def create(self, **kwargs) -> SubagentTask:  # noqa: ANN003
        task = SubagentTask(**kwargs)
        self._items[task.task_id] = task
        return task

    def get(self, task_id: str) -> SubagentTask:
        return self._items[task_id]

    def list_tasks(self) -> list[SubagentTask]:
        return list(self._items.values())

    def mark_running(self, task_id: str) -> SubagentTask:
        task = self._items[task_id]
        if task.status != "queued":
            raise ValueError(f"task {task_id} is not queued")
        task.status = "running"
        task.started_at = datetime.now(timezone.utc)
        return task

    def attach_child_run(self, task_id: str, child_run_id: str) -> SubagentTask:
        task = self._items[task_id]
        task.child_run_id = child_run_id
        return task

    def mark_succeeded(self, task_id: str) -> SubagentTask:
        return self._mark_terminal(task_id, "succeeded")

    def mark_failed(self, task_id: str) -> SubagentTask:
        return self._mark_terminal(task_id, "failed")

    def mark_cancelled(self, task_id: str) -> SubagentTask:
        return self._mark_terminal(task_id, "cancelled")

    def mark_timed_out(self, task_id: str) -> SubagentTask:
        return self._mark_terminal(task_id, "timed_out")

    def set_terminal_payload(
        self,
        task_id: str,
        *,
        result_summary: str | None = None,
        error_text: str | None = None,
    ) -> SubagentTask:
        task = self._items[task_id]
        if task.status not in SUBAGENT_TERMINAL_STATUSES:
            raise ValueError(f"task {task_id} is not terminal")
        task.result_summary = result_summary
        task.error_text = error_text
        return task

    def _mark_terminal(self, task_id: str, status: str) -> SubagentTask:
        task = self._items[task_id]
        if task.status in SUBAGENT_TERMINAL_STATUSES:
            return task
        task.status = status
        task.finished_at = datetime.now(timezone.utc)
        return task
