# 主链评测基础能力执行计划

> **面向编码 agent：** 必须使用 `executing-plans` 落地这份计划。只有用户明确授权并行委派时，才使用 `subagent-driven-development`。执行步骤继续使用复选框 `- [ ]` 追踪。
>
> 这份计划的仓库执行约束：
> - 改文件前先在命名分支上工作
> - 整轮执行使用 `long-run-execution`
> - 保持 runtime 热路径稳定，同时让 eval 留在离线运维面
> - 只有用户明确要求时才 commit 或 push

**目标：** 完整落地 `eval-foundation-design-20260430`，让 `marten-runtime` 可以运行黄金任务回放套件，把评分历史写入 SQLite，与基线对比，生成 Markdown 与 JSON 报告，并让每条 case 都能追溯到 `run_id` / `trace_id` / Langfuse 证据。

**架构：** 实现继续放在产品热路径之外。新的 eval 层通过生产已在使用的 `/sessions`、`/messages` 和 diagnostics endpoints 驱动现有 in-process HTTP app，再把分数和产物写入本地 SQLite store 与文件报告。整轮落地分四个 Slice：骨架与持久化、执行与评分、baseline 对比、外部 suite 扩展。

**技术栈：** Python 3.11、`tomllib`、`sqlite3`、`argparse`、`pathlib`、`hashlib`、FastAPI `TestClient`、现有 runtime diagnostics、现有 Langfuse observer、`unittest`。

---

## 0. 计划作用与边界

这份执行计划直接约束编码 agent 的行为。它服务的目标很单一：把 `/Users/litiezhu/workspace/github/marten-runtime/docs/2026-04-30-main-chain-eval-foundation-design.md` 变成一套可运行、可验证、可追溯的仓库能力。

这份计划覆盖全部 Slice：

- Slice 1：骨架、模型、加载、存储、报告基础层
- Slice 2：执行器、评分器、CLI、`main_chain_core` 套件
- Slice 3：baseline、对比、回归摘要
- Slice 4：`main_chain_mcp`、`main_chain_subagent`、文档与最终验证

这份计划不扩展以下范围：

- 在线评测服务
- UI 面板
- 评测结果写回 runtime 热路径
- 通用实验平台
- 长期记忆效果研究

## 1. 编码 agent 全局约束

### 1.1 分支与工作区

- [ ] 从命名分支开始执行，禁止在 `main` 上直接改文件
- [ ] 忽略与本计划无关的脏工作区内容
- [ ] 每个 Slice 结束都跑该 Slice 的证明命令

### 1.2 架构约束

- [ ] eval 代码只进入离线运维面，入口保持在 `scripts/run_eval.py`
- [ ] runtime 主链继续保持：`channel -> binding -> runtime loop -> builtin / MCP / skill -> delivery / diagnostics`
- [ ] 不把 eval 引入 `src/marten_runtime/runtime/loop.py` 的常规执行路径
- [ ] 不新增 host-side intent routing、tool router、workflow orchestration
- [ ] 不把 `scripts/run_acceptance.py` 改造成 eval runner

### 1.3 技术约束

- [ ] 只使用现有依赖和 Python 标准库
- [ ] `case` / `suite` 格式固定使用 TOML
- [ ] 历史存储固定使用 `sqlite3`
- [ ] 产物固定输出到 `reports/evals/`
- [ ] 数据库固定输出到 `data/evals.sqlite3`
- [ ] `scripted` 模式只服务 harness 测试和本地无外部依赖验证
- [ ] `live` 模式服务真实质量评测

### 1.4 测试约束

- [ ] 新测试集中放到 `tests/evals/`
- [ ] 继续使用 `unittest`
- [ ] `tests/test_acceptance.py` 保持 smoke 角色
- [ ] 外部依赖型 suite 通过 manifest 声明依赖和跳过条件
- [ ] 仓库级验证不依赖真实云凭据才能通过

### 1.5 文档与状态约束

- [ ] 实现中涉及长期边界时同步 `docs/README.md`
- [ ] 命令用法进入 `README.md` 的测试/运维邻近区域
- [ ] 当前分支进展进入 `STATUS.md`

## 2. 设计对齐矩阵

