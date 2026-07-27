# `docs/` 文档生命周期台账

## 结论

`docs/` 当前包含 28 份 Markdown 文档，分成两类证据：

- **当前证据**：持续约束当前项目理解、配置、部署、验证或架构决策。
- **历史证据**：保存某次设计、执行、审计或演进阶段的原始推理。

CodeStable 承担面向后续开发的目标与当前真相：

- `.cs/vision/` 统领目标产品世界。
- `.cs/spec/` 统领当前项目能力、边界和质量约束。
- `.cs/notes/` 保存文档治理、技术选型和可复用历史判断。
- `.cs/epics/` 与 `.cs/issues/` 承接仍在演化或等待关闭的变化。

本轮已完成 3 个根目录设计归档迁移和 8 个详细文档合并。原始设计推理保留在 archive，执行清单的 durable outcomes 进入继任设计、压缩摘要和 architecture changelog。

## 状态词

| 字段 | 含义 |
| --- | --- |
| 当前证据 | 当前开发、运维或架构判断仍会直接读取 |
| 历史证据 | 用于追溯某个时间点的需求、方案、执行或审计 |
| 已吸收 | 长期结论已经进入 `.cs/spec/`、ADR、changelog 或稳定公开文档 |
| 部分吸收 | CodeStable 已保存主结论，原文仍承担详细契约或推理 |
| 未吸收 | 方案仍在评审，尚未进入当前项目真相 |
| 保留 | 文件继续承担清晰且独立的阅读职责 |
| 待评审 | 当前方案等待产品与实现边界确认 |
| 架构已确认；语料待评审 | 内置运行架构已确认，语料治理责任仍需产品确认 |
| 已迁移归档 | 文件已从 `docs/` 根目录进入 `docs/archive/` |
| 已接收合并 | 文件已经吸收被整理文档的独有结论 |

## 当前入口与稳定决策

| 文件 | 证据角色 | CodeStable 吸收 | 当前状态 | 主要职责或吸收位置 |
| --- | --- | --- | --- | --- |
| `docs/README.md` | 当前证据 | 部分吸收 | 保留并更新 | 公开文档导航；当前真相入口指向 `.cs/spec/index.md` |
| `docs/DEPLOYMENT.md` | 当前证据 | 部分吸收 | 保留 | 部署与排障契约；摘要进入 `.cs/spec/operations-and-verification.md` |
| `docs/CONFIG_SURFACES.md` | 当前证据 | 部分吸收 | 保留 | 配置归属契约；摘要进入 `.cs/spec/index.md` 与运维 spec |
| `docs/LIVE_VERIFICATION_CHECKLIST.md` | 当前证据 | 部分吸收 | 保留 | 外部实链验证证据；摘要进入运维 spec |
| `docs/ARCHITECTURE_EVOLUTION.md` | 当前证据 | 部分吸收 | 保留 | 当前快照与阶段叙事；主边界进入 runtime 与 capability spec |
| `docs/ARCHITECTURE_CHANGELOG.md` | 当前证据 | 部分吸收 | 保留并更新 | 追加式架构时间线和文档整理证据 |
| `docs/architecture/adr/README.md` | 当前证据 | 部分吸收 | 保留 | 稳定架构决策索引 |
| `docs/architecture/adr/0001-thin-harness-boundary.md` | 当前证据 | 已吸收 | 保留 | Thin harness 边界进入 `.cs/spec/runtime-main-chain.md` |
| `docs/architecture/adr/0002-progressive-disclosure-default-surface.md` | 当前证据 | 已吸收 | 保留 | Progressive disclosure 进入 runtime spec |
| `docs/architecture/adr/0003-self-improve-runtime-learning-not-architecture-memory.md` | 当前证据 | 已吸收 | 保留 | Self-improve 与 memory 分工进入 capability spec |
| `docs/architecture/adr/0004-llm-first-tool-routing-boundary.md` | 当前证据 | 已吸收 | 保留 | LLM-first routing 边界进入 runtime spec |

## 当前支持型设计

| 文件 | 证据角色 | CodeStable 吸收 | 当前状态 | 主要职责或吸收位置 |
| --- | --- | --- | --- | --- |
| `docs/2026-04-17-langfuse-observability-design.md` | 当前证据 | 部分吸收 | 保留 | Langfuse 详细接线和 fail-open 推理；摘要进入运维 spec |
| `docs/2026-04-30-main-chain-eval-foundation-design.md` | 当前证据 | 部分吸收 | 保留 | Eval harness 详细设计；摘要进入运维 spec |
| `docs/2026-05-11-provider-reliability-design.md` | 当前证据 | 部分吸收 | 保留 | Provider reliability 详细职责和诊断模型；摘要进入 capability 与运维 spec |

## 待评审设计

| 文件 | 证据角色 | CodeStable 吸收 | 当前状态 | 主要职责或吸收位置 |
| --- | --- | --- | --- | --- |
| `docs/2026-07-23-bazi-agent-design.md` | 当前证据 | 未吸收 | 实现契约、配置归属、地点解析与排盘算法口径已复核；穿刺与语料治理待执行 | Bazi Agent、builtin Bazi、bundled `taibu-core`、Taibu/Amap 地点解析、固定默认值与 secret 传播、时间/换日/起运契约、Knowledge/RAG 与领域 Skill 的组合方案 |

