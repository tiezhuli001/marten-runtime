# 旧迭代文档吸收地图

## 结论

仓库里的旧 design、plan、checklist 与 EasySDD feature 文档仍有追溯价值。CodeStable 接入采用“当前真相进入 Project Spec，历史过程留在原文档，稳定决策继续由 ADR 与 architecture changelog 提供证据”的组织方式。

本次已经吸收：

- Runtime 主链、thin harness、LLM-first、agent-owned assets、连续性、能力面、运维与质量约束进入 `.cs/spec/`。
- Knowledge/RAG 迭代中仍成立的能力、数据边界、模型策略、降级、reindex 与验证进入 `.cs/spec/knowledge-runtime.md`。
- 原有文档保持原路径，供设计推理、历史命令和技术选型追溯。

## 触发场景

处理以下任务前使用本 note：

- 准备迁移、删除或归档旧 design / plan 文档。
- 发现旧文档状态与代码现实冲突。
- 需要判断一条结论应进入 `.cs/spec/`、`.cs/epics/`、`.cs/issues/` 或 `.cs/notes/`。
- 需要追溯某项 runtime capability 为什么采用当前边界。

## 文档分组与吸收判断

### 活跃架构真相

以下文档继续作为当前证据源，并由 `.cs/spec/` 提供面向开发者的阅读入口：

- `README.md` 与 `docs/README.md`：当前范围、能力和主阅读路径。
- `docs/ARCHITECTURE_EVOLUTION.md`：面向新读者的阶段叙事。
- `docs/ARCHITECTURE_CHANGELOG.md`：追加式架构时间线与验证证据。
- `docs/architecture/adr/`：长期稳定的架构决策。
- `docs/CONFIG_SURFACES.md`、`docs/DEPLOYMENT.md`、`docs/LIVE_VERIFICATION_CHECKLIST.md`：配置、部署和实链验证真相。

### 日期命名的 design 与 review 文档

`docs/2026-*.md` 保留仍承担当前支持职责的设计，`docs/archive/2026-*.md` 保存已完成阶段的完整设计推理。长期仍成立的结论由 ADR、changelog、当前代码和 `.cs/spec/` 统领。

处理规则：

- 当前行为与边界优先读取 `.cs/spec/`、ADR、changelog、代码与测试。
- 需要了解被选方案、排除方向或阶段风险时，再进入对应 design。
- Design 的历史措辞与当前代码发生漂移时，在活跃真相层修正，并保留原文档的时间点语义。

### `docs/archive/`

Archive 保存少量仍有审计价值的旧设计、审计和执行计划。`docs/archive/README.md` 已明确记录 2026-04-14 到 2026-04-25 等波次的长期结论已经进入活跃文档。

这些计划继续承担证据职责。CodeStable 无需为已完成计划补建 open issue 或 epic，也无需复制逐步执行清单。

### EasySDD Knowledge/RAG feature

目录：`easysdd/features/2026-05-19-knowledge-rag-runtime/`

三份材料分别承担：

- `knowledge-rag-runtime-design.md`：接口、数据、边界与实现方案。
- `knowledge-rag-runtime-execution-plan.md`：按 chunk 推进和退出信号。
- `knowledge-rag-runtime-selection-research.md`：embedding、reranker 与 vector store 选型依据。

当前代码已经包含 `src/marten_runtime/knowledge/`、builtin `knowledge`、skill、配置、测试与 `knowledge_retrieval` eval。`docs/ARCHITECTURE_CHANGELOG.md` 的 2026-05-19 条目记录了该能力进入基线。原文 frontmatter 的 `status: draft` 已经落后于实现状态。

长期结论已进入 `.cs/spec/knowledge-runtime.md`。三份原文继续作为技术证据，后续可以在专门的文档清理任务中统一修正元数据或迁移目录。

## 后续 CodeStable 归属

- 当前稳定项目行为与边界：`.cs/spec/`。
- 跨模块、分批推进、仍在变化的大需求：`.cs/epics/{NNN}-o-{name}/spec.md`。
- 可关闭行动与验证：`.cs/issues/{NNN}-o-{name}.md`。
- 小改追溯：完成后写 `.cs/issues/{NNN}-x-ff-{name}.md`。
- 可复用调研与操作经验：`.cs/notes/{NNN}-{name}.md`。
- 产品目标全景：用户确认后维护 `.cs/vision/`。

## 相关位置

- `.cs/notes/002-docs-lifecycle-inventory.md`
- `.cs/spec/index.md`
- `.cs/spec/runtime-main-chain.md`
- `.cs/spec/continuity-and-capabilities.md`
- `.cs/spec/knowledge-runtime.md`
- `.cs/spec/operations-and-verification.md`
- `docs/archive/README.md`
- `docs/ARCHITECTURE_CHANGELOG.md`
- `easysdd/features/2026-05-19-knowledge-rag-runtime/`
