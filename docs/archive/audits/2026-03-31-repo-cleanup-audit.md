# Repo Cleanup Audit

## Goal

在执行下一轮能力收敛实现前，先确认当前仓库是否存在应清理的临时产物、结构迁移残留、以及需要人工确认是否保留的历史设计/计划文档。

本审计只做分类，不在本文件中直接删除任何内容。

## Audit Date

- 2026-03-31

## Audit Inputs

- `git status --short`
- `find .logs -maxdepth 2 -type f`
- current docs tree under `docs/` and `docs/plans/`
- current `skills/` tree migration state

## Summary

当前仓库 **不干净**，原因不是单一问题，而是三类内容混在一起：

1. 正常且必须保留的阶段性实现结果
2. 明确应清理的临时验证产物
3. 需要人工确认保留策略的历史文档与导出物

结论：

- 不能直接做“一键清理”
- 应先删除明确的临时产物
- 再对文档保留策略做一次人工确认
- 结构迁移产生的 `D` 状态删除项大多属于预期变更，不应误判成垃圾

## Category A: Must Keep

这些内容与当前已完成实现直接对应，不应在清理时删除。

### A1. Current runtime implementation files

这些变更属于当前主实现：

- `src/marten_runtime/interfaces/http/bootstrap.py`
- `src/marten_runtime/skills/*`
- `src/marten_runtime/runtime/*`
- `src/marten_runtime/tools/builtins/automation_tool.py`
- `src/marten_runtime/tools/builtins/mcp_tool.py`
- `src/marten_runtime/tools/builtins/skill_tool.py`
- `src/marten_runtime/tools/builtins/self_improve_tool.py`
- `src/marten_runtime/data_access/*`
- `src/marten_runtime/self_improve/*`

### A2. Current test coverage

这些测试对应已落地实现，不应作为“历史垃圾”清理：

- `tests/test_runtime_mcp.py`
- `tests/test_skills.py`
- `tests/test_runtime_loop.py`
- `tests/test_contract_compatibility.py`
- `tests/test_tools.py`
- `tests/test_data_access_adapter.py`
- `tests/test_self_improve_*`

### A3. Current single-level skills structure

这些目录是当前结构收敛后的目标形态，应保留：

- `skills/automation_management/`
- `skills/example_repo_helper/`
- `skills/example_time/`
- `skills/github_trending_digest/`（后续已收敛为 MCP-first 能力并移除 skill 文件）
- `skills/self_improve/`
- `skills/self_improve_management/`

### A4. Current design / execution docs that match implemented slices

这些文档属于当前 repo 的阶段性设计与计划记录，当前 README/docs 也仍在引用其中一部分：

- `docs/2026-03-30-self-improve-design.md`
- `docs/archive/2026-03-31-agent-domain-query-adapter-design.md`
- `docs/archive/2026-03-31-automation-domain-adapter-design.md`
- `docs/2026-03-31-progressive-disclosure-llm-first-capability-design.md`
- `docs/plans/2026-03-30-self-improve-plan.md`
- `docs/plans/2026-03-31-agent-domain-query-adapter-plan.md`
- `docs/plans/2026-03-31-automation-domain-adapter-plan.md`
- `docs/plans/2026-03-31-progressive-disclosure-llm-first-capability-plan.md`
- `docs/plans/2026-03-31-progressive-disclosure-capability-refinement-plan.md`（historical at audit time; durable truth later moved to `docs/architecture/adr/0002-progressive-disclosure-default-surface.md`, `docs/ARCHITECTURE_CHANGELOG.md`, and `docs/ARCHITECTURE_EVOLUTION*.md`）

说明：

- 它们可能在将来需要做 docs index/README 收敛，但当前不能直接删
- 否则会破坏阶段性可追溯性和已有 docs 入口

## Category B: Safe To Remove

这些内容是临时验证产物或典型运行期噪声，删除风险低。

### B1. Local live verification log

- `.logs/live-smoke-20260331-8050.log`

判断依据：

- 属于一次性 live smoke 输出
- 不属于 repo 设计文档、测试用例、运行时必要资源
- `.logs/` 当前也未被 `.gitignore` 忽略

建议动作：

1. 删除 `.logs/live-smoke-20260331-8050.log`
2. 若未来仍需本地日志目录，补 `.gitignore`：
   - `.logs/`

## Category C: Needs Human Confirmation

这些内容不应由 agent 自动删除，需要先确认保留策略。

### C1. Runtime-managed lessons export

- `apps/example_assistant/SYSTEM_LESSONS.md`

判断依据：

- 这是运行时导出文件，不是典型源码
- 但 docs/README 当前已经把 `SYSTEM_LESSONS.md` 视作产品能力的一部分
- 如果删除，可能影响当前 self-improve slice 的真实状态展示

