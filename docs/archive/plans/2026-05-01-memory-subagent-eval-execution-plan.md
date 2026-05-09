# Memory 长期收益与子代理任务推进评测执行计划

> **面向编码 agent：** 必须使用 `executing-plans` 落地这份计划。只有用户明确授权并行委派时，才使用 `subagent-driven-development`。执行步骤继续使用复选框 `- [ ]` 追踪。
>
> 这份计划的仓库执行约束：
> - 改文件前先在命名分支上工作
> - 整轮执行使用 `long-run-execution`
> - 保持 eval 留在离线运维面，同时保持 runtime 热路径稳定
> - 保持 LLM-first 边界稳定；行为问题优先通过 prompt、tool 描述、capability 元数据和 case 设计修正
> - 只有用户明确要求时才 commit 或 push

**目标：** 在现有评测基础层之上，补齐 `memory 长期收益评测` 与 `subagent 任务推进评测` 两个专项套件，让 `marten-runtime` 可以用统一 runner / store / compare / report 执行不同评分族的评测，并把每条分数追溯到真实运行证据。

**架构：** 继续复用已经完成的 case/suite TOML、HTTP app executor、SQLite store、baseline compare、Markdown / JSON / HTML 报告。新增内容只放在评分层和取证层：用一个很薄的 `grader registry` 按 suite 选择评分器，用 `score_breakdown_json.components` 承载通用维度结果，用 executor 在需要时补采集 session / subagent 诊断证据。现有 `main_chain_*` 套件继续走原来的主链评分器。

**技术栈：** Python 3.11、`tomllib`、`sqlite3`、FastAPI `TestClient`、现有 runtime diagnostics、现有 `/diagnostics/subagent/*` 与 `/diagnostics/session/*` 接口、`unittest`。

---

## 0. 计划作用与边界

这份计划直接约束编码 agent 的实现行为，目标很单一：在 `/Users/litiezhu/workspace/github/marten-runtime/docs/2026-04-30-main-chain-eval-foundation-design.md` 和 `/Users/litiezhu/workspace/github/marten-runtime/docs/archive/plans/2026-04-30-main-chain-eval-foundation-execution-plan.md` 已落地的基础上，补齐下一阶段最值得做的两类专项评测。

这份计划覆盖全部 Slice：

- Slice 1：评分族骨架与通用组件分数面
- Slice 2：证据采集增强与 executor 对齐
- Slice 3：`memory_long_horizon` 套件与评分器
- Slice 4：`subagent_task_progress` 套件与评分器
- Slice 5：compare / report 展示、文档索引、最终 proof

这份计划保持以下边界：

- 继续复用现有 SQLite 历史存储，不新增第二套存储
- 继续复用现有 `scripts/run_eval.py`，不新开服务
- 继续复用现有 HTML/Markdown/JSON 报告面，不做在线面板
- 不把评测逻辑写回 runtime 热路径
- 不把 memory 或 subagent 的产品修复混入本轮范围
- 不进入 `个性化偏好留存评测`
- 不建设通用 rubric 平台

## 1. 仓库现状结论

编码 agent 在动手前要先锁定三条结论：

1. 现有基础层已经够用
   - `evals/suites/*.toml`
   - `evals/cases/**`
   - `src/marten_runtime/evals/{models,loader,executor,store,compare,report}.py`
   - `scripts/run_eval.py`

2. 当前缺口集中在评分层
   - 当前 `graders.py` 只适合主链四维：`outcome / tool_path / efficiency / context`
   - `memory 长期收益` 与 `subagent 任务推进` 需要各自的专属评分维度

3. 当前最优实现方式是统一框架、分族评分
   - 同一个 runner
   - 同一个 SQLite store
   - 同一个 baseline compare
   - 同一个 HTML / Markdown / JSON report
   - 按 suite 选择不同 grader

## 2. 编码 agent 全局约束

### 2.1 分支与执行纪律

- [ ] 从命名分支开始执行，禁止在 `main` 上直接改文件
- [ ] 每完成一个 Slice 都运行该 Slice 的 proof
- [ ] proof 失败时先修实现，再继续下一个 Slice
- [ ] 每个 Slice 结束都检查计划与实现有没有漂移

### 2.2 架构约束