| 设计文档主题 | 执行计划落点 |
| --- | --- |
| 评测位于离线运维面 | Chunk 2 / Task 6-8 |
| 与 test / trace 分层 | Chunk 1 / Task 1，Chunk 2 / Task 6-8 |
| 主链证据关联 | Chunk 2 / Task 7，Chunk 3 / Task 10-11 |
| TOML case / suite | Chunk 1 / Task 2-3 |
| SQLite 历史存储 | Chunk 1 / Task 4 |
| JSON / Markdown 报告 | Chunk 1 / Task 5，Chunk 3 / Task 11 |
| baseline compare | Chunk 3 / Task 10-12 |
| `main_chain_core` 首先进入基线 | Chunk 2 / Task 8-9 |
| `main_chain_mcp` / `main_chain_subagent` 后续扩展 | Chunk 4 / Task 13-14 |
| live 与 scripted 分层 | Chunk 2 / Task 7-9，Chunk 4 / Task 13-14 |
| 外部依赖留在明确边界内 | Chunk 4 / Task 13-14 |

## 3. 仓库贴合清单

这份计划直接复用当前仓库已有入口：

- `src/marten_runtime/interfaces/http/app.py`
- `src/marten_runtime/interfaces/http/bootstrap.py`
- `tests/http_app_support.py`
- `tests/test_http_runtime_diagnostics.py`
- `tests/contracts/test_runtime_contracts.py`
- `tests/runtime_loop/test_context_status_and_usage.py`
- `tests/test_langfuse_observability.py`
- `src/marten_runtime/runtime/history.py`
- `scripts/run_acceptance.py`

编码 agent 在实现时要主动利用这些现状：

- `/messages` 响应已经带 `trace_id`，最终事件已经带 `run_id`
- `/diagnostics/run/{run_id}` 和 `/diagnostics/trace/{trace_id}` 已可直接复用
- `.gitignore` 已忽略 `data/` 和 `*.sqlite3`
- `.venv/bin/python` 当前存在，可作为本地验证解释器

## 4. 文件结构锁定

### 4.1 新建文件

- `evals/suites/main_chain_core.toml`
- `evals/suites/main_chain_mcp.toml`
- `evals/suites/main_chain_subagent.toml`
- `evals/cases/main_chain_core/direct_answer_cn.toml`
- `evals/cases/main_chain_core/time_single_tool_cn.toml`
- `evals/cases/main_chain_core/runtime_context_status_cn.toml`
- `evals/cases/main_chain_core/session_catalog_cn.toml`
- `evals/cases/main_chain_core/memory_write_then_read_cn.toml`
- `evals/cases/main_chain_core/memory_replace_then_read_cn.toml`
- `evals/cases/main_chain_core/multi_turn_time_then_context_cn.toml`
- `evals/cases/main_chain_core/multi_turn_memory_reuse_cn.toml`
- `evals/cases/main_chain_core/session_new_continuity_cn.toml`
- `evals/cases/main_chain_core/session_resume_continuity_cn.toml`
- `evals/cases/main_chain_core/context_compaction_continuity_cn.toml`
- `evals/cases/main_chain_core/proactive_compaction_cn.toml`
- `evals/cases/main_chain_core/runtime_usage_window_cn.toml`
- `evals/cases/main_chain_core/tool_followup_to_final_cn.toml`
- `evals/cases/main_chain_core/direct_answer_followup_cn.toml`
- `evals/cases/main_chain_mcp/github_get_me_cn.toml`
- `evals/cases/main_chain_mcp/github_recent_commit_cn.toml`
- `evals/cases/main_chain_mcp/github_multi_turn_followup_cn.toml`
- `evals/cases/main_chain_mcp/github_trace_correlation_cn.toml`
- `evals/cases/main_chain_subagent/subagent_github_lookup_cn.toml`
- `evals/cases/main_chain_subagent/subagent_completion_notice_cn.toml`
- `evals/cases/main_chain_subagent/subagent_parent_summary_cn.toml`
- `evals/fixtures/session_histories/context_pressure_long_thread.md`
- `evals/fixtures/session_histories/session_switch_source_thread.md`
- `evals/fixtures/memory/user_preference_basic.md`
- `src/marten_runtime/evals/models.py`
- `src/marten_runtime/evals/loader.py`
- `src/marten_runtime/evals/store.py`
- `src/marten_runtime/evals/report.py`
- `src/marten_runtime/evals/graders.py`
- `src/marten_runtime/evals/executor.py`
- `src/marten_runtime/evals/compare.py`
- `scripts/run_eval.py`
- `tests/evals/__init__.py`
- `tests/evals/test_models.py`
- `tests/evals/test_loader.py`
- `tests/evals/test_store.py`
- `tests/evals/test_report.py`
- `tests/evals/test_graders.py`
- `tests/evals/test_executor.py`
- `tests/evals/test_compare.py`
- `tests/evals/test_run_eval_script.py`
- `tests/evals/test_suite_manifests.py`

