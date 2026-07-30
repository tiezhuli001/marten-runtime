---
kind: issue
title: "Bazi 私有结构化案例库与双层检索"
type: feature
status: open
created: 2026-07-29
epic: ".cs/epics/003-o-bazi-case-library/spec.md"
---

# Bazi 私有结构化案例库与双层检索

## 目标

完成 Epic `S00-S03` 与 `S05`：提供 owner 隔离的私有案例权威存储、可重建 Knowledge 投影、自然语言工具能力和可重复的 with/without-cases 收益评估。

## 实施清单

- [x] 固定 case/event/schema、owner 与错误契约。
- [x] 实现独立 SQLite store 和版本化事件更新。
- [x] 将当前 turn 成功 Bazi 结果作为不可由模型覆盖的保存快照。
- [x] 实现 owner 专属 Knowledge 投影及更新、归档、删除同步。
- [x] 注册 `bazi_case` capability，并更新 Bazi Agent 工具说明和证据顺序。
- [x] 实现结构分与语义分联合检索，分别返回相似、差异、验证事件和限制。
- [x] 增加 8+ mock 案例和 theory-only / theory+cases 对照评估。
- [x] 运行 focused、Bazi/Knowledge、全量回归和静态检查。

## 不包含

- 共享案例申请、匿名化预览、Operator 审核与公开发布。
- 历史 session 批量抽取或网络命例导入。
- 用案例替代经典理论、确定性排盘或现实专业建议。

## 完成证据

- 独立权威库：`data/bazi_cases/bazi_cases.sqlite3`，启动时幂等创建 case/event schema；本地运行数据由现有 `data/` ignore 规则排除。
- Tool acceptance 覆盖同轮 `chart -> dayun`、`resolve_pillars -> dayun`、缺少可信 owner、事件证据等级和一句话保存。
- 生命周期测试覆盖 owner 隔离、版本更新、投影原子替换失败、归档、删除和隐私字段不进入 projection。
- `evals/cases/bazi_case_library/private_cases_v1.json` 提供 8 个 career/wealth/marriage/education 案例；`scripts/eval_bazi_case_library.py` 使用真实本地 embedding/reranker 运行。
- 真实本地评估：with-cases verified event Recall@3 `100%`，相对 theory-only 提升 `+100` 个百分点，结果契约完整率 `100%`，builtin fact conflicts `0`。
- Focused Bazi case/Knowledge 测试、compileall 与 `git diff --check` 通过；全量 Python 回归 `1601/1601` 通过。
- Issue 保持 open，等待用户授权关闭；共享审核发布 `S04` 未在本次范围内实施。

## Schema V2 增量

- [x] 增加 interpretation、topic conclusions、predictions、reviews 和 raw text，并迁移 V1 SQLite。
- [x] 从真实 Bazi chart 规范化四柱、藏干、五行、十神、关系和大运特征。
- [x] 增加 `import_text`，覆盖用户提供的多案例文本格式。
- [x] 将案例评分升级为结构 45% + 时运 20% + 语义 20% + 反馈质量 15%。
- [x] 实现 direct/near、最低分阈值、同盘多反馈和完整结果解释。
- [x] 扩充 30+ corpus 及 exact/near/distractor 查询，运行真实本地模型评估。
- [x] 运行 focused、Bazi/Knowledge、全量回归和静态检查。

三份语雀来源直接访问时返回 `401 Unauthorized`；用户随后提供本地 Markdown，并已通过 `import_text` 补录筛选后的实际案例。

## Schema V2 完成证据

- 32 个案例、28 个独立查询使用本地 `bge-small-zh-v1.5 + bge-reranker-base`：exact Recall@1、near Recall@3、反馈 Recall@3、干扰拒绝率和结果契约完整率均为 `100%`。
- owner 泄漏、prediction-as-event、builtin fact conflict 均为 `0`。
- focused Bazi case/runtime 回归通过，全量 Python 回归 `1611/1611` 通过。
- Issue 保持 open，等待用户授权关闭；三份语雀案例已通过用户提供的本地 Markdown 补录。

## 本地案例补录证据

- 用户将三份语雀材料汇总到本地 `案例.md`；parser 已支持 Markdown 案例标题、逐行四柱、两行或逗号分隔大运。
- 26 个四柱完整案例中筛选出 15 个包含明确学历、职业、财富、婚姻、子女或命主反馈的案例；11 个只有理论判断或未来预测的案例未导入。
- 初次导入在默认 owner 私有 namespace 生成 15 sources / 80 chunks；后续确认其属于 Operator 可信语料并迁移至共享 curated 层。
- “网络赌博破财”“跨境电商离婚”“乙未运发家身价 2000W”三项真实本地检索均以 direct 结果命中对应案例。

