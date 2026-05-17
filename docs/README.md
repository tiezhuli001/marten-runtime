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

主 HTTP 服务启动后，访问 `/evals` 查看当前评测链路状态、suite、历史 runs、分数变化、基线对比和报告入口。

![Eval 运维总览](./assets/eval-ops-home.png)

| 入口 | 内容 |
| --- | --- |
| `/evals` | 评测总览、最近运行、套件、分数变化 |
| `/evals/suites` | HTML 套件清单；`Accept: application/json` 返回 JSON |
| `/evals/runs` | HTML 历史运行；`Accept: application/json` 返回 JSON |
| `/evals/runs/{eval_run_id}/view` | 单次运行详情、对比结果、稳定性、用例明细 |
| `/evals/reports/{eval_run_id}` | 完整 HTML 报告 |

CLI 入口：

```bash
PYTHONPATH=src .venv/bin/python scripts/run_eval.py \
  --suite main_chain_core \
  --mode scripted \
  --profile openai_gpt_5_4 \
  --baseline latest_passed
```

主要套件：

- `main_chain_core`：主链黄金任务
- `main_chain_mcp`：真实 MCP 工具链路，只用于 `live` mode
- `main_chain_subagent`：主线程与子代理链路
- `memory_long_horizon`：长期记忆收益
- `subagent_task_progress`：子代理调度与非 MCP 任务推进
- `subagent_external_mcp_completion`：子代理外部 MCP 完成链路，只用于 `live` mode

`main_chain_mcp` 与 `subagent_external_mcp_completion` 的正式效果评估使用真实 provider、真实 MCP server 和真实 GitHub 返回：

```bash
PYTHONPATH=src .venv/bin/python scripts/run_eval.py \
  --suite main_chain_mcp \
  --mode live \
  --profile openai_gpt_5_4 \
  --baseline latest_passed

PYTHONPATH=src .venv/bin/python scripts/run_eval.py \
  --suite subagent_external_mcp_completion \
  --mode live \
  --profile openai_gpt_5_4 \
  --baseline latest_passed
```

产物位置：

- SQLite 历史：`data/evals.sqlite3`
- 报告目录：`reports/evals/<eval_run_id>/`
- 汇总报告：`summary.md`、`summary.json`、`summary.html`
- 单 case 详情：`cases/<case_id>.json`

边界：eval 运维面只复用 eval harness、SQLite store、报告层和 HTTP diagnostics；`/messages` 主链仍由 runtime loop 与 LLM 工具选择驱动。

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
