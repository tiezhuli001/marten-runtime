from __future__ import annotations

from marten_runtime.knowledge.service import KnowledgeService


def run_knowledge_tool(payload: dict, *, knowledge_service: KnowledgeService) -> dict:
    action = str(payload.get("action") or "").strip().lower()
    if not action:
        raise ValueError("action is required")
    namespace = str(payload.get("namespace") or "")
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
        return knowledge_service.search(
            namespace=namespace,
            query=str(payload.get("query") or ""),
            top_k=int(payload["top_k"]) if payload.get("top_k") is not None else None,
            filters=dict(payload.get("filters") or {}),
        )
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
