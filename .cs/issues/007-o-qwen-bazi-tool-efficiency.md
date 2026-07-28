---
kind: issue
title: "Qwen Bazi 工具调用效率"
type: performance
status: open
created: 2026-07-25
---

# Qwen Bazi 工具调用效率

## 目标

将真实 `qwen3.6-plus` Bazi 主链的重复工具调用、累计 token 和端到端延迟降到可接受范围，同时保持排盘事实、Knowledge 引用与敏感观测契约。

## 当前证据

- 真实合成飞书 run `run_6029afae` 成功完成 Bazi、Amap、Knowledge 与飞书投递。
- 工具序列包含 5 次 Bazi 与 2 次 Knowledge 调用，累计 70,685 tokens，耗时约 2 分钟。
- 前一 run `run_8580caed` 使用 7 次 Bazi、2 次 Knowledge与 88,538 tokens，并暴露 Qwen 文本工具标记；文本工具标记已由 runtime finalization 防护修复。

## 范围

- 统计各 Bazi action、Knowledge action、模型轮次、输入/输出 token 与阶段耗时。
- 收敛 Skill 的 action 选择和停止条件，减少等价 chart/dayun/Knowledge 重复调用。
- 为 Qwen profile 建立真实与 scripted 性能基线，保持最终引用和错误降级测试。

## 验证

- 相同固定输入连续 3 次完成，最终文本均含有效 `source_id`、`chunk_id`，且无文本工具标记。
- 每次 action 数、模型轮次、累计 token 与端到端 p50/p95 有明确预算。
- Bazi、Knowledge、runtime loop 与飞书回归保持通过。

## 2026-07-25 执行记录

- Bazi Skill 增加农历出生与四柱输入的精确 payload、每轮 action 预算和成功后停止规则。
- Bazi builtin 对模型产生的十进制整数字符串与 `true/false` 字符串执行无歧义规范化，保持范围、日期和非法文本校验。
- 同一 run 内完全相同的成功 Bazi 请求复用已验证结果，`chart -> dayun` 保持为两个独立 action。
- `chart|resolve_pillars` 与含正文、`source_id`、`chunk_id` 的 theory search 成功后，RuntimeLoop 将新工具请求转为无工具 finalization，阻止 `time`、重复 search 和额外 Bazi action 执行。
- provider 返回无法解析的 JSON 响应时按短暂响应异常重试最多 3 次；结构性协议错误保持单次失败。
- 当前凭据所属服务不提供 `qwen3.6-plus`，Bazi 转用该服务已提供的 `openai_gpt_5_4` profile 完成真实验收。
- 农历输入 run `run_b093f2fc`：`chart=1`、`knowledge.search=1`、无重复 action，4 次模型请求，36,158 tokens，92.44 秒；最终文本包含真实引用且无 `<invoke>`，飞书投递成功。
- 历史四柱输入 run `run_db6cd5b6` 使用 `resolve_pillars=1`、`knowledge.search=1`；当前完整分析契约已升级为唯一已出生候选执行 `resolve_pillars=1`、`dayun=1`、`knowledge.search=1`。
- 工具执行数从基线 7-9 次降为固定 2 次，token 从 70,685-88,538 降为 34,954-36,158；延迟仍由 4 次大模型请求主导。
- 回归通过：Python 1451/1451，Node bridge 42/42，`compileall`，`pip check`，`git diff --check`。

## GPT-5.6 模型基准

- 新凭据确认提供 `gpt-5.6-luna`、`gpt-5.6-sol`、`gpt-5.6-terra`。
- 相同短响应各执行 3 次，全部单次成功：`luna` 中位数/最大值 `2.842/2.956` 秒，`sol` 为 `4.074/7.016` 秒，`terra` 为 `3.400/3.876` 秒。
- 相同强制 `bazi.resolve_pillars` 调用全部一次成功且参数完全正确：`luna/sol/terra` 分别耗时 `3.363/4.901/3.360` 秒。
- `luna` 真实主链 run `run_960b9bba`：`resolve_pillars + knowledge.search`，4 次模型请求，35,722 tokens，252.91 秒，真实引用完整，无 `<invoke>`。
- `terra` 真实主链 run `run_df22a8f1`：`resolve_pillars + knowledge.search`，4 次模型请求，35,015 tokens，161.93 秒，真实引用完整，无 `<invoke>`。
- `sol` 真实主链 run `run_bced8735`：只执行 `resolve_pillars`，跳过 Knowledge search 后生成引用字段，未满足真实引用链要求；3 次模型请求，25,637 tokens，107.11 秒。
- 5.6 系列中 `terra` 是满足完整 Bazi/RAG 契约的最快模型。当前 `gpt-5.4` 四柱主链基线为 85.29 秒，继续作为生产默认模型。

