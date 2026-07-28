---
kind: epic
title: "Knowledge 经典书籍层与管理入口"
status: open
created: 2026-07-28
---

# Knowledge 经典书籍层与管理入口

## 决策状态

- 2026-07-28 用户确认采用“两阶段 Knowledge”路线，并批准阶段一优先实施。
- 阶段一固定交付经典书籍层、Knowledge Console、真实语料检索基线、发布/回滚与稳定后的性能基准。
- 阶段二案例库不阻塞阶段一；阶段一实现保持 namespace、citation 与管理契约可被案例投影复用。

## 这个 Epic 要改变什么

把已经可用的 Knowledge/RAG runtime，从“最小 fixture 能闭环”推进到“Operator 可以通过 UI 管理经典书籍，生产语料可追溯、可重复发布，检索质量可量化，配置与真实延迟有稳定证据”。第一条参考变化线使用 `bazi-theory`，但 Console、manifest、验证、eval 和发布方法保持领域无关。

## 为什么现在做

当前底层能力、Operator API、Bazi 真实 RAG 主链和降级路径已经进入 `main`，但生产导入仍要求人工拼装 multipart/API 调用。用户已经确认需要 UI 作为长期管理入口；剩余主要风险是 UI 若先于 corpus contract，会固化不完整 metadata 与不可复现的发布过程。因此本阶段先固定 manifest/preview/publish 契约，再用窄 Console 承载它，随后稳定检索质量。

## 来源 Vision 与 Project Spec

- `.cs/vision/index.md`：可组合 Knowledge 能力、自托管数据边界与主链可验证性。
- `.cs/spec/knowledge-runtime.md`：当前入库、检索、模型、降级、Operator 与后续真实性能基准契约。
- `.cs/notes/004-bazi-classical-source-audit.md`：古籍来源、许可、固定版本和目标 production theory 书目。
- `docs/2026-07-23-bazi-agent-design.md`：`bazi-theory` / `bazi-cases` 分工、source metadata、引用和生产语料责任边界。
- `.cs/notes/005-knowledge-runtime-selection-history.md`：底层技术选型和第一版实现历史证据。

## 当前真相

- KnowledgeService 已提供 namespace 隔离的文本入库、Markdown 标题感知 chunk、FTS/vector/hybrid retrieval、rerank、引用、删除、reindex、job、模型状态与统计。
- Operator API 已提供 Bearer 保护的查询、`.txt/.md` 上传、软删除、reindex、分页、`10 MiB` 上限、reviewed metadata、staging 清理与重启恢复。
- Knowledge Console 已提供短时签名 session、CSRF、source/job/chunk 浏览、upload preview/publish、检索试查、reindex 与显式删除；非法 namespace 返回 422，不会静默落入默认库。
- `bazi-theory-classics-selected-v1` 已固定六个经典选段、12 个 chunk、manifest/digest、12 个 gold case 和候选代码树绑定报告；隔离真实 BGE baseline 的全部质量指标为 1.0，空结果与禁止来源命中为 0。
- 空库发布、重复发布、缺 embedding 自动修复、namespace reindex、显式删除与 manifest 重放均已演练；manifest 外 source 只报告 drift，不自动删除。
- 2026-07-28 经用户授权，Operator 已显式删除本地 `bazi-theory` 的 9 个 manifest 外旧 source；随后用户通过 Console 审核《子平真诠》本义完整版，当前正式库为 7 sources / 110 chunks，release plan 有 1 个 manifest 外 drift。
- 当前 Console 支持完整 chunk preview、上传级 chunk 参数、namespace embedding profile、检索临时参数和原子 namespace reindex。
- Console 导入表单已简化为文件、可选标题和可选来源链接；其余索引 identity 与内部 metadata 自动生成，Jobs 在 UI 中命名为“导入任务”。
- 当前默认 BGE embedding、BGE reranker、SQLite FTS5 与 sqlite-vec 保持基线，不因缺少生产 corpus 证据而先行替换。
- 本地 `bazi-theory-sandbox` 的独立 namespace eval 记录了审核前快照：整书去重后为 15 sources / 792 chunks、23 个查询，Recall@1 为 0.9130、Recall@3/5 为 1.0、MRR 为 0.9565。审核《子平真诠》本义完整版后，草稿箱当前为 14 sources / 694 chunks。
- `bazi-theory-sandbox` 现作为 UI 草稿箱，不参与 Bazi Agent 解盘检索；`bazi-theory` 是唯一正式理论检索 namespace。Console 上传、导入任务、审核发布和正式检索已经形成单一流程。

