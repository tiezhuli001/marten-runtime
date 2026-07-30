---
kind: epic
title: "Bazi 结构化案例库与双层知识推理"
status: open
created: 2026-07-28
---

# Bazi 结构化案例库与双层知识推理

## 决策状态

- 2026-07-28 用户确认案例库是 Knowledge 的第二层，并认可独立阶段实施。
- 2026-07-29 经典书籍层、Console 与检索基线已稳定，本 Epic 开始实施。
- 用户一句话保存默认形成私有结构化案例，共享发布必须经过匿名化、授权和审核。
- 本次实现 `S00-S03` 与 `S05` 的私有案例 MVP；`S04` 共享审核和发布另行实施。

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

- `bazi_case.save_current/import_text`：从当前 run 创建私有案例，或导入一个或多个格式化文本案例。
- `bazi_case.get/list/update_events/archive/delete`：只在 owner scope 内管理。
- `bazi_case.search`：结构化 filter + semantic projection，返回相似点、差异点和验证状态。
- `bazi_case.submit_for_review`：生成匿名化预览，不直接发布。
- Operator review/publish：仅阶段后段增加，发布 reviewed shared projection。

## 本次实现范围

- 支持当前 Bazi run 一句话保存、查看、列表、事件更正、归档和删除私有案例。
- 支持 owner 范围内的结构化相似度与 Knowledge 语义投影联合检索。
- 检索结果必须返回相似点、差异点、已验证事件和适用限制，案例引用使用 `case_id/case_version`，不得混入经典引用。
- Bazi Agent 获得 `bazi_case` capability，按“排盘事实 -> 经典理论 -> 私有案例”顺序使用证据。
- 建立 mock 案例评估，对比 theory-only 与 theory+cases 的事件可核验性和具体性。
- 不实现共享申请、匿名化预览、Operator 审核和公开案例检索；相关接口在 `S04` 实施时增加。

## 身份与安全契约

- owner key 由运行时可信上下文中的 `channel_id:user_id` 计算；两者规范化后不可为空，否则拒绝读写。模型 payload 不接受 owner 字段。
- `session_id` 和 `run_id` 仅用于来源追踪，不能替代 owner 身份；跨 session 的同一 owner 可以访问自己的案例。
- 私有投影使用 owner key 的不可逆摘要形成独立 namespace，不把 owner、姓名、精确地址或出生输入写入 chunk 文本、embedding 和搜索结果。
- 工具结果不返回规范化出生输入；trace 使用 `sensitive_bazi` 观察策略，案例工具只返回盘面摘要和必要标识。
- archive 后不参与检索；delete 同时软删除权威记录和 Knowledge 投影。投影失败时保留权威记录并返回明确的可重试错误，不报告保存成功。

## 存储与投影契约

- 使用独立 SQLite 数据库 `data/bazi_cases/bazi_cases.sqlite3`，至少包含 case、event 和 projection 状态；JSON 字段使用稳定排序序列化。
- Case 唯一键为 `case_id`，更新事件时 `case_version + 1`；所有读写 SQL 必须同时带 owner key。
- 权威记录保存 Bazi 工具成功结果中的 `inputFingerprint`、engine、result schema、time basis、结构化 result 和来源 run/session。
- 每个 active private case 生成一个 owner 专属 Knowledge source，`source_id` 稳定绑定 `case_id`；更新时替换 source，归档或删除时移除 source。
- 投影正文只包含四柱等非身份盘面特征、问题、分析摘要和非敏感事件；metadata 至少包含 `evidence_kind=case_record`、`case_id`、`case_version`、事件类别和 verification 状态。
- 权威写入与投影更新在 service 层串行执行；投影更新失败时回滚本次权威写入，避免状态分裂。

## Tool 契约

- 单一工具 `bazi_case`，action 为 `save_current/import_text/get/list/update_events/archive/delete/search`。
- `save_current` 从当前 turn 的最近一次成功 Bazi 结果读取确定性快照；无当前结果返回 `BAZI_CASE_CURRENT_RUN_REQUIRED`。payload 可提交解释、主题结论、预测、反馈和复盘，但不能覆盖确定性盘面。
- `import_text` 接收一个或多个“性别、四柱、可选大运、分主题分析、命主反馈”案例块；格式不完整的块不入库。
- 事件输入要求 category、description、evidence_type；`user_reported` 默认 `reported`，`document_verified/operator_verified` 才可为 `verified`，`model_inferred` 固定为 `unverified`。
- `search` 接收 query、可选 current_chart 和 event_category、top_k。正常返回 `matches`；没有案例返回成功空列表，投影不可用时返回可诊断错误，不回退到其他 owner。
- `get/update/archive/delete` 对不存在或不属于当前 owner 的 case 统一返回 `BAZI_CASE_NOT_FOUND`，避免暴露他人记录是否存在。

