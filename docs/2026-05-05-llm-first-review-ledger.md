# 2026-05-05 LLM-first review ledger

## 范围

- 会话源：`/Users/litiezhu/.codex/sessions/2026/05/02/rollout-2026-05-02T18-38-48-019de844-fe09-7c23-b7c7-8cadf6caf836.jsonl`
- 仓库：`/Users/litiezhu/workspace/github/marten-runtime`
- 分支：`codex/eval-foundation-design-20260430`
- 目标：把 23 轮 review findings 压成根因清单，区分重复修复、真实新增、测试预期漂移

## 总结论

这 23 轮里同时存在两类现象：

1. 同一根因在反复冒出近邻变体。
2. 少量真实新增问题和测试预期漂移混在一起。

主导死循环的是第 1 类。

当前这批问题已经收敛到 7 个根因组，今天复跑热点回归、开放式对抗探测、compileall、diff check 后，清单状态是：

- 已修复：7 组
- 同根因变体：已并入 7 组
- 未验证：0 组
- 仍未修：0 组

## 为什么会跑到 23 轮

1. 很多修复起点是短语级补洞，下一轮很容易被同义表达、反向话术、示例文案、裸字面回复打穿。
2. 首轮 finalization 合同、tool followup 合同、memory intent 合同分布在不同层，修一层后会露出旁边那层的漏口。
3. grounding 规则变严格后，一部分老测试还在断言旧文案，review 会把“实现更严格”和“测试预期过旧”一起报出来。

## 终极去重清单

| 根因组 | 代表性 findings | 结论 | 状态 | 当前证据 |
|---|---|---|---|---|
| durable memory intent 与 mutation grounding | 模糊“记住 …”误写长期记忆；模糊 delete 误删长期记忆；`删除偏好` 无法触发 delete；memory write/delete 成功话术缺少 grounded 校验；`save it to memory` / `delete it from memory` 类表达漏检 | 已收敛到结构化 intent：`intent=durable_write/durable_delete` + `source_excerpt` + 本轮 memory 工具成功结果确认 | 已修复 | `tests.test_memory_intent`、`tests.tools.test_memory_tool`、`tests.test_recovery_flow`、`tests.runtime_loop.test_tool_followup_and_recovery.RuntimeLoopToolFollowupAndRecoveryTests.test_runtime_repairs_memory_paraphrase_claims_with_contract_repair` |
| live time/date/weekday contract | 首轮凭空报当前时间；date-only/weekday/date-paraphrase 漏检；英文/中文 paraphrase 漏检；中文数字/裸字面日期时间漏检 | 已收敛到结构化 `live_time` claim + 本轮 `time` 结果确认，示例/解释任务也保持在 LLM 路径 | 已修复 | `tests.test_recovery_flow`、`tests.runtime_loop.test_tool_followup_and_recovery.RuntimeLoopToolFollowupAndRecoveryTests.test_runtime_keeps_first_turn_live_time_paraphrases_in_llm_path`、`...test_runtime_keeps_first_turn_weekday_reply_in_llm_path` |
| live runtime context contract | 首轮凭空报 token/window/status；`effective window` / `compression` / `replay budget` / `remaining capacity` 变体漏检；裸数字、裸状态词漏检 | 已收敛到结构化 `live_runtime_context` claim + 本轮 `runtime.context_status` 结果确认，概念解释和示例数值文案保持放行 | 已修复 | `tests.test_recovery_flow`、`tests.test_context_governance`、`tests.runtime_loop.test_tool_followup_and_recovery.RuntimeLoopToolFollowupAndRecoveryTests.test_runtime_keeps_first_turn_runtime_paraphrases_in_llm_path` |
| session / subagent success contract | 首轮可凭空确认 session.new、session.resume、current session id、spawn_subagent accepted；自然语言 paraphrase 漏检；错类型成功文案漏检 | 已收敛到结构化 session/subagent claim + 本轮 session / spawn_subagent 结果确认 | 已修复 | `tests.test_recovery_flow`、`tests.runtime_loop.test_tool_followup_and_recovery.RuntimeLoopToolFollowupAndRecoveryTests.test_runtime_repairs_session_family_paraphrases_with_contract_repair`、`...test_runtime_repairs_unbacked_spawn_subagent_acceptance_claim_with_contract_repair` |
| tool followup / recovery evidence coverage | exact grounded summary 命中却因 `coverage_tokens` 存在而被误判；多步 tool followup 汇总不稳定；round-trip 文案与实际 history 不一致 | 已收敛到“先认 exact `result_summary`，再看 `coverage_tokens`”，并保留更严格的本轮 evidence coverage | 已修复 | `tests.test_recovery_flow`、`tests.test_tool_outcome_flow`、`tests.runtime_loop.test_tool_followup_and_recovery`、`tests.runtime_loop.test_direct_rendering_paths` |
| eval run metadata / artifact parity | live eval 未读取 repo `.env`；dirty 状态漏 untracked；`eval_run_id` 秒级冲突；`artifact_root` / `artifact_path` 漂移 | eval 基础设施问题独立存在，已逐项修复，属于真实新增问题 | 已修复 | `tests.evals.test_run_metadata`、`tests.evals.test_store`、`tests.evals.test_report`、`tests.evals.test_run_eval_script` |
| stricter grounding 与测试预期漂移 | 当前实现已经输出 grounded 文案，老测试仍断言旧的宽松文案；典型点在 time、MCP commit、MCP inventory、loop-meta 文案 | 这组属于“实现变严格后测试要跟上”，今天已把热点老测试更新到 grounded 输出 | 已修复 | `tests.runtime_loop.test_direct_rendering_paths`、`tests.runtime_loop.test_tool_followup_and_recovery` |