- [ ] 评测代码继续只放在离线运维面
- [ ] `scripts/run_eval.py` 继续是唯一命令入口
- [ ] runtime 主链继续保持：`channel -> binding -> runtime loop -> builtin / MCP / skill -> delivery / diagnostics`
- [ ] 不把专项评分逻辑写进 `src/marten_runtime/runtime/loop.py`
- [ ] 不引入 host-side intent router、tool router、workflow controller
- [ ] memory / subagent 评测的行为判断依赖观察结果，不新增 runtime if/else 分流

### 2.3 设计优雅约束

- [ ] 同一类信息只保留一个权威载体
- [ ] 组件分数统一放到 `score_breakdown_json.components`
- [ ] 评分器选择统一走 `grader registry`
- [ ] suite 维度差异统一靠 manifest 和 case 元数据表达
- [ ] 取证增强优先复用现有 diagnostics 接口
- [ ] 没有复用价值的通用化先不做

### 2.4 测试约束

- [ ] 新测试继续放到 `tests/evals/`
- [ ] 继续使用 `unittest`
- [ ] scripted proof 必须覆盖两个新套件
- [ ] live proof 依赖缺失时要明确给出 blocked/skip 语义
- [ ] 现有 `main_chain_core` compare/report 能力继续保持兼容

### 2.5 文档与状态约束

- [ ] 本计划文档实现后，`docs/README.md` 要出现入口
- [ ] `STATUS.md` 要记录这份计划已经起草完成
- [ ] 计划文档只写执行约束，不写产品宣传性描述

## 3. 方案锁定

### 3.1 评分器选择方式

新增 `grader_id`，由 suite manifest 负责声明，case 默认继承 suite 的 `grader_id`。

锁定三类评分器：

- `main_chain_core`
- `memory_long_horizon`
- `subagent_task_progress`

编码 agent 要避免把 `case.family` 继续承担评分器路由职责。当前仓库里 `family` 已经被 case 用作主题分类，继续复用它会造成语义漂移。

### 3.2 通用组件分数面

新增一个统一分数载体：

- `score_breakdown_json.components`

每个 component 至少包含：

- `key`
- `label`
- `weight`
- `ratio`
- `score`
- `passed`
- `details`

保留现有 `EvalCaseResult` 的这四个 legacy 字段：

- `outcome_score`
- `tool_path_score`
- `efficiency_score`
- `context_score`

用法锁定：

- `main_chain_*` 继续按现有四维填充 legacy 字段
- 新专项套件的总分以 `components` 为准
- 新专项套件的 legacy 字段允许作为兼容占位保留，不承担主要解释职责
- compare/report 新增组件级展示时，一律读取 `components`
- compare/report 额外生成 suite 级 `component_summary`，用于回答“这一轮 memory recall 或 subagent integration 整体提升了多少”
- suite 级 `component_summary` 至少包含 `key`、`label`、`current_score`、`baseline_score`、`delta`、`case_count`

这样可以保持 SQLite schema 轻量稳定，同时让新专项拥有通用评分解释面，也让报告首页可以直接展示各组件的整体变化。

### 3.3 case 模型扩展方式

在 `EvalCaseSpec` 上新增三块轻量元数据：

- `grader_id: str | None`
- `component_weights: dict[str, int]`
- `gate_components: list[str]`
- `grader_case: dict[str, object]`

约束锁定：

- 当前 `main_chain_*` case 继续保留 `weights`
- 新专项 case 使用 `component_weights`
- `component_weights` 总和必须等于 `100`
- `gate_components` 只允许引用 `component_weights` 中已定义的 key
- `grader_case` 只放当前评分器需要的期望字段

### 3.4 suite 模型扩展方式

在 `EvalSuiteSpec` 上新增：

- `grader_id: str`

可选新增：

- `case_defaults: dict[str, object]`

当前最简实现可以只加 `grader_id`，然后由 loader 在 suite 级别把默认 `grader_id` 回填到 case。`case_defaults` 这轮先不做，保持结构更薄。

`suite.required_dependencies` 同时升级为 live 阻塞检查的权威输入。`scripts/run_eval.py` 统一按 manifest 解析依赖项，首批支持：

- `provider`
- `mcp`
- `subagent`

runner 只读取 `required_dependencies`，不再按 `suite_id` 写分支判断。

### 3.5 评分状态与 gate 规则

状态规则保持统一：

- `passed`
- `failed`
- `blocked`
- `warning`

专项评分的 gate 规则锁定为：

