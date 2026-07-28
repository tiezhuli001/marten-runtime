# 连续性与能力面

## 读者该带走什么

Runtime 通过多个职责清晰的 bounded slice 提供连续性和能力扩展。Session、memory 与 Knowledge 保存不同类型的信息；builtin、MCP、skill 与 subagent 提供不同的执行边界。

## 连续性分层

### Session

Session 保存当前对话的连续性。SQLite persistence 支持跨进程恢复，restore 由 compacted summary、最近 user turns、近期 tool outcome summaries 与 thin memory 组成，并受单一 replay budget 约束。

`session.new` 与 `session.resume` 提供显式会话控制。Source session compaction 可以排队执行，target session 的恢复路径保持即时。

### Memory

Memory 保存跨会话稳定事实和用户偏好。当前基线使用 SQLite + FTS5，支持 `global`、`agent`、`workspace` 等作用域以及优先级、类型和状态过滤。

`MEMORY.md` 是可读导出与显式导入入口。Memory 负责稳定事实，session history 负责对话过程，self-improve 负责经过 gate 的 runtime lessons。

### Knowledge

Knowledge 保存可检索文档与资料，使用 namespace 隔离不同知识库。它提供 source、chunk、FTS、embedding、vector、rerank、reindex 与 ingest job，详细契约见 [Knowledge/RAG Runtime](./knowledge-runtime.md)。

## 能力类型

### Builtin family tools

Builtin tools 承担 runtime 自有能力，例如 time、session、memory、knowledge、automation、self-improve、skill、MCP 与 subagent control。每个 family 通过 schema、权限与 side-effect rule 形成机器可验证契约。

### MCP

MCP 连接外部系统。Live server 定义位于 `mcps.json`，默认按 server / family 摘要暴露，具体工具按需发现和调用。GitHub Trending sidecar 是 repo-local MCP 的代表性窄扩展。

### 文件型 skills

Skill 提供模型可读的行为规则、流程与使用指导。正文按需加载，状态变化通过 builtin 或 MCP 执行。`knowledge_management` skill 就采用这种分工：skill 说明 namespace、引用与确认规则，builtin `knowledge` 完成真实操作。

### Lightweight subagents

Subagent 为隔离后台任务提供 child runtime、权限上限、parent / child lineage、cooperative cancellation 与完成通知。它扩展执行能力，同时保持 parent runtime 为协调边界。

### Automation 与 self-improve

Automation 提供窄范围 recurring definition 与 operator surface。Self-improve 保存 failure / recovery evidence 和经过 gate 的 lessons。两者都依附 runtime contract，并保持独立持久化职责。

## Provider 韧性

Provider metadata 位于 `config/providers*.toml`，model profile 与 fallback chain 位于 `config/models*.toml`。Runtime 统一处理 retry、backoff、profile failover、error kind 与 run-level reliability diagnostics。

一次 run 的 diagnostics 可以看到 attempted profiles、attempted providers、retry count、fallback count、final provider 与 failover stage。

## 质量约束

- Session restore 始终有界，避免历史上下文无限增长。
- Memory 与 Knowledge 使用独立数据模型和调用语义，保持检索目标清晰。
- 外部能力通过声明和 permission surface 接入，selected agent 决定最终可见范围。
- Provider、MCP、tracing 与本地模型故障都需要可诊断的 degraded result。
- Side-effect 操作通过参数校验、权限、scope 与确认规则保护。

## 证据索引

- `docs/ARCHITECTURE_CHANGELOG.md`
- `docs/CONFIG_SURFACES.md`
- `src/marten_runtime/session/`
- `src/marten_runtime/memory/`
- `src/marten_runtime/knowledge/`
- `src/marten_runtime/runtime/provider_reliability.py`
- `src/marten_runtime/subagents/`
- `src/marten_runtime/tools/builtins/`
- `skills/`