## 这 23 轮更像什么

这次并不是 23 个互不相关的问题串行出现。

更准确的描述是：

- 7 个根因组反复暴露边界变体
- 其中 2 组夹杂了真实新增基础设施问题
- 最后 1 组是测试预期漂移

当前主热点文件仍然是：

- `/Users/litiezhu/workspace/github/marten-runtime/src/marten_runtime/runtime/recovery_flow.py`

原因很直接：它正好站在“LLM 输出语义”和“host-side grounded enforcement”的交界面。

## 补充收尾问题

这份 23 轮去重清单已经收敛后，又发现了一个清单外的隐藏问题：

| 问题 | 现象 | 结论 | 状态 | 当前证据 |
|---|---|---|---|---|
| test app 生命周期清理不完整 | `build_test_app(...)` 返回的临时 app 在部分测试里只靠 `TemporaryDirectory` 隐式回收；后台 `compaction_worker` 仍可能碰到已回收的临时 sqlite，带出 `ResourceWarning` 或间歇性后台异常噪声 | 属于测试基础设施清理缺口，不是 23 轮 review 死循环主根因；已在 `tests/http_app_support.py` 增加自动 finalizer，统一停止 worker、关闭子代理服务并清理临时目录 | 已修复 | `PYTHONWARNINGS=default PYTHONPATH=src .venv/bin/python -m unittest -v tests.evals.test_executor tests.test_acceptance tests.test_gateway tests.test_init_script`、`PYTHONPATH=src .venv/bin/python -m unittest discover -v tests` |

## 今天的最终验证

### 定向复跑

- `PYTHONPATH=src .venv/bin/python -m unittest -v tests.runtime_loop.test_direct_rendering_paths.RuntimeLoopDirectRenderingPathTests.test_runtime_uses_combined_followup_reply_and_summary_without_third_llm tests.runtime_loop.test_tool_followup_and_recovery.RuntimeLoopToolFollowupAndRecoveryTests.test_runtime_routes_fixed_three_step_sequence_back_through_followup_llm`
- 结果：`2/2 OK`

### 热点回归

- `PYTHONPATH=src .venv/bin/python -m unittest -v tests.test_llm_client tests.test_recovery_flow tests.test_tool_outcome_flow tests.test_context_governance tests.test_gateway tests.runtime_loop.test_tool_followup_and_recovery tests.runtime_loop.test_direct_rendering_paths tests.test_memory_intent tests.tools.test_memory_tool`
- 结果：`184 tests OK`

### 开放式对抗探测

- `PYTHONPATH=src .venv/bin/python -m unittest -v tests.runtime_loop.test_tool_followup_and_recovery.RuntimeLoopToolFollowupAndRecoveryTests.test_runtime_repairs_session_family_paraphrases_with_contract_repair tests.runtime_loop.test_tool_followup_and_recovery.RuntimeLoopToolFollowupAndRecoveryTests.test_runtime_keeps_first_turn_live_time_paraphrases_in_llm_path tests.runtime_loop.test_tool_followup_and_recovery.RuntimeLoopToolFollowupAndRecoveryTests.test_runtime_keeps_first_turn_runtime_paraphrases_in_llm_path tests.runtime_loop.test_tool_followup_and_recovery.RuntimeLoopToolFollowupAndRecoveryTests.test_runtime_repairs_memory_paraphrase_claims_with_contract_repair`
- 结果：`4/4 OK`

### 卫生检查

- `PYTHONPATH=src .venv/bin/python -m compileall -q src tests`
- `git diff --check`
- 结果：通过

## 最终判断

当前这条分支已经走出 review 死循环。

死循环的主因是“同根因边界变体连续暴露”，当前修复把边界从短语级补洞推进到了结构化合同与本轮 evidence grounding，热点回归和开放式对抗探测都已经转绿。
