# Challenge Eval 设计

> 日期：2026-05-17
> 状态：Implemented on branch codex/eval-challenge-assessment-20260517
> 分支：`codex/eval-challenge-assessment-20260517`
> 范围：为 `marten-runtime` 增加能衡量迭代收益的 challenge eval 体系

## 1. 设计目标

当前 gate eval 已能证明主链、memory、MCP、subagent 等基础链路保持稳定，但大量 scripted case 会稳定得到 100 分。它适合作为回归门禁，无法充分衡量一次 prompt、capability、memory 策略、tool-followup、subagent 策略升级后的质量收益。

Challenge eval 的目标是补齐“升级是否真的更好”的评估能力：

1. 在更难任务上衡量模型完成质量。
2. 用分项评分展示收益来源。
3. 用 baseline delta 展示相对提升和退化。
4. 把 token、tool call、LLM round、retry 纳入效率评估。
5. 通过 live-only suite 覆盖真实 MCP、真实 provider、真实 subagent 行为。

最终判断一次迭代是否有价值，需要同时看：

- gate eval 是否保持通过。
- challenge eval 是否有核心分项提升。
- 同分情况下 token、工具轮次、重试次数是否下降。
- live challenge 是否在多次运行中保持稳定。

## 2. 非目标

本设计暂时不建设通用实验平台，也不引入大规模 LLM-as-judge。

当前阶段不做：

- 在线 A/B 实验平台。
- 多模型排行榜。
- 大规模并发评测集群。
- 自动修改 runtime 热路径。
- 纯主观长文本打分。
- embedding / 语义相似度评测。

第一版只使用结构化 grader、anchor groups、diagnostics、baseline compare、stability report。

## 3. 设计原则

### 3.1 Gate eval 与 challenge eval 分层

- gate eval：证明基础链路健康，目标是稳定通过。
- challenge eval：证明质量变化，目标是暴露差异。

现有 suite 保持 gate 属性：

- `main_chain_core`
- `memory_long_horizon`
- `subagent_task_progress`
- `main_chain_subagent`
- `main_chain_mcp`
- `subagent_external_mcp_completion`

新增 suite 使用 `challenge_*` 命名，报告中明确作为收益评估入口。

### 3.2 评分要能产生差异

Challenge case 不追求每次 100 分。case 应包含多个可部分得分的分项：

- 任务是否完成。
- 工具路径是否正确。
- 证据是否充分。
- 状态是否连续。
- 效率是否改善。

每个分项独立计算，最终通过 `component_summary` 和 `baseline delta` 观察变化。

### 3.3 LLM-first 边界

Challenge eval 只观察 runtime 行为：

- final text
- tool calls
- diagnostics
- memory rows
- subagent task records
- token usage

评测代码负责验证事实与结构，模型继续负责意图理解、工具选择、skill 触发和答案组织。评测体系不得把业务意图路由逻辑带回 runtime。

### 3.4 live 与 scripted 的职责

- scripted challenge：稳定验证 harness、grader、报告和部分 runtime 行为。
- live challenge：验证真实 provider、真实 MCP、真实 token、真实工具链路。

MCP 正式效果评估必须使用 live mode。scripted mode 可以模拟普通工具链路，但不能替代真实 MCP 质量评估。

## 4. Suite 设计

第一版新增 4 个 suite。

| suite | mode | 目标 |
| --- | --- | --- |
| `challenge_memory` | `scripted` + `live` | 衡量记忆在干扰、覆盖、隔离、屏蔽场景下的收益 |
| `challenge_mcp` | `live` only | 衡量真实 MCP 多轮调用、错误恢复、结果归因 |
| `challenge_subagent` | `scripted` + `live` | 衡量子代理委派、重复派发控制、结果整合 |
| `challenge_integrated` | `live` only | 衡量 memory + MCP + subagent + skill 的综合链路 |

推荐第一批实现顺序：

1. `challenge_memory`
2. `challenge_mcp`
3. `challenge_subagent`
4. `challenge_integrated` 中的 skill case