### 4.2 修改文件

- `.gitignore`
- `README.md`
- `docs/README.md`
- `STATUS.md`
- `tests/http_app_support.py`

### 4.3 明确不改的文件

除非实现中发现真实阻塞，否则当前计划不改：

- `src/marten_runtime/runtime/loop.py`
- `src/marten_runtime/runtime/capabilities.py`
- `src/marten_runtime/tools/builtins/*.py`
- `src/marten_runtime/interfaces/http/app.py`
- `tests/test_acceptance.py`

## 5. 评测 CLI 契约先锁定

在编码前先锁定 CLI 形态，避免实现后反复重构：

```bash
PYTHONPATH=src .venv/bin/python scripts/run_eval.py \
  --suite main_chain_core \
  --mode live \
  --profile openai_gpt_5_4 \
  --baseline latest_passed
```

第一版参数集合固定为：

- `--suite <suite_id>`
- `--mode live|scripted`
- `--profile <profile_name>`
- `--baseline <baseline_name>`
- `--baseline-run <eval_run_id>`
- `--write-baseline <baseline_name>`
- `--db-path <path>`
- `--report-root <path>`
- `--list-suites`

退出码固定为：

- `0`：suite pass
- `1`：suite fail
- `2`：usage / config / dependency block

## 6. 指纹与命名规则先锁定

### 6.1 `eval_run_id`

格式固定：

- `eval_<suite_id>_<YYYYMMDDHHMMSS>_<shortsha>`

### 6.2 `config_fingerprint`

按以下输入计算 `sha256`：

- `config/` 全部文件
- `apps/` 全部文件
- `skills/` 全部文件
- `mcps.json`，若不存在则使用 `mcps.example.json`

### 6.3 `suite_fingerprint`

按以下输入计算 `sha256`：

- suite manifest 文件
- suite 引用的全部 case 文件
- case 引用的全部 fixture 文件

### 6.4 产物路径

- SQLite：`data/evals.sqlite3`
- 报告目录：`reports/evals/<eval_run_id>/`
- case 级 JSON：`reports/evals/<eval_run_id>/cases/<case_id>.json`

## 7. Chunk 1：基础骨架与持久层

### Task 1: 本地产物策略与目录骨架

**Files:**
- Modify: `.gitignore`
- Create: `evals/suites/main_chain_core.toml`
- Create: `evals/cases/main_chain_core/direct_answer_cn.toml`
- Create: `tests/evals/__init__.py`

- [ ] **Step 1: 更新本地产物忽略规则**

在 `.gitignore` 增加：

- `reports/evals/`

保持 `data/` 和 `*.sqlite3` 继续作为本地运行产物。

- [ ] **Step 2: 创建 eval 目录骨架**

创建目录：

- `evals/suites/`
- `evals/cases/main_chain_core/`
- `evals/cases/main_chain_mcp/`
- `evals/cases/main_chain_subagent/`
- `evals/fixtures/session_histories/`
- `evals/fixtures/memory/`
- `tests/evals/`

- [ ] **Step 3: 写入最小 suite 和最小 case 占位文件**

目标：让 loader 测试有真实仓库输入，文件内容先保持最小合法结构。

- [ ] **Step 4: 证明目录和忽略规则已生效**

Run:

```bash
cd /Users/litiezhu/workspace/github/marten-runtime && \
rg -n 'reports/evals/' .gitignore && \
find evals -maxdepth 3 -type f | sort
```

Expected:

- `.gitignore` 命中 `reports/evals/`
- `evals/` 下已出现 suite/case 占位文件

### Task 2: 定义 eval 模型层

**Files:**
- Create: `src/marten_runtime/evals/models.py`
- Create: `tests/evals/test_models.py`

- [ ] **Step 1: 先写失败测试，锁定模型字段和校验**

测试至少覆盖：

- `EvalCaseSpec`
- `EvalSuiteSpec`
- `EvalTurnSpec`
- `EvalWeights`
- `EvalCaseResult`
- `EvalRunSummary`

校验至少覆盖：

- `weights` 总和必须等于 `100`
- `case_id`、`suite_id` 必填
- `required_calls` 的 `min_calls <= max_calls`
- `mode` 只能是 `live` / `scripted`

- [ ] **Step 2: 实现最小模型代码**

模型职责：

- 配置模型
- 执行结果模型
- 对比结果模型
- 报告摘要模型

