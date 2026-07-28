---
kind: epic
title: "Bazi Agent 内置排盘与 Knowledge 引用闭环"
status: open
created: 2026-07-24
---

# Bazi Agent 内置排盘与 Knowledge 引用闭环

## 这个 Epic 要改变什么

Marten 增加一条完整的 Bazi 顶层 agent 主链：用户通过 HTTP 或 Feishu 进入 `main`，main 识别领域意图并同步 handoff 给同级 `bazi` agent；Bazi 调用 builtin `bazi` 和 Knowledge，生成带引用、可诊断、受隐私保护的文化分析。

## 为什么现在做

排盘计算、地点解析、历史时间、Knowledge 权限、管理入库、敏感观测和生产交付跨越 Python、Node、SQLite、HTTP 与 Docker。设计契约已经收敛，实施仍需要按风险和依赖拆分，保证每个切片都能独立验证并保持 runtime 主链可运行。

## 来源 Vision

- `.cs/vision/index.md`：摘取“可组合的 agent、builtin、skill 与 Knowledge 能力”和“自托管敏感数据边界”；Knowledge Console UI 与通用命理产品扩展留在后续变化线。

## 关联 Project Spec

- `.cs/spec/runtime-main-chain.md`：Bazi 必须沿现有 selected-agent、tool follow-up、delivery 与 diagnostics 主链接入。
- `.cs/spec/continuity-and-capabilities.md`：builtin、skill、Knowledge 与 provider 保持已有能力归属。
- `.cs/spec/knowledge-runtime.md`：复用现有 KnowledgeService、namespace、检索、job 与模型运行时。
- `.cs/spec/operations-and-verification.md`：secrets、诊断、Docker、测试和真实主链证据沿用现有运维入口。

## 当前方案

实现采用风险优先的受管理垂直切片。`taibu-core@3.4.0`、`lunar-javascript@1.7.7`、`sect1-v1` 与 Taibu 地点模块作为 bundled bridge 的固定供应链；Python builtin 负责输入、历史时间、进程、权限、错误和敏感观测；Knowledge 管理 API 复用同一 service 与配置；Bazi agent 与 skill 只承担模型可读工作流和输出边界。

首版生产产物为同时包含 Python runtime、Node runtime、bridge、锁定依赖、许可证与 SBOM 的 Docker 镜像。逐调用 Node 子进程承担首版隔离，延迟或并发预算达到 eval 阈值后再升级长驻 worker。

## 需求变化

- 新增 Marten builtin `bazi` 的 `chart`、`dayun`、`resolve_pillars` action。
- 新增 Bazi 顶层 agent、always-on skill、main handoff 与 Knowledge action/namespace scope。
- 新增受 Bearer operator token 保护的 Knowledge 最小管理 HTTP API。
- 将 Knowledge ingest job 的重启恢复、staging 所有权和错误状态变成显式持久化契约。
- 新增 Bazi 敏感观测投影、真实地点 provider 边界与历史中国民用时间归一化。

## 架构考量

- 计算留在锁定 Taibu 内核，Marten 只维护必要的 sect、地点、时间和协议适配，减少算法分叉。
- Builtin schema 对模型公开地点语义，坐标和 provider 细节留在 bridge 内部。
- Operator API 和 agent Knowledge tool 使用独立权限入口，共享同一个 KnowledgeService 和 SQLite 数据模型。
- 共享生产实例中的所有 Knowledge-enabled agent 使用显式 action/namespace scope；Bazi namespace 写入只经过 Operator API。
- 第一版固定 Amap、timeout、输出上限和上传上限为代码常量，当前配置面只增加两个 secret。
- Knowledge Console UI 依据真实入库与恢复证据另开设计，当前 Epic 只交付可复用后端。
- 顶层 agent handoff 与 subagent 分离：handoff 在同一用户 turn 内同步转交完整处理权，subagent 继续承担临时并行或隔离任务。

## 质量约束与取舍

- 功能适宜性：同一出生事实的 `chart`、`dayun` 与 `resolve_pillars` 使用一致的时间、地点、换日和 engine identity；固定 fixture 与 fingerprint 验证。
- 可靠性：bridge timeout 回收整个进程组；provider、上传、embedding 与进程重启都收敛为稳定错误和可诊断终态。
- 信息安全性：Bazi 敏感输入、地点、坐标、operator token 与 provider key 保持在受控边界，trace/history/diagnostics 使用脱敏视图。
- 可维护性：供应链来源、patch、protocol、schema migration、agent scope 和默认值均有单一归属与契约测试。
- 性能效率：上传流式处理并限制为 `10 MiB`；逐调用 Node 进程保留明确升级触发。

## 统一语言

- **Engine source commit**：npm `taibu-core@3.4.0` 的 `gitHead=1f7f8920ef2c2b032401427623ac0b9a7496c68d`。
- **Place resolver source commit**：Taibu `14860a26e3c428bb9c0a3eee3ba88e7cb57b1e6c` 的 MIT 地点模块来源。
- **Operator API**：受 `KNOWLEDGE_OPERATOR_TOKEN` 保护的 `/knowledge/**` HTTP 管理面。
- **Interrupted job**：进程重启时遗留的中间态 job，统一进入 `failed + KNOWLEDGE_JOB_INTERRUPTED + retryable=true`。

## 当前推进

### 可推进范围

