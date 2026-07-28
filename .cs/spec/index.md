# Project Spec

## 这个项目是什么

`marten-runtime` 是面向自托管场景的轻量 agent runtime harness。它把消息入口、agent 绑定、运行时上下文、LLM、builtin / MCP / skill 能力、结果投递和诊断组织成一条可运行、可验证的主链。

项目服务两类读者：

- 使用者与运维者：用最小配置启动 runtime，通过 HTTP 或 Feishu 发起 agent 任务，并从 diagnostics 与 eval 观察执行结果。
- 开发者与维护者：沿着明确的 runtime contract 增加能力，同时守住 thin harness 与 LLM-first 边界。

## 当前状态与重点

当前基线已经具备完整的交互式 runtime 主链：

```text
channel -> binding -> selected agent -> runtime context -> LLM
        -> builtin / MCP / skill / subagent -> LLM -> delivery / diagnostics
```

维护工作的优先级由这条主链决定：主链正确性、operator 可理解性、薄边界、验证与诊断优先。能力扩展以 bounded slice 的方式挂接主链，运行时身份与 prompt 资产归属于 agent。

## 能力地图

- [运行主链与架构边界](./runtime-main-chain.md)：理解一次消息怎样完成路由、执行、工具往返、投递与诊断，以及宿主承担哪些责任。
- [连续性与能力面](./continuity-and-capabilities.md)：理解 session、memory、skill、MCP、automation、subagent 与 provider resilience 怎样协作。
- [Knowledge/RAG Runtime](./knowledge-runtime.md)：理解已实现的 namespace-scoped 知识入库、检索、重排、降级和模型资产边界。
- [运维与验证](./operations-and-verification.md)：理解配置归属、启动路径、健康检查、diagnostics、测试与 eval 证据。

## 使用路径

- 启动最小 HTTP runtime：从 `./init.sh` 或 Docker Compose 进入，配置一个 provider credential，检查 `/healthz`、`/readyz` 与 `/diagnostics/runtime`。
- 接入真实聊天：在 HTTP 主链健康后启用 Feishu websocket，通过 binding 进入 selected agent，再用 run / trace diagnostics 关联实链证据。
- 增加外部能力：通过 MCP server、文件型 skill 或 builtin family tool 声明能力，由 LLM 选择何时展开和调用。
- 维护长期上下文：session 保存对话连续性，memory 保存跨会话稳定事实与偏好，Knowledge 保存可检索文档材料。
- 判断一次改动是否更好：单元测试与契约测试证明行为，diagnostics 与 tracing 证明运行事实，eval 比较体验和能力质量。

## 架构落点

- Runtime 与生命周期：`src/marten_runtime/runtime/`
- HTTP、Feishu、bootstrap 与 diagnostics：`src/marten_runtime/interfaces/http/`
- Agent registry 与资产：`config/agents.toml`、`agents/<agent_id>/`
- Builtin tools：`src/marten_runtime/tools/builtins/`
- MCP 与 skills：`src/marten_runtime/mcp/`、`skills/`
- Session、memory、knowledge：`src/marten_runtime/session/`、`src/marten_runtime/memory/`、`src/marten_runtime/knowledge/`
- Eval：`src/marten_runtime/evals/`、`evals/`、`scripts/run_eval.py`

## 统一语言

- **主链**：从 channel ingress 到 binding、agent、runtime、LLM、能力调用、delivery 与 diagnostics 的执行路径。
- **Thin harness**：宿主负责声明、组装、执行、检查、恢复、持久化、投递与诊断，普通自然语言的能力选择留在模型路径。
- **Capability family**：模型默认看到的稳定能力入口；具体 skill 正文或 MCP tool 细节按需展开。
- **Selected agent**：一次 turn 实际使用的 agent 身份；它决定资产根、tool surface、prompt mode 与 model profile。
- **Session**：有界的对话连续性与恢复单元。
- **Memory**：跨会话稳定事实和偏好的结构化持久层。
- **Knowledge namespace**：可检索知识材料的逻辑隔离键。

## 阅读路径

- 第一次理解项目：先读本页，再读 [运行主链与架构边界](./runtime-main-chain.md)。
- 准备增加能力：读 [连续性与能力面](./continuity-and-capabilities.md)，再核对相关 ADR 与 capability declaration。
- 准备修改知识检索：先读 [Knowledge/RAG Runtime](./knowledge-runtime.md)，再查看原设计证据与当前测试。
- 准备部署或排障：读 [运维与验证](./operations-and-verification.md)，再进入部署指南或 live checklist。
- 追溯历史迭代如何进入当前真相：先读 [旧迭代文档吸收地图](../notes/001-legacy-iteration-docs-map.md)，逐文件状态见 [文档生命周期台账](../notes/002-docs-lifecycle-inventory.md)。

## 当前边界

### 基线内

- HTTP 与 Feishu 共享 runtime 主链。
- Declarative binding 与 selected-agent routing。
- Builtin tools、MCP、文件型 skills 与 lightweight subagents。
- SQLite session persistence、bounded replay、compaction 与 structured memory。
- Namespace-scoped Knowledge/RAG、diagnostics、可选 Langfuse tracing 与离线 eval。

### 延后方向

- Durable delivery queue 与 worker-first execution。
- Planner / swarm orchestration。
- Host-side natural-language intent classifier。
- General memory platform 与无边界的 workflow platform。

## 关键考量

- 主链是系统中心。新增边界需要说明它怎样增强主链的正确性、可靠性、可操作性或可验证性。
- 能力选择由模型承担。宿主通过清晰描述、schema、权限、执行与错误诊断提高选择质量。
- 配置按职责分层：secrets 在 `.env`，公开默认值在 `config/*.example.toml`，本地覆盖在 `config/*.toml`，MCP live 定义在 `mcps.json`，agent 行为资产在 `agents/<agent_id>/`。
- 历史 design 与执行计划承担证据职责；当前真相由 `.cs/spec/`、活跃 README / docs、ADR、代码与验证共同确认。

## 质量约束与取舍

- 可靠性：同一会话按 FIFO lane 串行，provider 失败进入 retry / backoff / profile failover，外部 tracing 采用 fail-open 边界。
- 可维护性：runtime contract、capability family、agent assets、配置面和持久化职责保持清晰分层；关键边界由 ADR、测试与 diagnostics 共同保护。
- 性能效率：上下文恢复与 replay 有界，模型资产懒加载，Knowledge 在模型或 sqlite-vec 缺失时保留可诊断的 FTS 路径。
- 信息安全性：secrets 与本地配置留在被忽略文件，diagnostics 对敏感连接参数进行脱敏，模型与运行数据留在本地持久化目录。
- 灵活性：provider、model profile、agent tool surface、MCP server、Knowledge 模型与检索参数都通过声明式配置切换。

## 证据索引

- `README.md`
- `docs/README.md`
- `docs/ARCHITECTURE_EVOLUTION.md`
- `docs/ARCHITECTURE_CHANGELOG.md`
- `docs/architecture/adr/`
- `docs/CONFIG_SURFACES.md`
- `docs/DEPLOYMENT.md`
- `docs/LIVE_VERIFICATION_CHECKLIST.md`
- `AGENTS.md`
