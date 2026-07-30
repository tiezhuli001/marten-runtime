# Knowledge/RAG Runtime

## 读者该带走什么

Knowledge 是已经进入当前基线的通用 RAG runtime capability。任意 agent 可以通过 namespace 使用同一套文本入库、chunk、FTS / vector 检索、rerank、引用、删除、reindex、状态与统计能力。

它与 memory 分工明确：memory 保存用户偏好和稳定事实，Knowledge 保存可检索文档材料。Bazi 案例使用独立结构化权威库，仅把去身份化的检索文本投影到 Knowledge。

## 主流程

```mermaid
flowchart LR
    A["ingest_text / ingest_file"] --> B["Normalize Source"]
    B --> C["Chunk"]
    C --> D["SQLite Source + Chunk"]
    D --> E["FTS5"]
    D --> F["Embedding"]
    F --> G["sqlite-vec"]

    H["search(namespace, query)"] --> I["FTS Candidates"]
    H --> J["Vector Candidates"]
    I --> K["Merge"]
    J --> K
    K --> L["Rerank / Weighted Rerank"]
    L --> M["Cited Results + Diagnostics"]
```

## 当前能力

Builtin `knowledge` 提供：

- `ingest_text`：同步写入小文本 source。
- `ingest_file`：创建大文件 ingest job。
- `ingest_status` 与 `cancel_ingest`：查询或控制 ingest job。
- `search`：按 namespace 检索并返回 source、chunk、score parts 与 diagnostics。
- `get_chunk`：读取完整 chunk。
- `delete_source`：按 namespace 软删除 source 及其检索内容。
- `reindex`：按当前 embedding 配置重建 namespace 或 source 的向量。
- `stats`：查看 namespace 与存储统计。
- `model_status` 与 `unload_models`：观察或释放懒加载的 embedding / reranker 模型。

## 数据与隔离

- SQLite 主库存放 source、chunk、namespace、embedding、vector map、ingest job 与 search run。
- 所有读写都带 namespace，namespace 是知识库逻辑隔离键。
- FTS5 负责关键词召回，sqlite-vec 负责向量召回；metadata 条件在两类候选截断前执行，避免限定证据类型被未过滤候选挤出。
- Source 删除采用软删除，search 与 get 只返回 active 内容。
- 相同 namespace 内的重复 `uri + version` 更新既有 source，减少重复结果。
- 私有 Bazi 案例保存在 `data/bazi_cases/bazi_cases.sqlite3`；owner 由可信 `channel_id:user_id` 摘要得到，owner 专属 Knowledge namespace 只存可重建投影。
- 案例投影先完成全部 embedding，再原子替换 source/chunk/vector；归档和删除会同步移除投影，失败时恢复权威记录版本。

## Bazi 双层知识

- `bazi-theory` 是经典理论层，默认排除 `case_record`；共享审核案例是当前案例层，未来用户主动保存的案例可按可信用户身份建立私有范围，两者都不能覆盖 builtin 排盘事实。
- `bazi_case.save_current` 只读取同一 turn 中最近一次成功 Bazi 工具结果，模型不能提交或改写确定性快照。
- Bazi 案例采用 `bazi.case.v3`，将确定性盘面、方法解释、主题结论、待验证预测、真实反馈和复盘分别保存，并增加书籍来源坐标、事件主体和提取质量；V1/V2 SQLite 启动时原位迁移。
- `bazi_case.import_text` 支持批量格式化案例；命主反馈进入 reported event，未来判断进入 prediction，不将预测当作已发生事件。
- `bazi_case.search` 检索共享审核案例，并在存在可信用户身份时组合该用户主动保存的私有案例；排序采用结构 45%、时运 20%、语义 20% 和反馈质量 15%，同盘 direct 优先，低于 `0.60` 的 near 结果不展示。
- theory citation 与 case citation 分开。没有私有案例时返回成功空列表，Bazi Agent 继续基于经典证据回答。
- 当前书籍和 Operator 导入案例进入共享审核层；私有生命周期仅用于未来用户明确执行“一句话保存”的案例，共享申请与匿名化仍属于后续 `S04`。
- 书籍案例通过通用 TXT 章节适配器、`BookProfile`、候选识别、A-D 分级与去重后导入；默认只有含明确反馈的 A/B 案例进入 active shared 库。
- 应期关系引擎确定性计算天干五合/生克/伏吟、地支三合/三会/六合/冲/刑/害/破/伏吟，以及本气、中气、余气藏干作用，并支持原局、大运、流年跨层多方组合。六合、三合和三会按目标五行是否透干引化输出「合化成立/合化未成」，冲刑害破输出受影响五行、日主十神和宫位；LLM 只解释计算结果。完整解盘从起运开始最多保留六个大运、每运十年，过三关仍只使用当前年及以前。关键神煞必须按真实年份配对且仅作辅助；经验解释以 `modern_commentary + timing_method` 进入 theory RAG。
- 完整解盘固定执行排盘、full dayun、理论检索、案例检索和一次正式生成；正式生成使用紧凑工具材料但保留完整十一栏与应期契约。Bazi Agent 由 LLM 综合判断，宿主只提供计算事实、检索证据、格式与事实一致性校验，不生成事件归属、健康部位、学历档位、财富评分或收入金额，也不自动改写模型的命理结论。过三关在格式与事实校验通过后增加一次窄上下文 LLM 语义审查，只判断每条是否具备现实对象、动作和结果；不通过时由主模型仅重写该栏目，审查模型与宿主均不提供事件答案。

