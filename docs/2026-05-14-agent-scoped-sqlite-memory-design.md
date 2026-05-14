---
doc_type: design
status: implemented
feature: agent-scoped-sqlite-memory
created: 2026-05-14
summary: "Replace file-primary MEMORY.md with agent-scoped SQLite structured memory, FTS5 retrieval, and readable MEMORY.md exports after runtime app removal."
---

# Agent-scoped SQLite Memory Design

> Date: 2026-05-14  
> Repository: `marten-runtime`  
> Scope: long-term user memory storage, retrieval, prompt injection, memory tool contract, migration, diagnostics  
> First implementation target: Phase 1-3, covering SQLite store, MemoryLoader, and `ThinMemoryService` adaptation

## 0. Current Context

`marten-runtime` now uses agents as the runtime identity. The runtime `app` abstraction was removed on 2026-05-12. Agent prompt assets live under paths such as `agents/main/`, and runtime diagnostics expose `agent_id` through the agent-owned path.

Current memory is a thin file-backed slice:

- service: `src/marten_runtime/memory/service.py::ThinMemoryService`
- storage path: `data/memory/users/{encoded_user_id}/MEMORY.md`
- injection point: `src/marten_runtime/interfaces/http/bootstrap_handlers.py` calls `state.memory_service.render_prompt_memory(user_id or "")`
- prompt insertion: `src/marten_runtime/runtime/llm_message_support.py` appends `request.memory_text` as a system message
- tool entry: `src/marten_runtime/tools/builtins/memory_tool.py::run_memory_tool`
- safety gate: `intent=durable_write|durable_delete` plus `source_excerpt` copied from the current user message

The current file-first model is explainable and local, but it loads the whole `MEMORY.md` block with only a character cap. It has limited scope control, no structured lifecycle, and no retrieval quality signal beyond section text.

## 1. Goals And Boundaries

### 1.1 Goals

1. Make SQLite the primary memory store for durable, structured user memory.
2. Keep memory local-first, inspectable, editable through exported Markdown, and easy to migrate.
3. Add FTS5 retrieval so prompt injection can include relevant memory rather than a flat truncated file.
4. Align memory scope with the current agent-owned runtime model.
5. Preserve existing public service/tool entry points during the first implementation phase.
6. Keep host code as a thin harness: storage, retrieval, lifecycle, safety checks, export, diagnostics.
7. Keep memory writes explicit in Phase 1-3; LLM-driven automatic consolidation can come later through a separate design.

### 1.2 Scope Model

| Scope | Meaning | Required discriminator | First-stage behavior |
| --- | --- | --- | --- |
| `global` | user-wide durable preferences, facts, constraints | none | always eligible for the user |
| `agent` | durable preferences or working hints for one runtime agent | `agent_id` | eligible only for the selected agent |
| `workspace` | repository or local workspace memory for coding-style agents | `workspace_id` | schema-supported, loader-ready, lightly used in first stage |
| `session` | short and medium continuity from session history or compaction | existing session store | stays outside this durable memory store |

Legacy `app=main_agent` semantics map to `scope=agent, agent_id=main` during migration or compatibility handling.

### 1.3 Explicit Out Of Scope

- Tags as a first-class metadata field.
- Embeddings, vector databases, sqlite-vss, and semantic reranking.
- Runtime `app` scope or new app-like identity.
- Project memory as a first-class runtime concept.
- Model-autonomous background memory consolidation.
- Training or fine-tuning memory behavior.
- Remote memory persistence.

### 1.4 Tags Decision

First-stage memory does not include `tags`. The confirmed baseline is `scope + type + section + content + FTS5`. This matches the local personal-assistant direction discussed for OpenClaw, Claude Code, and Nanobot-style memory: file/scope structure, readable memory, search, and controlled loading before metadata expansion. Tags can be reconsidered after evals show FTS5 plus scope/type/section is insufficient.

## 2. Design Principles