- `C00-C13` 实现与自动化验证已完成；main 顶层路由、Bazi 同步 handoff、关联 run 与单次投递契约已经进入生产代码。
- 设计契约、稳定错误、状态机、配置归属、依赖顺序和验收标准已经明确。
- 第一批从锁定依赖与纯本地 fixture 开始，不依赖真实高德 Key 或生产 theory corpus。
- Knowledge Operator API 可以与 Taibu bridge 切片并行实现，最终在真实主链汇合。

### Issues

- [x] `.cs/issues/001-o-taibu-sect1-day-boundary.md`：实现三个 EightChar 点和反查子时民用日期枚举的 sect 1 窄补丁与边界 fixture。
- [x] `.cs/issues/002-o-taibu-place-resolution.md`：实现地点模块适配、直辖市精度、Amap adapter、turn cache 与隐私边界。
- [x] `.cs/issues/003-o-bazi-bridge-builtin-runtime.md`：交付 bundled bridge、历史时间、协议、Python manager、builtin schema 和 runtime 注册。
- [x] `.cs/issues/004-o-knowledge-operator-backend.md`：交付 Operator auth、分页查询、上传、schema migration、staging 与重启恢复。
- [x] `.cs/issues/005-o-bazi-agent-rag-vertical-slice.md`：交付 agent/skill/binding、全实例显式 Knowledge scope、最小 theory fixture 与真实回答闭环。
- [x] `.cs/issues/006-o-bazi-production-evals.md`：交付 Docker/SBOM、完整 eval、真实 provider smoke、删除路径和生产质量门。
- [x] `.cs/issues/007-o-qwen-bazi-tool-efficiency.md`：完成重复工具防护、证据完成后无工具 finalization 与两条真实飞书验收；延迟 P2 保留在该 issue 执行记录。
- [ ] `.cs/issues/008-o-bazi-readable-analysis-output.md`：修复卡片 JSON 泄漏，交付书名/篇章引用和子平格局法、盲派双方法解盘结构。
- [x] `.cs/issues/009-o-top-level-agent-handoff.md`：已交付 main 顶层意图路由、同步 handoff、单次最终投递与 subagent 边界；issue 保持 open，等待关闭授权。

### 执行规则

- Chunk 按 `C00 -> C12` 顺序执行。每个 chunk 先增加会失败的行为测试，再实现，再运行本 chunk 测试与指定回归。
- 一个 chunk 只有在“完成目标、测试、文档/issue 执行记录、`git diff --check`”全部完成后才能进入下一 chunk。
- 外部 provider 使用 fake server 或注入 adapter 完成自动化测试。真实 `AMAP_WEB_SERVICE_KEY` 只在 `C12` 的受控 smoke 中使用。
- 测试和运行命令统一使用仓库 `.venv/bin/python`；Node 测试使用 `third_party/taibu_bridge/` 锁定的 Node major 与原生 `node:test`。
- 每个 chunk 保持主链可启动。跨 chunk 的临时接口只能存在于当前 issue 分支内，并在该 chunk 完成前固定为最终 contract。
- Issue 达到完成条件后更新执行记录；关闭与毕业回写按 CodeStable 关闭授权执行。

### Chunk 总览

| Chunk | 完成目标 | 对应 issue | 主要依赖 |
| --- | --- | --- | --- |
| `C00` | 固定基线、目录骨架与测试入口 | `003` | 当前分支质量门 |
| `C01` | 锁定 Taibu 供应链并证明 sect 1 窄补丁 | `001` | `C00` |
| `C02` | 固定 bridge JSON 协议与 canonical renderer | `003` | `C01` |
| `C03` | 固定历史时间、有效时间与 fingerprint | `003` | `C02` |
| `C04` | 完成地点 resolver 与 Amap adapter | `002` | `C02`、`C03` |
| `C05` | 完成 Python bridge manager、进程安全与 run cache | `002`、`003` | `C04` |
| `C06` | 完成 builtin、runtime 注册与敏感观测 | `003` | `C05` |
| `C07` | 完成 Knowledge job schema migration 与恢复 | `004` | `C00` |
| `C08` | 完成 Knowledge Operator HTTP API | `004` | `C07` |
| `C09` | 完成 AgentSpec scope、Bazi agent 与 skill | `005` | `C06`、`C08` |
| `C10` | 完成 theory 入库与 HTTP/Feishu RAG 主链 | `005` | `C09` |
| `C11` | 完成 Docker、许可证、SBOM 与启动自检 | `006` | `C10` |
| `C12` | 完成完整 eval、真实 smoke 与发布质量门 | `006` | `C11` |
| `C13` | 完成 main 顶层路由与同步 Bazi handoff | `009` | `C09`、`C10` |

### C00：基线保护与实现骨架

**完成目标**

- 记录实现前基线，建立 bridge、测试 fixture 和 Bazi Python 模块的目录边界。
- 新增测试入口后，现有 runtime 与 Knowledge 行为保持通过。

**改动范围**

- 新增 `third_party/taibu_bridge/` 空骨架、`test/` 与 `tests/fixtures/bazi/`。
- 确认后续模块落点为 `src/marten_runtime/tools/builtins/bazi_tool.py` 与 `src/marten_runtime/runtime/bazi_bridge.py`；本 chunk 不创建空生产模块。
- 在 `STATUS.md` 和 issue `003` 记录基线命令与结果。

**执行步骤**

1. 运行现有 AgentSpec、runtime contract、Knowledge 与 diagnostics 测试，保存测试数量和结果。
2. 建立 Node package 骨架，固定 `type=module`、Node major 和 `node --test` 脚本。
3. 建立共享 fixture 目录，按 `clock`、`true_solar`、`resolve_pillars`、错误协议分类。
4. 增加 fixture 加载测试，并确认 capability catalog 在 `C06` 前尚未注册 `bazi`。