## 完整解盘主链强化

- 完整解盘固定执行 `chart/resolve_pillars -> dayun -> bazi-theory search -> shared + owner-private case search -> finalization`；案例空结果不阻塞回答。
- 运行时强制一次组合案例检索，模型不能在经典检索后提前结束，也不能因空结果降低案例阈值。
- 后续增量已补齐天干五合/克/伏吟、地支三合/三会/六合/冲/刑/害/破/伏吟及跨原局、大运、流年的多方组合；关键神煞继续使用 engine 结构化结果。

## 书籍案例与应期方法增量

- [x] Schema V3 增加来源坐标、事件主体和提取质量，并兼容 V1/V2 数据。
- [x] 实现章节归一化、profile、候选聚合、质量分级、去重和 A/B 导入的通用提取器。
- [x] 为 `命运开启智慧之门`、`八字命理评点` 生成可复核提取报告。
- [x] 实现原局/大运/流年跨层完整干支关系引擎并接入应期逐年表。
- [x] 将经验性应期与取象方法作为现代注解导入 theory RAG，并保留章节与行号。
- [x] 导入真实 A/B 案例，以留出案例运行检索和应期质量前后评估。
- [x] 完成 focused、Bazi/Knowledge、全量回归与静态检查。

本增量不实施共享案例发布，不把书中经验断语写成确定性算法。用户提供的本地书籍按可信输入处理，明确反馈统一记录为 `document_verified`。

### 书籍增量证据

- 两本书共保留 62 个 active A/B 案例；14 个在窗口规则收窄后降为 C/D 的候选已归档并移除投影。当时本地案例仍有 15 个位于默认 owner 私有空间。
- `bazi-theory` 新增 2 个方法 source / 157 chunks，全部具有 embedding 与 sqlite-vec 索引；代表查询使用 `hybrid_rerank` 并命中第 720、382 章。
- 该阶段共有 77 个 active cases / 327 active chunks；随后 62 个书籍案例和 15 个本地可信案例均迁移到共享 curated 层。
- 真实评估：应期年份 Recall@3 `0.50 -> 1.00`，案例 Recall@3、方法 RAG Recall@3、事件主体准确率和 citation 完整率均为 `100%`，prediction-as-event 为 `0`。
- 最终 focused 回归 `49 passed`；全量 Python 回归 `1620 passed + 97 subtests`，未保留失败项。

## 作者经验、完整应期与共享书籍案例增量

- [x] 强制完整解盘使用 full dayun，并在最终材料中保留全部逐年事实。
- [x] 补充天干相生、关键藏干作用和《命运开启智慧之门》主要神煞范围。
- [x] 导入可信书籍完整章节并生成带原文坐标的作者经验卡。
- [x] 实现格局、应期、健康取象和神煞多主题理论查询及篇章去重。
- [x] 将书籍案例迁移为共享审核案例，组合检索共享与 owner 私有案例。
- [x] 增加作者经验、共享隔离、应期完整性和真实命盘评估并执行全量回归。

### 本增量完成证据

- 《命运开启智慧之门》导入 257 个完整相关章节、985 张作者经验卡；重新索引后为 731 个章节 chunks、990 个经验卡 chunks，均具有 embedding 与 sqlite-vec 索引。
- 书籍案例正式层为 62 个 `shared_curated`；原默认 owner 下的 15 个本地可信案例随后迁移到同一共享层，用户主动保存的 `active_private` 当前为 0。
- 作者经验评估覆盖第 707-711 章、火旺木焚和婚姻方法：Recall@3、原文坐标完整率、hybrid rerank 可用率均为 100%。
- 书籍管线评估：应期年份 Recall@3 `0.50 -> 1.00`；案例 Recall@3、方法 RAG Recall@3、主体准确率、引用完整率均为 100%，prediction-as-event 为 0。
- 目标命盘真实 HTTP 主链得到 `甲戌 丁卯 庚戌 庚辰`，执行 `chart -> dayun -> knowledge.search -> bazi_case.search`；1997-2026 共 30 年完整保留，2016 禄神、2017 羊刃、2018 华盖、2019 文昌、2021 天乙、2022 天医、2024 流霞均进入模型材料。
- 目标盘理论检索返回经典原文、作者经验卡和完整教学章节；共享案例未达到 0.60 阈值时返回空案例而不强行类比。

## 本地可信案例共享迁移

