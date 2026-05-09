from __future__ import annotations

import time

from fastapi.testclient import TestClient

from marten_runtime.evals.models import EvalCaseSpec

_TERMINAL_STATES = {"succeeded", "failed", "cancelled", "timed_out"}


def collect_subagent_diagnostics(
    client: TestClient,
    *,
    case: EvalCaseSpec,
    active_session_id: str,
    parent_run_ids: list[str],
) -> dict[str, object]:
    parent_run_set = {item for item in parent_run_ids if item}
    await_child_completion = bool(case.grader_case.get("await_child_completion"))
    timeout_ms = int(case.grader_case.get("timeout_ms") or 5000)
    poll_interval_ms = int(case.grader_case.get("poll_interval_ms") or 100)
    deadline = time.time() + (timeout_ms / 1000.0)
    timed_out = False
    listing_payload = fetch_subagent_listing(client)
    relevant = filter_relevant_subagents(listing_payload, active_session_id, parent_run_set)
    while await_child_completion and (
        not relevant or any(str(item.get("status") or "") not in _TERMINAL_STATES for item in relevant)
    ):
        if time.time() >= deadline:
            timed_out = True
            break
        time.sleep(max(0.01, poll_interval_ms / 1000.0))
        listing_payload = fetch_subagent_listing(client)
        relevant = filter_relevant_subagents(listing_payload, active_session_id, parent_run_set)
    tasks = [build_subagent_task_detail(client, item) for item in relevant if str(item.get("task_id") or "")]
    return {
        "listing": listing_payload,
        "tasks": tasks,
        "parent_session": fetch_parent_session(client, active_session_id),
        "timeout": timed_out,
    }


def build_subagent_task_detail(client: TestClient, item: dict[str, object]) -> dict[str, object]:
    task_id = str(item.get("task_id") or "")
    detail_response = client.get(f"/diagnostics/subagent/{task_id}")
    detail = (
        detail_response.json()
        if detail_response.status_code == 200
        else {"task_id": task_id, "http_status": detail_response.status_code}
    )
    child_run_id = str(detail.get("child_run_id") or "")
    if child_run_id:
        child_run_response = client.get(f"/diagnostics/run/{child_run_id}")
        detail["child_run"] = (
            child_run_response.json()
            if child_run_response.status_code == 200
            else {"run_id": child_run_id, "http_status": child_run_response.status_code}
        )
    child_session_id = str(detail.get("child_session_id") or "")
    if child_session_id:
        child_session_response = client.get(f"/diagnostics/session/{child_session_id}")
        detail["child_session"] = (
            child_session_response.json()
            if child_session_response.status_code == 200
            else {"session_id": child_session_id, "http_status": child_session_response.status_code}
        )
    return detail


def fetch_parent_session(client: TestClient, active_session_id: str) -> dict[str, object]:
    if not active_session_id:
        return {}
    parent_session_response = client.get(f"/diagnostics/session/{active_session_id}")
    if parent_session_response.status_code == 200:
        return parent_session_response.json()
    return {"session_id": active_session_id, "http_status": parent_session_response.status_code}


def fetch_subagent_listing(client: TestClient) -> dict[str, object]:
    response = client.get("/diagnostics/subagents")
    if response.status_code != 200:
        return {"items": [], "count": 0, "http_status": response.status_code}
    return response.json()


def filter_relevant_subagents(
    listing_payload: dict[str, object],
    active_session_id: str,
    parent_run_ids: set[str],
) -> list[dict[str, object]]:
    items = []
    for item in list(listing_payload.get("items") or []):
        if not isinstance(item, dict):
            continue
        parent_session_id = str(item.get("parent_session_id") or "")
        parent_run_id = str(item.get("parent_run_id") or "")
        if active_session_id and parent_session_id == active_session_id:
            items.append(item)
            continue
        if parent_run_id and parent_run_id in parent_run_ids:
            items.append(item)
    return items