原因：memory 和 MCP 当前最直接影响主链质量；skill 单独评估较单薄，放在 integrated suite 更能体现真实价值。

## 5. 通用评分模型

Challenge case 使用 `component_weights`，不使用旧的 `weights`。

推荐通用结构：

```toml
[component_weights]
task_success = 35
reasoning_quality = 20
tool_path_quality = 20
state_continuity = 15
efficiency = 10

gate_components = ["task_success", "tool_path_quality"]
```

### 5.1 task_success

衡量最终任务是否完成。

证据来源：

- final text 必含信息。
- anchor groups 命中。
- forbid tokens 未出现。
- case-specific expected facts。

### 5.2 reasoning_quality

衡量答案是否基于证据，是否处理冲突和不确定性。

证据来源：

- final text 是否引用或整合工具结果。
- 是否避免旧记忆、错误工具结果或无依据结论。
- 多源结果是否被正确合成。

### 5.3 tool_path_quality

衡量工具选择和调用顺序。

证据来源：

- required tool calls。
- forbidden tool calls。
- MCP 多轮调用数量。
- skill 加载行为。
- subagent spawn 数量。

### 5.4 state_continuity

衡量跨轮、跨会话、memory、subagent 结果是否被正确使用。

证据来源：

- memory rendered context。
- memory tool call。
- session resume / session new diagnostics。
- subagent completion notice。
- parent session history。

### 5.5 efficiency

衡量质量相同或接近时的成本收益。

证据来源：

- `token_total`
- `llm_request_count`
- `tool_calls_count`
- retry / repair 次数
- failover 标记

效率分项第一版使用绝对阈值评分，并在 compare 报告中展示 token、工具轮次、LLM round 的 delta。baseline-relative 奖励作为后续增强，避免第一版把历史对比逻辑耦合进单 case grader。

## 6. Baseline delta 设计

Challenge eval 的报告重点展示 delta。

需要在现有 compare 基础上突出：

```json
{
  "total_score_delta": 4.5,
  "pass_rate_delta": 0.0,
  "component_summary": [
    {"key": "task_success", "delta": 5.0},
    {"key": "tool_path_quality", "delta": 8.0},
    {"key": "efficiency", "delta": -2.0}
  ],
  "token_delta": -1200,
  "tool_call_delta": -1,
  "retry_delta": 0
}
```

判定规则：

- `total_score_delta > 0`：整体收益。
- 核心分项提升：真实能力收益。
- 总分持平且 token / tool / retry 下降：效率收益。
- gate component 下降：回归。
- live suite 分数波动大：稳定性风险。

## 7. Case 设计

### 7.1 `challenge_memory`

#### `memory_interference_recall_cn`

目标：多轮干扰后仍召回正确偏好。

检查点：

- 使用当前有效 memory。
- final text 命中新偏好 anchor。
- 干扰信息未覆盖偏好。
- memory 调用次数受控。

#### `memory_scope_isolation_cn`

目标：global / agent / workspace 记忆同时存在时，只使用当前 scope 可见内容。

检查点：

- 当前 scope 内容出现。
- 其他 agent / workspace 内容不出现。
- memory loader 诊断显示 scope 正确。

#### `memory_overwrite_conflict_cn`

目标：旧偏好被新偏好覆盖后，最终答案使用新偏好。

检查点：

- replace 发生。
- final text 使用新值。
- 旧值未泄漏。

#### `memory_should_not_write_cn`

目标：用户临时表达、一次性约束、测试文本不应被持久化。

检查点：

- 未调用 memory append / replace。
- final text 正常回应当前请求。
- 后续回合不加载这条临时内容。

### 7.2 `challenge_mcp`

#### `mcp_multi_turn_repo_investigation_cn`

目标：真实 GitHub 查询 + 多轮 follow-up，最终给出可验证结论。

检查点：

- 使用 GitHub MCP。
- 至少两轮工具调用。
- final text 包含 repo / commit / path 等证据。
- trace / run diagnostics 可关联。

#### `mcp_result_synthesis_cn`

目标：多次 MCP 结果合成，避免只复述最后一次工具结果。