- [x] 增加按 `source_run_id` 选择 Operator 导入记录的可重复迁移命令。
- [x] 迁移顺序为先建立并验证共享投影，再归档原私有副本；预测、事件和复盘引用重新生成并保持关联。
- [x] `案例.md` 筛选出的 15 个案例已迁移完成；当前为 77 个 `active_shared`、0 个 `active_private`，共享活动指纹数为 77。
- 私有案例机制继续保留，仅承载未来用户明确执行“一句话保存”产生的案例。
- 真实 HTTP 复测 `run_31b2f3bf` 使用新 owner 完成 `chart -> dayun(full) -> knowledge.search -> bazi_case.search`；案例查询未达到 `0.60` 阈值时返回空列表，没有强行类比。
- 后续性能复测将中文工具结果改为紧凑 UTF-8 JSON，峰值输入由 55,148 降至 26,210、累计 token 由 196,535 降至 120,134；作者卡定向检索已修复。早期固定财富评分和收入区间方案已经废止。
- Provider 上下文继续保留完整应期事实；事件归属、健康、学历、婚姻和财富判断由 LLM 结合理论与案例完成，宿主不再计算财富分数或自动补写领域结论。
- 修复非飞书渠道被局部 `feishu_card` 覆盖完整 Markdown，以及通用 finalization fallback 覆盖 Bazi 已合并文本的问题；最终答案十一栏无缺失。
- 最终全量回归 `1637 passed + 97 subtests`，compileall 与 `git diff --check` 通过。
- 最终全量 Python 回归 `1634 passed + 97 subtests`；真实 provider 主链成功，5 次模型请求，最终回答完成格局、行运、健康、学历、事业、婚姻、六亲、财富和过三关分析。

## 作者经验卡真实检索修复

- 根因是 metadata 过滤原先发生在 FTS/vector 候选截断之后；作者经验卡可能在截断前已被普通章节挤出。严格 FTS 的多词 AND 查询也会因经验卡缺少其中一个词而返回空结果。
- FTS、sqlite-vec 和 JSON cosine 现在都在候选排序前应用 metadata 过滤；限定内容类型的 FTS 在严格查询为空时使用 OR-term 回退，文本包含回退继续保留相同过滤条件。
- 完整解盘只执行一个当前主题的高信号 `content_type=author_method` 查询；最终证据优先保留作者经验卡，`timing_method` 只在作者卡为空时替代。
- 作者方法评估的 Recall@3、引用完整率和 hybrid rerank 可用率均为 `100%`。生产库定向查询可返回 15 张作者卡，超过 100 个高分非目标 chunk 的测试也不会遮蔽目标卡。
- 最终真实 HTTP 复测 `run_c192b0c1` 成功执行 `chart -> dayun(full) -> knowledge.search -> bazi_case.search -> final generation`；理论层返回《子平真诠》原文、《命运开启智慧之门》作者经验卡和完整教学章节。
- `bazi-theory` 与 `bazi-cases-curated` 已按服务使用的绝对模型路径 hash 重建，共重建 2,347 和 327 个 chunks；最终运行的理论、作者卡和案例查询均为 `hybrid_rerank`，无 vector/rerank 降级。
- 修复否定表述“2025 不单独作为桃花年”被应期校验误判的问题。最终运行耗时 `80.261s`，5 次模型请求，provider retry 为 0，累计 `114,285` tokens；十一栏完整，`missing_bazi_sections=[]`、`bazi_timing_contract_violations=[]`，无私有案例措辞。

## 完整生成性能与契约稳定性

- 完整解盘在四项必要工具完成后使用独立 `bazi_final_generation` 请求；该请求保留完整十一栏、应期、财富和引用契约，不暴露工具定义，并使用紧凑排盘、大运、理论与案例材料。
- 首次生成若只有少量领域契约违规，仅修复违规栏目；合并后重新检查十一栏与应期契约，通过后直接返回，不再触发通用完整重写。
- 财富栏在首次生成前强制复核四项算式、唯一收入区间和现实基线边界，消除了本轮真实运行中唯一出现的局部修复原因。
- 最终真实 HTTP 运行 `run_3173107d` 成功执行 `chart -> dayun(full) -> knowledge.search -> bazi_case.search -> bazi_final_generation`；5 次模型请求，provider retry、fallback 和生成重写均为 0。
- 该运行总耗时 `75.090s`，最终生成 `38.664s / 2,035 tokens`，累计 `112,086 tokens`；相对 `run_c192b0c1` 的 `80.261s` 总耗时和约 `46.7s` 最终生成分别减少 `5.171s` 和约 `8.0s`，未删除任何工具步骤或输出栏目。
- 最终状态为 `accepted`；理论证据仍包含《子平真诠》原文、《命运开启智慧之门》作者经验卡和完整教学章节，案例低于 `0.60` 时保持空结果而不强行类比。
- 最终全量回归 `1647 passed + 97 subtests`，`compileall` 与 `git diff --check` 通过。

## 完整解盘内容质量修正

