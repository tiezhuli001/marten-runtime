from __future__ import annotations

from marten_runtime.knowledge.service import KnowledgeService


_NAMESPACE_ACTIONS = frozenset(
    {
        "ingest_text",
        "ingest_file",
        "ingest_status",
        "cancel_ingest",
        "search",
        "get_chunk",
        "delete_source",
        "reindex",
        "stats",
    }
)


def run_knowledge_tool(
    payload: dict,
    *,
    knowledge_service: KnowledgeService,
    tool_context: dict | None = None,
) -> dict:
    action = str(payload.get("action") or "").strip().lower()
    if not action:
        raise ValueError("action is required")
    namespace = str(payload.get("namespace") or "")
    scope_error = _scope_error(action=action, namespace=namespace, tool_context=tool_context)
    if scope_error is not None:
        return scope_error
    if action == "ingest_text":
        return knowledge_service.ingest_text(namespace=namespace, source=dict(payload.get("source") or {}))
    if action == "ingest_file":
        return knowledge_service.ingest_file(
            namespace=namespace,
            file_path=str(payload.get("file_path") or ""),
            source=dict(payload.get("source") or {}),
        )
    if action == "ingest_status":
        return knowledge_service.ingest_status(namespace=namespace, job_id=str(payload.get("job_id") or ""))
    if action == "cancel_ingest":
        return knowledge_service.cancel_ingest(namespace=namespace, job_id=str(payload.get("job_id") or ""))
    if action == "search":
        result = knowledge_service.search(
            namespace=namespace,
            query=str(payload.get("query") or ""),
            top_k=int(payload["top_k"]) if payload.get("top_k") is not None else None,
            filters=dict(payload.get("filters") or {}),
        )
        if str((tool_context or {}).get("agent_id") or "") == "bazi" and result.get("ok") is True:
            result = dict(result)
            result["runtime_guidance"] = (
                "Search results already contain text, source_id, and chunk_id. "
                "Cite this evidence and generate the final response now. Do not call get_chunk."
            )
        return result
    if action == "get_chunk":
        return knowledge_service.get_chunk(namespace=namespace, chunk_id=str(payload.get("chunk_id") or ""))
    if action == "delete_source":
        return knowledge_service.delete_source(namespace=namespace, source_id=str(payload.get("source_id") or ""))
    if action == "reindex":
        return knowledge_service.reindex(
            namespace=namespace,
            source_id=str(payload.get("source_id") or "").strip() or None,
        )
    if action == "stats":
        return knowledge_service.stats(namespace=namespace)
    if action == "model_status":
        return knowledge_service.model_status()
    if action == "unload_models":
        return knowledge_service.unload_models()
    raise ValueError(f"unsupported knowledge action: {action}")


def _scope_error(*, action: str, namespace: str, tool_context: dict | None) -> dict[str, object] | None:
    context = tool_context or {}
    allowed_actions = context.get("allowed_knowledge_actions")
    if allowed_actions is not None and action not in allowed_actions:
        return {
            "ok": False,
            "error_code": "KNOWLEDGE_ACTION_FORBIDDEN",
            "message": "knowledge action is outside the selected agent scope",
            "retryable": False,
            "action": action,
        }
    allowed_namespaces = context.get("allowed_knowledge_namespaces")
    if action in _NAMESPACE_ACTIONS and allowed_namespaces is not None and namespace not in allowed_namespaces:
        return {
            "ok": False,
            "error_code": "KNOWLEDGE_NAMESPACE_FORBIDDEN",
            "message": "knowledge namespace is outside the selected agent scope",
            "retryable": False,
            "action": action,
        }
    return None