- 只看 `gate_components`
- `gate_components` 里所有组件都 passed，且 observation 没有 hard error，case 才能进入 `passed`
- `required = false` 的 case 仍可进入 `warning`

## 4. 证据采集锁定

### 4.1 继续复用的证据

当前 executor 已经能稳定拿到：

- `final_text`
- `run_id`
- `trace_id`
- `tool_calls`
- `provider_ref`
- `final_provider_ref`
- `compaction`
- 每轮 `/messages` 响应与 `/diagnostics/run/{run_id}` 结果

这些证据继续保留。

### 4.2 memory 套件新增证据

memory 专项优先复用已有工具调用证据：

- `tool_calls[*].tool_name`
- `tool_calls[*].tool_payload`
- `tool_calls[*].tool_result`
- `final_text`
- `turns`
- `active_session_id`

这套专项本轮不要求新增 memory 专用诊断接口。

### 4.3 subagent 套件新增证据

subagent 专项需要 executor 在 case 结束后补采集：

- `active_session_id` 对应的 `/diagnostics/session/{session_id}` 历史
- 每个 `spawn_subagent` 返回 `task_id` 对应的 `/diagnostics/subagent/{task_id}` 详情
- 必要时 `client.get("/diagnostics/subagents")` 的列表结果
- 每个 child `run_id` 对应的 `/diagnostics/run/{child_run_id}`

这些信息全部塞进 observation 的 `diagnostics_json`，不再新开第二个 observation 模型。

### 4.4 等待子代理完成的规则

只对 `grader_id = subagent_task_progress` 且 `grader_case.await_child_completion = true` 的 case，executor 执行有限轮询：

- 默认 `poll_interval_ms = 100`
- 默认 `timeout_ms = 5000`
- 到达终态：`succeeded / failed / cancelled / timed_out`
- 超时后把证据写入 `diagnostics_json.subagent.timeout = true`
- 超时本身是否 fail，由评分器决定

这条逻辑只属于 eval harness，不属于 runtime 热路径。

## 5. 评分族定义

## 5.1 `memory_long_horizon`

这个 suite 要回答的问题是：memory 能否真的留下长期收益，而不是只证明工具可用。

组件集合锁定为：

- `capture`
  - 该写的时候写了
  - section / action / content 与 case 期望一致
- `delayed_recall`
  - 隔轮或切换 session 后还能正确拿回目标记忆
- `overwrite_correctness`
  - 更新后的值成为新基线
- `stale_rejection`
  - 旧值或冲突值不再污染最终回答
- `utility_gain`
  - 最终回答真的应用了记忆，而不是只把记忆原文复述出来

本轮 memory suite 的 case 集合锁定为：

- `memory_capture_preference_cn.toml`
- `memory_delayed_recall_same_session_cn.toml`
- `memory_delayed_recall_cross_session_cn.toml`
- `memory_overwrite_then_recall_cn.toml`
- `memory_long_gap_with_interference_recall_cn.toml`
- `memory_stale_conflict_rejection_cn.toml`
- `memory_preference_applied_to_output_cn.toml`

每条 case 只声明自己关心的 component，未声明的 component 不参与该 case 评分。

推荐的 `grader_case` 字段集合锁定为：

- `expected_memory_action`
- `expected_section`
- `expected_content_contains`
- `recall_contains_all`
- `recall_forbid_all`
- `utility_contains_all`
- `utility_forbid_all`
- `expected_session_transition`
- `min_interference_turns`
- `max_memory_calls`

### 5.2 `subagent_task_progress`

这个 suite 要回答的问题是：子代理是否真的推进了任务，而不是只留下“已受理”或重复委派。

组件集合锁定为：

- `delegation_quality`
  - 该委派时发起一次正确委派
  - 该主线程直答时保持主线程完成
- `child_progress`
  - child 任务进入 running / succeeded，且有真实 child run 证据
- `child_completion`
  - child 走到终态，并有明确结果摘要
- `parent_integration`
  - parent 会话收到完成通知，后续追问能利用 child 结果
- `duplicate_dispatch_penalty`
  - 同一任务没有重复 spawn，没有无意义二次派发

本轮 subagent suite 的 case 集合锁定为：

- `subagent_background_task_acceptance_cn.toml`
- `subagent_child_completion_notice_cn.toml`
- `subagent_followup_uses_child_result_cn.toml`
- `subagent_multi_child_progress_cn.toml`
- `subagent_duplicate_dispatch_penalty_cn.toml`
- `subagent_simple_request_stays_main_thread_cn.toml`