## 相似检索与输出规则

- 最终分为命局结构 45%、大运流年 20%、问题主题语义 20%、真实反馈质量 15%；结构分内部使用日主/月令、五行向量、十神向量、格局/用神和干支关系图。
- 完全相同四柱进入 direct 组并优先返回；非 direct 低于 `0.60` 不展示，`0.60-0.75` 为一般参考，`>=0.75` 为高度相似。
- 每条结果至少列出一项真实相似点；有可比较但不一致的特征时列出差异点。不得仅凭向量分数声称盘面相似。
- `verified_events` 仅包含 verification 为 `verified` 的事件；reported 与 inferred 分栏返回。限制字段固定说明单个案例不能证明因果或替代理论规则。
- 双层回答中经典 citation 与 case citation 使用不同字段；案例冲突只降低案例适用性，不修改 builtin 盘面事实。

## 可测量验收

- 至少 30 个 mock 案例，覆盖 exact、near、反馈查询和干扰查询。
- owner 隔离泄漏为 0；归档和删除案例 Recall@K 为 0；确定性字段被 payload 覆盖次数为 0。
- exact Recall@1 为 `100%`，near Recall@3 不低于 `85%`，反馈 Recall@3 不低于 `80%`，结果契约完整率为 `100%`。
- 在预设问题上，theory+cases 的已验证事件 Recall@3 相比 theory-only 至少提高 0.20，经典规则 citation 完整率不下降，builtin 事实冲突为 0。
- focused tests、Bazi/Knowledge 回归、全量 Python tests、compileall 和 `git diff --check` 全部通过后才达到提交条件。

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
- 首次解盘只返回高质量分析，不主动索取反馈或要求补充现实事件；用户可在后续自然对话中自行反馈，只有明确说“保存案例”才触发保存。
- 案例事件区分 observed/verified/inferred，用户更正可追溯，模型推断不能伪装成事实。
- 双层回答明确区分经典依据与案例类比，并至少说明一个相似点、一个差异点和案例适用限制。
- with-cases eval 必须在具体性或可核验性上优于 theory-only，且事实冲突、过度确定性和确认偏差不恶化，才允许扩大共享案例量。

## 当前不实施

- 自动从所有历史 session 批量抽取案例。
- 未确认的公共网络命例抓取或导入。
- 跨用户推荐、排行榜或“命中率”宣传。
- 用案例统计替代经典规则、确定性计算或现实专业建议。

## 2026-07-29 书籍案例与应期方法提取增量

### 通用提取管线

- 输入先统一为带来源坐标的章节和段落；首批支持 UTF-8 TXT，后续格式只需增加文档适配器，不改案例识别与入库契约。
- 使用 `BookProfile` 描述章节标题、案例提示词、反馈提示词和排除方法，不为每本书复制独立解析器。
- 所有候选统一生成 `CaseCandidate`，确定性字段只由 parser 产生；叙述性分析、事件和反馈允许后续受约束模型补全，但不得覆盖四柱、性别和大运。
- 跨相邻章节聚合预测与反馈；按盘面、性别、事件和来源章节去重，并保留原文片段和行号供复核。
- A 级要求四柱、性别、大运、分析和反馈；B 级要求四柱、性别、分析和反馈；C 级无反馈；D 级为规则示例。默认只导入 A/B。
- 用户提供的书籍视为可信材料；书中明确反馈使用 `document_verified/verified`，不进行来源可信度复审。

### Schema V3 来源与质量字段

- `source_ref`：书名、作者、章节、路径或 URI、起止行、文件摘要。
- `subject`：事件与预测明确区分本人、父亲、母亲、配偶、子女、家庭、事业平台和资产。
- `extraction_quality`：完整度、置信度、A-D 等级和拒绝原因；可从 SQLite V1/V2 原位迁移，旧记录使用空来源和 unknown 质量。

### 应期分层

