# 主链评测基础能力设计

> 日期：2026-04-30  
> 状态：已实现，保留为背景设计  
> 范围：`marten-runtime` 主链黄金任务回放评测基础能力

> 说明：当前长期真相已经进入 `docs/ARCHITECTURE_EVOLUTION.md` 与 `docs/ARCHITECTURE_CHANGELOG.md`；实现过程计划已归档到 `docs/archive/plans/`。

## 1. 设计结论

`marten-runtime` 下一步最值得建设的评测基础能力是一条完整但很薄的主链评测链路：

- 固定黄金任务集
- 统一评测执行器
- SQLite 历史存储
- 基线对比
- Markdown / JSON 报告
- `run_id` / `trace_id` / Langfuse 证据关联

这条能力面向当前阶段的核心目标：**让后续迭代能被证明为“更好用”**。

## 2. 为什么现在建设

仓库当前已经具备两层基础：

- 测试层：`tests/test_acceptance.py`、contracts、runtime loop suites 已能证明链路和契约健康
- 观测层：`/diagnostics/run/{run_id}`、`/diagnostics/trace/{trace_id}`、可选 Langfuse tracing 已能提供完整运行证据

当前最缺的是第三层：

- 评测层：证明 prompt、capability 描述、tool surface、上下文治理、记忆使用、profile 选择这些迭代是否真的带来质量提升

项目已经进入“更好用优先”的阶段，评测基础能力应该进入当前基线。

## 3. 目标

这套能力需要稳定回答五个问题：

1. 当前版本在固定黄金任务上的总表现是多少
2. 相对上一条基线，哪些 case 提升了，哪些退化了
3. 退化发生在结果、工具路径、链路效率、上下文稳定性的哪一层
4. 每条分数背后对应的是哪一次真实运行证据
5. 后续每次 prompt 或配置改动后，能否快速重复同一批回放

## 4. 当前范围

第一版只进入以下范围：

1. **主链黄金任务回放**
   - direct answer
   - single tool
   - multi-turn tool follow-up
   - context pressure / compaction continuity

2. **本地优先的离线运维面**
   - 通过命令行触发
   - 通过 in-process HTTP app 执行
   - 通过 SQLite 和文件报告沉淀结果

3. **真实 runtime 证据关联**
   - 每条 case 记录 `run_id`
   - 每条 case 记录 `trace_id`
   - Langfuse 可用时记录 `langfuse_url`

4. **基础对比能力**
   - 与命名基线比较
   - 与最近一次同类 run 比较
   - 输出回归 case 列表和分项变化

## 5. 当前范围外

第一版先把主链评测能力做实，以下主题留在后续阶段：

- 个人长期记忆收益评测
- 用户偏好长期漂移评测
- 多周趋势看板
- 浏览器 UI 面板
- 在线评测服务化
- 评测结果写回 runtime 热路径
- 大规模并发评测集群
- 通用实验平台
- 全量 LLM rubric 打分体系

## 6. 架构边界

### 6.1 评测位置

评测能力位于**离线运维面**。

它通过已有 HTTP app 和 runtime diagnostics 驱动主链，位置在主产品链路之外。这样可以保持当前 runtime spine 的边界稳定：

`operator CLI -> eval executor -> HTTP app -> runtime loop -> builtin / MCP / skill -> diagnostics / report`

### 6.2 与测试的边界

测试和评测各自承担清晰职责：

- `tests/*`：证明功能、契约、回归安全
- `evals/*`：证明使用质量变化和迭代收益

`tests/test_acceptance.py` 继续保持 smoke 属性。评测体系承接“更好用”的分数比较。

### 6.3 与 tracing 的边界

Langfuse 和 run diagnostics 继续承担证据采集职责。

评测系统负责：

- 触发运行
- 抽取证据
- 计算分数
- 保存历史
- 生成对比报告

### 6.4 与 LLM-first 边界的关系

评测体系保持对 runtime 的外部观察方式。

它读取：