## 范围边界

### 本 Epic 包含

- 可版本化的 corpus manifest、source digest、reviewed metadata 与发布标识。
- 复用现有 Operator/KnowledgeService 的 validate/preview、dry-run、幂等 publish 与 drift 路径。
- 受现有 Operator 权限保护的 Knowledge Console：namespace/source/job 浏览、书籍上传、metadata 编辑、chunk preview、发布、删除确认、reindex 与检索试查。
- 沿用 FastAPI server-rendered HTML 的轻量实现，不为一个管理页引入独立 React/Vue 前端构建链。
- 基于真实 corpus 的 gold query set、离线召回/排序/引用质量基线与失败切片。
- 由 eval 证据驱动的 chunking、candidate pool、ranking weight 和 reranker 参数调整。
- corpus 发布、reindex、回滚、diagnostics 和固定配置记录。
- 检索形态稳定后的 3 次 live smoke 与每场景至少 20 次正式性能基准。

### 本 Epic 不包含

- 多角色 RBAC、多人会签审批、富文本在线编辑器或通用 CMS。
- PDF/Word/网页抓取、多模态、GraphRAG 或外部向量数据库。
- 结构化 `bazi-cases` 保存与双层推理；它由下一阶段 `.cs/epics/003-o-bazi-case-library/spec.md` 管理。
- 无 eval 证据的 embedding/reranker 更换、在线双索引迁移或自动 reindex。
- 将受版权限制、个人敏感或未 reviewed 的正文提交到仓库。

## 规划结论

阶段一先交付经典书籍层。当前第一个切片仍是 corpus manifest、preview/publish contract 和 baseline，因为 UI 必须建立在稳定契约上；随后立即交付窄 Knowledge Console。案例 schema 在阶段一期间完成设计，但案例保存、共享和双层检索放到阶段二实施。

## 工作分类

### 实现事项

1. 定义领域无关的 corpus manifest 与 validator，复用现有 source metadata、`uri + version` 幂等语义和 Operator API。
2. 增加 validate/preview 与 dry-run/publish contract，输出 create/update/unchanged/error；缺失于 manifest 的线上 source 不自动删除。
3. 增加 server-rendered Knowledge Console，复用同一 contract 完成上传、预览、发布、job 观察、删除、reindex 与试查。
4. 增加 corpus-scale retrieval dataset、grader 与报告，记录 corpus release、Knowledge config hash 和逐查询证据。
5. 只对被 baseline 证明的问题调整现有 chunk/search 配置或最小代码边界。
6. 固定发布、reindex、回滚与性能基准操作步骤。

### 产品确认事项

1. `bazi-theory` 第一版 release 的明确篇章范围，以及是否允许声明“覆盖”而不是“完整收录”。
2. corpus owner、内容 reviewer 与发布批准责任人。
3. 近现代资料的正式书目信息、授权依据和可保存内容边界。
4. `bazi-cases` 的许可、匿名化标准和审核责任；未确认前保持 deferred。

### 证据采集事项

1. 目标书目/篇章覆盖矩阵、来源固定 revision、digest 和 metadata 完整率。
2. 关键词、释义、跨章节、负向/歧义查询的 Recall@K、MRR、首条命中、引用完整率和失败样本。
3. FTS-only、hybrid rerank、不同 candidate pool/chunk 参数的可重复对照。
4. 稳定配置后的 HTTP/runtime/provider 分段延迟、tokens、retry/fallback 和失败率。

## Issues

- [x] `.cs/issues/010-o-knowledge-corpus-baseline.md`：实现与验证完成；保持 open，等待 production owner/reviewer/approver 和用户关闭授权。
- [x] `.cs/issues/011-o-knowledge-console-classics.md`：实现与验证完成；保持 open，等待用户关闭授权。
- [x] `.cs/issues/012-o-knowledge-console-index-profiles.md`：上传级 chunk 参数、namespace embedding profile、原子 reindex 与检索试查参数已实现并验证。
- [x] `.cs/issues/013-o-knowledge-rag-answer-quality.md`：实现与验证完成；Issue 保持 open，等待用户关闭授权。
- `013` 由当前正式语料失衡、概念查询噪声、冷启动延迟和完整 Bazi Agent 解释成本的实测证据触发；不预建模型迁移事项。

## 执行 Chunk