- 确定性模块计算天干五合、克、同干，地支三合、三会、六合、冲、刑、害、破、同支，以及原局/大运/流年跨层多方组合；输出关系参与者、层级和柱位，不直接断具体事件。
- 十神、宫位和已有 engine 神煞作为附加事实；经验性的婚姻、健康、事业、六亲应期和取象条件进入 `bazi-theory`，标记 `evidence_kind=modern_commentary`、`content_type=timing_method`。
- 用户主动保存的完整命例进入 owner 私有案例层，Operator 导入的可信命例进入共享 curated 层；理论规则、案例反馈和确定性关系在最终提示中分栏，案例不得覆盖 engine 事实。
- 逐年模型材料保留羊刃、飞刃、血刃、白虎、流霞、灾煞、桃花、红鸾、天喜、驿马、金舆、华盖、空亡、文昌、天乙、天德、月德、太极、国印、福星、天医、将星、官符和天罗地网等主要神煞。《命运开启智慧之门》的稳定方法边界作为约束：神煞不独立决定吉凶，只在五行生克、用忌和岁运关系已有方向时辅助主题归属与取象。

### 查询规划与领域重排

- theory 查询由本轮排盘事实生成，固定包含日主五行、月令、月令主气十神、透干十神、主要干支关系和用户明确主题；格局、旺衰、喜用与做功只作为候选扩展词，不得提前写成确定结论。
- case 查询使用同一盘面画像并补充当前大运；最终排序继续采用命局结构 45%、大运流年 20%、主题语义 20%、真实反馈 15%，用户出生原话不参与相似盘评分。
- 通用 embedding/reranker 先产生候选池，`bazi-theory` 再按月令取格、日主/月令同现、主气十神、关键关系和证据等级执行领域重排；其他 namespace 不受影响。
- 完整解盘在多主题检索外增加一次 `content_type=author_method` 定向候选检索；最终证据优先保留经典原文、作者经验卡和作者教学章节，`timing_method` 仅在没有作者经验卡时替代该位置。
- embedding profile hash 变化后必须显式 reindex 正式 theory、共享案例和 owner 私有案例 namespace；评估同时报告 vector/rerank 状态，禁止把 FTS 降级结果记为正式质量指标。

### 本增量验收

- `命运开启智慧之门` 与 `八字命理评点` 使用同一提取器和不同 profile 产生候选报告，重复的删减版文件不再次导入。
- A/B 案例导入后可由盘面、主题和反馈检索；书籍反馈不进入 pending prediction。
- 关系真值表覆盖五合、克、三合、三会、六合、六冲、三刑/自刑、六害、六破、伏吟及原局+大运+流年的多方组合。
- 留出案例按 case/chapter 切分，对比旧关系、完整关系、关系+方法 RAG、关系+方法 RAG+案例检索；报告关系完整率、应期 Recall@3、正负一年命中率、主体准确率、案例 Recall@3、引用完整率和误报率。
- focused、Bazi/Knowledge 回归、全量 Python tests、compileall 和 `git diff --check` 通过后达到提交条件。

## 2026-07-29 作者经验、完整应期与共享书籍案例增量

### 作者材料

- 可信书籍按章节完整导入 `bazi-theory`，保留作者、书名、章节、行号和原文；教学、格局、婚姻、健康、应期、神煞与案例章节均可检索。
- 同一来源额外生成作者经验卡，字段为主题、适用条件、五行方向、岁运触发、神煞辅助、结论范围、例外条件和原文坐标。经验卡是原文章节的派生检索入口，不替代原文。
- Skill 只保存证据顺序、应用边界和输出规则；作者的具体断法不写成长篇 prompt。确定性代码只计算排盘、五行、十神、干支关系和神煞事实，不把作者断语硬编码成事件结论。

### 完整解盘检索与材料

- 完整解盘的 `dayun` 必须使用 `detailLevel=full`；已有不含 `流年列表` 的 dayun 不视为完整应期结果。
- 最终模型材料保留首个流年至当前年的完整逐年表，结构摘要只用于排序，不删除年份。
- 天干应期事实覆盖相生、相克、五合和伏吟；关键藏干作用作为独立、可追踪的辅助事实。地支继续覆盖三合、三会、六合、冲、刑、害、破和伏吟。
- 理论查询在一次工具调用内部执行格局、应期、健康取象和神煞主题子查询，按用户主题选择权重，并对同来源同篇章结果去重。
- 神煞以《命运开启智慧之门》列出的常用范围为基础；原局限定项目不错误写入逐年表，丧门吊客等特殊项目只在对应星宫严重受损时辅助判断。

### 双层案例检索