- 最终输出
- 工具调用链路
- 运行诊断字段
- 上下文治理结果

它不把新的 host-side intent routing 逻辑带回 runtime。项目的 LLM-first 边界继续保持在产品主链内部。

### 6.5 与生产数据的边界

评测运行使用**隔离的临时数据目录**。

每次评测都生成独立的临时 workspace：

- 代码来源：当前 checkout
- 配置来源：当前 repo 的 `config/`、`agents/`、`skills/`
- 数据来源：临时 `data/` 目录
- 会话来源：评测专用 session id

这样可以保证：

- 评测不会污染真实会话和真实 memory
- 评测结果可以重复回放
- 评测上下文具备清晰边界

## 7. 设计约束

1. **一条 case 只对应一次规范运行**  
   单次评测不做隐藏重跑。任何重跑都生成新的 `eval_run_id`。

2. **默认串行执行**  
   第一版 `concurrency = 1`，优先保证证据清晰和成本稳定。

3. **live 评测优先服务主链质量判断**  
   `scripted` 模式只用于评测 harness 自身测试。

4. **基础套件优先依赖 builtin/runtime 面**  
   第一条必跑套件尽量减少外部依赖，先把核心主链评测做稳定。

5. **每条结果必须能回链到运行证据**  
   case 结果必须带 `run_id`、`trace_id`、diagnostics 摘要、原始输出落盘路径。

6. **评测命令和日常测试命令分离**  
   `python -m unittest` 继续只做测试。评测通过独立命令运行。

7. **评测结果默认本地保存**  
   第一版以 SQLite + 文件报告为基线，优先保证单机可用性和历史可追溯性。

8. **配置漂移必须可见**  
   每次 run 记录 `git_sha`、branch、profile、provider、`config_fingerprint`。

## 8. 套件分层

第一版按三层组织：

### 8.1 `main_chain_core`

这是第一版必须落地的核心套件。

覆盖面：

- direct answer
- single builtin tool
- runtime status / context status
- memory read / write 的基础 continuity 行为
- 多轮 tool follow-up
- 长上下文后 compaction continuity

依赖：

- 一个 live provider key
- 当前 repo 配置

### 8.2 `main_chain_mcp`

覆盖真实 MCP 调用路径。

覆盖面：

- GitHub MCP 主链
- MCP multi-turn follow-up
- trace correlation

依赖：

- live provider key
- live MCP 配置
- 对应 PAT / 凭据

### 8.3 `main_chain_subagent`

覆盖主线程委派和 child completion 的主链体验。

覆盖面：

- `spawn_subagent`
- child tool path
- parent completion summary
- 通知链路

依赖：

- live provider key
- subagent surface enabled
- 对应工具依赖

第一期实现只把 `main_chain_core` 作为必须套件进入基线。

## 9. 目录布局

```text
marten-runtime/
├── evals/
│   ├── suites/
│   │   ├── main_chain_core.toml
│   │   ├── main_chain_mcp.toml
│   │   └── main_chain_subagent.toml
│   ├── cases/
│   │   ├── main_chain_core/
│   │   │   ├── direct_answer_cn.toml
│   │   │   ├── time_single_tool.toml
│   │   │   ├── runtime_context_status.toml
│   │   │   ├── multi_turn_tool_followup.toml
│   │   │   └── context_compaction_continuity.toml
│   └── fixtures/
│       ├── session_histories/
│       └── memory/
├── scripts/
│   └── run_eval.py
├── src/marten_runtime/evals/
│   ├── loader.py
│   ├── models.py
│   ├── executor.py
│   ├── graders.py
│   ├── store.py
│   ├── compare.py
│   └── report.py
├── data/
│   └── evals.sqlite3
└── reports/
    └── evals/
        └── <eval_run_id>/
            ├── summary.json
            ├── summary.md
            └── cases/
                └── <case_id>.json
```

- `evals/`：声明式任务集
- `src/marten_runtime/evals/`：评测执行与存储实现
- `data/evals.sqlite3`：本地历史库
- `reports/evals/`：人可读和机可读产物