**单元测试与验证**

- `PYTHONPATH=src .venv/bin/python -m unittest -v tests.test_agent_specs tests.test_runtime_capabilities tests.test_http_runtime_diagnostics tests.contracts.test_runtime_contracts`
- `PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -p 'test_knowledge*.py'`
- `cd third_party/taibu_bridge && npm test`
- `git diff --check`

**完成条件**

- 基线测试全部通过，Node 测试入口可执行，目录责任与设计文档一致。
- 运行时公开能力面尚未出现半成品 `bazi`。

### C01：Taibu 供应链与 sect 1 窄补丁

**完成目标**

- `taibu-core@3.4.0` 与 `lunar-javascript@1.7.7` 由 lockfile 精确固定。
- `sect1-v1` 修改命盘、Dayun 原局、反查最终候选三个 EightChar 点，并修正反查子时 `23:00/00:00` 的民用日期枚举；来源与摘要可重复验证。

**改动范围**

- `third_party/taibu_bridge/package.json`、`package-lock.json`、`.node-version`。
- `UPSTREAM.md`、`PATCHES.md`、三份许可证与 `patches/taibu-core+3.4.0-sect1.patch`。
- `third_party/taibu_bridge/test/upstream.test.mjs`、`sect1-boundary.test.mjs`。

**执行步骤**

1. 用 `npm ci` 安装锁定依赖，读取 npm `gitHead` 与 package integrity。
2. 保存 patch 前三个目标文件摘要，生成最小 unified diff，应用后保存 patch 后摘要。
3. 增加 `verify:upstream` 与 `prepare:engine` 脚本：前者校验 package version、gitHead、lockfile integrity、原文件摘要和许可证，后者只接受“原始摘要”或“已应用摘要”，对原始文件应用 patch，对已应用文件幂等成功，对任何其他摘要立即失败。
4. 固定本地、CI 与 Docker 安装顺序为 `npm ci -> npm run verify:upstream -> npm run prepare:engine -> npm test`，保证每次干净安装都产生相同 patched engine。
5. 增加 22:59、23:00、23:30、23:59、00:00 fixture。
6. 增加反查午夜预筛选 sect 1/2 等价测试，并验证同一子时四柱同时返回前一民用日 `23:00` 与当日 `00:00`。

**单元测试与验证**

- `cd third_party/taibu_bridge && npm ci && npm run verify:upstream && npm run prepare:engine && node --test test/upstream.test.mjs test/sect1-boundary.test.mjs`
- 重复执行 `npm run prepare:engine`，第二次必须以“已应用且摘要匹配”成功结束；修改任一目标文件后，`verify:upstream`/`prepare:engine` 必须失败。
- 固定样例 `1988-02-15 23:30` 必须返回日柱 `辛丑`、时柱 `戊子`。

**完成条件**

- issue `001` 的全部验证项通过。
- Engine source commit 固定为 `1f7f8920ef2c2b032401427623ac0b9a7496c68d`，地点来源 commit 保持独立。

### C02：Bridge 协议与 canonical renderer

**完成目标**

- `index.mjs` 实现单行 stdin/stdout JSON 协议，三 action 获得稳定 request/response envelope。
- 结果只从 Taibu canonical `structuredContent` 进入 Marten contract。

**改动范围**

- `third_party/taibu_bridge/index.mjs`、`PROTOCOL.md` 与协议内部模块。
- `test/protocol.test.mjs`、`renderer.test.mjs`、`action-mapping.test.mjs`。

**执行步骤**

1. 先为 protocol version、requestId、tool/action mapping 和 engine metadata 写失败测试。
2. 实现 `protocolVersion=1` 解析，只接受一行 UTF-8 JSON 请求。
3. 映射 `chart/dayun/resolve_pillars` 到 `bazi/bazi_dayun/bazi_pillars_resolve`。
4. 接入 `executeTool` 与 canonical renderer，固定三个 `resultSchemaVersion`。
5. 固定错误分类：协议不匹配、空输出、多行输出、JSON 损坏、action 不支持、上游业务错误。
6. 保证 stdout 只含协议结果，诊断只写 stderr。

**单元测试与验证**

- `cd third_party/taibu_bridge && node --test test/protocol.test.mjs test/renderer.test.mjs test/action-mapping.test.mjs`
- 测试 requestId 原样回传、engine 四字段完整、`detailLevel` 生效、校验前失败的 fingerprint 为 `null`。
- 对 stdout 做逐字节断言，保证只有一行 JSON 和末尾换行。

**完成条件**

- 三 action 的成功与失败 envelope 可由独立 Node 进程稳定调用。
- `PROTOCOL.md` 与设计 4.1/4.2 字段完全一致。

### C03：历史时间、有效时间与 fingerprint

**完成目标**

- 支持 `1901-2100`、公历/农历、历史 civil time、UTC+8 归一化、真太阳有效时间和 Yun sect 1。
- `chart` 与 `dayun` 对同一出生事实返回完全相同 fingerprint。

**改动范围**

- Bridge 时间归一化与 fingerprint 内部模块。
- `test/time-normalization.test.mjs`、`fingerprint.test.mjs`、`dayun-consistency.test.mjs`。
- `tests/fixtures/bazi/time-boundaries.json`。

**执行步骤**