## 模型与配置

公开模板位于 `config/knowledge.example.toml`，本地覆盖位于 `config/knowledge.toml`。核心配置区域包括：

- `[knowledge.chunking]`：chunk 尺寸、overlap、最大长度与 batch size。
- `[knowledge.embedding]`：provider、model、local path、dimension 与下载策略。
- `[knowledge.reranker]`：reranker model、local path 与 top N。
- `[knowledge.vector_store]`：sqlite-vec backend。
- `[knowledge.search]`：top K、candidate pool 与 ranking weights。

模型文件保存在被忽略的 `data/models/`。Runtime 启动只创建 adapter，模型在首次相关操作时懒加载；idle TTL 与 `unload_models` 控制释放。

当前默认组合来自第一版自托管与中文场景取舍：

```text
Embedding: BAAI/bge-small-zh-v1.5
Reranker: BAAI/bge-reranker-base
Vector store: SQLite + sqlite-vec
Text index: SQLite FTS5
```

## 降级与恢复

- Embedding 模型缺失：ingest 保留 source、chunk 与 FTS；search 返回 FTS 路径和 embedding diagnostics。
- sqlite-vec 扩展缺失：vector status 标记 disabled，FTS 检索继续工作。
- Reranker 缺失：使用 weighted rerank，并返回 rerank status。
- Embedding config hash 与 namespace 索引不一致：vector status 标记 config mismatch，operator 运行 `knowledge.reindex --namespace <name>` 恢复向量检索。
- Embedding config hash 包含解析后的模型路径；运维脚本重建索引时必须使用与服务启动相同的仓库绝对路径解析，不能直接用未解析的相对路径配置。
- Vector 索引记录不一致：返回 backend error 与 reindex 建议。
- 进程启动会把遗留 `queued/reading/chunking/embedding` job 统一收敛为 `failed + KNOWLEDGE_JOB_INTERRUPTED + retryable=true`，并清理 job-owned staging；完成、失败与取消同样走统一终态清理，另有 orphan staging 清理保护。

## Operator 管理面