This design follows the current project boundary and common agent-memory patterns:

- **Saved durable memory is separate from chat history.** Durable facts and preferences live in a managed store; session history and compaction remain separate continuity sources.
- **Memory is user-controllable.** Users can inspect, replace, and delete stored memories through the existing memory tool surface and generated Markdown export.
- **Prompt injection is selective.** The loader injects a small, relevant slice with precedence and budget rules.
- **Memory entries carry provenance.** Every write keeps `source_excerpt`, optional `source_run_id`, timestamps, status, type and priority.
- **Lifecycle is explicit.** Replace marks older entries `superseded`; delete marks entries `deleted`; active queries filter by status.
- **Retrieval starts simple and verifiable.** FTS5 plus structured filters provide deterministic local retrieval before adding embedding complexity.
- **Current environment wins.** Durable memory is guidance for personalization and continuity; live runtime state, current user message, and repository state remain higher-precedence inputs.

External reference points used for this design:

- OpenAI Memory FAQ: saved memories are context, user-manageable, and separate from chat history.
- OpenAI context personalization cookbook: local-first state, memory injection, staged notes, dedupe, conflict handling, and precedence rules.
- OpenAI Agents SDK memory docs: progressive disclosure, small injected summary, searchable memory artifacts, stale-memory handling, and multi-agent memory layouts.

## 3. Data Model

### 3.1 `MemoryItem`

New model in `src/marten_runtime/memory/models.py`:

```python
class MemoryItem(BaseModel):
    memory_id: str
    user_id: str
    scope: Literal["global", "agent", "workspace"]
    agent_id: str | None = None
    workspace_id: str | None = None
    type: Literal["preference", "fact", "constraint", "workflow_hint"]
    section: str
    content: str
    source_excerpt: str = ""
    source_run_id: str | None = None
    status: Literal["active", "superseded", "deleted"] = "active"
    priority: int = 50
    created_at: str
    updated_at: str
```

Validation rules:

- `scope=global`: `agent_id` and `workspace_id` are stored as `NULL`.
- `scope=agent`: canonicalized `agent_id` is required.
- `scope=workspace`: `workspace_id` is required; `agent_id` is optional metadata.
- `priority` is clamped to `0..100`.
- `content`, `section`, and `user_id` are normalized using the same whitespace discipline as the existing service.

### 3.2 SQLite Tables

Primary table:

```sql
CREATE TABLE IF NOT EXISTS memory_items (
  memory_id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  scope TEXT NOT NULL,
  agent_id TEXT,
  workspace_id TEXT,
  type TEXT NOT NULL,
  section TEXT NOT NULL,
  content TEXT NOT NULL,
    source_excerpt TEXT NOT NULL DEFAULT '',
  source_run_id TEXT,
  status TEXT NOT NULL DEFAULT 'active',
  priority INTEGER NOT NULL DEFAULT 50,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
```

FTS table:

```sql
CREATE VIRTUAL TABLE IF NOT EXISTS memory_items_fts USING fts5(
  memory_id UNINDEXED,
  content,
  section
);
```

Indexes:

```sql
CREATE INDEX IF NOT EXISTS idx_memory_items_active_lookup
ON memory_items(user_id, status, scope, agent_id, workspace_id, type);

CREATE INDEX IF NOT EXISTS idx_memory_items_priority_recent
ON memory_items(user_id, status, priority, updated_at);
```

FTS synchronization uses the store methods rather than SQL triggers in Phase 1. This keeps lifecycle behavior explicit in Python tests.

## 4. Store Interface

New files:

- `src/marten_runtime/memory/store.py`
- `src/marten_runtime/memory/sqlite_store.py`

Interface:

```python
class MemoryStore(Protocol):
    def append(self, item: MemoryItem) -> MemoryItem: ...
    def replace(self, memory_id: str, new_item: MemoryItem) -> MemoryItem: ...
    def delete(self, memory_id: str) -> MemoryItem: ...
    def get(self, memory_id: str) -> MemoryItem | None: ...
    def list_active(
        self,
        user_id: str,
        *,
        scope: str | None = None,
        agent_id: str | None = None,
        workspace_id: str | None = None,
        type: str | None = None,
        limit: int | None = None,
    ) -> list[MemoryItem]: ...
    def search(
        self,
        user_id: str,
        query: str,
        *,
        scope: str | None = None,
        agent_id: str | None = None,
        workspace_id: str | None = None,
        type: str | None = None,
        limit: int = 10,
    ) -> list[MemoryItem]: ...
```

Behavior:

- `append` inserts one active item and indexes it into FTS.
- `replace` marks the target item `superseded`, inserts a new active item, and updates FTS for both lifecycle changes.
- `delete` marks the target item `deleted` and removes or filters it from FTS search results.
- `list_active` returns active items sorted by `priority DESC, updated_at DESC, memory_id ASC`.
- `search` applies structured filters first, FTS query second, then the same priority/recency order.

## 5. MemoryLoader

New file:

- `src/marten_runtime/memory/loader.py`

Request model:

```python
class MemoryLoadRequest(BaseModel):
    user_id: str
    agent_id: str | None = None
    workspace_id: str | None = None
    current_message: str = ""
    char_budget: int = 800
    per_scope_limit: int = 8
    search_limit: int = 12
```

Result model:

```python
class MemoryLoadResult(BaseModel):
    items: list[MemoryItem]
    rendered_text: str | None
    active_count: int
    loaded_count: int
    budget_chars: int
```

Loading order:

1. Load active `global` items for the user.
2. Load active `agent` items for the selected `agent_id`.
3. Load active `workspace` items when `workspace_id` is available.
4. Search FTS5 with `current_message` using the same scope eligibility filters.
5. Deduplicate by `memory_id`.
6. Sort by `priority DESC, updated_at DESC`, with FTS hits boosted inside equal priority groups.
7. Render until `char_budget` is reached.

Rendered prompt format:

```text
User memory:
- [preference][global] 回答默认使用中文，保持简洁。
- [constraint][agent:main] 对 marten-runtime 的改动保持 thin harness 边界。
- [workflow_hint][workspace:marten-runtime] 先跑 targeted tests，再跑相关 eval。
```

The loader keeps memory concise. Detailed inspection stays available through `memory.get` and exported Markdown.

## 6. `ThinMemoryService` Adaptation

Existing public methods remain available:

```python
load(user_id: str) -> MemoryDocument
render_prompt_memory(user_id: str, *, agent_id: str | None = None, workspace_id: str | None = None, current_message: str = "") -> str | None
append(user_id: str, *, section: str, content: str, scope: str = "global", agent_id: str | None = None, workspace_id: str | None = None, type: str = "fact", source_excerpt: str = "", source_run_id: str | None = None, priority: int = 50) -> MemoryDocument
replace(user_id: str, *, section: str, content: str, scope: str = "global", agent_id: str | None = None, workspace_id: str | None = None, type: str = "fact", source_excerpt: str = "", source_run_id: str | None = None, priority: int = 50, memory_id: str | None = None) -> MemoryDocument
delete(user_id: str, *, section: str, content: str | None = None, scope: str | None = None, agent_id: str | None = None, workspace_id: str | None = None, memory_id: str | None = None) -> MemoryDocument
```

Compatibility behavior:

- Existing callers using only `section` and `content` still work.
- Default `scope` is `global` for compatibility.
- `replace` without `memory_id` replaces active entries in the same `(user_id, scope, agent_id, workspace_id, section, type)` bucket by marking old entries `superseded` and inserting normalized new lines as active items.
- `delete` without `memory_id` deletes by section and optional content under the provided scope filter.
- `load` returns a `MemoryDocument` rendered from active SQLite items and points `path` at the exported `MEMORY.md` path.

Constructor:

```python
ThinMemoryService(
    root: str | Path,
    *,
    store: MemoryStore | None = None,
    db_path: str | Path | None = None,
    max_write_chars: int = 1000,
    prompt_char_limit: int = 800,
)
```

When `store` is absent, the service creates `SQLiteMemoryStore` at `root / "memory.sqlite3"`.

## 7. Markdown Export

New file:

- `src/marten_runtime/memory/export.py`

`MEMORY.md` becomes a generated human-readable view. The export keeps the current user path:

```text
data/memory/users/{encoded_user_id}/MEMORY.md
```

Export example:

```markdown
# MEMORY

## global / preferences
- 回答默认使用中文，保持简洁。

## agent:main / constraints
- 对 marten-runtime 的改动保持 thin harness 边界。

## workspace:marten-runtime / workflow_hints
- 修改 runtime 主链后跑 targeted tests 和 memory_long_horizon eval。
```

Export timing:

- after `append`
- after `replace`
- after `delete`
- after migration

Manual edits to `MEMORY.md` are supported through an explicit import command, not by hot reloading on every request. The same script that migrates old files must support a safe import path from edited Markdown back into SQLite:

```bash
PYTHONPATH=src .venv/bin/python scripts/migrate_memory_md_to_sqlite.py \
  --memory-root data/memory \
  --db-path data/memory/memory.sqlite3 \
  --import-edited-markdown
```

Import rules:

- import reads only `data/memory/users/{encoded_user_id}/MEMORY.md` files.
- import rewrites active items for sections represented in Markdown and leaves unrelated scopes untouched.
- import marks replaced SQLite rows as `superseded`, then inserts imported rows as `active`.
- import supports `--dry-run` and reports user count, changed item count, and skipped malformed sections.
- conflict handling is deterministic: Markdown is the operator-approved source for imported sections, SQLite history remains available through `superseded` rows.

## 8. Memory Tool Contract

Existing tool name stays `memory`.

New schema fields:

```json
{
  "action": "append",
  "scope": "global",
  "agent_id": null,
  "workspace_id": null,
  "type": "preference",
  "section": "output_style",
  "content": "回答默认使用中文，保持简洁。",
  "priority": 70,
  "intent": "durable_write",
  "source_excerpt": "记住：以后默认用中文简洁回答"
}
```

Tool rules:

- `action=get` returns active memory grouped by scope, type, and section.
- `action=append|replace` requires `intent=durable_write`, `source_excerpt`, `scope`, `type`, `section`, and `content`.
- `action=delete` requires `intent=durable_delete`, `source_excerpt`, and either `memory_id` or enough filters to identify a section/content target.
- `scope=agent` requires `agent_id`; the tool can default to `tool_context.agent_id` when payload omits it.
- `source_excerpt` validation continues to check the current user message.
- Returned payload preserves `memory_text`, `rendered_memory`, and `sections` for direct rendering compatibility, and adds `items` for structured consumers.

Capability declaration updates:

- Replace older bucket examples such as `project` with `workspace`.
- Add scope/type guidance.
- State that `agent` memory uses selected runtime `agent_id`.

## 9. Runtime Integration

### 9.1 Bootstrap

Update `src/marten_runtime/interfaces/http/bootstrap_runtime.py`:

```python
memory_service = ThinMemoryService(
    resolved_repo_root / "data" / "memory",
    db_path=resolved_repo_root / "data" / "memory" / "memory.sqlite3",
)
```

### 9.2 Request Handling

Update `src/marten_runtime/interfaces/http/bootstrap_handlers.py`:

```python
memory_text=state.memory_service.render_prompt_memory(
    user_id or "",
    agent_id=selected_agent.agent_id,
    current_message=message_text,
)
```

The exact variable names should follow the existing selected-agent resolution inside the handler. The important contract is: memory loading receives the same selected agent identity as the runtime loop.

### 9.3 Tool Context

Update runtime tool context creation so `run_memory_tool` receives:

```python
{
  "user_id": user_id,
  "agent_id": selected_agent.agent_id,
  "message": current_user_message,
  "run_id": run_id,
}
```

This lets the memory tool default `scope=agent` writes to the selected agent when instructed, and lets the store save `source_run_id`.

## 10. Migration And Edited Markdown Import

New script:

- `scripts/migrate_memory_md_to_sqlite.py`

Inputs:

- `--memory-root data/memory`
- optional `--db-path data/memory/memory.sqlite3`
- optional `--dry-run`
- optional `--import-edited-markdown` for explicit import from edited `MEMORY.md` back into SQLite

Rules:

| Markdown section | type | scope |
| --- | --- | --- |
| `preferences` | `preference` | `global` |
| `facts` | `fact` | `global` |
| `constraints` | `constraint` | `global` |
| `workflow_hints` / `workflow hints` | `workflow_hint` | `global` |
| other sections | `fact` | `global` |

Legacy compatibility:

- Any old payloads or rows referring to `app_id=main_agent` map to `scope=agent, agent_id=main`.
- Any old user file path remains the same exported view path after migration.

Migration/import result:

- active SQLite items inserted
- `MEMORY.md` regenerated from SQLite after migration
- edited Markdown can be imported back with explicit `--import-edited-markdown`
- dry-run summary reports user count, item count, section mapping, changed item count, and skipped empty entries

## 11. Diagnostics

Add a `memory` block to `/diagnostics/runtime` or the existing runtime diagnostics payload:

```json
{
  "memory": {
    "store_kind": "sqlite",
    "active_count": 12,
    "loaded_count_last_turn": 3,
    "budget_chars": 800,
    "fts_enabled": true
  }
}
```

Phase 1-3 can expose store kind and active count first. `loaded_count_last_turn` can be added when the request path records the latest loader result.

## 12. Implementation Plan

1. Add structured models, store protocol, and SQLite store.
   - New files: `memory/store.py`, `memory/sqlite_store.py`
   - Exit signal: store tests prove append/list/search/replace/delete and FTS5 filtering.
2. Add `MemoryLoader`.
   - New file: `memory/loader.py`
   - Exit signal: loader tests prove global + agent + FTS selection, dedupe, and char budget.
3. Adapt `ThinMemoryService`.
   - Modify: `memory/service.py`, `memory/render.py`, `memory/models.py`
   - Exit signal: existing `tests/test_memory_service.py` passes with SQLite-backed service.
4. Add Markdown export.
   - New file: `memory/export.py`
   - Exit signal: append/replace/delete regenerates readable `MEMORY.md`.
5. Extend memory tool schema and capability declaration.
   - Modify: `tools/builtins/memory_tool.py`, `runtime/capabilities.py`
   - Exit signal: memory tool tests cover scope/type/source_run_id and legacy payload compatibility.
6. Wire runtime request context.
   - Modify: `interfaces/http/bootstrap_runtime.py`, `interfaces/http/bootstrap_handlers.py`, runtime tool context construction.
   - Exit signal: runtime tests prove selected `agent_id` reaches loader/tool context.
7. Add migration script.
   - New file: `scripts/migrate_memory_md_to_sqlite.py`
   - Exit signal: script test migrates sample `MEMORY.md` and regenerates export.
8. Add diagnostics and eval coverage.
   - Modify diagnostics route and memory long-horizon cases as needed.
   - Exit signal: targeted tests and scripted `memory_long_horizon` eval pass.

## 13. Test Design

### 13.1 Store Tests

New `tests/test_memory_sqlite_store.py`:

- append creates active rows and FTS rows
- list filters by user, scope, agent, workspace, type
- search returns only active eligible items
- replace marks older item `superseded` and returns new active item
- delete marks item `deleted` and removes it from active search
- priority and recency ordering are stable

### 13.2 Loader Tests

New `tests/test_memory_loader.py`:

- global memory loads for any selected agent
- agent memory loads only for matching `agent_id`
- workspace memory loads only for matching `workspace_id`
- FTS query recalls relevant facts from `current_message`
- high priority items survive tight char budgets
- duplicate items from list + FTS are rendered once

### 13.3 Service And Tool Tests

Update existing tests:

- `tests/test_memory_service.py`
- `tests/test_memory_intent.py`
- `tests/tools/test_memory_tool.py`

Cases:

- old `append(user_id, section, content)` still works
- `render_prompt_memory(user_id, agent_id="main", current_message="...")` returns loader-rendered text
- memory tool validates `scope`, `type`, `source_excerpt`, and `intent`
- direct rendering still receives `sections`

### 13.4 Runtime And Eval Tests

Targeted tests:

- bootstrap creates SQLite memory service
- request handler passes selected `agent_id` into memory loader
- memory tool receives `tool_context.agent_id`
- `evals/suites/memory_long_horizon.toml` remains green in scripted mode

Memory eval coverage must explicitly include:

1. selected `agent_id` loads user `global` memory plus matching `agent` memory.
2. non-matching `agent` memory and non-matching `workspace` memory are blocked from the prompt slice.
3. overwrite/replace produces one active current item; older superseded content is absent from prompt recall and direct memory reads.

## 14. Acceptance Criteria

Phase 1-3 acceptance:

- SQLite store supports append, replace, delete, get, list, and search.
- FTS5 recalls memory related to the current message.
- `ThinMemoryService` public methods remain usable.
- `render_prompt_memory()` uses `MemoryLoader` and selected `agent_id`.
- `MEMORY.md` is generated as a readable export.
- Existing memory tool behavior remains compatible.
- Current `memory_long_horizon` scripted eval has no regression and covers load/block/replace behavior.

Full feature acceptance:

- memory tool supports `scope`, `type`, `priority`, `source_run_id`, `agent_id`, and `workspace_id`.
- legacy file memory migrates into SQLite.
- legacy `main_agent` references map to `agent:main`.
- diagnostics expose memory store kind and loader counts.
- unit tests, targeted runtime tests, compile check, and memory eval pass.

## 15. Risks And Controls

| Risk | Control |
| --- | --- |
| Agent scope accidentally revives app-like behavior | schema uses `agent_id`; no `app_id` field in active table or tool contract |
| Prompt gets noisy as memory grows | loader budget, priority, FTS search, and per-scope limits |
| Stale memory overrides current facts | prompt wording treats memory as guidance; current message/runtime state remains higher priority |
| Replace/delete become ambiguous | prefer `memory_id` when available; otherwise use narrow section/type/scope filters |
| SQLite FTS syntax errors from arbitrary user text | escape or tokenize query terms in `SQLiteMemoryStore.search()` |
| Manual `MEMORY.md` edits drift from SQLite | document export as generated view; provide migration/import path |

## 16. Design Check

### 16.1 Goal Alignment

- The design upgrades storage and loading quality while preserving the existing `memory` builtin and `ThinMemoryService` entry points.
- The design follows the current agent-owned runtime baseline by using `agent_id` and omitting `app_id` from active schemas and contracts. It keeps first-stage metadata small by omitting tags.
- The design keeps the first implementation lightweight: SQLite, FTS5, Markdown export, and tests.

### 16.2 Industry Pattern Alignment

- Durable memory is separate from chat/session history.
- Users can inspect and delete memory.
- Prompt injection is selective and budgeted.
- Memory entries carry provenance, timestamps, lifecycle status, type and priority.
- Retrieval starts with deterministic local search and can later add semantic retrieval after evals prove need.

### 16.3 Repository Fit

- The storage path stays under `data/memory`, matching the current service root.
- Runtime injection continues through `memory_text`, matching `RuntimeContext` and `LLMMessage` construction.
- The design extends existing memory tool safety checks instead of adding a parallel mutation path.
- Tests map to current test files and eval suite names.