1. 写 1900 拒绝、1901 下限、1919、1940-1949、1986-1991 历史 fixture。
2. 实现 `recorded_civil` 与 `beijing_standard`，检测 DST 跳跃和歧义。
3. 农历输入先转为来源公历，再执行同一 civil-time 归一化。
4. 固定 bridge 子进程 `TZ=UTC` 的时间组件处理和 ICU 自检。
5. 从 `trueSolarTime + dayOffset` 取得有效时间，禁止从 `correctionMinutes` 反推。
6. 按设计字段顺序生成 canonical JSON 和 sha256 fingerprint。
7. 过滤 `resolve_pillars` 的 1900 年候选，验证 chart/dayun 原局一致。

**单元测试与验证**

- `cd third_party/taibu_bridge && node --test test/time-normalization.test.mjs test/fingerprint.test.mjs test/dayun-consistency.test.mjs`
- 分别在 `TZ=UTC`、`TZ=Asia/Shanghai` 和另一宿主时区启动测试进程，固定 corpus 结果必须一致。
- 验证 `2022-03-09 20:51` 男命起运为 `8年9月10天`、`2030-12-19 20:51`。

**完成条件**

- 设计 4.2.2 的全部字段、边界和错误都由 fixture 覆盖。
- 相同出生事实只有一个 fingerprint，算法标识变化必然改变 fingerprint。

### C04：地点解析与 Amap adapter

**完成目标**

- `true_solar` 只接受地点文本，通过 bundled resolver 得到 canonical 地点结果。
- 中国大陆地域、普通省级拒绝、四直辖市等价精度和 provider 错误语义固定。

**改动范围**

- `place-resolution.mjs`、`providers/amap.mjs`、地点来源许可证与摘要。
- `test/place-resolution.test.mjs`、`amap-provider.test.mjs`、`resolved-place.test.mjs`。

**执行步骤**

1. 从固定 Taibu commit 提取地点模块，记录原文件摘要和本地适配差异。
2. 删除公开手动坐标优先和 fallback 继续计算路径。
3. 实现地点文本规范化、多候选、大陆 allowlist、坐标范围与 GCJ-02 声明。
4. 固定北京/天津/上海/重庆 adcode 城市等价规则。
5. 实现 Amap endpoint、redirect 拒绝、deadline、credential、限流和网络错误映射。
6. 实现 Marten-internal `resolvedPlace` 再校验，成功时跳过 provider。

**单元测试与验证**

- `cd third_party/taibu_bridge && node --test test/place-resolution.test.mjs test/amap-provider.test.mjs test/resolved-place.test.mjs`
- fake fetch 覆盖成功、无结果、多结果、普通省级、四直辖市、港澳台/海外、非法坐标、401/配额/429/5xx/timeout/redirect。
- provider 请求断言只包含地点文本和 key，日志与错误断言不包含完整 query URL 或 key。

**完成条件**

- issue `002` 中 Node resolver 相关验证全部通过。
- 所有失败保持 `true_solar` 并停止排盘。

### C05：Python bridge manager、进程安全与 run cache

**完成目标**

- Python 能可靠调用 bridge，限制环境、时间和输出，并在超时/取消时回收整个进程组。
- 同一 run 的 chart/dayun 复用一个地点事实，新 run 重新解析。

**改动范围**

- `src/marten_runtime/runtime/bazi_bridge.py` 与必要 runtime state。
- `src/marten_runtime/runtime/loop.py` 的 `turn_tool_state` 传播。
- 新增 `tests/test_bazi_bridge_manager.py`、`tests/runtime_loop/test_bazi_turn_tool_state.py`。

**执行步骤**

1. 用 fake bridge 写 manager 成功、缺失、超时、取消、非零退出、信号退出、空/多行/损坏/超限输出测试。
2. 解析 Node 绝对路径，固定 timeout、stdout/stderr 上限和 `start_new_session=True`。
3. 从 runtime `resolved_env` 构造 child env allowlist，并固定 `TZ=UTC`。
4. 校验 protocol version、requestId、engine、fingerprint 和 normalizedTime。
5. 在 `RuntimeLoop.run()` 创建 run-scoped mutable state，并传入每次 tool context。
6. 实现地点缓存键、成功/失败缓存和 `resolvedPlace` 复用。

**单元测试与验证**

- `PYTHONPATH=src .venv/bin/python -m unittest -v tests.test_bazi_bridge_manager tests.runtime_loop.test_bazi_turn_tool_state`
- 进程组测试必须证明 child/grandchild 都被回收。
- child env 快照只包含 allowlist，`AMAP_WEB_SERVICE_KEY` 仅在首次 provider 调用时存在。
- 两个并发 run 使用独立 `turn_tool_state`，相同地点各自调用 provider 一次且互不读取缓存。

**完成条件**

- Manager 的所有失败都转为设计规定的稳定 Bazi 错误。
- provider 调用计数 fixture 证明同一 run 为 1、新 run 为 1。

### C06：Builtin、runtime 注册与敏感观测

**完成目标**

- 模型获得稳定 `bazi` family schema，三个 action 沿现有 capability/ToolRegistry/bootstrap 主链执行。
- Bazi turn 从 trace 创建前开始执行敏感观测策略。

**改动范围**

- `src/marten_runtime/tools/builtins/bazi_tool.py`、`tools/registry.py`。
- `runtime/capabilities.py`、`interfaces/http/runtime_tool_registration.py`、`bootstrap_runtime.py`、`runtime_diagnostics.py`。
- `runtime/history.py`、`run_lifecycle.py`、`run_outcome_flow.py`、`observability/langfuse.py`、`self_improve/recorder.py`、`review_payloads.py`。
- 新增 `tests/test_bazi_tool.py`、`tests/test_bazi_runtime_registration.py`、`tests/runtime_loop/test_bazi_sensitive_observability.py`。