- 配置 `KNOWLEDGE_OPERATOR_TOKEN` 后注册受 Bearer 保护的 `/knowledge/**` 管理路由；未配置 token 时路由保持关闭。
- Operator 可以分页查询 namespace/source/chunk/job 与 stats，流式上传 `.txt/.md`，执行显式软删除和 source/namespace reindex。
- 上传上限为 `10 MiB`，支持 UTF-8/UTF-8-SIG/GB18030，metadata 至少包含 title、license、provenance、calculation scope 与 reviewed 状态。
- `/knowledge/console` 提供 server-rendered 管理页：Operator token 登录后获得短时签名 HttpOnly/SameSite session，写操作要求 CSRF；可浏览 source/job/chunk、上传 preview、保存草稿、审核发布、检索试查、reindex 与显式删除。
- Console 中 `bazi-theory-sandbox` 显示为“草稿箱”，只承载待审核来源；`bazi-theory` 显示为“正式库”，是 Bazi Agent 唯一检索的理论 namespace。两者是同一经典书籍库的两个内容状态，不是两个同时参与解盘的知识层。
- Console 上传只进入草稿箱。导入任务完成后可预览完整 metadata 与 chunks；点击“审核通过并发布”会原样复制 chunks 和当前 embedding 到正式库，写入审核时间与来源信息，再从草稿箱软删除。正式库页面不提供上传入口。
- UI 中“导入任务”是文件读取、chunk 和 embedding 的处理记录；审核发布是来源详情页上的同步管理动作，不创建第二条导入任务。
- Preview 展示 digest、metadata、source identity、全部 chunks 和长度分布；上传可调整 `target_chars`、`overlap_chars`、`max_chars`，参数随 source metadata 保存。
- `[knowledge.embedding_profiles.<profile_id>]` 声明可选择的 namespace embedding profile；同一 namespace 不混用向量空间。profile 切换先生成全部新向量，成功后一次性替换，失败保留原索引。
- 检索试查支持临时 top K、candidate pool 与归一化 ranking weights，不修改生产默认值。
- Console 与 HTTP 管理面、agent tool 共享同一 KnowledgeService；非法 namespace 直接返回 `422 KNOWLEDGE_NAMESPACE_INVALID`，不得回退到默认 namespace；agent action/namespace scope 不授予 Operator 权限。

## Corpus release 与质量证据

- `corpora/<namespace>/<version>/manifest.toml` 固定 release id、source identity、digest、reviewed metadata、许可、来源、篇章和计算适用范围；validator 在写库前拒绝重复 identity、digest 漂移、非法 namespace 与不完整 metadata。
- `plan/publish` 采用 additive、幂等语义：create/update/unchanged 明确可见，manifest 外的 active source 只报告 drift，不自动删除；已发布 source 缺失当前 embedding 时会显式 reindex 修复。
- `evals/cases/knowledge_corpus/` 与 `scripts/eval_knowledge_corpus.py` 生成 release-bound retrieval 报告，拒绝 manifest 外 drift，并记录 manifest/gold digest、base commit、候选代码树 SHA256、逻辑数据库快照、Knowledge config/model、逐 case evidence 与 Recall@K/MRR/引用完整率。
- 当前正式 release 为 `bazi-theory-classics-structured-v2`：六本经典拆为 9 个证据类型明确的 source、402 chunks；《子平真诠》原文、现代解读和命例分离，manifest drift 为 0。
- v2 的 24-case 概念评估达到 Recall@1 `70.8%`、Recall@3 `95.8%`、Recall@5 `100%`、MRR `82.3%` 和 citation completeness `100%`，默认检索没有课程或命例命中。
- 本地长期运行的 `bazi-theory` 可能同时保留 manifest 外旧 source；它们属于显式 drift，Operator 必须审查后再删除或迁移，release 工具不得替用户自动清理。

## 架构边界

- Knowledge 是 runtime capability，领域 agent 与采集 adapter由上层扩展承担。
- LLM 根据 capability description 与 `knowledge_management` skill 选择调用时机。
- Tool 和 service 承担参数、权限、持久化、检索与诊断。
- 模型资产留在本地目录，普通 runtime 启动保持轻量。
- Embedding 空间切换采用显式 reindex，索引记录保存 model id、dimension 与 config hash。
- `evidence_kind` 区分古籍原文、历代注解、现代注解、Marten 释义、课程讲义和命例；默认理论检索排除课程与命例。
- Console AI 解释最多使用 3 条检索证据，只执行一次模型请求，不进入 Bazi Agent；无直接证据时不调用模型并明确拒答。
- Knowledge 可配置启动预热并保持本地模型常驻；检索与回答结果分别报告 embedding/FTS/vector/rerank 和 retrieval/generation/total 耗时。

## 验证基线

当前测试与 eval 覆盖：