推荐的 `grader_case` 字段集合锁定为：

- `expected_spawn_count`
- `expected_child_terminal_status`
- `expected_child_tool_names`
- `parent_notice_contains_all`
- `followup_contains_all`
- `followup_forbid_all`
- `allow_zero_spawn`
- `await_child_completion`
- `min_child_success_count`
- `max_spawn_count`

## 6. 文件结构锁定

### 6.1 新建文件

先创建目录骨架：

- `evals/cases/memory_long_horizon/`
- `evals/cases/subagent_task_progress/`
- `src/marten_runtime/evals/family_graders/`

- `docs/archive/plans/2026-05-01-memory-subagent-eval-execution-plan.md`
- `evals/suites/memory_long_horizon.toml`
- `evals/suites/subagent_task_progress.toml`
- `evals/cases/memory_long_horizon/memory_capture_preference_cn.toml`
- `evals/cases/memory_long_horizon/memory_delayed_recall_same_session_cn.toml`
- `evals/cases/memory_long_horizon/memory_delayed_recall_cross_session_cn.toml`
- `evals/cases/memory_long_horizon/memory_overwrite_then_recall_cn.toml`
- `evals/cases/memory_long_horizon/memory_long_gap_with_interference_recall_cn.toml`
- `evals/cases/memory_long_horizon/memory_stale_conflict_rejection_cn.toml`
- `evals/cases/memory_long_horizon/memory_preference_applied_to_output_cn.toml`
- `evals/cases/subagent_task_progress/subagent_background_task_acceptance_cn.toml`
- `evals/cases/subagent_task_progress/subagent_child_completion_notice_cn.toml`
- `evals/cases/subagent_task_progress/subagent_followup_uses_child_result_cn.toml`
- `evals/cases/subagent_task_progress/subagent_multi_child_progress_cn.toml`
- `evals/cases/subagent_task_progress/subagent_duplicate_dispatch_penalty_cn.toml`
- `evals/cases/subagent_task_progress/subagent_simple_request_stays_main_thread_cn.toml`
- `evals/fixtures/memory/durable_preferences_cn.md`
- `evals/fixtures/memory/stale_conflict_cn.md`
- `src/marten_runtime/evals/grader_registry.py`
- `src/marten_runtime/evals/family_graders/__init__.py`
- `src/marten_runtime/evals/family_graders/main_chain.py`
- `src/marten_runtime/evals/family_graders/memory_long_horizon.py`
- `src/marten_runtime/evals/family_graders/subagent_task_progress.py`
- `tests/evals/test_grader_registry.py`
- `tests/evals/test_memory_family_grader.py`
- `tests/evals/test_subagent_family_grader.py`

### 6.2 修改文件

- `src/marten_runtime/evals/models.py`
- `src/marten_runtime/evals/loader.py`
- `src/marten_runtime/evals/graders.py`
- `src/marten_runtime/evals/executor.py`
- `src/marten_runtime/evals/compare.py`
- `src/marten_runtime/evals/report.py`
- `scripts/run_eval.py`
- `tests/evals/test_models.py`
- `tests/evals/test_loader.py`
- `tests/evals/test_executor.py`
- `tests/evals/test_compare.py`
- `tests/evals/test_report.py`
- `tests/evals/test_run_eval_script.py`
- `tests/evals/test_suite_manifests.py`
- `docs/README.md`
- `STATUS.md`

### 6.3 明确不改的文件

除非遇到真实阻塞，这轮不改：

- `src/marten_runtime/runtime/loop.py`
- `src/marten_runtime/runtime/capabilities.py`
- `src/marten_runtime/tools/builtins/*.py`
- `src/marten_runtime/interfaces/http/app.py`
- `tests/test_acceptance.py`

## 7. Slice 1：评分族骨架与兼容层

### Task 1: 扩展模型，锁定 suite/case 的评分元数据

**Files:**
- Modify: `src/marten_runtime/evals/models.py`
- Modify: `tests/evals/test_models.py`