- 经 Operator 导入的可信书籍案例和本地可信案例进入共享 curated 层，所有 Bazi 用户可读；只有用户明确执行“保存这个盘为案例”产生的记录保持 owner 私有。
- 同盘优先，其次共享可信案例和 owner 私有相似案例；结果明确返回可见性、来源、相似点、差异点和反馈等级。
- 共享案例和私有案例使用相同的结构/时运/语义/反馈评分及 `0.60` 最低近似阈值，任何案例都不得覆盖排盘事实和理论依据。

### 验收

- 1994 年真实命盘从 chart 到最终材料保持完整逐年数据，查询词不含出生原句，格局、作者方法和案例证据可区分。
- 第 707–711 章神煞方法、“火旺木焚”和婚姻教学方法均可稳定召回并带原文坐标。
- 任意可信 owner 可检索共享可信案例，同时不能读取其他 owner 主动保存的私有案例。
- 概念、应期、作者经验、案例和真实命盘评估通过；全量测试、compileall 与 `git diff --check` 通过。

### 实施结果

- 完整章节与作者经验卡共同进入 `bazi-theory`；完整章节覆盖教学、婚姻、健康、财富、事业、六亲、神煞、格局、用神和应期，经验卡保留条件、五行方向、岁运触发、神煞辅助、结论范围、例外与原文坐标。
- 完整解盘理论检索在一次工具调用内执行格局核心、应期、健康、神煞、婚姻和六亲子查询，并增加月令经典查询；结果按 chunk 去重后固定保留经典原文、作者方法和完整章节。
- 62 个可信书籍案例和 15 个本地可信案例进入共享 curated 层，共 77 个活动案例；当前用户私有案例为 0，活动案例不存在跨 owner 重复指纹。
- 目标命盘真实主链验证排盘、完整逐年应期、理论检索、案例阈值和最终生成；无足够相似案例时保持空结果，不降低阈值。
- 作者经验卡检索已将 metadata 条件下推到 FTS 和 vector 候选生成阶段，并为严格 FTS 空结果增加限定内容类型的 OR-term 回退，避免普通章节在候选截断前遮蔽作者卡。
- 真实 HTTP 运行 `run_3173107d` 的最终证据包含《命运开启智慧之门》作者经验卡和完整教学章节；理论与案例 namespace 均为 `hybrid_rerank`，十一栏和应期契约检查均无缺失。完整主链保留四项必要工具和一次正式生成，5 次模型请求、无 provider retry/fallback/生成重写，总耗时 `75.090s`，最终生成 `38.664s / 2,035 tokens`。

## 2026-07-29 私有案例 MVP 实施证据

- `S00-S02`：新增独立 SQLite 权威库、owner 摘要隔离、版本化事件、同轮 Bazi 快照和 owner 专属 Knowledge 投影；投影先生成全部向量再原子发布。
- `S03`：Bazi Agent 新增 `bazi_case` capability，工具规则固定 theory-first/case-second，返回独立 case citation、相似点、差异点、验证分栏与限制。
- 连续工具链支持 `chart -> dayun` 和 `resolve_pillars -> dayun`；保存时选择含四柱的结果并附带同轮大运数据，模型不能覆盖确定性快照。
- `S05`：8 个 mock 案例真实本地评估达到 verified event Recall@3 `100%`、相对 theory-only `+100` 个百分点、结果契约完整率 `100%`、builtin fact conflicts `0`。
- 全量 Python 回归 `1601/1601`、compileall 和 `git diff --check` 通过。
- `S04` 共享申请、匿名化、审核和发布仍未实施；Epic 与 Issue 保持 open，等待用户授权关闭。

## 2026-07-29 Schema V2 与相似盘检索决策

用户确认真实案例不能只保存“四柱 + 文本摘要”，必须区分原局分析、主题结论、待验证预测、真实反馈和复盘。本次继续扩展私有案例 MVP；三份语雀文档直接访问返回 `401 Unauthorized` 后，用户提供了本地 Markdown 供同一文本导入接口处理。

### Case Schema V2

- 确定性盘面新增规范化四柱、藏干、十神、月令、日主、五行强弱向量、十神分布、干支关系、大运列表和当前大运；全部由 Bazi engine 或确定性文本 parser 产生。
- `interpretation` 保存 school、method、strength、pattern、用神、喜神、忌神、basis 和 confidence，不得写入 calendar fact。
- `topic_conclusions` 按事业、财运、婚姻、健康、学历、子女等主题保存结论、依据、适用时间和限制。
- `predictions` 独立保存预测主题、时间、触发关系、结论与 `pending/confirmed/partial/missed/unknown` 状态；未经反馈不能进入真实事件。
- `events` 只保存实际反馈及其证据等级；`reviews` 将预测与事件关联并记录命中、部分命中、未命中和更正。
- 保存私有 `raw_case_text` 和提取来源片段用于复核；raw text 不直接参与结构评分。
- schema version 升为 `bazi.case.v2`，SQLite 启动迁移必须保留 V1 数据并提供默认空结构。