## GPT-5.4 最终验收

- 配置已固定：`default_profile`、main、coding 与 Bazi agent 均使用 `openai_gpt_5_4`，provider 请求模型为 `gpt-5.4`。
- 四柱 run `run_fa7d9283` 完成 4 次模型请求、`resolve_pillars + knowledge.search`、2 条真实引用和飞书投递。
- 当前四柱完整分析链已升级为 `resolve_pillars + dayun + knowledge.search`，唯一已出生候选会自动起运并支撑具体流年分析。
- 农历真太阳时 run `run_8136a7c7` 完成 3 次模型请求、`chart + knowledge.search`、Amap 区县解析、2 条真实引用和飞书投递。
- 两条最终消息均无未解析工具标记；最终回归为 Python 1456/1456、Node 42/42，scripted eval 5/5、100 分。

## 2026-07-27 提交前真实主链

- 当前工作树服务在 `http://127.0.0.1:8000` 启动并达到 `healthz=ok`、`readyz=ready`。
- 合成四柱 run `run_2d1b8549` 完成 `resolve_pillars -> dayun -> knowledge.search`，Knowledge 使用 `hybrid_rerank`，vector 与 reranker 均可用；最终回答 2668 字，必需章节完整，用户侧无内部 `source_id/chunk_id`。
- 本次 provider retry 与 fallback 均为 0，但最终答案契约触发一次无工具重写；总计 5 次模型请求、146,552 tokens、109.558 秒运行时长，HTTP 端到端为 111.920 秒。
- 正确性和恢复路径通过，不构成提交阻碍；模型轮次、token 与延迟继续作为 P2，由本 issue 保持跟踪。

## 2026-07-27 性能优化复验

- Bazi 最终生成移除无关 skill、memory、repository 与 channel protocol 上下文；Dayun provider 结果只保留最高信号的 14 个流年，重复低信号年度与小运不再进入最终请求。
- 输出契约优先执行确定性规范化：过三关的复合/模糊事件压缩为单一可核验动作，无证据的二婚/外缘套话只在婚姻栏删除；局部修复结果在规范化后再次检查十一栏，禁止修复过程裁掉完整栏目。
- 最新源码首次 smoke `run_c4bce53a` 暴露局部修复后只剩命盘与过三关的回归；该结果不作为验收证据。新增栏目保全与紧凑多主题事件测试后，聚焦回归 `145/145` 通过。
- 最终真实 run `run_52fde342` 完成 `resolve_pillars -> dayun -> knowledge.search`，Knowledge 为 `hybrid_rerank` 且 vector/reranker 可用；正文 3,480 字，十一栏完整，`missing_bazi_sections=[]`，`bazi_timing_contract_violations=[]`。
- `run_52fde342` 使用 4 次模型请求、89,916 输入 tokens、3,203 输出 tokens、93,119 合计 tokens，runtime 79.566 秒，HTTP 84.002 秒，provider retry/fallback 均为 0，未触发第 5 次 `bazi_output_repair`。
- 相比 `run_2d1b8549`，模型请求减少 20%，累计 tokens 下降 36.5%，runtime 下降 27.4%，HTTP 端到端下降 24.9%；最终生成单次 provider 延迟仍有随机波动，是剩余 P2 风险。
- 最新自动化验证通过：Python `1556/1556`、Node `43/43`、scripted Bazi eval `eval_bazi_agent_20260727153018655828_c7a21d4_0000` 为 `5/5` 且 100 分、`compileall`、host/container `pip check`、`git diff --check`。
- 构建镜像 `marten-runtime:precommit-20260727-perf`（`sha256:3e6a5c10b9fc38e77d72a4b0d2b94254fb2bd8ce5e1f128ec8537997420ee84e`）；build-time self-check、断网 self-check、SBOM/许可材料、断网容器 `healthy`、`healthz=ok`、`readyz=ready` 均通过。
- 用户确认当前性能优化已达到提交条件。真实 provider 的连续 smoke 与正式 p50/p95 基准转入 `.cs/spec/knowledge-runtime.md` 的“后续真实性能基准”，待 RAG 语料与检索形态稳定后执行，不再阻塞本次提交。