## Archive 设计、审计与演进证据

| 文件 | 证据角色 | CodeStable 吸收 | 当前状态 | 主要职责或吸收位置 |
| --- | --- | --- | --- | --- |
| `docs/archive/README.md` | 当前证据 | 部分吸收 | 保留并更新 | Archive 导航与整理结果 |
| `docs/archive/audits/ARCHITECTURE_AUDIT.md` | 历史证据 | 已吸收 | 保留 | ADR 0002 仍引用该审计，保存阶段性架构评估 |
| `docs/archive/branch-evolution/2026-04-09-fast-path-inventory-and-exit-strategy.md` | 历史证据 | 已吸收 | 保留 | 保存 fast-path deviation 与退出条件的独立证据 |
| `docs/archive/2026-03-29-private-agent-harness-design.md` | 历史证据 | 已吸收 | 已迁移归档 | 第一波 harness 设计推理 |
| `docs/archive/2026-03-31-progressive-disclosure-llm-first-capability-design.md` | 历史证据 | 已吸收 | 已迁移归档 | Progressive disclosure 与 LLM-first 原始设计推理 |
| `docs/archive/2026-04-01-feishu-generic-card-protocol-design.md` | 历史证据 | 已吸收 | 已迁移归档并接收合并 | Feishu renderer 设计与 message-pipeline 执行结论 |
| `docs/archive/2026-04-06-thin-llm-context-compaction-design.md` | 历史证据 | 已吸收 | 保留并接收合并 | Compaction 设计与原执行计划 durable outcomes |
| `docs/archive/2026-04-07-context-usage-accuracy-design.md` | 历史证据 | 已吸收 | 保留并接收合并 | Usage accuracy 设计与原执行计划 durable outcomes |
| `docs/archive/2026-04-07-llm-tool-episode-summary-design.md` | 历史证据 | 已吸收 | 保留并接收合并 | Tool episode 设计与原执行计划 durable outcomes |

## Archive 压缩摘要

| 文件 | 证据角色 | CodeStable 吸收 | 当前状态 | 主要职责或吸收位置 |
| --- | --- | --- | --- | --- |
| `docs/archive/plans/2026-04-11-repo-slimming-summary.md` | 历史证据 | 已吸收 | 保留并接收合并 | Repo slimming 与 bootstrap assembly hygiene 结果 |
| `docs/archive/plans/2026-04-28-status-history-summary.md` | 历史证据 | 已吸收 | 保留并接收合并 | STATUS 历史与 deep cleanup wave 结果 |
| `docs/archive/plans/2026-05-01-eval-foundation-summary.md` | 历史证据 | 已吸收 | 保留 | Eval 执行证据，详细设计由 2026-04-30 design 承担 |
| `docs/archive/plans/2026-05-05-llm-first-review-summary.md` | 历史证据 | 已吸收 | 新增压缩摘要 | 23 轮 review 的 7 个根因组、合同与验证结果 |

## 本轮整理记录

### 已迁移归档

- `2026-03-29-private-agent-harness-design.md`
- `2026-03-31-progressive-disclosure-llm-first-capability-design.md`
- `2026-04-01-feishu-generic-card-protocol-design.md`

### 已合并并移除详细文件

- `2026-04-28-deep-repo-cleanup-checklist.md` → `2026-04-28-status-history-summary.md`
- `2026-05-05-llm-first-review-ledger.md` → `2026-05-05-llm-first-review-summary.md`
- `2026-04-01-bootstrap-assembly-hygiene-plan.md` → `2026-04-11-repo-slimming-summary.md`
- `2026-04-01-feishu-message-pipeline-unification-plan.md` → `2026-04-01-feishu-generic-card-protocol-design.md`
- `2026-04-05-github-trending-mcp-plan.md` → `ARCHITECTURE_CHANGELOG.md` 与 capability spec
- `2026-04-07-thin-llm-context-compaction-plan.md` → compaction design
- `2026-04-07-context-usage-accuracy-plan.md` → context usage design
- `2026-04-07-llm-tool-episode-summary-plan.md` → tool episode summary design

## 分类后的阅读顺序

### 理解当前系统

1. `.cs/spec/index.md`
2. `.cs/spec/runtime-main-chain.md`
3. `.cs/spec/continuity-and-capabilities.md`
4. `.cs/spec/operations-and-verification.md`
5. 相关 ADR、公开运维文档与代码证据

### 追溯决策

1. 相关 `.cs/spec/` 章节
2. 对应 ADR
3. `docs/ARCHITECTURE_CHANGELOG.md`
4. 日期型 design 或 archive 原始证据

## 资产边界

`docs/assets/` 保存公开文档引用的图片证据。图片跟随引用它们的当前文档保留，其生命周期由引用关系决定。

## 相关位置

- `.cs/notes/001-legacy-iteration-docs-map.md`
- `.cs/spec/index.md`
- `docs/README.md`
- `docs/archive/README.md`
