---
kind: issue
title: "Knowledge Operator 最小管理后端"
type: feature
status: open
created: 2026-07-24
epic: ".cs/epics/001-o-bazi-agent/spec.md"
---

# Knowledge Operator 最小管理后端

## 目标

Operator 可以通过统一受保护的 HTTP API 查询 Knowledge namespace/source/job，安全上传审核后的 `.txt/.md`，执行软删除与 reindex，并在进程重启后获得单一、可重试、已清理 staging 的 job 终态。

## 范围

- 包含：Bearer operator auth、固定分页/envelope、`10 MiB` 流式上传、source metadata、`python-multipart`、SQLite migration、job recovery、staging ownership/cleanup、Knowledge diagnostics。
- 包含：GET/DELETE/reindex 200、upload 202、401/404/413/422 的固定 HTTP status 与错误 envelope。
- 不包含：Knowledge Console UI、自定义 ingest profile、PDF/Word、草稿审核工作流和多角色 RBAC。

## 归属

- 隶属 Epic：`.cs/epics/001-o-bazi-agent/spec.md`
- 相关 spec：`.cs/spec/knowledge-runtime.md`
- 相关设计：`docs/2026-07-23-bazi-agent-design.md`

## 现状如何工作

KnowledgeService 已提供 tool-oriented ingest、search、delete、reindex、stats 与 job 持久化。HTTP app 当前没有 Knowledge 管理 router 和统一授权；file ingest 读取已有路径并启动 daemon thread；job 表没有 staging 所有权、结构化 error code、retryable 或启动恢复。

## 执行 Chunk

- `C07`：Knowledge job schema migration、staging 所有权与重启恢复。
- `C08`：Operator Bearer auth、查询、上传、删除、reindex 与 diagnostics。
- 权威步骤、测试命令与完成条件见 `.cs/epics/001-o-bazi-agent/spec.md` 的 `C07-C08`。

## 影响范围

- 必须修改：HTTP router/bootstrap、runtime env/diagnostics、Knowledge store/job/service、SQLite migration、依赖声明、`.env.example` 与部署文档。
- 需要验证：所有管理接口授权、分页、上传超限/编码/路径、终态清理、重启恢复、旧数据库迁移和现有 Knowledge tool 回归。
- 仍待调查：实现时确认现有 SQLite migration helper 的最佳扩展位置。

## 质量目标

- 信息安全性：所有 `/knowledge/**` 请求先通过恒定时间 Bearer 校验，token 不进入日志与 diagnostics；以未授权集成测试和敏感扫描验证。
- 可靠性：中间态 job 在重启后统一进入 `failed + KNOWLEDGE_JOB_INTERRUPTED + retryable=true`，job-owned staging 被清理；以持久化重启 fixture 验证。
- 性能效率：上传以流式计数限制为 `10 MiB`，避免请求体和文件双份驻留内存；以上限测试验证。
- 可维护性：HTTP、tool 与未来 UI 共享 KnowledgeService 和同一数据库 schema；以现有 tool 回归和 migration test 验证。

## 实现设计

### 这次要怎么做

在 HTTP 层增加单一 Operator router，router 只负责授权、协议和 staging；KnowledgeService 继续拥有 ingest/delete/reindex；store/job 层增加恢复所需字段与查询。Router 缺少 secret 时保持未注册，避免形成默认开放的管理面。

### 请求 / 数据怎么走

上传请求先鉴权，再流式写入 runtime-owned staging，计算 sha256 并生成默认 uri/version；创建带 staging 相对路径的 ingest job 后由现有 service 处理。终态、取消和启动恢复都通过统一 cleanup helper 删除 job-owned staging。

### 一步步怎么改

1. 增加 `KNOWLEDGE_OPERATOR_TOKEN` resolved env、auth dependency、router 开关和 diagnostics。
2. 增加 namespace/source/job list store 查询、固定分页与排序。
3. 增加 `python-multipart` 和单文件 multipart upload，执行扩展名、编码、metadata 与流式大小校验。
4. 为 job 表增加 `error_code`、`retryable`、`staged_file_path`，编写旧库 migration。
5. 抽取终态 cleanup 与启动 reconciliation，增加 24 小时 orphan cleanup。
6. 接入删除/reindex/stats，并保持 Agent tool action/namespace scope 独立。
7. 运行 HTTP、service、store、migration、restart 与现有 Knowledge 回归测试。

## 验证

- 缺少 token 时 router 不存在且 diagnostics 可解释；无效 token 返回 401，service 调用计数为零。
- GET/DELETE/reindex 成功返回 200，upload accepted 返回 202；资源、参数、格式与大小错误命中固定 404/422/413。
- `10 MiB` 边界接受，超出一个字节返回 413 并清理 staging；`.txt/.md` 与三种编码通过。
- source/job 分页稳定，旧数据库迁移保留现有数据。
- queued/reading/chunking/embedding 重启后统一失败、可重试并清理 staging；completed/failed/cancelled 同样无残留。
- 现有 Knowledge tool、hybrid retrieval、delete/reindex 与 model status tests 保持通过。

## 执行记录

### C07（2026-07-24）

- 为 ingest job 增加 `error_code`、`retryable`、`staged_file_path` 与状态索引，旧 schema 原地增量迁移可重复执行。
- 中间态启动恢复统一写入 `failed + KNOWLEDGE_JOB_INTERRUPTED + retryable=true`，旧 job 保留审计证据。
- 终态使用原子条件更新，completed/failed/cancelled 首个终态生效；终态目录清理、24 小时 orphan 清理与失败诊断可重复执行。
- staging 只接受上传根目录内的两段相对路径，并校验实际文件路径、目录权限和清理边界。
- 验证：C07/store/service 29/29、完整 Knowledge 回归 83/83、`compileall` 与 `git diff --check` 通过。

### C08（2026-07-24）

- 增加仅在 `KNOWLEDGE_OPERATOR_TOKEN` 配置时注册的 `/knowledge/**` router，并在 multipart 解析前执行恒定时间 Bearer 校验和声明大小检查。
- 实现 namespace/source/chunk/job 固定分页查询、stats、软删除、source/namespace reindex 与统一 HTTP envelope。
- 实现 `.txt/.md` 流式上传、`10 MiB` 实际字节限制、UTF-8/UTF-8-SIG/GB18030 校验、reviewed metadata、服务端文件名与稳定 source identity。
- 相同 source 的并发 ingest 使用 source 级引用计数锁，独立 job 证据和 staging 保持完整。
- 增加 Knowledge runtime diagnostics、`python-multipart` 依赖、环境变量示例和部署/配置文档。
- 验证：C08 聚焦 21/21、Knowledge 全回归 94/94、并发重复上传连续 10/10、HTTP/bootstrap 20/20、`pip check`、`compileall` 与 `git diff --check` 通过。