### 录入能力

- `save_current` 接收当前 Bazi 事实，并允许模型提交 interpretation、topic conclusions、predictions、events 和 reviews；模型不能提交四柱、十神或大运事实。
- `import_text` 支持用户示例中的“性别/编号、两行四柱、两行大运、原局/事业/婚姻/命主反馈”等格式；一次文本可包含多个案例。
- parser 只能确定性提取格式明确的盘面和章节；“命主反馈”进入 reported event，其他自然语言进入分析或待验证预测，不自动升级为 verified。

### V2 检索评分

候选先限定 owner、active status 和可选 topic，再合并直接同盘、结构近似和 Knowledge 语义候选。最终分数：

```text
命局结构 45% + 大运流年 20% + 问题主题语义 20% + 真实反馈质量 15%
```

命局结构内部固定为：日主/月令 8%、五行向量 10%、十神向量 10%、格局/用神 8%、合冲刑害关系 9%。完全相同四柱进入 direct 组并优先返回；同盘多个案例全部保留，再按时运、主题和反馈质量排序。非 direct 结果低于 `0.60` 不展示，`0.60-0.75` 为一般参考，`>=0.75` 为高度相似。

### V2 结果与评估

- 每条结果返回 match type、总分、四个 score parts、盘面相似点、差异点、时运触发、verified/reported events、pending predictions、reviews、独立 case citation 和限制。
- 至少 30 个 corpus 案例，查询集必须同时包含 exact、near 和 distractor，不能只用被查询案例自身证明召回。
- exact Recall@1 `100%`；near Recall@3 `>=85%`；真实反馈 Recall@3 `>=80%`；结果契约完整率 `100%`。
- owner 泄漏、prediction-as-event、builtin fact conflict 均为 `0`；V2 before/after 指标通过后替换 V1 评分。

### Schema V2 实施证据

- 已实现 V1 SQLite 原位迁移、真实对象式四柱特征、确定性文本导入、预测/反馈/复盘引用约束、direct/near 排序与最低分过滤。
- 本地 `bge-small-zh-v1.5 + bge-reranker-base` 对 32 个案例、28 个独立查询评估：exact Recall@1、near Recall@3、反馈 Recall@3、干扰拒绝率和结果契约完整率均为 `100%`。
- owner 泄漏、prediction-as-event、builtin fact conflict 均为 `0`；全量 Python 回归 `1611/1611` 通过。
- 三份语雀案例已由用户汇总为本地 Markdown；26 个完整盘中筛选并导入 15 个有明确现实反馈的案例，其余纯理论或预测案例未导入。这 15 个 Operator 可信案例已从早期默认 owner 私有空间迁移到共享 curated 层。

## LLM-first 推理边界

- 排盘工具负责确定性计算，案例检索与 theory RAG 负责提供证据，Skill 负责方法和输出约束；命理判断由 LLM 完成。
- 宿主不得生成事件归属、健康部位、学历档位、婚姻结论、财富评分或收入金额，不得用代码模板改写模型结论。
- 确定性校验仅保护工具事实、引用、神煞年份、现实财富基线和输出结构，不替代模型解释。

## 2026-07-30 应期、作者资料与过三关质量门增量