## 10. case 文件模型

第一版使用 `TOML`，原因很直接：

- 当前仓库已经广泛使用 TOML
- Python 3.11 自带 `tomllib`
- 配置风格与项目现有习惯一致

### 10.1 case 基本字段

每个 case 至少包含：

```toml
case_id = "time_single_tool_cn"
suite_id = "main_chain_core"
family = "single_tool"
enabled = true
required = true
description = "询问当前北京时间，应该走 time 工具并在一轮内完成"
agent_id = "main"
profile_name = "openai_gpt_5_4"

tags = ["cn", "builtin", "time", "finalize"]

[[turns]]
role = "user"
content = "告诉我现在北京时间几点。"

[setup]
session_history_fixture = "none"
memory_fixture = "none"
automation_fixture = "none"

[expectations.final_text]
contains_all = ["北京时间"]
contains_any = [":", "点"]
forbid_all = ["我无法访问", "我不能获取"]

[[expectations.tool_path.required_calls]]
tool_name = "time"
min_calls = 1
max_calls = 1

[expectations.efficiency]
max_llm_requests = 2
max_tool_calls = 1

[weights]
outcome = 60
tool_path = 25
efficiency = 15
```

### 10.2 多轮 case

多轮 case 通过 `turns` 顺序执行，保持同一个 session：

```toml
[[turns]]
role = "user"
content = "先告诉我当前时间。"

[[turns]]
role = "user"
content = "再告诉我当前上下文窗口使用情况。"
```

### 10.3 长上下文 case

长上下文 case 通过 `session_history_fixture` 提供长历史材料，通过 diagnostics 校验 compaction 行为和 continuity 行为。

### 10.4 当前边界里的 fixture 能力

第一版 fixture 能力保持克制：

- session history seed
- memory seed
- automation seed
- MCP prerequisite declaration

第一版先不引入任意 Python 脚本式 fixture。

## 11. 执行流程

`scripts/run_eval.py` 负责整条评测执行流程。

### 11.1 执行入口

建议命令形态：

```bash
PYTHONPATH=src .venv/bin/python scripts/run_eval.py --suite main_chain_core --profile openai_gpt_5_4 --baseline latest_passed
```

### 11.2 执行步骤

1. 解析 suite manifest 和 case 文件
2. 解析当前 git branch / sha / dirty state
3. 计算 `suite_fingerprint` 和 `config_fingerprint`
4. 创建 `eval_run_id`
5. 创建临时 eval workspace
6. 拷贝当前 `config/`、`agents/`、`skills/` 到临时 workspace
7. 创建隔离 `data/` 目录
8. 通过 `create_app(...)` 或 `build_http_runtime(...)` 启动 in-process app
9. 按 case 顺序执行用户 turn
10. 读取每轮 `run_id`、`trace_id`
11. 拉取 `/diagnostics/run/{run_id}`、`/diagnostics/trace/{trace_id}`
12. 执行 grader 计算分数
13. 写入 SQLite
14. 生成 JSON 与 Markdown 报告
15. 计算与 baseline 的差异
16. 输出 suite 摘要

### 11.3 执行路径选择

第一版统一通过 **HTTP app surface** 执行，执行入口保持在外层 HTTP app。

这样可以覆盖更多真实主链行为：

- session plumbing
- diagnostics writing
- channel-facing surface contract
- runtime bootstrap wiring

## 12. 评分模型

### 12.1 四个核心维度

第一版统一围绕四个维度打分：

1. **结果分**  
   用户目标有没有完成

2. **工具路径分**  
   该走的工具有没有走，链路顺序是否符合预期

3. **链路效率分**  
   LLM 请求轮数、tool 调用次数、额外回合是否控制在预算内

4. **上下文稳定分**  
   长线程里 compaction、continuity、context status 是否符合预期

### 12.2 权重策略

每个 case 显式声明 `weights`，权重和必须等于 `100`。