| Chunk | 完成目标 | 主要证据 |
| --- | --- | --- |
| `K00` | 固定 corpus release、治理责任和基线快照 | `部分完成`：release/schema/config 已固定，production 责任人待确认 |
| `K01` | 完成 manifest validator 与幂等 preview/publish | `完成`：validator/publisher/preview 与缺向量恢复通过 |
| `K02` | 交付经典书籍 Knowledge Console | `完成`：auth、preview/publish/review/search、chunk/profile 参数、reindex 与 delete 通过 |
| `K03` | 建立真实 corpus gold set 与离线检索基线 | `完成`：12/12 case，全部核心指标 1.0 |
| `K04` | 只修复有证据的 chunk/retrieval 问题 | `无需改动`：当前隔离 baseline 未发现检索失败切片 |
| `K05` | 固定 corpus 发布、reindex 与回滚 | `完成`：空库、幂等、缺向量、删除后重放均通过 |
| `K06` | 完成 live smoke 与正式性能基准 | `移出阶段一完成条件`：按用户决策等待 RAG/corpus/output contract 完全冻结后单独执行 |
| `K07` | 完成 RAG 概念问答质量迭代 | `完成`：v2 结构化经典、24-case eval、单次 AI 解释、模型预热和阶段耗时通过 |

### K00：治理契约与基线快照

- 逐项列出六本子平核心目标书目当前计划纳入的篇章；未纳入内容明确标记，不宣称全集。
- manifest 至少记录 namespace、release id、source id、title、uri、version、sha256、license、provenance、review status、calculation scope 和内容类型；古籍追加 work、chapter、edition/source、固定 source URL 与 verification status。
- 锁定当前 chunking、embedding、reranker、vector backend、candidate pool、weights 与输出契约快照。
- 在 owner/reviewer 尚未确认时可以完成 schema 和本地 fixture，但不得把未批准 corpus 标记为 production release。

### K01：校验、预览与幂等发布

- Validator 拒绝重复 source identity、缺少 required metadata、digest 不匹配、非 reviewed active source、非法 namespace 和不可读取文本。
- Dry-run 输出 create/update/unchanged/error，不加载模型、不写数据库、不打印 token 或敏感正文。
- Import 复用 Operator API 或 KnowledgeService 的现有 ingest contract；不得创建第二套数据库写入路径。
- Manifest 中缺失的现有 source 只报告 drift，不自动软删除；删除继续要求显式 Operator 操作。

### K02：经典书籍 Knowledge Console

- 复用项目现有 FastAPI HTML 页面模式，提供 namespace 总览、source/chunk/job 浏览、上传表单、metadata 校验、chunk preview、publish、删除确认、reindex 与检索试查。
- Console 使用 `KNOWLEDGE_OPERATOR_TOKEN` 建立短时 operator session；token 不进入 URL、HTML、localStorage、日志或 diagnostics。写操作使用 HttpOnly/SameSite cookie 与 CSRF 防护。
- Preview 只进入有 TTL 的 runtime-owned staging，不创建 active source；publish 使用 preview id 与 digest，防止预览后文件被替换。
- UI 不实现多人审批、富文本编辑或任意 SQL/配置编辑；复杂管理需求继续由后续证据决定。

### K03：真实 corpus 检索基线

- Gold set 覆盖原词命中、同义改写、篇章定位、跨来源比较、适用条件、歧义词和无依据问题。
- 每个 case 声明 expected source/heading、允许的替代证据、禁止来源和最低检索模式，不以最终 LLM 文风代替 retrieval correctness。
- 报告至少包含 Recall@1/3/5、MRR、expected-source first rank、citation metadata completeness、empty-result/false-positive 数量和逐 case evidence。
- 报告绑定 corpus release id、数据库快照标识、Knowledge config hash 和代码 commit，禁止混合不同配置样本。

### K04：证据驱动调优

- 优先调整已有 `target_chars`、overlap、candidate pool、weights、reranker top N 和 metadata filter。
- 只有当前 Markdown heading chunker 无法满足已确认失败类型时，才增加最小的结构元数据或 corpus-specific preprocessing；领域逻辑不进入通用 retriever。
- 只有现有 BGE 组合在稳定 corpus 和已调参数下仍无法达到已确认质量门时，才建立模型迁移设计与 reindex 成本评估。

### K05：发布与回滚

