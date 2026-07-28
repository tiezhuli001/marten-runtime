---
kind: issue
title: "Knowledge RAG 问答质量与经典语料替换"
type: feature
status: open
created: 2026-07-28
epic: ".cs/epics/002-o-knowledge-corpus-quality/spec.md"
---

# Knowledge RAG 问答质量与经典语料替换

## 决策状态

- 用户确认在结构化案例库之前增加一个短周期的 RAG 问答质量迭代。
- 本迭代同时处理经典语料结构、重复 source、概念问答评估、Console AI 解释和本地检索延迟。
- 六个精选 source 在结构化替代版本通过评估前继续保留；不得先删除再补语料。
- 草稿箱中的现代讲义、课程和命例不作为六本经典的全文替代品，也不批量审核进入正式理论库。

## 观察到的问题

- 正式 `bazi-theory` 当前为 7 sources / 110 chunks：六个经典精选 source 合计 12 chunks，《子平真诠》本义完整版占 98 chunks（约 89%）。
- 《子平真诠》精选 source 与完整版存在原文重复，例如“八字用神，专求月令……”同时出现在两者中；完整版还混合古籍原文、现代解读和命例，且 DOC 提取后的 heading 为空。
- 草稿箱当前为 14 个近现代盲派 source / 694 chunks，不包含另外五本经典的可替代全文；其中 3 个未校正 OCR source 合计 429 chunks。
- 当前 manifest 对正式库报告 1 个外部 drift，即已审核的《子平真诠》本义完整版；旧的六 source / 12 chunk baseline 不再代表当前正式库。
- “月劫格有什么特征”热检索约 0.57-1.06 秒；冷检索约 11.3 秒，其中 embedding 加载约 5.9 秒、reranker 加载和推理约 5.3 秒。模型闲置 300 秒后卸载，慢查询会重复出现。
- 同一问题通过完整 Bazi Agent 做“检索后解释”耗时 53.6 秒、3 次模型请求、累计 69,532 tokens，并触发一次不必要的最终重写。
- 大模型能够正确抽取“透官逢财印、透财逢食伤、透杀遇制伏”，但会加入未被引文直接证明的性格延伸，并出现重复书名符号。

## 目标

1. 将经典原文、历代或现代注解、课程讲义、Marten 释义和命例区分为不同证据类型。
2. 将《子平真诠》本义完整版恢复章节并拆分原文、现代解读和命例，消除无标题长 chunk。
3. 逐步补齐另外五本经典的结构化全文或核心章节，建立可替换精选 source 的新版 corpus release。
4. 增加概念问答评估集，证明检索结果能支持准确、可引用的现代中文解释。
5. 在 Console 增加独立的“AI 解释”模式，只使用 Top 2-3 检索证据并执行一次模型请求，不调用完整 Bazi Agent 输出规则。
6. 本地运行时预热并保持 Knowledge 模型可用，在 UI 中展示 embedding、召回、rerank 和生成耗时。

## 语料分类

新增稳定的 `evidence_kind`，至少包含：

| 类型 | 含义 | 默认理论问答权重 |
| --- | --- | --- |
| `classical_original` | 可追溯版本的古籍原文 | 最高 |
| `historical_commentary` | 可追溯的历代注本 | 高，必须显示注者与版本 |
| `modern_commentary` | 近现代作者的解释或整理 | 中，不能冒充古籍原文 |
| `marten_interpretation` | Marten 基于原文编写的释义 | 中，必须关联原文 citation |
| `course_notes` | 课程、讲义或学习笔记 | 默认不进入正式经典问答 |
| `case_record` | 命例、事件和复盘 | 不进入理论层默认检索，留给案例库 |

附加规则：

- 每个 chunk 必须继承 `work`、`chapter`、`evidence_kind`、版本来源和审核状态。
- 原文与注解不得放在同一个无结构 chunk 中；同页出现时也要拆成独立检索单元并建立关联。
- `ocr_unreviewed` 不得进入正式库；必须完成文字、章节、段落和关键术语校正后才能审核。
- 理论问答默认排除 `course_notes` 和 `case_record`；需要比较流派时才显式纳入相应现代注解。

## 五本经典来源计划

用户提供的本地文档视为可信来源，不再检查真实性、授权或来源资格。选材优先采用机器可读文本，其次采用可稳定提取的 DOC/PDF；发布前只检查会影响检索的文本提取质量、章节标题、段落结构、OCR 错字和证据类型，不对用户提供材料重新做可信度判断。