- 应期确定性层补充岁运地支本气、中气、余气对原局透干及大运透干的生克合伏吟；原有岁运透干对全部原局藏干、天干五合生克、地支三合三会刑冲合害破和神煞继续保留。后续增加六合/三合/三会的化神透干判定，以及冲刑害破受影响五行、十神和宫位。模型材料从起运开始最多取六个大运、每运十年，不再携带 126 年全量数据。
- 通用章节识别兼容“第1章：标题”“第 20章 标题”和“第15章标题”。《八字是科学它祖宗》导入 46 个领域章节、87 张作者卡和 4 个应期方法 chunks；《修真密码十天干》导入 16 个领域章节和 84 张作者卡，共新增 532 个正式 theory chunks。
- 作者方法评估新增“大运定阶段、流年定应验”“星宫位确定人事对象”“寻根基、找出处、引动原理、干支密断”三组查询；10 个查询的 Recall@3、引用坐标完整率和 hybrid rerank 可用率均为 `100%`。完整解盘的五条证据最多保留两个不同作者来源的方法卡，并继续保留经典和完整教学章节。
- 过三关语义审查升级为三至五条高信号事件、重大性、明确结果和原局/大运/流年三层依据；首次解盘不主动索取反馈，语义修复结果必须再次经过结构检查和语义审查。Bazi 工具调用仍限制八轮，最终质量请求单独获得最多五轮，不允许未通过结果进入通用降级回复。
- 真实 HTTP 运行 `run_bc5f647c` 完成 `chart -> dayun(full) -> knowledge.search -> bazi_case.search -> final generation/repair/review`，最终状态 `accepted`；十一栏无缺失、输出契约无违规，过三关保留 2012、2017、2020、2024 四条高信号事件。该轮 10 次模型请求、无 provider error、累计 `141,795` tokens、总耗时 `206.836s`；当前优先保证内容质量，性能优化后续单独处理。
- 最终聚焦回归 `128` 项、全量 Python 回归 `1664/1664`、作者方法评估、`compileall` 和 `git diff --check` 全部通过。

## 2026-07-30 完整解盘稳定编排增量

- 首次模型请求只负责理解出生信息并调用 `bazi.chart`；宿主随后按已验证状态固定执行 `bazi.dayun(full) -> knowledge.search -> bazi_case.search`。这些确定性步骤不再各自请求模型，也不改变 LLM 对格局、喜用、主题和事件的判断权。
- 最终模型使用严格 JSON Schema 返回十一栏结构化草稿；宿主只负责栏目顺序、Markdown 渲染和标点规范化，不生成或替换命理结论。
- `verification_events` 明确分为年份、单一事件、流年依据、大运依据、原局依据和同年神煞辅助。事件字段由 schema 禁止列表分隔符，语义审查继续判断重大性、现实动作、完成结果和三层证据。
- 确定性事实校验失败时最多进行一次完整结构化草稿修复；过三关语义审查失败时最多进行一次 `verification_events` 字段修复，合并后必须复审。未通过时明确失败，不使用自由文本多轮重写。
- 完整理论检索覆盖过三关、应期、神煞、健康、婚姻、六亲、事业、财富和学历，并合并为三个主题子查询；最终 Top 8 保留经典、作者方法和不同主题教学章节，减少重复检索。
- 单元测试证明新链路的模型请求仅为出生解析、最终结构化生成和语义审查，确定性工具调用不会进入 provider 请求记录；旧测试客户端仍保留 Markdown 兼容路径。

### 真实验收证据

- 正式 HTTP 运行 `run_b94ef954` 按 `chart -> dayun(full) -> knowledge.search -> bazi_case.search` 完成；Knowledge 为 `hybrid_rerank`，vector 与 rerank 均为 `available`，案例低于阈值时保持空结果。
- Provider 请求严格为 `interactive -> bazi_final_generation -> bazi_output_semantic_review`，共 3 次；首次结构化草稿直接通过确定性校验和语义审查，无结构修复、语义修复、provider retry、fallback 或 error。
- 最终状态 `accepted`，十一栏完整；过三关为 2012、2017、2024 三条单事件，分别包含流年、大运、原局和同年神煞辅助事实；正文不邀请反馈，参考依据只输出一次。
- 该运行总耗时 `83.691s`，累计 `58,010 tokens`，峰值输入 `40,832 tokens`；对比 `run_e4e74961` 的 `149.603s / 143,789 tokens / 10 requests`，必要工具和质量审查均保留。
- 本增量聚焦回归 `183 tests`、此前全量回归 `1667/1667`、`compileall` 和 `git diff --check` 通过。最终重复全量运行有 2 个既有 bridge 大输出用例在整套负载下超时，相关用例单独复跑通过；本次链路与 schema 回归无失败。

## 2026-07-30 过三关分类质量增量