- [ ] 给 `EvalSuiteSpec` 增加 `grader_id`
- [ ] 给 `EvalCaseSpec` 增加 `grader_id`、`component_weights`、`gate_components`、`grader_case`
- [ ] 让 `weights` 支持“main_chain 继续使用、专项 case 可空”
- [ ] 新增校验：`component_weights` 总和为 `100`
- [ ] 新增校验：`gate_components` 只能引用已声明 component
- [ ] 继续保持现有 `weights` 校验逻辑对老 case 生效

### Task 2: 引入 `grader registry`

**Files:**
- Create: `src/marten_runtime/evals/grader_registry.py`
- Create: `src/marten_runtime/evals/family_graders/__init__.py`
- Create: `src/marten_runtime/evals/family_graders/main_chain.py`
- Modify: `src/marten_runtime/evals/graders.py`
- Create: `tests/evals/test_grader_registry.py`
- Modify: `tests/evals/test_compare.py`

- [ ] 把当前 `graders.py` 的主链逻辑移动到 `family_graders/main_chain.py`
- [ ] `graders.py` 保留一个稳定入口，内部委托给 registry
- [ ] registry 以 `case.grader_id` 选择评分器
- [ ] main-chain grader 继续产出当前四维分数
- [ ] main-chain grader 额外把四维结果写入 `score_breakdown_json.components`

### Task 3: compare / report 对组件分数保持兼容

**Files:**
- Modify: `src/marten_runtime/evals/compare.py`
- Modify: `src/marten_runtime/evals/report.py`
- Modify: `tests/evals/test_report.py`
- Modify: `tests/evals/test_compare.py`

- [ ] `EvalCaseComparison` 增加组件级 delta 结构
- [ ] `EvalRunComparison` 或报告输入新增 suite 级 `component_summary`
- [ ] compare 读取 `score_breakdown_json.components` 生成 case 级与 suite 级 component 汇总
- [ ] 报告首页展示 suite 级组件分数、基线分数、delta
- [ ] 报告详情页继续展示 case 级组件分数、基线分数、delta
- [ ] 当前 `main_chain_core` 报告继续可读

### Slice 1 Proof

Run:

```bash
cd /Users/litiezhu/workspace/github/marten-runtime && \
PYTHONPATH=src .venv/bin/python -m unittest -v \
  tests.evals.test_models \
  tests.evals.test_loader \
  tests.evals.test_grader_registry \
  tests.evals.test_compare \
  tests.evals.test_report \
  tests.evals.test_suite_manifests && \
PYTHONPATH=src .venv/bin/python -m compileall -q src tests && \
git diff --check
```

Expected:

- 新模型字段校验通过
- 老 `main_chain_*` case 继续能被 loader 正常加载
- compare/report 能显示 component 级信息
- `compileall` 与 `git diff --check` 通过

## 8. Slice 2：executor 证据采集增强

### Task 4: executor 为专项评分补取证

**Files:**
- Modify: `src/marten_runtime/evals/executor.py`
- Modify: `tests/evals/test_executor.py`

- [ ] 当 case 使用 `memory_long_horizon` 时，继续复用现有 `tool_calls + turns + final_text`
- [ ] 当 case 使用 `subagent_task_progress` 且 `await_child_completion = true` 时，轮询 `/diagnostics/subagent/{task_id}`
- [ ] 取回 parent session 历史：`/diagnostics/session/{active_session_id}`
- [ ] 取回 child run 诊断：`/diagnostics/run/{child_run_id}`
- [ ] 把这些证据写入 `diagnostics_json.subagent`
- [ ] 超时或缺证据时保留原始诊断内容，不要吞掉证据

### Task 5: scripted harness 补齐专项 case 的可控行为

**Files:**
- Modify: `src/marten_runtime/evals/executor.py`
- Modify: `tests/evals/test_executor.py`
- Modify: `tests/evals/test_run_eval_script.py`

- [ ] 扩展 scripted LLM stub，支持 memory suite 的新 case id
- [ ] 扩展 scripted child 行为，支持 subagent suite 的新 case id
- [ ] scripted subagent case 要能稳定产出 child success / parent notice / follow-up absorb 三类证据
- [ ] `scripts/run_eval.py` 跑 scripted 新套件时，产物路径和 baseline compare 继续正常

### Slice 2 Proof

Run:

```bash
cd /Users/litiezhu/workspace/github/marten-runtime && \
PYTHONPATH=src .venv/bin/python -m unittest -v \
  tests.evals.test_executor \
  tests.evals.test_run_eval_script \
  tests.evals.test_report && \
PYTHONPATH=src .venv/bin/python -m compileall -q src tests && \
git diff --check
```