**执行步骤**

1. 从设计 JSON Schema 建立单一 Python schema 常量并写 Draft 2020-12 contract test。
2. 实现真实日期、闰月、六十甲子、年份、timezone、birthPlace 条件校验。
3. 调用 manager 并组装 Marten envelope，模型视图移除精确经纬度，diagnostics 视图进一步脱敏。
4. 注册 capability、handler、runtime state 和 diagnostics，不改变现有 family 行为。
5. 增加通用 ToolDescriptor observation policy 与 agent-level `sensitive_bazi` 传播。
6. 覆盖 trace、generation、tool span、RunHistory、self-improve evidence 和 final text。

**单元测试与验证**

- `PYTHONPATH=src .venv/bin/python -m unittest -v tests.test_bazi_tool tests.test_bazi_runtime_registration tests.test_runtime_capabilities tests.contracts.test_runtime_contracts`
- `PYTHONPATH=src .venv/bin/python -m unittest -v tests.runtime_loop.test_bazi_sensitive_observability tests.runtime_loop.test_langfuse_runtime_observability tests.test_http_runtime_diagnostics`
- 对出生时间、原始地点、精确坐标、完整命盘和两个 secret 执行日志/trace/history 序列化零明文扫描。

**完成条件**

- `HTTPRuntimeState` 启动后可调用 `bazi`，现有 agent 未授权时看不到该 family。
- 设计 4.1、4.2.3、4.7、7、8 的 Bazi runtime 验收全部通过。

### C07：Knowledge job schema migration 与恢复

**完成目标**

- Knowledge job 持久化 `error_code`、`retryable`、`staged_file_path`，旧数据库可原地升级。
- 启动时遗留中间态统一转为 interrupted failed，并清理 job-owned 与过期 orphan staging。

**改动范围**

- `knowledge/sqlite_store.py`、`jobs.py`、`service.py`、`models.py`。
- 新增 `tests/test_knowledge_job_recovery.py`，扩展 `test_knowledge_store.py`、`test_knowledge_service.py`。

**执行步骤**

1. 先创建旧 schema fixture，写迁移后数据保留与新列默认值测试。
2. 增加 job 字段与索引，保持现有 job API 返回兼容。
3. 抽取 staging ownership 和终态 cleanup helper。
4. 实现启动 reconciliation：四个中间态统一写入 interrupted terminal。
5. 实现 completed/failed/cancelled 即时 cleanup 与 24 小时 orphan cleanup。
6. 验证重试创建新 job，旧 job 保留审计证据。
7. 保持 migration 为 additive/idempotent；上一版本代码在包含新列的数据库上仍可读取既有 source/chunk/job。

**单元测试与验证**

- `PYTHONPATH=src .venv/bin/python -m unittest -v tests.test_knowledge_store tests.test_knowledge_service tests.test_knowledge_job_recovery`
- fixture 覆盖 queued/reading/chunking/embedding、三种终态、缺失文件、重复启动和 cleanup 失败。
- fixture 覆盖 cancel/complete 竞争，终态只写入一次，cleanup 可重复执行。
- 重复执行 migration 和 reconciliation 必须幂等。

**完成条件**

- 数据库中不存在启动后仍处于遗留中间态的 job。
- cleanup 失败可诊断且不会覆盖原 job terminal 证据。
- 应用回退到上一版本时可忽略新增列并继续读取原有 Knowledge 数据。

### C08：Knowledge Operator HTTP API

**完成目标**

- `/knowledge/**` 在 token 配置时提供查询、上传、删除、reindex；缺少 token 时 router 不注册。
- 上传流式限制、metadata、状态码、分页和错误 envelope 完全固定。

**改动范围**

- 新增 `interfaces/http/knowledge_routes.py`，修改 `app.py`、runtime diagnostics、bootstrap env。
- 修改 `pyproject.toml`、`requirements.txt`、`.env.example`、部署与配置文档。
- 新增 `tests/test_knowledge_operator_http.py`、`tests/test_knowledge_uploads.py`。

**执行步骤**

1. 增加 `python-multipart` 与 `KNOWLEDGE_OPERATOR_TOKEN` resolved env。
2. 实现恒定时间 Bearer 校验、router 开关、401 与 `WWW-Authenticate`。
3. 增加 namespace/source/chunk/job 查询，固定分页、排序和 envelope。
4. 实现单文件 streaming upload，服务端文件名、sha256、默认 uri/version 和 reviewed metadata。
5. 在 10 MiB 边界同时检查 Content-Length 与实际字节数，错误路径删除 staging。
6. 复用 KnowledgeService 接入 delete、reindex、stats，保持 tool 行为一致。
7. 增加 operator diagnostics，敏感绝对路径与 token 只显示状态。

**单元测试与验证**

- `PYTHONPATH=src .venv/bin/python -m unittest -v tests.test_knowledge_operator_http tests.test_knowledge_uploads tests.test_http_runtime_diagnostics`
- 认证覆盖 router 缺失、header 缺失、scheme 错误、token 错误、token 正确和 service 零调用断言。
- 上传覆盖 10 MiB、10 MiB+1、伪造 Content-Length、`.txt/.md`、UTF-8/UTF-8-SIG/GB18030、路径穿越和不支持格式。
- 并发上传使用独立 staging；相同 `uri+version` 或相同默认 sha256 version 重复上传时更新同一 source，并保留独立 job 证据。
- `PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -p 'test_knowledge*.py'`

**完成条件**

