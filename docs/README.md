# 文档索引

这个目录保存 `marten-runtime` 的公开设计与运维文档。

## 从这里开始

1. [../README.md](../README.md)
2. [DEPLOYMENT.md](./DEPLOYMENT.md)
3. [ARCHITECTURE_EVOLUTION.md](./ARCHITECTURE_EVOLUTION.md)
4. [ARCHITECTURE_CHANGELOG.md](./ARCHITECTURE_CHANGELOG.md)
5. [architecture/adr/README.md](./architecture/adr/README.md)
6. [CONFIG_SURFACES.md](./CONFIG_SURFACES.md)
7. [LIVE_VERIFICATION_CHECKLIST.md](./LIVE_VERIFICATION_CHECKLIST.md)
8. [archive/README.md](./archive/README.md)

## 推荐阅读顺序

按这个顺序阅读最容易理解当前基线：

1. `README.md`
   - 当前范围、runtime 主链、部署入口
2. `DEPLOYMENT.md`
   - 最短部署路径、最小配置、启动方式、健康检查、可选集成
3. `ARCHITECTURE_EVOLUTION.md`
   - 读者友好的阶段叙事，解释架构为什么会变成今天这样
4. `ARCHITECTURE_CHANGELOG.md`
   - 追加式架构时间线、变化原因与验证证据
5. `architecture/adr/`
   - 稳定边界与长期决策
6. `CONFIG_SURFACES.md`
   - 配置归属与覆盖面说明
7. `LIVE_VERIFICATION_CHECKLIST.md`
   - 实链验证与运维检查

## 每份文档的职责

- `DEPLOYMENT.md`
  - 给运维或部署场景的最短可行路径
- `ARCHITECTURE_EVOLUTION.md`
  - 用阶段叙事解释主链、边界和演进原因
- `ARCHITECTURE_CHANGELOG.md`
  - 记录架构基线如何变化、为什么变化、如何验证
- `architecture/adr/`
  - 保存不宜漂移的稳定架构决策
- `CONFIG_SURFACES.md`
  - 说明每类配置应该放在哪个文件
- `LIVE_VERIFICATION_CHECKLIST.md`
  - 提供真实 `Feishu -> LLM -> MCP -> Feishu` 链路的检查清单
- `archive/`
  - 保留少量仍有追溯价值的历史设计、审计和计划

## 说明

- 主文档路径现在统一为中文单语：`README -> docs/README -> DEPLOYMENT -> ARCHITECTURE_EVOLUTION -> ARCHITECTURE_CHANGELOG -> ADR -> CONFIG_SURFACES`
- 架构文档需要让读者快速看懂两件事：当前 runtime 主链，以及这些边界为何成为基线
- 历史设计和执行文档仍然是次级材料；长期结论优先沉淀到 `ARCHITECTURE_CHANGELOG.md`
- archive 应保持克制，不要变成所有旧计划的堆放区
- 2026-04-09 branch-evolution 现在只保留一份归档说明：`docs/archive/branch-evolution/2026-04-09-fast-path-inventory-and-exit-strategy.md`
- 2026-04-11 repo slimming 工作已压缩到 `docs/archive/plans/2026-04-11-repo-slimming-summary.md`
- 2026-04-17 Langfuse observability design 保留在 `docs/2026-04-17-langfuse-observability-design.md`
- 2026-04-30 主链评测基础能力设计保留在 `docs/2026-04-30-main-chain-eval-foundation-design.md`
- 已完成的评测执行计划已压缩到 `docs/archive/plans/2026-05-01-eval-foundation-summary.md`
- 本地忽略的 `STATUS.md` 继续只承担分支执行看板角色

## 评测运维入口

主 HTTP 服务启动后，访问 `/evals` 查看 Gate / Challenge 当前主评测、suite、历史 runs、版本、基线和动态报告。

![Eval 运维总览](./assets/eval-ops-home.png)

| 入口 | 内容 |
| --- | --- |
| `/evals` 或 `/index.html` | 评测总览、当前主评测、版本采纳、基线采纳 |
| `/evals/suites` | HTML 套件清单；`Accept: application/json` 返回 JSON |
| `/evals/runs` | HTML 历史运行；`Accept: application/json` 返回 JSON |
| `/evals/versions/compare` | 已采纳版本之间的 suite 分数、状态和报告对比 |
| `/evals/runs/{eval_run_id}/view` | 单次运行详情、对比结果、稳定性、用例明细 |
| `/evals/reports/{eval_run_id}` | 动态 HTML 报告；对比部分按当前已采纳基线重新计算 |

基线采纳更新后，报告查看页会用新基线重算对比；原始评测分数、case 输出、工具链路和 provider 结果保持该次运行记录。

CLI 入口：