Expected:

- executor 能拿到 subagent 详情与 session 历史
- scripted 下专项证据稳定
- CLI 产物结构保持兼容

## 9. Slice 3：`memory_long_horizon` 套件与评分器

### Task 6: 建立 memory suite manifests 与 fixtures

**Files:**
- Create: `evals/suites/memory_long_horizon.toml`
- Create: `evals/cases/memory_long_horizon/*.toml`
- Create: `evals/fixtures/memory/durable_preferences_cn.md`
- Create: `evals/fixtures/memory/stale_conflict_cn.md`
- Modify: `tests/evals/test_loader.py`

- [ ] suite manifest 使用 `grader_id = "memory_long_horizon"`
- [ ] `default_mode = "live"`
- [ ] `scripted_supported = true`
- [ ] `required_dependencies = ["provider"]`
- [ ] live provider blocked 语义直接复用 runner 的通用依赖解析
- [ ] 每个 case 的 `component_weights` 只覆盖它真的关心的维度
- [ ] 每个 case 的 `gate_components` 只保留“答对当前问题必须成立”的维度
- [ ] `memory_long_gap_with_interference_recall_cn.toml` 至少包含一次 durable 写入、两段以上中间干扰、一次最终召回
- [ ] 这条长间隔 case 的中间干扰要覆盖“无关问答 + 无关工具”两类噪音，保证它评到的是真正的长期收益

### Task 7: 实现 memory family grader

**Files:**
- Create: `src/marten_runtime/evals/family_graders/memory_long_horizon.py`
- Modify: `src/marten_runtime/evals/grader_registry.py`
- Create: `tests/evals/test_memory_family_grader.py`

- [ ] 基于 `tool_calls` 判断 `capture`
- [ ] 基于后续 turn 的最终回答判断 `delayed_recall`
- [ ] 对长间隔 case 额外校验中间干扰后仍然引用同一 durable memory，而不是退回当前上下文猜测
- [ ] 基于 `replace` 后的新旧值切换判断 `overwrite_correctness`
- [ ] 基于最终回答禁词与旧值残留判断 `stale_rejection`
- [ ] 基于最终回答是否体现偏好应用判断 `utility_gain`
- [ ] 每个 component 的 `details` 必须能说明为什么得分或失分

### Task 8: scripted + compare proof 跑通 memory suite

**Files:**
- Modify: `tests/evals/test_run_eval_script.py`
- Modify: `tests/evals/test_report.py`

- [ ] scripted 运行 `memory_long_horizon` 一次
- [ ] 以第一次结果写 `latest_passed`
- [ ] 再跑一次 compare，确认报告可以展示 component delta

### Slice 3 Proof

Run:

```bash
cd /Users/litiezhu/workspace/github/marten-runtime && \
PYTHONPATH=src .venv/bin/python -m unittest -v \
  tests.evals.test_loader \
  tests.evals.test_memory_family_grader \
  tests.evals.test_run_eval_script \
  tests.evals.test_report && \
PYTHONPATH=src .venv/bin/python scripts/run_eval.py \
  --suite memory_long_horizon \
  --mode scripted \
  --profile openai_gpt_5_4 && \
PYTHONPATH=src .venv/bin/python scripts/run_eval.py \
  --suite memory_long_horizon \
  --mode scripted \
  --profile openai_gpt_5_4 \
  --baseline latest_passed && \
PYTHONPATH=src .venv/bin/python -m compileall -q src tests && \
git diff --check
```

Expected:

- memory suite scripted 通过
- compare 报告中能看到 memory 组件分数
- case 详情能解释 capture / recall / stale / utility 的得失

## 10. Slice 4：`subagent_task_progress` 套件与评分器

### Task 9: 建立 subagent suite manifests 与 cases

**Files:**
- Create: `evals/suites/subagent_task_progress.toml`
- Create: `evals/cases/subagent_task_progress/*.toml`
- Modify: `tests/evals/test_loader.py`