- issue `004` 全部验证通过，现有 Knowledge tool 和检索测试保持通过。
- API contract 与设计 5.5 的 status/envelope/metadata 完全一致。

### C09：AgentSpec scope、Bazi agent 与 Skill

**完成目标**

- `bazi` agent 只拥有 `bazi`、只读 Bazi Knowledge 与 `time`。
- 所有 Knowledge-enabled agent 在共享 Bazi 配置中使用显式 action/namespace scope。

**改动范围**

- `agents/specs.py`、`config/agents_loader.py`、`runtime/loop.py`、`knowledge_tool.py`。
- `config/agents.toml`、`config/bindings.toml`、`agents/bazi/`、`skills/bazi_analysis/SKILL.md`。
- 新增 `tests/test_bazi_agent_assets.py`，扩展 AgentSpec、Knowledge capability 与 binding 测试。

**执行步骤**

1. 为 `allowed_knowledge_namespaces`、`allowed_knowledge_actions`、`observation_policy` 写 loader 失败/兼容测试。
2. 贯通 selected agent 到 tool context，再在 Knowledge handler 校验 action 与 namespace。
3. 增加 `bazi` agent 资产、文化研究定位、信息确认、工具顺序和风险表达。
4. 增加 main 顶层 handoff catalog，保持每个 channel 只有一个 main default。
5. 为共享配置中的所有 Knowledge-enabled agent填写显式 scope。
6. 增加 production readiness 检查，family-level `None` scope 使 Bazi readiness 失败。

**单元测试与验证**

- `PYTHONPATH=src .venv/bin/python -m unittest -v tests.test_agent_specs tests.test_bazi_agent_assets tests.test_knowledge_runtime_capabilities tests.test_runtime_capabilities`
- 增加 `KNOWLEDGE_ACTION_FORBIDDEN`、`KNOWLEDGE_NAMESPACE_FORBIDDEN`、无 namespace read action 和旧配置兼容 fixture。
- 校验 Bazi agent 无 `mcp`、`memory`、Knowledge 写 action。

**完成条件**

- 共享配置满足显式 scope 不变量，Bazi namespace 只有 Operator API 可写。
- Skill 与 agent asset 能从现有 prompt/bootstrap 读取；main handoff 负责顶层自然语言路由。

### C10：Theory 入库与 RAG 真实主链

**完成目标**

- 通过 Operator API 录入最小许可 `bazi-theory` source，并完成一次带真实引用的 Bazi 回答。
- HTTP 与 Feishu 的 run、trace、tool span、fingerprint 和引用可关联。

**改动范围**

- 最小 theory fixture 与 source metadata。
- `evals/suites/bazi_agent.toml`、`tests/evals/test_bazi_family_grader.py`、focused acceptance tests。
- 必要的 HTTP/Feishu test fixtures。

**执行步骤**

1. 准备小型已许可 theory fixture，完整记录 `title`、`uri`、`version`、`corpus_type=theory`、`school`、`review_status=reviewed`、`license`、`provenance`、`calculation_scope` 和 `method`。
2. 通过 Operator API 上传并轮询 job 到 terminal，检查 namespace hash 与检索结果。
3. 执行 clock 排盘、true_solar 排盘、dayun 和 resolve_pillars 主链。
4. 让 skill 按事实、engine 标注、theory 引用、综合判断、现实建议分层输出。
5. 打通 HTTP selected-agent 流程，再使用 fake Feishu delivery 验证同一主链。
6. 增加无召回、Knowledge 模型缺失、地点失败和 fingerprint mismatch 的降级场景。

**单元测试与验证**

- `PYTHONPATH=src .venv/bin/python -m unittest -v tests.evals.test_bazi_family_grader tests.test_acceptance`
- `PYTHONPATH=src .venv/bin/python scripts/run_eval.py --suite bazi_agent --mode scripted --profile openai_gpt_5_4`
- 断言每条 theory 结论包含存在的 `source_id` 与 `chunk_id`，案例段只在有案例证据时出现。
- 敏感扫描覆盖用户消息、tool payload/result、final text、trace、history 与 self-improve evidence。

**完成条件**

- issue `005` 全部验证通过，第一阶段端到端退出信号成立。

### C13：Main 顶层路由与同步 Handoff

**完成目标**

- 默认 HTTP/Feishu 请求由 main 识别意图，并在同一 turn 内选择 main 或已授权的顶层 agent。
- Bazi handoff 只投递目标 agent 的最终回答，完整使用 Bazi 的运行时资产与权限。

**改动范围**

- `agents/specs.py`、`config/agents_loader.py`、`agents/registry.py`。
- 新增顶层 dispatch/handoff runtime 模块，并窄改 HTTP/Feishu bootstrap handler、run lineage 与 diagnostics。
- `config/agents.toml`、`config/bindings.toml`、main/Bazi agent 资产和 Bazi Skill。
- issue `009` 定义的单元、集成、隐私与真实链路测试。

**执行步骤**

1. 为 `routing_description`、`allowed_handoff_agents` 和 registry catalog 增加 loader 与启动校验测试。
2. 实现 main metadata-only 路由阶段与结构化决策，限制每 turn 一次 handoff。
3. 在同一 trace 内用原始用户消息启动目标 run，传播 `parent_run_id`，切换完整 AgentSpec、prompt、Skill、tool snapshot、Knowledge scope、model profile 与 observation policy。
4. 调整 session 持久化和 delivery，使用户消息与最终 assistant 消息各写一次，路由结果保持内部可诊断。
5. 删除占位 Bazi conversation binding，保留 main channel defaults、显式 requested-agent 与精确专用 binding 能力。
6. 加入明确农历、普通月份、区县地点的 Bazi 输入规则，并覆盖原始失败样例。