原因：

- 不同 family 的重点不同
- direct answer 和 context compaction case 的关注点天然不同
- 显式权重能保持 case 解释力

### 12.3 第一版 grader 类型

第一版只实现确定性 grader：

- `final_text.contains_all`
- `final_text.contains_any`
- `final_text.forbid_all`
- `tool_path.required_calls`
- `tool_path.forbidden_calls`
- `efficiency.max_llm_requests`
- `efficiency.max_tool_calls`
- `context.expect_compaction`
- `context.expect_preserved_tail_user_turns`
- `diagnostics.expect_provider_ref`
- `diagnostics.expect_final_provider_ref`

### 12.4 hard gate

每个 case 额外具备 gate 判定，第一版规则如下：

- `required = true` 的 case 必须通过最低 gate
- `outcome` 分必须大于 `0`
- 必需工具路径必须命中
- case 执行异常会直接记为 `failed`

suite gate 建议如下：

- required case 全通过
- suite pass rate >= `0.90`
- relative baseline delta >= `-2.0`

第一版先把这个阈值写死在执行器中，后续再开放成 suite 配置。

## 13. 历史存储设计

SQLite 作为第一版的唯一持久层。

路径：

- `/Users/litiezhu/workspace/github/marten-runtime/data/evals.sqlite3`

### 13.1 `eval_runs`

建议字段：

| 字段 | 含义 |
| --- | --- |
| `eval_run_id` | 本次评测唯一 id |
| `suite_id` | 套件 id |
| `started_at` / `finished_at` | 开始/结束时间 |
| `git_branch` | 当前分支 |
| `git_sha` | 当前提交 |
| `git_dirty` | 工作区状态 |
| `eval_mode` | `live` / `scripted` |
| `agent_id` | 目标 agent |
| `profile_name` | 使用的 profile |
| `provider_ref` | provider 引用 |
| `model_name` | 模型名 |
| `config_fingerprint` | 配置指纹 |
| `suite_fingerprint` | 套件指纹 |
| `baseline_eval_run_id` | 对比基线 |
| `total_score` | 总分 |
| `pass_rate` | 通过率 |
| `status` | passed / warning / failed |
| `artifact_root` | 报告目录 |

### 13.2 `eval_case_results`

建议字段：

| 字段 | 含义 |
| --- | --- |
| `eval_run_id` | 所属 run |
| `case_id` | case id |
| `family` | case family |
| `status` | passed / warning / failed / skipped |
| `total_score` | 总分 |
| `outcome_score` | 结果分 |
| `tool_path_score` | 工具路径分 |
| `efficiency_score` | 效率分 |
| `context_score` | 上下文稳定分 |
| `llm_request_count` | LLM 请求次数 |
| `tool_calls_count` | tool 调用次数 |
| `duration_ms` | 耗时 |
| `run_id` | runtime run id |
| `trace_id` | runtime trace id |
| `langfuse_url` | Langfuse 链接 |
| `final_text` | 最终文本 |
| `diagnostics_json` | 关键诊断快照 |
| `score_breakdown_json` | 打分细节 |
| `artifact_path` | case 产物路径 |

### 13.3 `eval_baselines`

建议字段：

| 字段 | 含义 |
| --- | --- |
| `suite_id` | 套件 id |
| `baseline_name` | 基线名称，如 `latest_passed` / `main` |
| `eval_run_id` | 指向的 run |
| `created_at` | 建立时间 |

这张表用于命名基线，不让比较逻辑只依赖“最近一次”。

## 14. 报告与对比

第一版报告输出两层：

### 14.1 命令行摘要

每次 run 结束直接输出：

- `eval_run_id`
- suite 总分
- pass rate
- 相对 baseline 的 delta
- 提升 case 数量
- 退化 case 数量
- top regressions
- artifact 路径

### 14.2 Markdown 报告

路径：

- `reports/evals/<eval_run_id>/summary.md`

报告结构：

