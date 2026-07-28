---
kind: issue
title: "Bazi Agent 与 RAG 真实主链穿刺"
type: feature
status: open
created: 2026-07-24
epic: ".cs/epics/001-o-bazi-agent/spec.md"
---

# Bazi Agent 与 RAG 真实主链穿刺

## 目标

用户通过 selected-agent 直达路径获得一次完整的 Bazi 回答：输入确认、排盘、按需大运、theory 检索、引用、风险表达、投递与脱敏 diagnostics 全部闭环。main 自然语言 handoff 由 issue `009` 补齐。

## 范围

- 包含：Bazi agent 资产、always-on skill、binding、所有 Knowledge-enabled agent 的显式 action/namespace scope、最小许可 theory fixture、HTTP/Feishu 真实主链。
- 不包含：生产案例库、Knowledge Console UI、Memory 跨会话保存和生产镜像发布。

## 归属

- 隶属 Epic：`.cs/epics/001-o-bazi-agent/spec.md`
- 依赖：`003` Bazi runtime、`004` Knowledge Operator 后端。

## 质量目标

- 功能适宜性：回答明确区分日历事实、engine 标注、theory 引用、综合判断与现实建议；以 eval grader 和真实主链检查验证。
- 信息安全性：Bazi agent 只拥有 `bazi`、只读 Knowledge 与 `time`，敏感原文不进入观测后端；以越权和字段扫描验证。
- 交互能力：缺字段、地点歧义、provider 故障与 Knowledge 降级都提供明确修正动作；以多轮 fixture 验证。

## 执行 Chunk

- `C09`：AgentSpec scope、Bazi agent、binding 与 skill。
- `C10`：Theory 入库、RAG eval 与 HTTP/Feishu 真实主链。
- 权威步骤、测试命令与完成条件见 `.cs/epics/001-o-bazi-agent/spec.md` 的 `C09-C10`。

## 一步步怎么改

1. 增加 `agents/bazi/` 角色资产与 `skills/bazi_analysis/SKILL.md`。
2. 扩展 AgentSpec/loader/tool context 的 Knowledge action/namespace scope 与 observation policy。
3. 配置精确 binding 和隔离 tool surface；迁移共享实例的其他 Knowledge-enabled agent，禁止 agent 对 Bazi namespace 执行写 action。
4. 通过 Operator API 录入许可已确认的最小 `bazi-theory` source。
5. 打通 HTTP 主链，再打通 Feishu 主链与脱敏 diagnostics。
6. 增加 Bazi skill、scope、引用、降级、风险表达与 tool-order eval。

## 验证

- Bazi agent 对 Knowledge 写 action、其他 namespace、通用 MCP 与 memory 均返回稳定拒绝。
- 共享配置中所有 Knowledge-enabled agent 都使用显式 scope，任何 agent 对 `bazi-theory`/`bazi-cases` 的写 action 均被拒绝。
- theory 召回时运行时保留真实 `source_id/chunk_id`，用户回答显示 `source_title/heading`；无召回或模型缺失时保留排盘事实和降级说明。
- chart/dayun fingerprint 一致，地点或时间口径不一致时停止综合解释。
- HTTP 与 Feishu 的最终回答、run、trace、tool span 和 diagnostics 可以用同一 request/run/fingerprint 关联。

## 执行记录

- `C09` 已完成：AgentSpec 增加显式 Knowledge namespace/action scope 与 `sensitive_bazi` observation policy。
- `bazi` agent 固定工具为 `bazi`、`knowledge`、`time`，Knowledge 仅允许读取 `bazi-theory` 与 `bazi-cases`。
- 已增加 Bazi agent 资产、always-on `bazi_analysis` skill 与 Feishu 精确会话 binding。
- production readiness 会拒绝 Knowledge-enabled agent 的 family-level scope，并检查 Bazi namespace 保持只读。
- 运行 80 项 AgentSpec、binding、skill、bootstrap、capability、diagnostics 与敏感观测测试，全部通过。
- `C10` 已完成：Operator API 上传并完成 reviewed `bazi-theory` fixture 入库，HTTP requested-agent 与 Feishu exact binding 均完成真实 Bazi -> Knowledge -> answer 主链。
- Bazi grader 校验内部真实引用、用户可读书名与篇章、chart/dayun fingerprint、工具顺序、无召回降级、mismatch 停止解释和风险表达。
- scripted Bazi eval 5/5、100 分；C10 聚焦主链 31/31；全部 Bazi 回归 41/41；`compileall` 与 `git diff --check` 通过。
- 最终四柱真实链路 `run_fa7d9283` 使用 `gpt-5.4`，执行 `bazi.resolve_pillars` 与 `knowledge.search`；Knowledge 为 `hybrid_rerank`，vector/reranker 均可用，2 条真实引用全部进入飞书卡片并完成投递。
- 最终农历真太阳时真实链路 `run_8136a7c7` 使用 `gpt-5.4`，执行 `bazi.chart` 与 `knowledge.search`；地点由 Amap 解析到区县，算法为 `taibu_true_solar_v1`，换日为 `lunar_javascript_sect1`，2 条真实引用全部进入飞书卡片并完成投递。
- 两条最终消息均无未解析工具标记；Bazi 排盘后 Knowledge 强制检索、完整引用注入和飞书卡片协议恢复均通过真实链路验证。
- 2026-07-26 架构复核确认：该 issue 验证了 requested-agent 与精确 binding 直达路径，默认 Feishu main 的自然语言 handoff 尚未实现，转由 issue `009` 管理。