优先用 `pydantic.BaseModel`，和仓库既有风格保持一致。

- [ ] **Step 3: 跑模型测试**

Run:

```bash
cd /Users/litiezhu/workspace/github/marten-runtime && \
PYTHONPATH=src .venv/bin/python -m unittest -v tests.evals.test_models
```

Expected:

- PASS

### Task 3: 实现 suite / case loader

**Files:**
- Create: `src/marten_runtime/evals/loader.py`
- Create: `tests/evals/test_loader.py`
- Modify: `evals/suites/main_chain_core.toml`
- Modify: `evals/cases/main_chain_core/direct_answer_cn.toml`

- [ ] **Step 1: 先写 loader 失败测试**

覆盖点：

- 读取单个 case TOML
- 读取 suite TOML
- 按 suite 装配 ordered cases
- 缺失 case 文件时抛清晰异常
- 缺失 fixture 文件时抛清晰异常
- 生成 `suite_fingerprint`

- [ ] **Step 2: 实现 loader**

固定实现：

- 使用 `tomllib`
- 使用显式路径解析
- 保留 case 顺序
- 保留 suite 元信息和依赖声明
- 输出已经校验过的 `EvalSuiteSpec`

- [ ] **Step 3: 让仓库内最小 suite 成为真实可加载输入**

`suite` 文件至少包含：

- `suite_id`
- `description`
- `mode_support`
- `case_files`
- `dependency_policy`

- [ ] **Step 4: 跑 loader 测试**

Run:

```bash
cd /Users/litiezhu/workspace/github/marten-runtime && \
PYTHONPATH=src .venv/bin/python -m unittest -v tests.evals.test_loader
```

Expected:

- PASS

### Task 4: 实现 SQLite store

**Files:**
- Create: `src/marten_runtime/evals/store.py`
- Create: `tests/evals/test_store.py`

- [ ] **Step 1: 先写 store 失败测试**

覆盖点：

- 首次打开自动建表
- 写入 `eval_runs`
- 写入 `eval_case_results`
- 写入和读取 `eval_baselines`
- 读取最新 passed baseline
- 同 suite / mode / profile 条件过滤

- [ ] **Step 2: 实现 schema 与 store API**

固定 API：

- `init_schema()`
- `record_run_start(...)`
- `record_case_result(...)`
- `record_run_finish(...)`
- `get_run(...)`
- `list_case_results(...)`
- `resolve_baseline(...)`
- `write_baseline(...)`

- [ ] **Step 3: 跑 store 测试**

Run:

```bash
cd /Users/litiezhu/workspace/github/marten-runtime && \
PYTHONPATH=src .venv/bin/python -m unittest -v tests.evals.test_store
```

Expected:

- PASS

### Task 5: 实现报告基础层

**Files:**
- Create: `src/marten_runtime/evals/report.py`
- Create: `tests/evals/test_report.py`

- [ ] **Step 1: 先写 report 失败测试**

覆盖点：

- 生成 `summary.json`
- 生成 `summary.md`
- 生成 `cases/<case_id>.json`
- Markdown 包含 `eval_run_id`、总分、`run_id`、`trace_id`

- [ ] **Step 2: 实现 report writer**

固定职责：

- 保证目录存在
- 写 JSON
- 写 Markdown
- 返回 artifact 路径摘要

- [ ] **Step 3: 运行 Chunk 1 验证**

Run:

```bash
cd /Users/litiezhu/workspace/github/marten-runtime && \
PYTHONPATH=src .venv/bin/python -m unittest -v \
  tests.evals.test_models \
  tests.evals.test_loader \
  tests.evals.test_store \
  tests.evals.test_report && \
PYTHONPATH=src .venv/bin/python -m compileall -q src tests && \
git diff --check
```

Expected:

- 全部 PASS
- `git diff --check` exit `0`

## 8. Chunk 2：执行器、评分器、CLI、核心套件

### Task 6: 实现确定性 grader

**Files:**
- Create: `src/marten_runtime/evals/graders.py`
- Create: `tests/evals/test_graders.py`

- [ ] **Step 1: 先写 grader 失败测试**

覆盖点：

- `contains_all`
- `contains_any`
- `forbid_all`
- `required_calls`
- `forbidden_calls`
- `max_llm_requests`
- `max_tool_calls`
- `expect_compaction`
- `expect_provider_ref`

- [ ] **Step 2: 实现四类分数计算**

固定输出：

