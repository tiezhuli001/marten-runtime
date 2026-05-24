---
name: knowledge_management
description: Use when a user wants to build, search, inspect, delete, or reindex a namespace-scoped knowledge base through the runtime knowledge tool.
---

# Knowledge Management

Use the builtin `knowledge` tool for actual operations. This skill only describes the chat workflow.

## Workflow

- Missing namespace: ask for the target `namespace` when the user has not provided one and the current task context does not imply one.
- Small text: call `knowledge` with `action=ingest_text`, `namespace`, and `source.text`.
- Large local file: call `knowledge` with `action=ingest_file`; return the `job_id` and current status from the tool result.
- Progress check: call `knowledge` with `action=ingest_status`, `namespace`, and `job_id`.
- Search: call `knowledge` with `action=search`, then cite returned `source_id` and `chunk_id` in the answer.
- Inspect source text: call `knowledge` with `action=get_chunk` for the cited `chunk_id`.
- Delete: use `action=delete_source` only when the user clearly authorizes deleting that source; destructive operations need 用户确认.
- Reindex: use `action=reindex` only when the user clearly authorizes rebuilding vectors and gives confirmation for the namespace, for example `knowledge.reindex --namespace fanqie`.
- Model status: call `knowledge` with `action=model_status` when the user asks whether local embedding/reranker models are loaded.
- Model unload: call `knowledge` with `action=unload_models` when the user asks to release knowledge model memory.

## Output rules

- For ingest jobs, tell the user the knowledge write is running and include `job_id`.
- For search answers, include concise citations using `source_id` and `chunk_id`; 中文回答可写“引用：source_id / chunk_id”。
- For missing model or config mismatch diagnostics, surface the tool message and the suggested `knowledge.reindex --namespace ...` command when provided.
- For model_status/unload_models, report only loaded/not_loaded, model_id, and idle_ttl_seconds.
