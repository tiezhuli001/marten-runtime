---
kind: epic
title: "Bazi 结构化案例库与双层知识推理"
status: open
created: 2026-07-28
---

# Bazi 结构化案例库与双层知识推理

## 决策状态

- 2026-07-28 用户确认案例库是 Knowledge 的第二层，并认可独立阶段实施。
- 本阶段规格先固化，当前不进入编码；待经典书籍层、Console 与真实检索基线稳定后启动。
- 用户一句话保存默认形成私有结构化案例，共享发布必须经过匿名化、授权和审核。

## 这个 Epic 要改变什么

在经典书籍层稳定后增加第二层 Knowledge：结构化 Bazi 案例库。用户完成分析后可以用一句话把当前盘保存为私有案例；系统在后续分析中先引用经典规则，再检索相似案例并明确相似点、差异点、已验证事件和适用限制，从而提升具体性但不让个案覆盖理论或确定性排盘事实。

## 为什么独立为第二阶段

案例包含出生信息、人生事件、分析结论和跨用户共享风险，数据生命周期、隐私、授权、结构化更新和检索方式都不同于书籍 source。若直接把案例塞进 KnowledgeSource 的自由 metadata，会导致事件无法查询、事实与推断混合、共享范围失控、用户更正难以版本化。因此案例需要独立 source-of-truth，再生成可重建的 Knowledge 检索投影。

## 与第一阶段的关系

- 第一阶段 `.cs/epics/002-o-knowledge-corpus-quality/spec.md` 交付经典书籍层、Console、corpus release 和真实 retrieval baseline。
- 本阶段复用 Knowledge embedding/vector/rerank、引用和 diagnostics，但不复用书籍上传表单作为案例写入入口。
- 阶段一期间固定本 spec 的 logical schema，避免经典层的 namespace、citation 和 output contract 阻塞后续双层检索；实现从阶段一 baseline 稳定后开始。

## 两层证据顺序

1. Builtin Bazi 返回 calendar facts、engine annotations、Dayun/Liunian 与 input fingerprint。
2. `bazi-theory` 检索经典原文、方法、适用条件与流派差异，作为高信任规则证据。
3. Case service 根据确定性盘面特征、当前问题与事件类别检索用户私有案例和 reviewed shared cases。
4. 最终回答分别输出“经典依据”和“案例类比”，说明每个案例的相似点、差异点、已验证程度与不可外推范围。
5. 案例与 theory 冲突时，保留冲突并降低案例权重；案例不得覆盖 builtin 事实。

## 结构化案例模型

### Case 身份与生命周期

- `case_id`、`schema_version`、`case_version`、`status`、`created_at`、`updated_at`。
- `owner_scope`：用户/tenant 身份；`visibility`：`private` 或 `shared_reviewed`。
- `source_type`：`user_saved`、`operator_imported` 或 `licensed_public`。
- `source_run_id`、`source_session_id`、`created_by_agent`，用于追溯案例从哪次分析产生。
- `consent_status`、`anonymization_status`、`review_status`、`reviewed_by`、`reviewed_at`。
- 状态建议：`draft -> active_private -> review_pending -> active_shared -> archived/deleted`。

### 排盘事实快照

- `input_fingerprint`、engine name/version、result schema version、calculation time basis。
- 四柱、性别、日主、月令、藏干、十神、合冲刑害、Dayun 列表与关键 Liunian。
- 确定性 engine 输出与后续 theory interpretation 分开保存；格局、旺衰、喜用等方法相关结论必须带 school/method/version，不能冒充 calendar fact。
- 私有记录可以保存重算所需的规范化出生输入；共享投影移除姓名、精确地址、直接标识和不必要的精确出生输入，只保留盘面与经审核的粗粒度背景。

### 可观察事件

每个事件独立记录：

- `event_id`、`category`：education、career、wealth、marriage、health、family、relocation、legal 或其他受控枚举。
- `time_start`、`time_end`、`time_precision`：exact year、range 或 life stage。
- `description`、`outcome`、`severity` 和用户可见摘要。
- `evidence_type`：`user_reported`、`document_verified`、`operator_verified` 或 `model_inferred`。
- `verification_status`、`confidence`；模型推断不得自动升级为用户已验证事实。
- 关联 Dayun/Liunian、natal trigger、theory citation 与适用 method。
- 单事件 privacy/redaction 标记，允许共享案例隐藏敏感事件而保留其他事件。