**单元测试与验证**

- AgentSpec/catalog：未知、禁用、自引用、未授权目标全部拒绝。
- 路由行为：普通问答到 main；出生资料、四柱、子平、盲派和大运到 Bazi；最近会话支持省略主语的连续追问。
- 主链行为：同一 trace 两个关联 run，Bazi run 为 `agent_bazi_full + sensitive_bazi + bazi/knowledge/time`，路由 run 为 metadata-only。
- 持久化与投递：单条 user、单条 assistant、单次最终 delivery、零中间路由文案、零 handoff 环路。
- 回归：router、binding、session、subagent、HTTP、Feishu、Bazi acceptance/eval、完整 Python 与 Node suite。

**完成条件**

- 真实飞书原始农历样例出现 `main dispatch -> bazi.chart -> knowledge.search -> final delivery`。
- 回复直接排盘并按子平格局法和盲派分析，不重复询问农历或公历转换。
- diagnostics、外部观测与 session 证明确认权限、隐私、lineage 和单次投递契约。
- RAG 降级不会改变排盘事实，fingerprint mismatch 会停止综合解释。

### C11：Docker、许可证、SBOM 与启动自检

**完成目标**

- 官方镜像包含 Python、固定 Node major、bridge、生产 npm 依赖、许可证和 SBOM。
- 干净环境启动时可诊断 bridge、ICU/timezone、Amap、Knowledge 与 Operator 状态。

**改动范围**

- `Dockerfile`、`compose.yaml`、bridge bootstrap/SBOM 配置。
- `docs/DEPLOYMENT.md`、`CONFIG_SURFACES.md`、`LIVE_VERIFICATION_CHECKLIST.md`。
- Docker/packaging contract tests。

**执行步骤**

1. 改为同 Debian family、固定 release digest 的 Python/Node 多阶段构建。
2. Node 阶段执行 `npm ci --omit=dev -> npm run verify:upstream -> npm run prepare:engine`，最终镜像复制 patched engine、Node runtime、bridge 和生产依赖，并在镜像测试中复核 patch 后摘要。
3. 生成 SPDX 或 CycloneDX SBOM 与第三方许可证清单。
4. 启动自检 Node major、bridge path、engine metadata、ICU 历史 offset 和 Knowledge schema。
5. 更新 compose secret 注入、数据卷和 outbound 说明。
6. 更新本地 bootstrap、部署、配置和 live verification 文档。

**单元测试与验证**

- `docker build -t marten-runtime:bazi-local .`
- 使用空 provider key 启动，验证 clock 可用、true_solar 透明失败、Operator router 关闭。
- 使用测试 token 启动，验证 `/knowledge/**` 认证、上传和检索。
- 在镜像内断网运行 clock 排盘，证明运行期无需 npm 下载。
- 扫描镜像确认许可证、SBOM、lockfile、Node 版本和两个 secret 零明文。

**完成条件**

- issue `006` 的生产封装部分完成。
- Compose health、ready、runtime diagnostics 与本地 bootstrap 文档一致。

### C12：完整 eval、真实 smoke 与发布质量门

**完成目标**

- 全部设计验收标准获得自动化或受控 smoke 证据。
- 产出 `PASS` 或带明确阻碍的发布质量门结论。

**改动范围**

- Bazi/Knowledge eval suite、grader、性能记录、真实 smoke 记录、session 删除与备份清理运行手册。
- issue `006` 执行记录、Epic 当前推进与 `STATUS.md`。

**执行步骤**

1. 运行全部 Node bridge tests、Bazi Python tests、Knowledge tests、runtime contracts 和 compileall。
2. 运行 scripted Bazi eval，覆盖 schema、时间、sect、Yun、地点、权限、上传恢复、引用、隐私和高风险表达。
3. 使用真实 `AMAP_WEB_SERVICE_KEY` 执行一次受控地点解析与 true_solar smoke，检查 outbound 与脱敏记录。
4. 使用真实 `KNOWLEDGE_OPERATOR_TOKEN` 完成 upload -> job -> search -> delete/reindex smoke。
5. 测量逐调用 Node 进程启动延迟、并发和输出大小，记录 worker 升级触发。
6. 演练 session 删除、保留周期与备份清理。
7. 运行文档链接、fixture 完整性、设计覆盖矩阵、SBOM/许可证与 `git diff --check`。

**单元测试与验证**

- `cd third_party/taibu_bridge && npm test`
- `PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -p 'test_bazi*.py'`
- `PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -p 'test_knowledge*.py'`
- `PYTHONPATH=src .venv/bin/python -m unittest -v tests.contracts.test_runtime_contracts tests.test_http_runtime_diagnostics tests.runtime_loop.test_langfuse_runtime_observability tests.test_acceptance`
- `PYTHONPATH=src .venv/bin/python -m compileall -q src tests`
- `PYTHONPATH=src .venv/bin/python scripts/run_eval.py --suite bazi_agent --mode scripted --profile openai_gpt_5_4`
- `git diff --check`
- Benchmark 执行 1 次 warm-up、50 次顺序 `clock/chart` 与 8 路并发；记录 p50/p95、进程启动占比、timeout 和 orphan process。

**完成条件**

- 设计第 10 节验收标准全部映射到通过证据。
- P0/P1 为零，P2/P3 有明确 owner 和后续 issue；release gate 为 `PASS` 或 `PASS_WITH_RISKS`。
- Epic 六个 issue 达到完成状态，等待用户授权关闭与毕业回写。
- 连续 3 次发布基准出现 p95 超过 1 秒、进程启动占 p95 至少 40%，或 8 路并发出现任何 timeout/orphan 时，创建长驻 worker 升级 issue。