- [ ] suite manifest 使用 `grader_id = "subagent_task_progress"`
- [ ] `default_mode = "live"`
- [ ] `scripted_supported = true`
- [ ] `required_dependencies = ["provider", "subagent"]`
- [ ] `scripts/run_eval.py` 只读取 `suite.required_dependencies` 进行阻塞判断
- [ ] case 设计优先覆盖“正确委派、推进成功、结果吸收、避免重复派发”四件事
- [ ] `subagent_multi_child_progress_cn.toml` 明确要求同一父任务拆成两个子任务，并要求 parent 后续回答吸收两个 child 的结果
- [ ] 这条多子任务 case 用来证明“合法多 child 推进”和“重复派发”是两种不同情况
- [ ] case 文案尽量明确，减少让模型靠模糊猜测来决定是否委派

### Task 10: 实现 subagent family grader

**Files:**
- Create: `src/marten_runtime/evals/family_graders/subagent_task_progress.py`
- Modify: `src/marten_runtime/evals/grader_registry.py`
- Create: `tests/evals/test_subagent_family_grader.py`

- [ ] 用 parent `spawn_subagent` 调用次数判断 `delegation_quality`
- [ ] 用 task 详情中的 `status / child_run_id / child_session_id` 判断 `child_progress`
- [ ] 用 child run 结果与 task 终态判断 `child_completion`
- [ ] 用 parent session history 中的 completion system message 和 follow-up answer 判断 `parent_integration`
- [ ] 对 `subagent_multi_child_progress_cn.toml` 校验两个 child 都有独立 `task_id / child_run_id / terminal status`，且 parent 汇总吸收两份结果
- [ ] 用额外 spawn 次数与重复 task 判断 `duplicate_dispatch_penalty`
- [ ] `duplicate_dispatch_penalty` 对合法双 child case 维持通过，对重复派发 case 明确扣分

### Task 11: scripted + compare proof 跑通 subagent suite

**Files:**
- Modify: `tests/evals/test_executor.py`
- Modify: `tests/evals/test_run_eval_script.py`
- Modify: `tests/evals/test_report.py`

- [ ] scripted 运行 `subagent_task_progress` 一次
- [ ] 以第一次结果写 `latest_passed`
- [ ] 再跑一次 compare，确认组件分数和 child evidence 能展示

### Slice 4 Proof

Run:

```bash
cd /Users/litiezhu/workspace/github/marten-runtime && \
PYTHONPATH=src .venv/bin/python -m unittest -v \
  tests.evals.test_loader \
  tests.evals.test_subagent_family_grader \
  tests.evals.test_executor \
  tests.evals.test_run_eval_script \
  tests.evals.test_report && \
PYTHONPATH=src .venv/bin/python scripts/run_eval.py \
  --suite subagent_task_progress \
  --mode scripted \
  --profile openai_gpt_5_4 && \
PYTHONPATH=src .venv/bin/python scripts/run_eval.py \
  --suite subagent_task_progress \
  --mode scripted \
  --profile openai_gpt_5_4 \
  --baseline latest_passed && \
PYTHONPATH=src .venv/bin/python -m compileall -q src tests && \
git diff --check
```

Expected:

- subagent suite scripted 通过
- compare 报告可读出 delegation / child completion / parent integration 的变化
- 报告详情能看到 child task id、child run id、terminal status 等关键证据

## 11. Slice 5：文档同步与最终 proof

### Task 12: 文档索引与状态同步

**Files:**
- Modify: `docs/README.md`
- Modify: `STATUS.md`

- [ ] `docs/README.md` 增加这份计划文档入口
- [ ] `docs/README.md` 在离线评测入口处补专项评测下一阶段说明
- [ ] `STATUS.md` 记录这份计划已落地，作为下一阶段执行输入

### Task 13: 最终 scripted proof 矩阵

**Files:**
- no code change

- [ ] 跑全量 eval 单测
- [ ] 跑 `main_chain_core` scripted compare
- [ ] 跑 `memory_long_horizon` scripted compare
- [ ] 跑 `subagent_task_progress` scripted compare
- [ ] 确认 HTML 报告能同时展示主链和专项组件分数

### Task 14: live proof 约束与仓库对齐检查

**Files:**
- Modify: `scripts/run_eval.py`
- Modify: `tests/evals/test_run_eval_script.py`
- Modify: `tests/evals/test_suite_manifests.py`