- 应期材料由当前年扩展到未来十年，藏干作用覆盖本气、中气和余气；过三关继续只使用已发生年份。
- 完整解盘作者卡按主题筛选，健康定向查询不再被财富卡替代；真实检索返回《命运开启智慧之门》第 749 章健康作者经验卡。
- 输出契约校验原局夫妻宫冲克，并严格校验神煞的真实年份、名称和辅助表述；拒绝跨年移用及“如见某神煞”假设。
- 参考依据统一书名、移除存储标签与内部方法编号，并在单一栏目内去重。
- 真实 HTTP 复测 `run_b069e9d7` 保持四工具主链，输出正确写明日支戌受时支辰冲、未来 2027 应期、2017 羊刃和 2024 流霞辅助证据；健康作者卡进入最终三条理论证据。
- 聚焦回归 `93 tests`、全量回归 `1654 tests`、`compileall` 和 `git diff --check` 均通过。

## LLM-first 边界修正

- 排盘与应期层只保留四柱、大运、干支关系、藏干关系、伏吟和引擎神煞等确定性事实；删除运行时事件候选、事件归属和领域结构模板。
- Knowledge、作者经验、案例和 Skill 作为证据与约束，由 LLM 完成格局、喜用、主题判断和应期解释。
- 输出契约不再计算财富分数、收入区间，不自动补写夫妻宫、父母健康或神煞结论，也不把模型事件描述替换为预设事件。
- 仍保留十一栏结构、排盘事实一致性、神煞年份配对、夫妻宫关系、现实财富基线和过三关单行单事件校验。
- 聚焦回归覆盖宿主不改写模型结论、Markdown 粗体不误判为财富乘法、过三关单事件结构和评估器不依赖固定学历/财富模型。
- 真实运行 `run_1f55c4bd` 使用 5 次模型请求完成 `chart -> dayun(full) -> knowledge.search -> bazi_case.search -> final generation`，无 retry/fallback，耗时 `71.969s`；理论证据包含经典、作者经验与教学章节，案例低于阈值时为空。
- 加强单事件格式后的真实运行 `run_f9caa745` 最终十一栏、引用和事实契约通过，但首次生成及局部修复仍未一次满足事件格式，触发完整重试并遇到一次 provider 504，总耗时 `193.324s`。最终事件字段已单一化，但“环境转折、方向切换”等仍偏抽象；不在宿主增加固定事件词表，留给后续模型输出质量评估处理。

## 过三关语义质量修正

- 结合《八字是科学它祖宗》的大运、流年与星宫位章节，以及《修真密码十天干》的“寻根基、找出处、引动原理、干支密断”，将过三关定义为用已发生事实校准推理：原局定对象和根基，大运定阶段，流年定具体应验。
- 完整解盘理论查询增加“过三关具体应验”意图；作者方法筛选不再把仅出现“大运流年”的普通财富卡当作过三关证据，真实检索稳定返回《命运开启智慧之门》第 406 章“流年就是具体应验的时间”。
- 新增独立 `bazi_output_semantic_review`：审查模型只判断事件是否包含现实对象、动作和结果，以 JSON 返回失败原因，不推演命理、不提供事件答案；失败后由主模型基于原排盘与检索证据只重写过三关。
- 宿主仍不维护事件词表、不映射命理关系到现实事件，也不自动生成或替换结论；语义审查只约束可核验性。
- 真实运行 `run_5814b2f6` 的审查拒绝“进入新工作阶段、居住地调整、感情推进”，主模型最终只保留“升学结果落定、工作计划被打断”两条高信号事实。主链 8 次模型请求、无 provider retry/error，总耗时 `100.094s`，累计 `129,548` tokens。
- 聚焦回归 `260` 项、全量回归 `1659` 项通过，`compileall` 与 `git diff --check` 通过。

## 应期与过三关质量门最终增量

- [x] 补充岁运藏干对原局和大运透干的确定性关系，同时保持逐年材料大小限制。
- [x] 将《八字是科学它祖宗》《修真密码十天干》的领域章节与作者经验卡导入正式 theory RAG。
- [x] 扩充过三关、应期和星宫位 Recall@3 评估，10 个查询全部命中且 vector/rerank 可用。
- [x] 将过三关审查升级为重大性、明确结果、三层依据和三至五条，并在修复后再次审查；首次解盘不主动索取反馈。
- [x] 结构或语义审查耗尽时返回明确失败，不再将未通过答案标成成功或走通用降级输出。
- [x] 真实运行 `run_bc5f647c` 最终 `accepted`，四项工具顺序、十一栏和过三关四条事件均符合当时契约；当前契约已取消首次解盘反馈入口，仅在用户明确要求时保存案例。
- [x] 最终全量回归 `1664/1664`、`compileall` 与 `git diff --check` 通过。