- 从空数据库重放 manifest，得到与已批准 release 一致的 source/chunk/digest 统计。
- 更新 release 使用显式 version/digest，完成 source replacement、reindex 和 config mismatch 恢复演练。
- 回滚使用上一 release manifest 和显式 Operator 操作，不依赖手工修改 SQLite。
- 发布记录保存 corpus release、Knowledge config hash、model ids、source/chunk counts、eval report 与变更摘要。

### K06：真实 provider 性能基准

- 先对每个固定场景连续运行 3 次，逐次报告耗时、模型请求、tokens、retry/fallback，并只计算 median 和 max。
- smoke 稳定后，每个场景至少收集 20 次有效请求，报告 HTTP/runtime/provider 延迟、p50/p95、失败率和累计 tokens。
- 场景固定覆盖 no-RAG、FTS degradation、hybrid rerank 与代表性长上下文；corpus release、模型 profile、prompt 和 retrieval config 全部固定。
- 基准只在 `K03-K05` 完成后开始，避免把检索形态变化误判为 provider 性能波动。

## 决策门

- `G01`：owner、reviewer、许可与第一 release 篇章范围得到明确确认，才能标记 production release。
- `G02`：`K03` baseline 评审后锁定质量门，才能进入 `K04` 调优；阈值不得在看到单次失败后临时放宽。
- `G03`：corpus release、chunking、retrieval config、prompt 与输出契约冻结，才能进入 `K06` 正式基准。
- `G04`：案例许可、匿名化和责任人全部确认后，才为 `bazi-cases` 建独立 issue。

## 2026-07-28 实施证据

- Release：`corpora/bazi-theory/v1/manifest.toml`，六个 reviewed selected sources、12 chunks；不宣称六本书全文覆盖，也未标记为最终 production-approved release。
- Retrieval：`reports/knowledge/bazi-theory-classics-selected-v1/summary.md`，12/12 case；Recall@1/3/5、MRR、expected-source-first、citation completeness、heading match 全部为 1.0。
- Rehearsal：空数据库发布得到 6 sources/12 chunks/12 embeddings；重复发布全部 unchanged；清空 embeddings 后六个 source 自动 reindex；显式删除后 manifest 重放恢复。
- Regression：Knowledge 相关回归、Bazi fixture/grader、scripted `knowledge_retrieval` eval、compileall、pip check 和 diff check 均通过；最终全量结果记录在 `STATUS.md`。
- Runtime：本地 Console 服务保留在 `http://127.0.0.1:18080` 供用户验收；正式 namespace 已发布 `bazi-theory-classics-structured-v2`，为 9 sources / 402 chunks，manifest drift 为 0。
- Answer quality：24-case 概念评估达到 Recall@3 `95.8%`、Recall@5 `100%`、citation completeness `100%`；Console AI 解释固定一次模型请求、最多 3 条证据，真实热检索低于 `1.5 s`。
- Sandbox evidence：`reports/knowledge/bazi-theory-sandbox-local-20260728/summary.md` 记录审核前 15-source / 792-chunk 快照的 23-case eval、OCR 占比与近重复统计；当前草稿箱为 14 sources / 694 chunks，3 个未审校 OCR 来源仍占 429 chunks。
- Review flow：Console 默认进入草稿箱；文件 preview 后创建草稿导入任务，任务完成后可检查来源与 chunks，审核通过会复制现有 chunks/vectors 到正式库并移除草稿。Bazi Agent 仍只检索 `bazi-theory`。

## 完成条件

- 一个 approved corpus release 可以从 manifest 在空数据库中重复导入，并得到一致 source/chunk/digest 结果。
- Operator 可以只通过 Knowledge Console 完成经典书籍的预览、发布、job 观察、检索试查、reindex 与显式删除，不需要手工构造 API 请求。
- 真实 corpus retrieval eval 可重复运行，质量门、失败切片和配置归属清楚，现有 synthetic suite 无回归。
- 任何检索调优都有 before/after 证据；没有为未证明的问题增加新服务、表、profile 或模型迁移。
- 发布、reindex、rollback 与 diagnostics 经过演练并形成操作记录。
- 正式 p50/p95 基准已按用户决策移出阶段一完成条件；后续执行时必须绑定同一 corpus/config/model/prompt 版本。

## 合并回 Project Spec 的候选

- `.cs/spec/knowledge-runtime.md`：corpus release、manifest、质量门、发布/回滚与稳定性能预算。
- `.cs/spec/operations-and-verification.md`：corpus import、eval、reindex、rollback 和 live benchmark 命令。
