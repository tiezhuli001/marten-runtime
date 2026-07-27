---
kind: issue
title: "Main 顶层 Agent 意图路由与同步 Handoff"
type: feature
status: open
created: 2026-07-26
epic: ".cs/epics/001-o-bazi-agent/spec.md"
---

# Main 顶层 Agent 意图路由与同步 Handoff

## 目标

默认 HTTP/Feishu 消息由 `main` 识别领域意图，并在同一用户 turn 内同步 handoff 给已注册的同级顶层 agent。八字请求进入 `bazi` 的完整 prompt、Skill、工具、Knowledge scope、模型与敏感观测环境，只向用户投递 Bazi 的最终回复。

## 架构契约

- `main`、`bazi`、后续 `fanqie` 属于服务启动时注册的顶层 agent；每个 agent 拥有独立 AgentSpec 与资产。
- `spawn_subagent` 只创建当前顶层 agent 的临时子任务，保持现有 child session、tool profile、队列和通知语义。
- `AgentSpec` 增加 `routing_description` 与 `allowed_handoff_agents`；main 的路由目录只包含已启用且获授权的目标。
- 默认 binding 选择 main；`requested_agent_id` 与 conversation/user 精确 binding 保留直达能力。
- main 路由阶段输出结构化目标 agent id。宿主限制每 turn 一次 handoff，校验目标注册、启用和授权，并禁止 handoff 环路。
- 目标 run 使用原始用户消息、同一 trace、独立 run id 和 `parent_run_id`；目标 agent 的 runtime assets、tool snapshot、Skill、Knowledge scope、model profile 与 observation policy 全量生效。
- 路由阶段不产生 channel 回复，也不写 assistant history；用户消息写一次，目标最终回复写一次。
- 自然语言 handoff 只作用于当前 turn；session 默认入口保持 main，连续跟进与领域切换在下一轮重新路由。
- 路由观测采用 metadata-only 策略，保存目标、模型、usage、延迟与错误，省略原始消息和模型输出正文。

## 实现边界

- AgentSpec/loader：顶层路由描述与授权目标。
- Agent registry：生成稳定、紧凑的可路由 agent catalog，并在启动时校验引用。
- Runtime：新增顶层 dispatch/handoff 协议，复用 provider retry、timeout、run history 与 trace lineage。
- HTTP/Feishu handler：一次 ingress 内执行 main dispatch 与目标 run，统一持久化和最终投递。
- Config：删除占位 Bazi conversation binding；HTTP/Feishu 默认 binding 保持 main。
- Bazi 输入：明确农历直接映射 `calendarType=lunar`，普通月份默认 `isLeapMonth=false`，中国大陆区县地点直接进入真太阳时解析。

## 验证

1. AgentSpec loader 拒绝空描述、未知/禁用 handoff 目标和自引用。
2. 普通问答路由到 main；农历出生资料、四柱、子平格局法、盲派与大运请求路由到 bazi；含糊跟进结合最近会话判断。
3. main 路由 run 的工具面不泄露给 Bazi，Bazi run 精确获得 `bazi/knowledge/time` 和 `sensitive_bazi`。
4. 每轮最多一次 handoff；无中间确认回复、无重复用户消息、无重复 assistant 消息。
5. HTTP requested-agent、精确 binding、automation 与 subagent 现有路径保持通过。
6. 真实飞书原始样例产生 `main dispatch -> bazi.chart -> knowledge.search -> final delivery`，且不再询问农历是否换算公历。

## 完成条件

- 设计中的顶层 agent、handoff、binding 与 subagent 术语和代码一致。
- 单元、集成、Bazi eval、完整 Python/Node 回归与真实飞书链路全部通过。
- 诊断能关联 main 路由 run 与 Bazi run，并证明敏感路由正文未进入外部观测。

## 执行记录

- 已增加 `routing_description`、`allowed_handoff_agents`、registry catalog 与启动校验。
- 已实现强制 `agent_route` 结构化调用、`metadata_only` 路由 run、目标 run `parent_run_id` 和同 trace 诊断。
- 默认 HTTP/Feishu main 请求可 handoff 到 Bazi；requested agent、精确 binding、automation 与 subagent 保持独立入口。
- 路由 provider 失败已转换为标准 error event，并保留失败 route run。
- 自动化验证通过：Python `1488/1488`、Node `43/43`、Bazi scripted eval `5/5` 且 100 分、`compileall`、`pip check`、`git diff --check`。
- 真实验收已完成：模拟飞书入站进入 main，真实模型路由到 Bazi，依次调用一次 `bazi.chart` 与一次 `knowledge.search`，通过真实飞书 API 投递最终卡片，死信为 0。
- 持久化正文包含完整四柱两行、可读来源标题，内部 Knowledge ID 为 0；本轮最后两条消息为 `user -> assistant`。issue 保持 open，等待关闭授权。
- 提交前审查修复了 handoff 后 session 错误停留在 Bazi 的问题；连续两个默认 HTTP turn 均产生独立 main 路由 run，显式 requested agent 与精确 binding 的持续语义保持不变。