```bash
PYTHONPATH=src .venv/bin/python scripts/run_eval.py \
  --suite main_chain_core \
  --mode scripted \
  --profile openai_gpt_5_4 \
  --baseline latest_passed
```

主要 Gate 套件：

- `main_chain_core`：主链黄金任务
- `main_chain_mcp`：真实 MCP 工具链路，正式效果使用 `live` mode
- `main_chain_subagent`：主线程与子代理链路
- `memory_long_horizon`：长期记忆收益
- `subagent_task_progress`：子代理调度与非 MCP 任务推进
- `subagent_external_mcp_completion`：子代理外部 MCP 完成链路，正式效果使用 `live` mode

产物位置：

- SQLite 历史和基线/版本记录：`data/evals.sqlite3`
- 报告目录：`reports/evals/<eval_run_id>/`
- 汇总产物：`summary.md`、`summary.json`、`summary.html`
- 单 case 详情：`cases/<case_id>.json`

边界：eval 运维面只复用 eval harness、SQLite store、报告层和 HTTP diagnostics；`/messages` 主链仍由 runtime loop 与 LLM 工具选择驱动。


## Challenge eval 入口

Challenge eval 用于衡量迭代收益，和 Gate eval 分层使用：Gate suite 证明主链稳定，Challenge suite 展示质量、工具路径、状态连续性和效率变化。Challenge suite 使用 hard cases 与分项评分，预期能拉开分数差异。

新增套件：

- `challenge_memory`：scripted，hard cases 覆盖干扰召回、scope 隔离、覆盖更新、临时指令不写入。
- `challenge_mcp`：live only，hard cases 覆盖真实 MCP 多来源证据、空结果恢复、工具结果归因。
- `challenge_subagent`：scripted，hard cases 覆盖委派边界、重复派发控制、未完成子任务状态连续性。
- `challenge_integrated`：live only，hard cases 覆盖 memory + MCP 冲突、subagent + MCP 边界、skill required/no-load。

推荐命令：

```bash
PYTHONPATH=src:. .venv/bin/python scripts/run_eval.py --suite challenge_memory --mode scripted --profile openai_gpt_5_4 --report-root reports/evals --db-path data/evals.sqlite3
PYTHONPATH=src:. .venv/bin/python scripts/run_eval.py --suite challenge_subagent --mode scripted --profile openai_gpt_5_4 --report-root reports/evals --db-path data/evals.sqlite3
PYTHONPATH=src:. .venv/bin/python scripts/run_eval.py --suite challenge_mcp --mode live --profile openai_gpt_5_4 --report-root reports/evals --db-path data/evals.sqlite3 --case-timeout-seconds 180
PYTHONPATH=src:. .venv/bin/python scripts/run_eval.py --suite challenge_integrated --mode live --profile openai_gpt_5_4 --report-root reports/evals --db-path data/evals.sqlite3 --case-timeout-seconds 240
```

报告中的 `Challenge Delta` 展示 total score delta、token delta、tool call delta、LLM request delta。报告页状态显示为“待提升”，Case 分数对比展示当前基线 ID。scripted mode 的 token 可能为 0；这代表使用 scripted LLM 验证 harness 和 grader，真实成本以 live mode 为准。Gate suite 出现 100 分代表链路健康；Challenge suite 预期出现 hard case 部分得分，100 分需要结合 `rubric_items` 证明确实满足全部要求。

当前 hard-case 基线示例：`challenge_memory` scripted 63.0，`challenge_subagent` scripted 88.3333，`challenge_mcp` live 93.3333，`challenge_integrated` live 80.5。后续升级通过 component summary、rubric item、Challenge Delta、版本对比和稳定性窗口观察收益。

## 当前状态

- 离线评测已经进入当前运维基线，当前可稳定回放 `main_chain_core`、`memory_long_horizon`、`subagent_task_progress` 并生成 compare / stability 报告
- 真实 MCP 效果评估使用 live-only 套件：`main_chain_mcp`、`subagent_external_mcp_completion`
- 默认 runtime agent 已经是 `main`
- Milestone A 的 agent runtime harness 已经落地
- HTTP `/messages` 与 Feishu interactive ingress 已具备 same-conversation FIFO queueing
- durable SQLite session persistence 已成为当前基线
- `requested_agent_id` 已能真实切换 agent 资产、allowed tool surface 和 model profile
- `session.new` / `session.resume` 已成为显式会话目录与切换控制面
- thin `memory` builtin 已作为一条受控 continuity slice 接入
- narrow self-improve loop 已实现并进入 runtime 基线
- `automation` family tool 已直接面向 automation store 提供 CRUD
- provider 配置已拆分到 `config/providers.toml` 与 `config/models.toml`
- Langfuse tracing 已作为可选 observability slice 接入
- 稳定架构真相以 `docs/architecture/adr/` 与 `docs/ARCHITECTURE_CHANGELOG.md` 为准