- 结构化过三关保留三至五条，每条增加不展示给用户的领域标签。候选只分婚姻恋爱、自身健康、父母六亲、工作变更、财务得失五列；每列比较一至两个相关年份，再按三层证据强度选择最终事件。
- 最终每列允许零至两条，不要求五列全部出现；某列被选中时只允许选择该列分数最高的一至两条。升学和单纯搬家不作为独立过三关栏目，证据不足的列直接舍弃；神煞只能辅助，不能为了数量把弱信号升级成住院、手术、婚姻或父母疾病。
- 确定性事件违规会与语义审查结果合并后再修复；结构化链路的过三关错误始终只重写事件数组，不再升级为整份十一栏重生成。事件修复最多两次，每次修复后重新经过确定性检查和语义审查。
- 增加干支层级一致性检查：天干作用只能连接天干，地支合冲刑害破只能连接地支；地支关系被写成直接合冲日干时拒绝结果。
- 真实 HTTP 运行 `run_fc1a957c` 完成 `chart -> dayun(full) -> knowledge.search -> bazi_case.search`，最终五条过三关覆盖升学、健康处置、首次入职、恋爱确定和搬家；父母健康因不能缩小为具体事实而未强行加入。十一栏完整、确定性违规为零、语义审查通过、参考依据一份。
- 该轮使用 `interactive -> final generation -> review -> event repair -> review -> event repair -> review` 共 7 次模型请求，无 provider retry/error，总耗时 `173.518s`、累计 `154,278 tokens`。内容质量达到本增量验收要求，但首次生成稳定性和耗时仍未达到性能目标。
- 本增量聚焦回归 `295 tests` 与 `13` 个子测试通过，`compileall` 和 `git diff --check` 通过。

## 2026-07-30 过三关预算优化

- 候选表固定覆盖婚恋、自身健康、父母六亲、工作变更、财务得失五列，每列一至两条；最终保留三至五条，每列最多两条。十一栏、完整逐年应期事实和语义审查不减少。
- 候选证据摘要、舍弃理由和最终事件三层依据改为短字段；最终结构化生成上限为 `3400 tokens`，候选局部修复为 `1600 tokens`，语义审查为 `500 tokens`。不增加独立候选模型阶段，避免重复发送全量排盘与 RAG 上下文。
- 宿主将事件字段与三层依据分开校验，不再把“与对象”等自然介词误判为多主题，也不跨越合法地支与天干分句匹配“地支直接作用日干”。模型漏填的候选舍弃理由只按入选状态和同列排名补充结构说明，不生成命理结论。
- 语义审查模型明确拒绝的事件，以及结构校验能精确定位的事件，在唯一匹配、删除后仍有至少三条且候选排名仍合法时直接移除；其余模型事件保持原文。不能安全删除时才请求局部修复。
- 局部修复只携带五列候选、违规项、原局四柱和候选年份对应的岁运关系，不再重复发送完整逐年表与全部 RAG。工具紧凑标签中的本、中、余明确指本气、中气、余气藏干，语义审查不得误判为地支直接作用天干。
- 真实 HTTP 运行 `run_c7187668` 完成 `chart -> dayun(full) -> knowledge.search -> bazi_case.search -> final generation -> semantic review`，最终状态 `accepted`，保留健康一条、工作两条共三条高信号记录；无候选修复请求。该轮使用 `3` 次模型请求、累计 `61,094 tokens`，相对失败基线 `run_ef3a3f6d` 的 `7` 次请求和 `155,473 tokens` 减少约 `60.7%`。总耗时 `146.025s`，其中 provider 最终生成累计约 `120.6s` 并发生一次 provider 重试，编排未重复生成正文。
- 最终聚焦回归 `270 passed + 13 subtests`，`compileall` 与 `git diff --check` 通过。

## 2026-07-30 六运边界与首次生成稳定性增量

- 模型材料从起运开始统一保留前六个大运，每运最多十个连续流年；目标盘原始工具返回 9 运，模型实际收到 1997–2056 的 6 运和 60 条流年，不再携带后续大运概要或 126 年逐年数据。
- 六合、三合、三会的合化成败及冲刑害破受伤属性同时进入正式生成和语义审查；审查器以候选年份确定性事实为准，不再把工具确认的合化成立误判为模型自行升级。
- 父母六亲事件中的健康、工作或财务词描述的是明确亲属，不再误判为命主自身的第二事件主题。事件展示统一去除重复年份和“结果落定”等无信息尾语，且喜用结论要求各栏目保持一致。
- 真实 HTTP 运行 `run_0fe6f134` 完成 `chart -> dayun(full) -> knowledge.search -> bazi_case.search`，Knowledge 返回 8 条经典、作者经验与教学章节证据，案例低于阈值时保持空结果。Provider 请求为 `interactive -> bazi_final_generation -> bazi_output_semantic_review`，共 3 次且全部首次成功；无结构修复、候选修复、provider retry、fallback 或 error，总耗时 `80.402s`，累计 `85,469 tokens`。
- 最终十一栏完整，格局喜用统一为身偏弱、财官偏旺、土金为用、木火为忌；过三关保留婚恋、健康、父亲、入职和换单位五条单事件，合化、刑冲害破和神煞均与确定性材料一致，参考依据只输出一次。
- 最终聚焦回归 `158 passed`；全量回归 `1681 passed + 96 subtests`，两个并发时序用例随后串行验证，其中 bridge 大输出清理竞态修复后连续 10 次通过，subagent HTTP 用例通过；`compileall` 与 `git diff --check` 通过。

