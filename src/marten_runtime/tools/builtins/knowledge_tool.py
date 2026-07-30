from __future__ import annotations

from marten_runtime.bazi.retrieval_query import (
    build_bazi_retrieval_plan,
    current_bazi_result_from_context,
    rerank_bazi_theory_results,
)
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
        requested_top_k = int(payload["top_k"]) if payload.get("top_k") is not None else None
        query = str(payload.get("query") or "")
        plan = None
        if (
            str((tool_context or {}).get("agent_id") or "") == "bazi"
            and namespace == "bazi-theory"
        ):
            plan = build_bazi_retrieval_plan(
                current_bazi_result_from_context(tool_context),
                user_message=str((tool_context or {}).get("message") or ""),
            )
            if plan is not None:
                query = plan.theory_query
        if plan is not None:
            candidate_top_k = max(
                (requested_top_k or knowledge_service.config.search.default_top_k) * 3, 15
            )
            result = _search_bazi_theory_queries(
                knowledge_service,
                namespace=namespace,
                display_query=query,
                queries=plan.theory_queries,
                classical_query=plan.classical_query,
                author_method_query=plan.author_method_query,
                top_k=candidate_top_k,
                filters=dict(payload.get("filters") or {}),
            )
        else:
            result = knowledge_service.search(
                namespace=namespace,
                query=query,
                top_k=requested_top_k,
                filters=dict(payload.get("filters") or {}),
            )
        if str((tool_context or {}).get("agent_id") or "") == "bazi" and result.get("ok") is True:
            result = dict(result)
            if plan is not None:
                result["results"] = rerank_bazi_theory_results(
                    list(result.get("results") or []),
                    plan=plan,
                    top_k=requested_top_k or knowledge_service.config.search.default_top_k,
                )
                result["query_plan"] = {
                    "strategy": "bazi_chart_multitopic_v3",
                    "facts": list(plan.facts),
                    "subqueries": list(plan.theory_queries),
                    "classical_query": plan.classical_query,
                    "author_method_query": plan.author_method_query,
                    "targeted_content_types": ["author_method"],
                }
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


def _search_bazi_theory_queries(
    knowledge_service: KnowledgeService,
    *,
    namespace: str,
    display_query: str,
    queries: tuple[str, ...],
    classical_query: str,
    author_method_query: str,
    top_k: int,
    filters: dict[str, object],
) -> dict[str, object]:
    responses = [
        knowledge_service.search(
            namespace=namespace,
            query=subquery,
            top_k=top_k,
            filters=filters,
        )
        for subquery in queries
    ]
    if "evidence_kind" not in filters and "content_type" not in filters:
        responses.append(
            knowledge_service.search(
                namespace=namespace,
                query=classical_query,
                top_k=top_k,
                filters={**filters, "evidence_kind": "classical_original"},
            )
        )
        responses.append(
            knowledge_service.search(
                namespace=namespace,
                query=author_method_query,
                top_k=top_k,
                filters={**filters, "content_type": "author_method"},
            )
        )
    failed = next((response for response in responses if response.get("ok") is not True), None)
    if failed is not None:
        return failed
    merged: dict[str, dict[str, object]] = {}
    for response in responses:
        for item in response.get("results") or []:
            chunk_id = str(item.get("chunk_id") or "")
            if not chunk_id:
                continue
            current = merged.get(chunk_id)
            if current is None or float(item.get("score") or 0.0) > float(current.get("score") or 0.0):
                merged[chunk_id] = dict(item)
    first = dict(responses[0])
    first["query"] = display_query
    first["results"] = list(merged.values())
    first["search_run_ids"] = [response.get("search_run_id") for response in responses]
    first["embedding_ms"] = round(sum(float(response.get("embedding_ms") or 0.0) for response in responses), 3)
    for field in ("fts_ms", "vector_ms", "rerank_ms", "total_ms"):
        first[field] = round(sum(float(response.get(field) or 0.0) for response in responses), 3)
    first["retrieval_mode"] = (
        "hybrid_rerank"
        if all(response.get("retrieval_mode") == "hybrid_rerank" for response in responses)
        else str(first.get("retrieval_mode") or "")
    )
    return first


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