建议：

- 如果目标是“发布一个干净的开源仓库快照”，应考虑把该文件改成模板化基线内容，而不是直接保留本地学习结果
- 如果目标是“保留当前本地验证状态”，则继续保留

### C2. Historical design / plan accumulation

当前 `docs/` 与 `docs/plans/` 下积累了多份阶段性设计/计划：

- `docs/2026-03-29-private-agent-harness-design.md`
- `docs/2026-03-30-conversation-lanes-provider-resilience-design.md`
- `docs/2026-03-30-self-improve-design.md`
- `docs/archive/2026-03-31-agent-domain-query-adapter-design.md`
- `docs/archive/2026-03-31-automation-domain-adapter-design.md`
- `docs/2026-03-31-progressive-disclosure-llm-first-capability-design.md`
- `docs/plans/2026-03-27-runtime-integration-hardening-plan.md`
- `docs/plans/2026-03-28-feishu-websocket-first-migration-plan.md`
- `docs/plans/2026-03-29-feishu-live-verification-plan.md`
- `docs/plans/2026-03-29-private-agent-harness-plan.md`
- `docs/plans/2026-03-30-conversation-lanes-provider-resilience-plan.md`
- `docs/plans/2026-03-30-github-hot-repos-mvp-plan.md`
- `docs/plans/2026-03-30-self-improve-plan.md`
- `docs/plans/2026-03-31-agent-domain-query-adapter-plan.md`
- `docs/plans/2026-03-31-automation-domain-adapter-plan.md`
- `docs/plans/2026-03-31-progressive-disclosure-llm-first-capability-plan.md`
- `docs/plans/2026-03-31-progressive-disclosure-capability-refinement-plan.md`（historical example only; current repo no longer needs the full plan body because progressive-disclosure truth now lives in ADR/changelog/evolution docs）

判断依据：

- 这些不属于“垃圾文件”，而是阶段性 engineering record
- 但对于公开仓库或长期维护仓库，数量会继续膨胀

建议的人工决策方向：

- 方案 A：全部保留，作为 architecture history
- 方案 B：保留 design，压缩 plan 到一个 index 或 archive 区
- 方案 C：只保留 still-relevant design/plan，把过期计划迁到 `docs/archive/`

当前建议：

- 在未确认文档保留策略前，不删除任何一份设计/计划文档

### C3. Structure migration deletes shown in git status

当前 `git status` 中这些 `D` 项大概率是结构迁移的预期结果：

- `apps/example_assistant/skills/example_repo_helper/SKILL.md`
- `skills/shared/automation_management/SKILL.md`
- `skills/shared/github_trending_digest/SKILL.md`
- `skills/shared/github_trending_digest/references/github_mcp_capabilities.md`（历史结构示例；当前孤儿 reference 已删除）
- `skills/system/example_time/SKILL.md`

判断依据：

- 当前 repo 目标结构是单层 `skills/<skill_id>/`
- 对应的新目录已经存在于 repo 根 `skills/`

结论：

- 这些不是“应恢复的历史文件”
- 也不是“需要额外清理的垃圾”
- 它们应被视为结构迁移结果的一部分

## Drift Risks Found During Audit

### Risk 1: `.logs/` 未被忽略

问题：

- live 验证日志容易继续污染工作区

建议：

- 把 `.logs/` 加入 `.gitignore`

### Risk 2: docs index / README 还没有对“历史文档保留策略”做收敛

问题：

- 文档越来越多，但还没有 archive/index policy

建议：

- 在后续单独做一次 docs hygiene，不混入功能实现计划

### Risk 3: `SYSTEM_LESSONS.md` 的仓库定位尚未定案

问题：

- 它既像运行产物，又像产品能力导出

建议：

- 在清理动作前先决定它是：
  - baseline file
  - generated runtime artifact
  - example snapshot

## Recommended Cleanup Sequence

建议按这个顺序执行，避免误删：

1. 删除明确的临时日志文件
2. 把 `.logs/` 加入 `.gitignore`
3. 明确 `SYSTEM_LESSONS.md` 的保留策略
4. 明确 design/plan 文档的 archive 策略
5. 再做一次 `git status` 复核

## Current Audit Verdict

- Plan alignment: 可继续执行，但 `capability declaration` 已被要求限制为静态元数据复用层，不能长成 framework
- Repo cleanliness: 当前不干净
- Safe immediate cleanup: 只有 `.logs/live-smoke-20260331-8050.log`
- Cleanup requiring human confirmation:
  - `apps/example_assistant/SYSTEM_LESSONS.md`
  - historical design / plan document retention policy