## 2026-07-30 过三关确定性事实引用增量

- 原局、大运和流年计算结果在单次运行内生成稳定事实 ID；不新增数据库。模型仍负责事件判断，只选择与事件相关的事实 ID，宿主校验年份和大运范围后生成流年、大运、原局和神煞依据文字。
- 神煞不再由模型自由抄写。跨年、未知或不适用的神煞 ID 由宿主直接删除，不触发模型修复；缺少流年、大运或原局层事实时只修复 `verification_candidates` 与 `verification_events`。
- 违规结果增加结构化 scope 与 repair strategy，编排不再依赖中文违规文案前缀判断修复范围。过三关错误不能升级为完整十一栏重生成。
- 完整 6 运 60 年材料继续保留；只为 12 个最高信号年份附加事实 ID，原局事实细分为四柱宫位、透干十神、藏干十神和确定性原局作用，避免只有四柱文本而缺少主题依据。
- 宿主按最终入选状态整理候选评分和舍弃理由，消除“事件已选但隐藏评分低于未选项”造成的无意义局部重试，不改变模型选择的事件。
- 真实 HTTP 运行 `run_afd0bb12` 完成 `chart -> dayun(full) -> knowledge.search -> bazi_case.search -> final generation -> semantic review`，最终状态 `accepted`。Provider 请求共 3 次，全部使用 `openai_gpt_5_4` 且首次成功；无正文修复、事件修复、provider retry、fallback 或 error，总耗时 `78.396s`，累计输入 `79,256 tokens`，峰值输入 `54,954 tokens`。
- 最终过三关保留 2022 健康处置、2016 工作单位变更、2017 财务进账三条高信号事件；2022 血刃来自同年确定性事实，未出现跨年神煞、自由生成关系或弱事件补数。
- 聚焦回归 `235 passed`，新增事实 schema、跨年神煞过滤、事实层缺失、事实索引和结构性评分整理测试。

## 2026-07-30 过三关栏目独立评选增量

- 过三关固定为婚姻恋爱、自身健康、父母六亲、工作变更、财务得失五个栏目。候选仍由 LLM 根据原局、大运、流年三层证据生成和评分，宿主不预设具体事件结论。
- 五个栏目分别按可信度排序，不做跨栏目总排名。每栏有可信度不低于 `70` 的候选时，必须选择该栏最高分一至两条；只有该栏全部候选低于阈值时才允许不输出。最终事件总数上限由五条提高为十条。
- 宿主不再改写已选候选的可信度。未选且低于阈值的候选统一标记为低于入选阈值；语义审查删除事件后必须再次满足栏目独立评选规则，否则只请求过三关局部修复。
- 聚焦回归 `187 tests` 通过；全量回归 `1684/1688` 通过，4 个失败来自同一既有 Bazi bridge 用例在全套模型加载后的超时，该用例单独复跑通过；`compileall` 与 `git diff --check` 通过。
- 过三关事实索引改为截至当前年的高信号 Top 16，未来流年不再占用历史校准候选位置；本盘 2018、2019、2023、2024 均可获得正式事实 ID。事件渲染取消 `- 1.` 二次序号，避免 Feishu 将其解析为 `a.` 和串行尾标。
- 婚恋应期只确定夫妻宫被引动。没有命主反馈时，巳亥冲等关系统一输出为“感情关系发生明显变动”，不得擅自细化为恋爱、分手或结婚；relationship 事件必须引用 `natal.pillar.2`、同年流年和所在大运事实。丁巳日柱桃花支按午处理，丁酉不标记为桃花。
- 真实 HTTP 运行 `run_4fa5ea1c` 首次生成通过，过三关输出 2019、2016 两条婚恋变动及健康、工作、财务事件；三次模型请求，无修复、provider retry、fallback 或 error，总耗时 `86.061s`。