- `outcome_score`
- `tool_path_score`
- `efficiency_score`
- `context_score`
- `score_breakdown_json`
- `status`

- [ ] **Step 3: 固定 gate 逻辑**

第一版 gate：

- required case 需要通过最低 gate
- `outcome_score > 0`
- 必需工具路径命中
- 异常执行直接 `failed`

- [ ] **Step 4: 跑 grader 测试**

Run:

```bash
cd /Users/litiezhu/workspace/github/marten-runtime && \
PYTHONPATH=src .venv/bin/python -m unittest -v tests.evals.test_graders
```

Expected:

- PASS

### Task 7: 实现执行器

**Files:**
- Create: `src/marten_runtime/evals/executor.py`
- Modify: `tests/http_app_support.py`
- Create: `tests/evals/test_executor.py`

- [ ] **Step 1: 先写 executor 失败测试**

覆盖点：

- 创建临时隔离 workspace
- 拷贝 `config/`、`apps/`、`skills/`
- 通过 HTTP app surface 执行 `/sessions` + `/messages`
- 从响应中拿到 `trace_id`
- 从最终 event 中拿到 `run_id`
- 读取 `/diagnostics/run/{run_id}`
- 读取 `/diagnostics/trace/{trace_id}`
- 收集最终文本、tool call 数、llm 请求数

- [ ] **Step 2: 在 `tests/http_app_support.py` 增加最小复用辅助**

建议增加：

- 拷贝 repo scaffold 的独立函数
- 基于指定 `repo_root` 创建 app 的函数
- 注入 `ScriptedLLMClient` / `DemoLLMClient` 的轻量入口

目标：让 eval executor 测试复用现有测试仓构造方式。

- [ ] **Step 3: 实现 `scripted` 模式执行路径**

`scripted` 模式职责：

- 用测试 app + fake / scripted LLM 跑完整主链
- 支持多轮 case
- 支持 fixture 注入
- 支持 diagnostics 拉取

- [ ] **Step 4: 实现 `live` 模式执行路径**

`live` 模式职责：

- 使用当前 repo 配置和当前环境 key
- 使用真实 profile
- 保留和 `scripted` 模式同样的 artifact 结构

- [ ] **Step 5: 固定依赖阻塞语义**

当 suite 依赖缺失时：

- `main_chain_core`：缺 provider key -> exit `2`
- `main_chain_mcp`：缺 MCP / PAT -> `blocked` 或 `skipped`，不污染 core suite
- `main_chain_subagent`：缺外部工具条件 -> `blocked` 或 `skipped`

- [ ] **Step 6: 跑 executor 测试**

Run:

```bash
cd /Users/litiezhu/workspace/github/marten-runtime && \
PYTHONPATH=src .venv/bin/python -m unittest -v tests.evals.test_executor
```

Expected:

- PASS

### Task 8: 实现 CLI 脚本

**Files:**
- Create: `scripts/run_eval.py`
- Create: `tests/evals/test_run_eval_script.py`

- [ ] **Step 1: 先写 CLI 失败测试**

覆盖点：

- `--list-suites`
- 指定 suite + scripted mode 可运行
- 缺必填参数给出清晰 usage
- suite fail 返回 exit `1`
- dependency block 返回 exit `2`

- [ ] **Step 2: 实现 `argparse` CLI**

脚本职责：

- 解析参数
- 加载 suite
- 创建 store
- 运行 executor
- 调 grader
- 写 store 与报告
- 输出命令行摘要

- [ ] **Step 3: 跑 CLI 测试**

Run:

```bash
cd /Users/litiezhu/workspace/github/marten-runtime && \
PYTHONPATH=src .venv/bin/python -m unittest -v tests.evals.test_run_eval_script
```

Expected:

- PASS

### Task 9: 落地 `main_chain_core` 套件

**Files:**
- Modify: `evals/suites/main_chain_core.toml`
- Create: `evals/cases/main_chain_core/*.toml`
- Create: `evals/fixtures/session_histories/context_pressure_long_thread.md`
- Create: `evals/fixtures/session_histories/session_switch_source_thread.md`
- Create: `evals/fixtures/memory/user_preference_basic.md`
- Create: `tests/evals/test_suite_manifests.py`

- [ ] **Step 1: 先把 5 个锚点 case 写全并跑通 scripted**

锚点 case：

- `direct_answer_cn`
- `time_single_tool_cn`
- `runtime_context_status_cn`
- `memory_write_then_read_cn`
- `multi_turn_time_then_context_cn`

- [ ] **Step 2: 扩到完整 core suite**