- [ ] `memory_long_horizon` live proof：只依赖 live LLM profile
- [ ] `subagent_task_progress` live proof：依赖 live LLM profile + subagent surface
- [ ] `scripts/run_eval.py` 按 `suite.required_dependencies` 统一解析 `provider` / `mcp` / `subagent`
- [ ] `tests/evals/test_run_eval_script.py` 覆盖 `--list-suites` 新 suite 可见、`memory_long_horizon` provider blocked、`subagent_task_progress` subagent blocked
- [ ] `tests/evals/test_suite_manifests.py` 覆盖五个 suite 的加载与新 suite case 数量：`memory_long_horizon = 7`，`subagent_task_progress = 6`
- [ ] live proof 命令进入计划文档
- [ ] 路径存在性检查通过
- [ ] 计划与仓库现状无冲突

### Slice 5 Proof

Run:

```bash
cd /Users/litiezhu/workspace/github/marten-runtime && \
PYTHONPATH=src .venv/bin/python -m unittest -v tests.evals.test_models tests.evals.test_loader tests.evals.test_store tests.evals.test_compare tests.evals.test_report tests.evals.test_executor tests.evals.test_run_eval_script tests.evals.test_suite_manifests tests.evals.test_grader_registry tests.evals.test_memory_family_grader tests.evals.test_subagent_family_grader && \
PYTHONPATH=src .venv/bin/python scripts/run_eval.py --suite main_chain_core --mode scripted --profile openai_gpt_5_4 --baseline latest_passed && \
PYTHONPATH=src .venv/bin/python scripts/run_eval.py --suite memory_long_horizon --mode scripted --profile openai_gpt_5_4 --baseline latest_passed && \
PYTHONPATH=src .venv/bin/python scripts/run_eval.py --suite subagent_task_progress --mode scripted --profile openai_gpt_5_4 --baseline latest_passed && \
PYTHONPATH=src .venv/bin/python -m compileall -q src tests && \
git diff --check
```

Expected:

- 三套 suite 都能 scripted compare
- 现有主链评测无回归
- 专项 suite 产物路径仍然落在 `reports/evals/<eval_run_id>/`
- HTML 报告首页能看到 suite 级 component 汇总与 delta
- `memory_long_gap_with_interference_recall_cn` 与 `subagent_multi_child_progress_cn` 都进入 compare 报告
- case 详情继续能看到组件级分数与 delta

## 12. live proof 命令锁定

### 12.1 memory live

```bash
cd /Users/litiezhu/workspace/github/marten-runtime && \
set -a && source .env && set +a && \
PYTHONPATH=src .venv/bin/python scripts/run_eval.py \
  --suite memory_long_horizon \
  --mode live \
  --profile openai_gpt_5_4 \
  --baseline latest_passed
```

### 12.2 subagent live

```bash
cd /Users/litiezhu/workspace/github/marten-runtime && \
set -a && source .env && set +a && \
PYTHONPATH=src .venv/bin/python scripts/run_eval.py \
  --suite subagent_task_progress \
  --mode live \
  --profile openai_gpt_5_4 \
  --baseline latest_passed
```

live 结果约束：

- 依赖缺失时返回明确 blocked 证据
- 依赖存在时写出 `summary.md`、`summary.json`、`summary.html`
- `summary.html` 能直观看到 case component breakdown

## 13. No-Drift 检查清单

编码 agent 每完成一个 Slice 都要回看这份清单：

- [ ] 没有新开第二套 eval runner
- [ ] 没有把专项评分写进 runtime 热路径
- [ ] 没有把 `case.family` 继续挪作评分器路由
- [ ] 没有把 component 分数散落到多个 JSON 字段
- [ ] 没有为 memory / subagent 新开独立报告体系
- [ ] 现有 `main_chain_core` compare / report 继续工作
- [ ] scripted proof 对两个新 suite 都可重复运行
- [ ] live proof 的依赖边界清晰且克制

## 14. 完成定义

这份计划对应的实现完成，必须同时满足：

1. `memory_long_horizon` 与 `subagent_task_progress` 两个 suite 都能被 `--list-suites` 列出
2. 两个 suite 都能 scripted 跑通并生成 compare 报告
3. HTML 报告首页能展示 suite 级 component 汇总与 delta，case 详情继续展示 component 级分数与 delta
4. `main_chain_core` 现有评测无回归
5. `docs/README.md` 与 `STATUS.md` 已同步
6. 实现仍然保持统一框架、分族评分、薄扩展的结构

这轮最重要的结果是：后续做 memory 和记忆收益优化、做子代理任务推进优化时，仓库已经有一套能证明“这次迭代到底有没有变好”的专项评测基线。