| 经典 | 本地候选 | 首选固定来源 | 处理要求 |
| --- | --- | --- | --- |
| 《穷通宝鉴》 | `books/国学/穷通宝鉴.pdf` | 用户提供的本地文件 | 按章规范化并检查提取质量 |
| 《滴天髓》 | `books/国学/滴天髓.pdf` | 用户提供的本地文件 | 恢复章节，原文与注本分离 |
| 《神峰通考》 | `books/国学/神峰通考.pdf` | 用户提供的本地文件 | 按篇章采集并检查歌诀断句 |
| 《渊海子平》 | `books/国学/八字 - 渊海子平.txt`、`渊海子平全书.doc`、`渊海子平.pdf` | 用户提供的本地文件 | 优先采用 TXT，排除非正文噪声 |
| 《三命通会》 | `books/国学/八字 - 三命通会.txt`、`派派小说_三命通会.txt`、`《三命通会》精美排版.doc`、`三命通会.pdf` | 用户提供的本地文件 | 优先采用结构最完整的机器可读版本，排除非正文噪声 |

《子平真诠》继续使用当前已审核完整版作为待整理输入，同时使用用户提供的本地 DOC/PDF 恢复结构；现代作者解读必须标为 `modern_commentary`。

## 替换与去重规则

1. 为每本经典建立“精选 source -> 新结构化章节”的覆盖矩阵。
2. 新 source 使用新的 release、source id、version 和 digest，不覆盖精选 source 的历史身份。
3. 逐条验证精选原文在新版本中的对应章节、文本一致性和 citation 可替代性。
4. 新旧 source 并存期间，评估报告必须单独统计重复召回和单一来源占比。
5. 新版本通过检索和问答评估后，使用显式 Operator 删除被完整覆盖的精选 source。
6. 未被新版本覆盖的精选内容继续保留；不得按书名批量删除。
7. 删除后重跑 manifest plan，要求正式 namespace 无意外 drift，并保存替换记录。

## 概念问答评估

建立不少于 20 个概念问题，至少覆盖：

- 月劫格、建禄格及二者关系。
- 用神的古典定义、顺用与逆用。
- 成格、破格、救应和格局变化。
- 财、官、印、食、杀、伤、劫、刃的适用条件。
- 原文与现代注解观点不同的比较问题。
- 语料没有依据时应拒绝扩展的负向问题。

每个 case 记录：

- 期望命中的 `work/chapter/evidence_kind`。
- 必须出现的原文证据、允许的解释和禁止的无依据结论。
- 允许的替代 source、禁止的课程或案例 source。
- Recall@1/3、MRR、首条证据类型、重复 source 比例和 citation 完整率。
- AI 解释的原文忠实度、解释可读性、原文/解释分离、无依据扩展和引用准确性。

每增加一批结构化内容，必须在发布到正式库前运行同一评估集，并保存 before/after 报告。

## Console AI 解释

- 在现有“检索试查”旁增加“AI 解释”，保留原始检索结果作为可展开证据。
- 默认只传入排序后的 Top 3；相同 source 的相邻重复 chunk 应合并或限制数量。
- prompt 明确要求输出“原文依据 / 现代解释 / 适用限制 / 引用”，不得把注解改写成古籍原文。
- 只调用一次指定的问答模型，不进入 Bazi Agent、不执行排盘工具、不触发 11 节命盘输出或最终重写。
- 模型输入只包含问题、必要指令和选定证据；目标输入不超过 6,000 tokens，输出不超过 800 tokens。
- 生成结果必须保留 source title、chapter、source id/chunk id 的内部映射；Console 对用户展示书名和章节。
- 无足够证据时返回“当前知识库没有足够依据”，不能依靠模型参数知识补写结论。

## 性能与可观测性

- 增加可配置的 Knowledge 模型启动预热；预热完成后服务才报告对应 Knowledge ready 状态。
- 本地 Console 使用场景保持 embedding/reranker 已加载，避免 300 秒闲置后反复冷启动；显式 unload 仍可用于资源释放。
- search result 增加 `embedding_ms`、`fts_ms`、`vector_ms`、`rerank_ms` 和 `total_ms`。
- AI 解释增加 `retrieval_ms`、`generation_ms`、模型请求数和 token 使用量，UI 分阶段展示。
- 当前硬件上，预热后的 Top 3 概念查询目标为 1.5 秒内；AI 解释固定为一次模型请求，provider 延迟单独报告，不用一次样本声明 p95。