- 配置、chunking、store、embedding、reranker 与 vector adapter。
- Namespace 隔离、软删除、FTS / vector / hybrid retrieval 与 metadata filter。
- Config mismatch、缺模型、缺 sqlite-vec 与 backend error 诊断。
- Metadata 过滤在 FTS、sqlite-vec、JSON cosine 和文本包含回退路径中的一致性，以及高分非目标候选不能遮蔽限定证据类型。
- Ingest job 状态、取消、tool schema、runtime capability 与 skill 行为。
- `knowledge_retrieval` eval 的关键词召回、语义召回、rerank、namespace isolation、config mismatch、进度与 delete behavior。
- Corpus publisher 的首次发布、重复发布、缺向量修复、namespace reindex、显式删除后重放，以及 corpus grader 的版本匹配与指标计算。
- Knowledge Console 的登录/cookie/session、CSRF、非法 namespace、preview/草稿导入、审核发布、正式库检索、source detail、reindex 与显式删除。
- 私有案例 V2 的文本导入、旧库迁移、真实对象式四柱特征、direct/near 排序、预测/反馈隔离和 32 案例检索评估。
- 私有案例 V3 的书籍来源、事件主体、提取质量、预测反馈复盘关联，以及关系真值表和真实书籍检索评估。

## 后续真实性能基准

真实 provider 的端到端延迟基准延期到 RAG 继续完善之后执行。触发条件是目标 namespace 的语料范围、chunking、embedding、reranker、candidate pool、提示词和最终输出契约已经稳定，避免检索与上下文形态持续变化时得到不可复用的延迟结论。

- Scripted eval 继续负责工具顺序、检索降级、引用和输出契约，不作为真实模型延迟证据。
- 稳定性 smoke 先使用同一输入连续运行 3 次，逐次报告耗时、模型请求数、tokens、retry 与 fallback；3 次样本只报告 median 和 max，不计算或宣称可靠 p95。
- 正式 live benchmark 每个固定场景至少完成 20 次有效请求，记录 HTTP/runtime/provider 阶段耗时、p50、p95、失败率、retry/fallback、模型请求数和累计 tokens。
- 基准场景至少覆盖无 RAG、FTS 降级、hybrid rerank 和代表性长上下文检索；不同语料版本、模型 profile 或检索配置不得混入同一统计样本。
- 该基准用于确认 RAG 完善后的生产延迟预算和长尾风险，不阻塞当前 Bazi/RAG 功能提交。

## 当前受管理变化

Knowledge 产品方向分两阶段管理：

- `.cs/epics/002-o-knowledge-corpus-quality/spec.md`：经典书籍 release contract、Knowledge Console、v2 结构化经典、概念问答、AI 解释、模型预热与发布/恢复演练已实现；Epic 保持 open，正式性能基准按用户决策延期。
- `.cs/epics/003-o-bazi-case-library/spec.md`：私有案例 MVP 已进入实现，交付 owner 隔离、对话保存、可重建检索投影和 theory-first/case-second 双层推理；共享审核发布保留在后续 `S04`。

## 旧迭代材料吸收结论

第一版 design、execution plan 与 selection research 的长期结论已进入本页和 `.cs/notes/005-knowledge-runtime-selection-history.md`。实现证据位于代码、测试、配置与 eval，架构时间线由 `docs/ARCHITECTURE_CHANGELOG.md` 维护。

本页吸收长期仍成立的能力、边界、降级、配置和质量约束。原迭代文档继续保留为历史证据，其 `status: draft` 代表旧文档元数据，当前实现状态由代码、测试、changelog 与本 spec 共同确认。

## 证据索引

- `.cs/notes/005-knowledge-runtime-selection-history.md`
- `docs/ARCHITECTURE_CHANGELOG.md`
- `docs/CONFIG_SURFACES.md`
- `src/marten_runtime/knowledge/`
- `src/marten_runtime/bazi_cases/`
- `src/marten_runtime/tools/builtins/knowledge_tool.py`
- `src/marten_runtime/tools/builtins/bazi_case_tool.py`
- `skills/knowledge_management/SKILL.md`
- `config/knowledge.example.toml`
- `evals/suites/knowledge_retrieval.toml`
- `tests/test_knowledge_*.py`
- `tests/test_bazi_case_*.py`