core suite 目标数：`15` 条 case。完整列表固定使用本计划第 4.1 节列出的 core case 文件名。

- [ ] **Step 3: 在 suite manifest 中锁定核心语义**

manifest 至少包含：

- `suite_id = "main_chain_core"`
- `default_mode = "live"`
- `scripted_supported = true`
- `required_dependencies = ["provider"]`
- `baseline_policy = "latest_passed_auto"`

- [ ] **Step 4: 为 suite manifest 写仓库级合法性测试**

测试覆盖：

- 三个 suite 文件都能被 loader 读入
- core suite case 数量达到 `15`
- 所有 case 权重总和为 `100`
- fixture 路径全部存在

- [ ] **Step 5: 跑 Chunk 2 验证**

Run:

```bash
cd /Users/litiezhu/workspace/github/marten-runtime && \
PYTHONPATH=src .venv/bin/python -m unittest -v \
  tests.evals.test_graders \
  tests.evals.test_executor \
  tests.evals.test_run_eval_script \
  tests.evals.test_suite_manifests && \
PYTHONPATH=src .venv/bin/python scripts/run_eval.py \
  --suite main_chain_core \
  --mode scripted \
  --profile openai_gpt_5_4 && \
PYTHONPATH=src .venv/bin/python -m compileall -q src tests && \
git diff --check
```

Expected:

- 单测 PASS
- `scripted` suite 运行成功
- 生成 `reports/evals/<eval_run_id>/summary.md`
- 生成 `data/evals.sqlite3`
- `git diff --check` exit `0`

## 9. Chunk 3：baseline、对比、回归摘要

### Task 10: 实现 baseline 与 compare 引擎

**Files:**
- Create: `src/marten_runtime/evals/compare.py`
- Modify: `src/marten_runtime/evals/store.py`
- Create: `tests/evals/test_compare.py`
- Modify: `tests/evals/test_store.py`

- [ ] **Step 1: 先写 compare 失败测试**

覆盖点：

- 同 case 对比分数 delta
- 新增 case / 缺失 case 标记
- top regression 排序
- baseline 解析顺序：显式 run > 命名 baseline > 自动 latest passed

- [ ] **Step 2: 实现 compare 结果模型和逻辑**

固定输出：

- total delta
- pass rate delta
- per-case delta
- regressions
- improvements

- [ ] **Step 3: 固定 baseline 写入策略**

策略锁定：

- 每次 `status = passed` 的 run 自动刷新 `latest_passed`
- `main` 这类命名基线只在 `--write-baseline <name>` 时更新

- [ ] **Step 4: 跑 compare 与 store 回归**

Run:

```bash
cd /Users/litiezhu/workspace/github/marten-runtime && \
PYTHONPATH=src .venv/bin/python -m unittest -v \
  tests.evals.test_store \
  tests.evals.test_compare
```

Expected:

- PASS

### Task 11: 扩展报告摘要

**Files:**
- Modify: `src/marten_runtime/evals/report.py`
- Modify: `src/marten_runtime/evals/models.py`
- Modify: `tests/evals/test_report.py`

- [ ] **Step 1: 先写报告对比部分失败测试**

Markdown 新增内容至少包含：

- baseline 来源
- total delta
- pass rate delta
- regressions
- improvements

- [ ] **Step 2: 实现报告对比段落**

`summary.md` 结构锁定为：

1. run 元信息
2. suite 总览
3. baseline 对比
4. regressions
5. improvements
6. case evidence table

- [ ] **Step 3: 跑 report 回归**

Run:

```bash
cd /Users/litiezhu/workspace/github/marten-runtime && \
PYTHONPATH=src .venv/bin/python -m unittest -v tests.evals.test_report
```

Expected:

- PASS

### Task 12: 把 compare 接到 CLI 与 executor 结果流

**Files:**
- Modify: `scripts/run_eval.py`
- Modify: `src/marten_runtime/evals/executor.py`
- Modify: `tests/evals/test_run_eval_script.py`
- Modify: `tests/evals/test_executor.py`

- [ ] **Step 1: 先写带 baseline 的 CLI 集成失败测试**

覆盖点：

- 首次 run 无 baseline 时可成功
- 第二次 run 自动关联 `latest_passed`
- 明确 `--baseline-run` 时优先使用指定 run
- `summary.md` 带 delta 段落

- [ ] **Step 2: 实现 compare 接线**

接线要求：