检查点：

- 多个工具结果均被使用。
- final text 覆盖多个 anchor group。
- 无未证实结论。

#### `mcp_recovery_after_empty_result_cn`

目标：第一次查询结果不足时，模型继续补证据。

检查点：

- 发现结果不足后继续调用合适工具。
- final text 明确基于补充证据。
- 无泛化编造。

### 7.3 `challenge_subagent`

#### `subagent_should_delegate_complex_task_cn`

目标：复杂任务进入 child agent。

检查点：

- spawn_subagent 出现一次。
- child task label 清晰。
- child completion 进入 parent session。
- parent final text 使用 child 结果。

#### `subagent_should_stay_main_thread_cn`

目标：简单任务由主线程完成。

检查点：

- 不调用 spawn_subagent。
- 直接完成任务。
- token 和 LLM round 受控。

#### `subagent_multi_child_synthesis_cn`

目标：多个独立子任务分别委派，并由 parent 合成。

检查点：

- spawn 数量与任务数一致。
- 无重复派发。
- parent final text 覆盖所有 child 结果。

### 7.4 `challenge_integrated`

#### `integrated_memory_mcp_recall_cn`

目标：先加载用户偏好，再用真实 MCP 查询事实，最终答案同时满足事实与偏好。

检查点：

- memory context 被加载。
- GitHub MCP 被调用。
- final text 包含事实结果。
- 输出风格符合 memory preference。

#### `integrated_subagent_mcp_memory_cn`

目标：parent 委派 child 查 GitHub，parent 结合 memory 偏好输出。

检查点：

- parent spawn child。
- child 使用 MCP。
- child completion 返回。
- parent final text 同时使用 child 结果和 memory preference。

#### `skill_required_load_and_apply_cn`

目标：用户明确要求使用某个 skill 时，模型加载 skill 并遵循关键步骤。

检查点：

- 出现 skill 加载工具调用。
- skill 加载次数受控。
- final text 满足 skill 文档中可结构化检查的关键约束。

建议使用已有轻量 skill，避免依赖外部服务。第一版可选择一个本地、确定性强、文档约束明确的 skill。

#### `skill_not_needed_stays_unloaded_cn`

目标：普通问题无需 skill 时，模型保持主链直答。

检查点：

- 不加载 skill。
- final text 回答当前问题。
- LLM round 和 token 受控。

## 8. Skill 评估边界

Skill eval 的价值不在于证明“文件能被读取”，而在于证明模型能在合适时机使用 skill。

因此 skill case 只检查 4 件事：

1. 应该加载时能加载。
2. 不该加载时保持主链完成。
3. 加载后遵循 skill 的关键约束。
4. 多轮时能继续使用 skill 产物。

Skill 不单独建 suite。第一版放入 `challenge_integrated`，避免评估单薄。

## 9. Grader 设计

新增 `challenge` family grader，或在现有 family grader 上扩展 challenge component。

推荐新增：

- `src/marten_runtime/evals/family_graders/challenge.py`

职责：

- 读取 `grader_case` 中声明的 component 检查规则。
- 生成统一 `EvalComponentScore`。
- 保持 grader declarative，避免把 case 语义写进 Python 分支。

`grader_case` 示例：

```toml
[grader_case.task_success]
contains_all = ["main", "SQLite"]
anchor_groups = [["commit", "提交"], ["memory", "记忆"]]
forbid_all = ["无法确认"]

[grader_case.tool_path_quality]
required_tools = ["github.get_file_contents"]
min_tool_calls = 2
max_tool_calls = 5

[grader_case.efficiency]
max_llm_requests = 4
max_tool_calls = 5
max_total_tokens = 18000
```

第一版 grader 能力保持有限：

- 文本 anchor 检查。
- forbidden token 检查。
- required / forbidden tool 检查。
- token / LLM round / tool call 阈值检查。
- subagent / memory / skill diagnostics 检查。

## 10. 报告设计

现有报告已有：

- total score
- case list
- component summary
- baseline compare
- stability summary
- token total

