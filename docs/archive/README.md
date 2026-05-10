# 归档索引

这个目录只保留少量仍有审计追溯价值的历史文档。

## 这里保留什么

- 仍然有助于解释旧代码或旧清理决策的过时设计历史
- 较早的清理 / 架构审计
- 少量已归档的执行计划，它们的长期真相已经进入活跃文档

## 当前分组

- 根目录归档设计说明：
  - `2026-04-06-thin-llm-context-compaction-design.md`
  - `2026-04-07-context-usage-accuracy-design.md`
  - `2026-04-07-llm-tool-episode-summary-design.md`
- `audits/`
  - 只在仍然具有独立追溯价值时保留的较早架构 / 清理审计
- `branch-evolution/`
  - 2026-04-09 branch-evolution 阶段保留的一份 fast-path inventory 说明
- `plans/`
  - 为 2026-04-14 之前工作保留的少量历史执行计划
  - 2026-04-30 与 2026-05-01 评测执行计划的压缩摘要
  - 2026-04-28 压缩后的 `STATUS.md` 历史摘要

## 已吸收后移除

2026-04-14 到 2026-04-25 的 plan/spec 波次，已在 2026-04-27 移除，对应长期结论已经吸收到 `README.md`、`docs/DEPLOYMENT.md`、`docs/ARCHITECTURE_EVOLUTION.md`、`docs/ARCHITECTURE_CHANGELOG.md` 与 `docs/CONFIG_SURFACES.md`。

2026-03-31 的 adapter-wave 三份归档文档，已在 2026-04-28 移除，因为 direct-store runtime 基线已经成为代码、测试、`README.md`、`docs/README.md` 与 `docs/ARCHITECTURE_CHANGELOG.md` 中唯一的活跃控制面形态。

## 规则

- 归档目录不属于主阅读路径。
- 稳定架构真相放在 `docs/architecture/adr/` 与 `docs/ARCHITECTURE_CHANGELOG.md`。
- 当前运维与部署真相放在主文档路径。
- 归档目录保持精简。