- executor 负责返回完整执行结果
- CLI 负责选择 baseline 并调用 compare
- store 负责写 baseline 与查询 baseline
- report 负责渲染 compare 结果

- [ ] **Step 3: 运行 Chunk 3 验证**

Run:

```bash
cd /Users/litiezhu/workspace/github/marten-runtime && \
PYTHONPATH=src .venv/bin/python -m unittest -v \
  tests.evals.test_store \
  tests.evals.test_compare \
  tests.evals.test_report \
  tests.evals.test_run_eval_script \
  tests.evals.test_executor && \
PYTHONPATH=src .venv/bin/python scripts/run_eval.py \
  --suite main_chain_core \
  --mode scripted \
  --profile openai_gpt_5_4 && \
PYTHONPATH=src .venv/bin/python scripts/run_eval.py \
  --suite main_chain_core \
  --mode scripted \
  --profile openai_gpt_5_4 \
  --baseline latest_passed && \
git diff --check
```

Expected:

- 第二次 run 的 `summary.md` 已包含 baseline compare 段落
- SQLite 中已有 `eval_baselines` 数据
- `git diff --check` exit `0`

## 10. Chunk 4：MCP / Subagent 套件扩展与最终文档

### Task 13: 落地 `main_chain_mcp` suite

**Files:**
- Create: `evals/suites/main_chain_mcp.toml`
- Create: `evals/cases/main_chain_mcp/*.toml`
- Modify: `tests/evals/test_suite_manifests.py`
- Modify: `tests/evals/test_run_eval_script.py`

- [ ] **Step 1: 在 manifest 中显式声明依赖**

`main_chain_mcp` 至少声明：

- provider
- `mcps.json` or `mcps.example.json`
- GitHub MCP discovery
- GitHub token

- [ ] **Step 2: 先用 manifest 测试锁定外部依赖行为**

缺依赖时行为固定：

- CLI 返回 exit `2`
- 报告状态为 `blocked`
- core suite 状态不受影响

- [ ] **Step 3: 补齐 MCP case 文件**

固定包括：

- `github_get_me_cn`
- `github_recent_commit_cn`
- `github_multi_turn_followup_cn`
- `github_trace_correlation_cn`

- [ ] **Step 4: 跑 MCP suite 合法性测试**

Run:

```bash
cd /Users/litiezhu/workspace/github/marten-runtime && \
PYTHONPATH=src .venv/bin/python -m unittest -v \
  tests.evals.test_suite_manifests \
  tests.evals.test_run_eval_script
```

Expected:

- PASS

### Task 14: 落地 `main_chain_subagent` suite

**Files:**
- Create: `evals/suites/main_chain_subagent.toml`
- Create: `evals/cases/main_chain_subagent/*.toml`
- Modify: `tests/evals/test_suite_manifests.py`
- Modify: `tests/evals/test_run_eval_script.py`

- [ ] **Step 1: 在 manifest 中显式声明依赖**

`main_chain_subagent` 至少声明：

- provider
- subagent surface enabled
- required tool profile available
- live MCP dependency when case 依赖 GitHub

- [ ] **Step 2: 锁定 blocked / skipped 语义**

缺依赖时行为固定：

- suite 状态 `blocked`
- CLI exit `2`
- case 结果保留 blocked reason

- [ ] **Step 3: 补齐 subagent case 文件**

固定包括：

- `subagent_github_lookup_cn`
- `subagent_completion_notice_cn`
- `subagent_parent_summary_cn`

- [ ] **Step 4: 跑 subagent suite 合法性测试**

Run:

```bash
cd /Users/litiezhu/workspace/github/marten-runtime && \
PYTHONPATH=src .venv/bin/python -m unittest -v \
  tests.evals.test_suite_manifests \
  tests.evals.test_run_eval_script
```

Expected:

- PASS

### Task 15: 更新仓库文档入口

**Files:**
- Modify: `README.md`
- Modify: `docs/README.md`
- Modify: `STATUS.md`

- [ ] **Step 1: 在 `README.md` 增加最小 eval 用法**

内容只放：

- `scripts/run_eval.py` 命令示例
- `data/evals.sqlite3`
- `reports/evals/`
- `main_chain_core` / `main_chain_mcp` / `main_chain_subagent` 的用途说明

- [ ] **Step 2: 在 `docs/README.md` 增加 eval 能力入口说明**

至少提到：

- design doc
- execution plan
- 命令入口

- [ ] **Step 3: 在 `STATUS.md` 记录 eval 基础能力进入实现状态**

写清楚：