1. run 元信息
2. suite 总览
3. baseline 对比
4. 分项分对比
5. 退化 case 清单
6. 提升 case 清单
7. 每条 case 的 `run_id` / `trace_id` / `langfuse_url`

### 14.3 JSON 报告

路径：

- `reports/evals/<eval_run_id>/summary.json`
- `reports/evals/<eval_run_id>/cases/<case_id>.json`

这层服务后续脚本查询、归档、统计。

## 15. 基线选择策略

第一版支持三种基线来源：

1. **显式 run id**
   - `--baseline-run <eval_run_id>`

2. **命名基线**
   - `--baseline main`
   - `--baseline latest_passed`

3. **自动最近基线**
   - 同 `suite_id`
   - 同 `eval_mode`
   - 同 `agent_id`
   - 同 `profile_name`
   - 最近一次 `status = passed`

默认策略建议使用第三种。

## 16. 直观查看方式

第一版先把“直观查看”定义成三层：

1. **终端摘要**  
   看当前 run 是否变好

2. **Markdown 报告**  
   看哪些 case 提升或退化

3. **trace 深挖入口**  
   通过 `run_id`、`trace_id`、`langfuse_url` 进入根因分析

第一版先不把图形面板做进 runtime。当前最有价值的是让“分数变化 -> 运行证据”这条链路闭合。

## 17. 与现有仓库能力的连接点

这套设计直接复用仓库现有能力：

- `create_app(...)` / HTTP runtime bootstrap
- `/diagnostics/run/{run_id}`
- `/diagnostics/trace/{trace_id}`
- run history / trace correlation
- Langfuse external refs
- 现有 acceptance fixture 和 scripted test pattern

当前仓库里 `scripts/run_acceptance.py` 只有占位性质，它继续保留 smoke 角色；评测能力通过 `scripts/run_eval.py` 单独承载。

## 18. harness 自身验证

评测系统自身也需要验证，建议三层：

### 18.1 单元测试

- case loader
- grader
- SQLite store
- baseline compare
- report rendering

### 18.2 集成测试

通过 `ScriptedLLMClient` 和测试 app，验证：

- 单轮 case 可执行
- 多轮 case 可执行
- diagnostics 能被拉取
- score 能正确落库
- compare 能正确标出 regression

### 18.3 本地 live smoke

用一个很小的 `main_chain_core` 子集跑 live provider，确认：

- runtime boot 成功
- provider 调用成功
- run/trace diagnostics 可读
- artifacts 生成完整

## 19. 成本与稳定性控制

第一版增加三条硬约束：

1. 默认串行执行
2. 默认只跑指定 suite
3. 默认只跑一轮，不做多次采样

同时记录：

- token usage
- 总耗时
- case 耗时
- provider/profile 信息

这能让第一版先把“可重复、可比较、可追溯”建立起来。

## 20. 推荐的落地顺序

### 阶段 1：基础骨架

- `evals/suites/` 与 `evals/cases/` 结构
- `models.py` / `loader.py`
- `store.py`
- `report.py`

### 阶段 2：执行与打分

- `executor.py`
- `graders.py`
- `scripts/run_eval.py`
- `main_chain_core` 首批 15~20 个 case

### 阶段 3：基线与对比

- baseline 表
- compare 逻辑
- markdown regression 报告

### 阶段 4：扩展套件

- `main_chain_mcp`
- `main_chain_subagent`

## 21. 完成标准

这份设计落地完成时，仓库应该具备以下能力：

- 能跑 `main_chain_core` 黄金任务回放
- 每次 run 自动保存到 SQLite
- 每次 run 自动生成 Markdown / JSON 报告
- 能和上一条基线做对比
- 每条 case 都能回链到 `run_id` / `trace_id`
- 退化 case 能直接定位到具体主链证据

## 22. 这份设计对项目阶段的意义

`marten-runtime` 当前已经具备功能、链路和观测基础。评测基础能力进入基线后，项目就会从“能跑、能查”进一步进入“能证明迭代收益”的阶段。
