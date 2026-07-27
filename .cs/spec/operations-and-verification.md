# 运维与验证

## 读者该带走什么

项目采用 template-first 配置和分层验证。最小 runtime 只需要一个 provider credential；Feishu、MCP、Langfuse 与本地 Knowledge 模型按需接入。

## 配置归属

- `.env`：secrets 与机器本地 override。
- `config/*.example.toml`：公开默认模板。
- `config/*.toml`：可选本地覆盖。
- `config/agents.toml`：agent registry、资产根、tool surface、prompt mode 与 model profile。
- `config/bindings.toml`：channel / user / conversation binding。
- `mcps.json`：live MCP server 定义与可选工具提示。
- `agents/<agent_id>/`：agent-owned prompt 与 bootstrap 资产。
- `data/`：session、memory、knowledge、eval 与本地模型等运行数据。

## 最短启动路径

### 本地进程

```bash
./init.sh
source .venv/bin/activate
PYTHONPATH=src python -m marten_runtime.interfaces.http.serve
```

### Docker Compose

```bash
docker compose up -d --build
```

启动后检查：

```bash
curl -sS http://127.0.0.1:8000/healthz
curl -sS http://127.0.0.1:8000/readyz
curl -sS http://127.0.0.1:8000/diagnostics/runtime
```

## Operator 观察面

- `/diagnostics/runtime`：配置解析、agent、channel、MCP、provider、observability 与整体健康。
- `/diagnostics/session/{session_id}`：session continuity 与恢复状态。
- `/diagnostics/run/{run_id}`：LLM request、tool calls、provider attempts、failover 与最终结果。
- `/diagnostics/trace/{trace_id}`：一次请求的 trace 关联。
- `/automations`：recurring automation 定义与状态。
- `/evals`：suite、历史 runs、baseline compare、稳定性与 HTML 报告。

## 验证层次

### 代码与契约

单元测试和 contract tests 验证模块职责、schema、错误路径、权限、恢复和主链行为。修改后从最近的 owner tests 开始，再扩大到相关 contract 与全量测试。

### 静态与构建

```bash
PYTHONPATH=src .venv/bin/python -m compileall -q src tests scripts/run_eval.py
git diff --check
```

### 本地 smoke

`./init.sh` 提供 fresh checkout 初始化与 smoke；`./init.sh --smoke-only` 复用已准备的 workspace。最小 smoke 覆盖 health、ready、runtime diagnostics 与 HTTP message path。

### Live chain

Feishu live 验证沿 `Feishu -> LLM -> tool / MCP / subagent -> LLM -> Feishu` 获取真实证据。启动前先确认 provider、MCP 与 Feishu credentials，再通过 `last_run_id` 进入 run diagnostics 和 runtime trace。

### Eval

```bash
PYTHONPATH=src .venv/bin/python scripts/run_eval.py \
  --suite main_chain_core \
  --mode scripted \
  --profile openai_gpt_5_4 \
  --baseline latest_passed
```

Eval 使用 SQLite 保存历史，在 `reports/evals/<eval_run_id>/` 生成 Markdown、JSON 与 HTML 报告。Core、memory、subagent 与 knowledge suites 分别评估主链、长期连续性、后台推进和检索质量。

## 故障定位顺序

1. 确认 `/healthz` 与 `/readyz`。
2. 打开 `/diagnostics/runtime` 核对 selected profile、agent、channel、MCP 与 tracing。
3. 用 session / run / trace id 缩小到单次请求。
4. 核对 provider attempts、tool calls、delivery 与 degraded reason。
5. 运行最接近该责任边界的测试或 eval suite。

## 质量约束

- Health、ready 与 diagnostics 提供自描述的 operator 入口。
- Secrets、token、chat identity 与敏感 URL 参数保持在本地并经过脱敏。
- Optional integration 的故障通过健康状态和 degraded result 暴露，主链拥有清晰的启动与失败边界。
- 验证证据与责任边界对应：模块测试证明局部，contract 证明接口，live chain 证明外部集成，eval 证明体验与能力质量。

## 证据索引

- `README.md`
- `docs/DEPLOYMENT.md`
- `docs/CONFIG_SURFACES.md`
- `docs/LIVE_VERIFICATION_CHECKLIST.md`
- `docs/README.md`
- `scripts/run_eval.py`
- `init.sh`
- `tests/`
- `evals/`