### 分析与复盘

- 原始问题、分析摘要、结论、建议与风险边界。
- theory citations 与 case citations 分栏保存，保留 source/chunk 或 case/version 标识。
- model profile、prompt/skill version、analysis schema version 和生成时间。
- `user_feedback`、命中/未命中复盘、后续更正；新复盘创建新 analysis/version，不覆盖历史证据。

### 检索投影

- 结构化 Case store 是权威真相；`bazi-cases` 中的文本/chunk/embedding 只是可重建投影。
- 投影包含盘面特征摘要、问题类别、经验证事件、分析方法、相似性标签和公开限制，不包含直接身份字段。
- 私有案例按 owner scope 检索，不进入共享 namespace；只有 `active_shared + reviewed + anonymized` 的版本进入共享 `bazi-cases` 投影。
- 投影版本绑定 case id/version、schema version 和 embedding config hash，案例更新后显式重建对应投影。

## 一句话保存流程

1. 用户在当前 Bazi run 后说“把这个盘保存为案例”。这一明确指令足以创建默认 `private` 案例，不要求用户填写长表单。
2. Agent 调用领域 case capability，使用当前 run 的 Bazi structured result、fingerprint、theory citations 和用户已经明确陈述的事件生成 case draft。
3. 确定性字段由工具结果填充；LLM 只能提取事件与摘要，所有未被用户明确确认的内容标记为 `model_inferred`。
4. 系统返回已保存字段、缺失事件和私有可见性；用户可以继续用自然语言补充、更正或删除。
5. 私有案例升级为共享案例必须单独发起，完成匿名化预览、许可/同意确认和 reviewer 审核；“保存为案例”绝不默认公开。

## 最小能力面

- `bazi_case.save_current`：从当前 run 创建私有案例。
- `bazi_case.get/list/update_events/archive/delete`：只在 owner scope 内管理。
- `bazi_case.search`：结构化 filter + semantic projection，返回相似点、差异点和验证状态。
- `bazi_case.submit_for_review`：生成匿名化预览，不直接发布。
- Operator review/publish：仅阶段后段增加，发布 reviewed shared projection。

## 执行 Chunk

| Chunk | 完成目标 | 主要证据 |
| --- | --- | --- |
| `S00` | 固定 schema、ownership、consent 与 privacy contract | model/schema tests、threat review |
| `S01` | 保存、查询、更正、删除私有结构化案例 | current-run save acceptance、owner isolation |
| `S02` | 建立可重建 case retrieval projection | projection/reindex/version tests |
| `S03` | 打通 theory-first + case-second 双层检索 | tool order、separate citations、conflict handling |
| `S04` | 完成匿名化 review/shared publish | consent/review/redaction tests |
| `S05` | 证明案例层带来收益而非确认偏差 | with/without cases eval、similarity/difference grader |

## 质量门

- 私有案例永不跨 owner/tenant 检索；共享案例必须同时满足 consent、anonymized 和 reviewed。
- 原始姓名、精确地址和直接身份字段不进入 embedding、trace、search result 或共享投影。
- “保存案例”只保存当前用户明确要求保存的 run；Agent 不主动静默沉淀用户盘面。
- 案例事件区分 observed/verified/inferred，用户更正可追溯，模型推断不能伪装成事实。
- 双层回答明确区分经典依据与案例类比，并至少说明一个相似点、一个差异点和案例适用限制。
- with-cases eval 必须在具体性或可核验性上优于 theory-only，且事实冲突、过度确定性和确认偏差不恶化，才允许扩大共享案例量。

## 当前不实施

- 自动从所有历史 session 批量抽取案例。
- 未确认的公共网络命例抓取或导入。
- 跨用户推荐、排行榜或“命中率”宣传。
- 用案例统计替代经典规则、确定性计算或现实专业建议。
