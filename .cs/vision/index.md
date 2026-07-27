# Vision

## 产品核心

`marten-runtime` 面向希望自托管 agent 的开发者与运维者，目标是提供一条清晰、可靠、可扩展、可诊断的执行路径：用户从熟悉的 channel 发起任务，agent 根据声明式资产和能力目录理解请求、调用工具并交付结果，维护者可以验证整条链路发生了什么。

目标体验的最小本质是：用较少的宿主复杂度，获得一套真实可运行的 agent runtime harness。

## 用户旅程

- 部署并启动：使用者准备一个 provider credential，通过本地进程或容器启动 runtime，并从 health、ready 与 diagnostics 确认系统状态。
- 发起 agent 任务：用户从 HTTP 或实时聊天入口发送请求，binding 选择 agent，LLM 组合 builtin、MCP、skill、Knowledge 或 subagent 完成任务。
- 扩展能力：开发者用声明式配置、MCP server、文件型 skill 或 bounded builtin capability 接入新能力，保持首轮能力面紧凑。
- 延续上下文：用户在 session 中连续工作，通过 memory 保存跨会话稳定事实，通过 Knowledge 使用可检索资料。
- 观察与改进：维护者从 diagnostics、tracing、测试和 eval 找到真实执行证据，判断一次变化对主链与用户结果的影响。

## 能力版图

- Channel 与 binding：承接 HTTP、Feishu 等入口，并把请求路由到 selected agent。
- Agent runtime：组装 agent-owned assets、上下文、model profile 与 capability surface，驱动 LLM 和工具往返。
- 能力生态：builtin family、MCP、skills、Knowledge、automation 与 lightweight subagents。
- 连续性：session persistence、bounded replay、compaction、memory 与 tool outcome continuity。
- 运维证明：health、ready、runtime / session / run / trace diagnostics、可选 tracing 与离线 eval。

## 基础与边界

- LLM-first：普通自然语言的理解、能力选择和组合留在模型路径。
- Thin harness：宿主聚焦声明、组装、执行、校验、恢复、持久化、投递和诊断。
- Progressive disclosure：能力先以稳定摘要暴露，skill 正文与 MCP tool 细节按需展开。
- Self-hosted 与 local-first：secrets、运行数据、模型资产和本地 override 由部署者控制。
- 主链优先：新能力需要增强执行路径的正确性、可靠性、可操作性或可验证性。
- Bounded slices：连续性、记忆、Knowledge、automation、subagent、tracing 与 eval 都以明确职责接入。

## 目标质量方向

- 可靠性：交互式主链在并发 turn、provider 抖动、长上下文、工具调用和 channel 投递条件下保持可恢复与可诊断。
- 可维护性：架构边界、agent 资产、配置面、能力契约和持久化职责保持清晰。
- 交互能力：使用者能从少量入口完成启动、发起任务、查看状态和定位问题。
- 灵活性：provider、model profile、agent、channel、MCP、skill 与 Knowledge 配置可以独立演化。
- 信息安全性：secrets、token、运行数据和敏感 diagnostics 受到本地边界与脱敏规则保护。

## 探索空间

现有历史文档记录过 durable queue、worker-first execution、planner / swarm、general memory platform 与领域型 Knowledge agent 等方向。它们保留为历史候选或延后方向，本次初始化未把这些方向提升为已确认产品目标。

新的跨 Epic 产品方向需要用户确认后进入本 Vision，并说明它服务的用户旅程、与现有能力区域的关系和进入基线的条件。

## 演化地图

- Runtime 主链：实现状态 `已实现`；当前现实见 [Project Spec](../spec/index.md) 与 [运行主链](../spec/runtime-main-chain.md)。
- 连续性与能力面：实现状态 `已实现`；当前现实见 [连续性与能力面](../spec/continuity-and-capabilities.md)。
- Knowledge/RAG：实现状态 `已实现`；当前现实见 [Knowledge/RAG Runtime](../spec/knowledge-runtime.md)。
- 运维、诊断与评测：实现状态 `已实现`；当前现实见 [运维与验证](../spec/operations-and-verification.md)。
- 新产品区域：实现状态 `未切片`；由后续用户确认的 Vision 分支与 Epic 承接。

## 统一语言

- **Agent runtime harness**：围绕 agent 执行主链提供组装、执行、持久化、投递与诊断的宿主系统。
- **主链**：用户请求从 channel 到 agent、LLM、能力调用、最终投递与诊断的完整路径。
- **能力区域**：可由模型选择并通过明确契约执行的 builtin、MCP、skill 或 bounded subsystem。
- **目标方向**：用户确认希望进入产品世界的长期结果。
- **历史候选**：在旧设计或计划中出现、当前仍保留讨论价值的方向。

## 阅读路径

- 想理解用户最终如何获得结果：从本页“用户旅程”开始，再读 [Project Spec](../spec/index.md)。
- 想理解当前 runtime 能力：读 [Project Spec](../spec/index.md) 的能力地图。
- 想查看历史方向怎样进入当前现实：读 [旧迭代文档吸收地图](../notes/001-legacy-iteration-docs-map.md)。
- 想从愿景摘取开发切片：先确认目标方向，再根据变化范围进入 Epic、Issue 或直接改。