- 当前分支
- 已完成 slices
- 最新验证命令

### Task 16: 最终证明矩阵

**Files:**
- Modify: `STATUS.md`

- [ ] **Step 1: 运行完整 eval 单测束**

Run:

```bash
cd /Users/litiezhu/workspace/github/marten-runtime && \
PYTHONPATH=src .venv/bin/python -m unittest -v \
  tests.evals.test_models \
  tests.evals.test_loader \
  tests.evals.test_store \
  tests.evals.test_report \
  tests.evals.test_graders \
  tests.evals.test_executor \
  tests.evals.test_compare \
  tests.evals.test_run_eval_script \
  tests.evals.test_suite_manifests
```

Expected:

- PASS

- [ ] **Step 2: 运行 eval 基础设施集成链路**

Run:

```bash
cd /Users/litiezhu/workspace/github/marten-runtime && \
PYTHONPATH=src .venv/bin/python scripts/run_eval.py \
  --suite main_chain_core \
  --mode scripted \
  --profile openai_gpt_5_4 && \
PYTHONPATH=src .venv/bin/python scripts/run_eval.py \
  --suite main_chain_core \
  --mode scripted \
  --profile openai_gpt_5_4 \
  --baseline latest_passed
```

Expected:

- 两次运行都成功
- 第二次运行能输出 compare 结果
- 产物完整生成

- [ ] **Step 3: 运行仓库保护性回归**

Run:

```bash
cd /Users/litiezhu/workspace/github/marten-runtime && \
PYTHONPATH=src .venv/bin/python -m unittest -v \
  tests.test_http_runtime_diagnostics \
  tests.contracts.test_runtime_contracts \
  tests.runtime_loop.test_context_status_and_usage \
  tests.test_acceptance && \
PYTHONPATH=src .venv/bin/python -m compileall -q src tests && \
git diff --check
```

Expected:

- PASS
- `git diff --check` exit `0`

## 11. 实现顺序硬规则

编码 agent 必须按这个顺序推进：

1. Chunk 1
2. Chunk 2
3. Chunk 3
4. Chunk 4

顺序约束原因：

- compare 依赖 store 和 result models
- CLI 依赖 executor、grader、report
- MCP / subagent suites 依赖基础 harness 完整可用

## 12. 每个 Chunk 的 done criteria

### Chunk 1 done criteria

- model / loader / store / report 单测全绿
- `evals/` 目录结构和最小 suite 已存在
- `.gitignore` 已覆盖 `reports/evals/`

### Chunk 2 done criteria

- `scripted` 模式能跑 `main_chain_core`
- 生成 SQLite 记录和 Markdown / JSON 产物
- core suite case 数达到 `15`

### Chunk 3 done criteria

- `latest_passed` 自动更新
- 第二次 scripted run 能输出 compare 摘要
- Markdown 报告出现 regressions / improvements 区块

### Chunk 4 done criteria

- `main_chain_mcp` 与 `main_chain_subagent` manifests 可加载
- 外部依赖缺失时有稳定 blocked 语义
- `README.md` 和 `docs/README.md` 有最小使用入口
- 仓库保护性回归通过

## 13. 设计偏移检查规则

编码 agent 在实现时必须主动对照下面几条做偏移检查：

- [ ] eval 入口仍然在离线 CLI，而不是 runtime 热路径
- [ ] `scripts/run_acceptance.py` 继续保留 smoke 角色
- [ ] case / suite 继续使用 TOML
- [ ] 历史存储继续使用 SQLite
- [ ] 报告继续输出 JSON + Markdown
- [ ] `main_chain_core` 继续是唯一默认基线套件
- [ ] `main_chain_mcp` / `main_chain_subagent` 继续受依赖门控
- [ ] 每个 case 继续挂 `run_id` / `trace_id` / `langfuse_url`

## 14. 仓库现状贴合检查规则

编码 agent 在每个 Chunk 结束时都要确认：

- [ ] 仍在命名分支上工作
- [ ] 仍复用 `create_app(...)` / HTTP app surface
- [ ] 仍复用已有 diagnostics endpoint
- [ ] 仍用 `unittest`
- [ ] 仍未引入新依赖
- [ ] 仍未改动 runtime 热路径核心文件

## 15. 这份计划完成后的状态定义

当全部 Chunk 落地后，`marten-runtime` 将新增一条完整的 eval 基础能力链：

- 黄金任务套件可以运行
- 历史结果可以持久化
- baseline 可以比较
- 回归可以被看见
- 每条分数都能追到主链证据