Challenge eval 需要在报告里突出：

1. Challenge suite 标识。
2. Gate component 回归列表。
3. 核心分项 delta。
4. token / tool call / retry delta。
5. live suite stability 样本数。

最小可行改动：

- 在 summary markdown 中为 `challenge_*` suite 增加 “Challenge Delta” 小节。
- 复用 `component_summary`。
- 从 case diagnostics 中提取 token / tool / retry 变化。

## 11. 数据与配置

新增文件布局：

```text
evals/suites/
  challenge_memory.toml
  challenge_mcp.toml
  challenge_subagent.toml
  challenge_integrated.toml

evals/cases/challenge_memory/
  memory_interference_recall_cn.toml
  memory_scope_isolation_cn.toml
  memory_overwrite_conflict_cn.toml
  memory_should_not_write_cn.toml

evals/cases/challenge_mcp/
  mcp_multi_turn_repo_investigation_cn.toml
  mcp_result_synthesis_cn.toml
  mcp_recovery_after_empty_result_cn.toml

evals/cases/challenge_subagent/
  subagent_should_delegate_complex_task_cn.toml
  subagent_should_stay_main_thread_cn.toml
  subagent_multi_child_synthesis_cn.toml

evals/cases/challenge_integrated/
  integrated_memory_mcp_recall_cn.toml
  integrated_subagent_mcp_memory_cn.toml
  skill_required_load_and_apply_cn.toml
  skill_not_needed_stays_unloaded_cn.toml
```

Suite 配置规则：

- `challenge_mcp.scripted_supported = false`
- `challenge_integrated.scripted_supported = false`
- `challenge_memory.scripted_supported = true`
- `challenge_subagent.scripted_supported = true`

## 12. 成功界定

### 12.1 功能成功

- 新增 challenge suite 可被 `--list-suites` 发现。
- suite manifest 全部能加载。
- scripted-supported suite 可在 scripted mode 运行。
- live-only suite 在 scripted mode 快速 blocked。
- live-only suite 缺少 provider / MCP / subagent 依赖时快速 blocked。

### 12.2 评估成功

一次迭代被视为有收益，需要满足：

1. gate eval 全部通过。
2. challenge eval 没有 gate component 回归。
3. 至少一个核心分项出现正向 delta。
4. 同分情况下 token / tool call / retry 至少一项下降。
5. live challenge 至少 2 次运行稳定。

### 12.3 反例成功

Challenge eval 也要能识别退化：

- 错误加载 skill。
- 应该加载 skill 时未加载。
- MCP 只复述最后一次结果。
- memory 使用旧偏好。
- subagent 重复派发。
- token 明显增加且质量未提升。

## 13. 测试计划

### 13.1 Loader / manifest

- 所有 `challenge_*` suite 能加载。
- live-only suite scripted mode 返回 blocked。
- case 的 `component_weights` 合计必须为 100。
- `gate_components` 必须存在于 component weights。

### 13.2 Grader 单测

- task success 支持 contains / anchors / forbid。
- tool path 支持 required / forbidden / min / max。
- efficiency 支持 token / LLM round / tool calls。
- skill trigger 支持 required / forbidden skill loading。
- memory / subagent diagnostics 能参与 state continuity。

### 13.3 Scripted eval

- `challenge_memory --mode scripted` 可运行并产生 component summary；通过 fixture 中的正反样本验证 grader 能区分满分、部分得分和失败。
- `challenge_subagent --mode scripted` 可运行并产生 component summary。

### 13.4 Live eval

- `challenge_mcp --mode live` 使用真实 MCP。
- `challenge_integrated --mode live` 覆盖 memory + MCP + skill 或 subagent 链路。
- 缺依赖时 blocked 报告清晰。

### 13.5 Compare / stability

- 与 `challenge_current` 对比生成 component delta；未传 `--baseline` 时 Challenge suite 默认使用该基线。
- token delta 可见。
- 多次运行后 stability sample size 增长。

## 14. 推进顺序

### Phase 1：Challenge 基础框架