### 设计覆盖矩阵

| 设计范围 | 执行 chunk | 主要证据 |
| --- | --- | --- |
| 4.1 Builtin schema、action mapping、Marten envelope | `C02`、`C06` | Node protocol tests、`test_bazi_tool`、runtime contract |
| 4.2 供应链、patch、protocol、canonical renderer | `C01`、`C02` | upstream digest、sect fixture、protocol/renderer tests |
| 4.2.1 地点解析、直辖市、provider、turn cache | `C04`、`C05` | fake Amap contract、resolvedPlace、provider call count |
| 4.2.2 历史时间、真太阳时、sect/Yun、fingerprint | `C03` | historical timezone corpus、cross-TZ、chart/dayun consistency |
| 4.2.3 固定默认值、resolved env、diagnostics | `C05`、`C06` | manager env/limit tests、runtime diagnostics |
| 4.3-4.5 Agent、Knowledge scope、Skill | `C09` | loader/scope/assets tests、production readiness |
| 4.6 Marten 内置代码与上游复用边界 | `C00-C06`、`C11` | 目录 contract、来源摘要、bridge/builtin tests、镜像内容检查 |
| 4.7 注册、错误、观测 | `C05`、`C06` | manager failures、ToolRegistry/bootstrap、sensitive scans |
| 5.1-5.4 theory RAG、metadata、检索与收益 | `C10` | reviewed fixture、citation grader、with/without RAG eval |
| 5.5 Knowledge 最小管理后端 | `C07`、`C08` | migration/recovery、auth/upload/API tests |
| 6 端到端流程与输出契约 | `C09`、`C10` | HTTP/Feishu acceptance、tool order、output grader |
| 7 故障与降级 | `C02-C10` | 各责任模块的错误 fixture 与恢复测试 |
| 8 信息安全性与安全性 | `C06`、`C09`、`C10`、`C12` | scope denial、敏感扫描、risk-expression eval |
| 9 第一/二阶段 | `C00-C10`、`C12` | focused tests、scripted eval、主链证据 |
| 9 条件性案例库 | 后续 `D01` | 案例许可、匿名化与审核责任确认后建独立 issue |
| 9 第四阶段生产封装 | `C11`、`C12` | image smoke、SBOM、real provider、release gate |
| 10 验收标准 | `C12` | 逐项 requirement-to-evidence 清单 |
| Knowledge Console UI | Epic 外后续设计 | Bazi 完成后单独建立需求和执行计划 |

### 后段决策门

- `G01`（进入 `C10` 前）：最小 theory fixture 的许可证、provenance 和 `reviewed` 状态已确认。
- `G02`（进入 `C11` 前）：已固定共享生产 session 保留 90 天、部署 operator 负责删除、主存储删除后 30 天内清理备份，并写入部署契约。
- `G03`（进入 `C12` 真实 smoke 前）：可用的 `AMAP_WEB_SERVICE_KEY` 与 `KNOWLEDGE_OPERATOR_TOKEN` 已通过 secret manager 注入。
- `D01`（条件性案例库）：theory-only 对照评测完成，案例许可、匿名化标准和审核责任人已确认；随后建立独立受管理 issue，保持当前 Epic 的 Bazi 核心交付边界。

### 剩余阻碍

- 实现、自动化验证、测试 Operator token smoke 与离线镜像验证均无阻碍。
- 真实 Amap true-solar smoke 已通过；共享生产部署继续按运行手册从 secret manager 注入 `AMAP_WEB_SERVICE_KEY`。

## 暂不推进范围

- Knowledge Console UI、按上传任务自定义 chunk profile、生产案例库扩容、海外历史时区、Memory 跨会话保存与长驻 Node worker。

## 未确认问题

- 生产 theory/case corpus 的责任人、许可与匿名化流程在共享生产 rollout 前确认；首批穿刺使用仓库内许可已确认的最小 fixture。

## 关闭条件

- 九个 issue 完成并获得各自验证证据。
- `HTTP/Feishu -> main dispatch -> bazi handoff -> skill -> builtin bazi -> bundled bridge -> Knowledge -> answer -> redacted diagnostics` 真实主链闭环。
- 历史时间、sect 1、直辖市、provider 失败、operator 越权、上传超限、重启恢复与敏感字段 fixture 全部通过。
- 共享配置中任何 agent 都无法写入 Bazi namespace，family-level `None` scope 无法通过 production readiness。
- Docker 镜像包含固定 Node major、bridge、lockfile、许可证与 SBOM，并通过启动和真实 smoke。
- 关闭时把稳定 Bazi 与 Knowledge Operator 能力毕业到 Project Spec，并检查 Vision 实现程度。

## 合并回 Project Spec 的候选

- `.cs/spec/continuity-and-capabilities.md`：Bazi builtin、agent 与 skill 的稳定组合边界。
- `.cs/spec/knowledge-runtime.md`：Operator API、上传资源边界、job 恢复与 staging 清理。
- `.cs/spec/operations-and-verification.md`：两个 secret、Bazi diagnostics、Docker 供应链与生产验证入口。

## 相关材料

- `docs/2026-07-23-bazi-agent-design.md`：实现契约、接口、状态、错误、隐私与验收的权威设计。
- `.cs/notes/003-bazi-calculation-contract-audit.md`：历法、时间、地点、换日与 engine provenance 的证据。