## 执行切片

| 切片 | 完成目标 | 主要证据 |
| --- | --- | --- |
| `Q00` | 固定 evidence schema、来源清单和替换矩阵 | schema tests、source inventory |
| `Q01` | 结构化《子平真诠》并拆分原文/解读/命例 | heading/evidence tests、重复报告 |
| `Q02` | 采集并规范化另外五本经典的全文或核心章节 | revision/digest/章节覆盖矩阵 |
| `Q03` | 建立概念检索与解释评估 | 20+ cases、before/after report |
| `Q04` | 实现单次模型请求的 Console AI 解释 | browser acceptance、调用与 token 证据 |
| `Q05` | 预热模型并展示分阶段耗时 | cold/warm benchmark、UI timings |
| `Q06` | 发布新版 corpus，显式删除被替代精选 source | manifest plan、零意外 drift、回滚演练 |

## 验收标准

- 正式库不存在无法区分原文、现代解读和命例的混合 chunk。
- 五本经典每个已发布章节都有固定来源、digest、标题和 `classical_original` 标记。
- `ocr_unreviewed`、`course_notes` 和 `case_record` 不进入正式经典问答默认结果。
- “月劫格有什么特征”Top 3 至少包含定义和成格条件，且无不相关命例占据首位。
- AI 解释只执行一次模型请求，准确引用成格条件，不生成未被证据支持的人格或现实断言。
- 预热后的 Top 3 检索在当前本地硬件上不超过 1.5 秒，并显示各阶段耗时。
- 新 corpus release 通过全部概念评估和既有 Knowledge/Bazi 回归后，才删除被覆盖的精选 source。
- 删除后 manifest、数据库 source/chunk 统计、eval 报告和回滚步骤一致且可重复。

## 不包含

- 自动审核或批量发布草稿箱全部内容。
- 把近现代课程、讲义或命例伪装成古籍原文。
- 第二层结构化案例库的保存、共享和相似案例检索。
- 在线自动下载模型、自动调整生产参数或更换 embedding/reranker。
- 在本迭代执行正式 provider p50/p95 压测。

## 建议验证

```text
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -p 'test_knowledge_*.py'
PYTHONPATH=src .venv/bin/python scripts/eval_knowledge_corpus.py --manifest corpora/bazi-theory/v2/manifest.toml
PYTHONPATH=src .venv/bin/python scripts/manage_knowledge_corpus.py plan --manifest corpora/bazi-theory/v2/manifest.toml
PYTHONPATH=src .venv/bin/python -m unittest tests.test_bazi_theory_fixture tests.evals.test_bazi_family_grader -v
git diff --check
```

## 2026-07-28 实施证据

- `Q00-Q02`：新增 `evidence_kind` 与默认理论检索排除规则；`bazi-theory-classics-structured-v2` 发布 9 sources / 402 chunks，六本经典均有结构化章节，《子平真诠》原文、现代解读和命例分为独立 source。
- `Q03`：24 个概念 case 的隔离评估达到 Recall@1 `70.8%`、Recall@3 `95.8%`、Recall@5 `100%`、MRR `82.3%`、citation completeness `100%`，课程/命例误入为 `0`。
- `Q04`：Console AI 解释只取最多 3 条直接相关证据并发起 1 次模型请求；真实 `月劫格有什么特征` 验收使用 2 条直接包含“月劫”的 `classical_original`，不再补入无直接术语依据的片段；响应不重复返回完整召回正文。Console 上传要求选择证据类型，审核拒绝缺失或非法 `evidence_kind` 的 source/chunk。
- `Q05`：启动预热 embedding 与 reranker，`model_idle_ttl_seconds = 0`；修复后真实热检索为 `703.6 ms`，单次生成 `11157.3 ms`，UI 展示 embedding、FTS、vector、rerank、生成和总耗时。
- `Q06`：发布前创建 SQLite 备份，显式删除 replacement matrix 中 7 个旧 source；发布后 manifest 为 9 unchanged / 0 drift，正式库为 9 sources / 402 chunks。
- Browser：`docs/assets/knowledge-console-ai-answer.png` 记录正式 Console AI 解释、模型请求数、tokens、证据类型和阶段耗时。
- Regression：136 项 Knowledge 和 1588 项全量 Python 测试通过；v2 隔离 eval、compileall 与 `git diff --check` 通过。
- Issue 保持 open，等待用户授权关闭；正式 provider p50/p95 基准继续按既定决策延期。