- 新增 challenge suite manifests。
- 新增 challenge grader。
- 新增 loader / manifest / blocked tests。
- 报告显示 challenge delta。

### Phase 2：Memory challenge

- 新增 4 个 memory challenge cases。
- 补 scripted fixtures。
- 跑 baseline compare。

### Phase 3：MCP challenge

- 新增 3 个 live-only MCP challenge cases。
- 使用真实 GitHub MCP。
- 跑 2 次稳定性样本。

### Phase 4：Subagent challenge

- 新增委派边界、重复派发控制、未完成 child 处理 case。
- 验证 parent integration、复用已有 child 结果、避免编造 child 输出。

### Phase 5：Integrated + Skill challenge

- 新增 integrated memory + MCP case。
- 新增 skill required / skill not-needed case。
- 检查 skill 加载、遵循、效率。

## 15. 最佳下一步

先实现 Phase 1 和 Phase 2。

原因：

- 能最快让 eval 从纯 gate 变成收益评估。
- memory challenge 不依赖外部服务，适合作为第一批稳定样本。
- MCP / integrated live challenge 成本更高，适合作为第二批。


## 16. 实现状态

本分支已实现 hard-case 版 challenge eval：

- `challenge_memory`：4 个 hard case，支持 scripted 运行和 compare/stability 报告，覆盖干扰、scope、覆盖、临时指令屏蔽。
- `challenge_mcp`：3 个 live-only hard case，依赖 provider + MCP，覆盖多来源证据、空结果恢复、结果归因。
- `challenge_subagent`：3 个 hard case，支持 scripted 运行和 subagent diagnostics，覆盖委派边界、重复派发控制、未完成 child 处理。
- `challenge_integrated`：4 个 live-only hard case，覆盖 memory + MCP 冲突、subagent + MCP 边界、skill required/no-load。
- `challenge` grader 支持 `rubric_items` 部分得分，报告已显示 `Challenge Delta`，包含 total score、token、tool call、LLM request delta。

运行入口：

```bash
PYTHONPATH=src:. .venv/bin/python scripts/run_eval.py --suite challenge_memory --mode scripted --profile openai_gpt_5_4 --report-root reports/evals --db-path data/evals.sqlite3
PYTHONPATH=src:. .venv/bin/python scripts/run_eval.py --suite challenge_subagent --mode scripted --profile openai_gpt_5_4 --report-root reports/evals --db-path data/evals.sqlite3
PYTHONPATH=src:. .venv/bin/python scripts/run_eval.py --suite challenge_mcp --mode live --profile openai_gpt_5_4 --report-root reports/evals --db-path data/evals.sqlite3 --case-timeout-seconds 180
PYTHONPATH=src:. .venv/bin/python scripts/run_eval.py --suite challenge_integrated --mode live --profile openai_gpt_5_4 --report-root reports/evals --db-path data/evals.sqlite3 --case-timeout-seconds 240
```

解释规则：

- gate eval 主要看是否通过。
- challenge eval 主要看 component summary、`rubric_items`、Challenge Delta 和 stability。
- scripted mode token 为 0 时表示成本由 scripted LLM 屏蔽，真实 token 成本以 live mode 报告为准。
- MCP 正式质量评估以 live mode 的真实 MCP 返回为准。
- challenge suite 出现 100 分时，需要检查 hard case 是否仍有足够区分度，或用报告证明确实满足全部 rubric。

当前 hard-case 基线：

- `challenge_memory` scripted：63.0，pass_rate 0.25，报告 `reports/evals/eval_challenge_memory_20260518032013593515_ce45627_0000`。
- `challenge_subagent` scripted：88.3333，pass_rate 0.6667，报告 `reports/evals/eval_challenge_subagent_20260518032016123323_ce45627_0000`。
- `challenge_mcp` live：93.3333，pass_rate 0.6667，报告 `reports/evals/eval_challenge_mcp_20260518032047952398_ce45627_0000`。
- `challenge_integrated` live：80.5，pass_rate 0.5，报告 `reports/evals/eval_challenge_integrated_20260518033600485760_ce45627_0000`。
