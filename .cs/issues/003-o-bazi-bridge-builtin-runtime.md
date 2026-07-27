---
kind: issue
title: "Bazi bundled bridge 与 builtin runtime"
type: feature
status: open
created: 2026-07-24
epic: ".cs/epics/001-o-bazi-agent/spec.md"
---

# Bazi bundled bridge 与 builtin runtime

## 目标

Marten 通过稳定 builtin `bazi` 调用本地 bundled Node bridge，在 `1901-2100` 范围内完成可审计的 `chart`、`dayun` 与 `resolve_pillars`，并把 engine、时间口径、fingerprint、错误和敏感诊断沿现有 runtime 主链返回。

## 范围

- 包含：bridge 依赖与协议、历史 civil time 归一化、canonical result、Python manager、进程回收、builtin schema/host validation、runtime state/注册、turn tool state、敏感观测策略。
- 包含：集成 `001` 的 sect patch 与 `002` 的地点结果；这些算法适配仍由各自 issue 负责。
- 不包含：Agent prompt/skill、Knowledge Operator API、生产 Docker 与完整 eval。

## 归属

- 隶属 Epic：`.cs/epics/001-o-bazi-agent/spec.md`
- 相关设计：`docs/2026-07-23-bazi-agent-design.md`
- 依赖：`.cs/issues/001-o-taibu-sect1-day-boundary.md`、`.cs/issues/002-o-taibu-place-resolution.md`

## 现状如何工作

当前 HTTP bootstrap 显式注册 capability 与 builtin handler，RuntimeLoop 为每次工具调用创建 tool context，错误通过统一 tool outcome 进入 follow-up、history 与 diagnostics。仓库尚无 Bazi builtin、Node bridge、engine protocol 或出生时间归一化责任。

## 执行 Chunk

- `C00`：基线保护与实现骨架。
- `C02`：Bridge 协议与 canonical renderer。
- `C03`：历史时间、有效时间与 fingerprint。
- `C05`：Python bridge manager、进程安全与 run cache。
- `C06`：Builtin、runtime 注册与敏感观测。
- 权威步骤、测试命令与完成条件见 `.cs/epics/001-o-bazi-agent/spec.md` 的对应 chunk。

## 影响范围

- 必须修改：`third_party/taibu_bridge/`、builtin tool、runtime state、capability declaration、HTTP registration/bootstrap、ToolDescriptor、RuntimeLoop tool context、观测与 history 投影。
- 需要验证：协议损坏、timeout/取消、进程组回收、输出上限、历史时区、真实日期/闰月、fingerprint、三 action 结果与敏感字段。
- 仍待调查：实现时确认当前 Node 探测和 Docker build 的最小复用入口。

## 质量目标

- 功能适宜性：相同出生事实产生一致 chart/dayun fingerprint，三个 action 遵守固定 engine 与算法身份；以 contract fixture 验证。
- 可靠性：超时或取消回收整个子进程组，损坏输出无法进入模型结果；以故障注入测试验证。
- 信息安全性：child env 使用 allowlist，birth payload/result 在 trace/history/diagnostics 中投影为脱敏视图；以敏感字段扫描验证。
- 可维护性：protocol、engine source、patch、schema 与 action mapping 由单一 bridge contract 保护；以来源摘要和升级测试验证。

## 实现设计

### 这次要怎么做

先建立完全本地、可重复的 Node bridge protocol 和 fixture，再接入 Python manager 与 builtin。历史时间、地点与 sect 都在 bridge 请求进入 Taibu 前收敛成一次有效公历时间，Marten envelope 保存来源审计事实。

### 功能怎么分工

- Bridge：锁定依赖、时间标准化、Taibu action、canonical renderer、engine/fingerprint/normalizedTime。
- Manager：Node 路径、child env、timeout、输出上限、进程组和协议校验。
- Builtin：JSON Schema、host validation、错误映射、模型视图与脱敏视图。
- Runtime：capability、registration、turn-scoped state 与 observation policy 传播。

### 一步步怎么改

1. 建立 `third_party/taibu_bridge/`、lockfile、来源摘要、许可证、patch 校验和 Node 版本文件。
2. 实现 JSON line protocol、canonical renderer、engine identity、历史时间与 fingerprint fixture。
3. 实现 `BaziBridgeManager` 的 env allowlist、timeout、进程组回收和输出校验。
4. 实现 builtin schema、真实日期/闰月/六十甲子/年份校验和稳定错误 envelope。
5. 接入 runtime state、capability、ToolRegistry、HTTP bootstrap 与 run-scoped tool state。
6. 接入 `sensitive_bazi` agent/tool observation projection 和 diagnostics。
7. 运行 action contract、故障注入、时区、隐私与 focused runtime tests。

## 验证

- 1900 年拒绝，1901 下限和 1919/1940-1949/1986-1991 历史 fixture 通过。
- `chart`、`dayun`、`resolve_pillars` 的 schema、result version、engine、fingerprint 与 normalizedTime 完整。
- timeout、非零退出、多行/损坏/超限输出和 request id mismatch 返回稳定错误并回收进程。
- `TZ=UTC` 与不同宿主时区的固定 corpus 一致。
- birth 时间、地点、坐标、provider key 和完整命盘在日志、trace、history、diagnostics 中零明文命中。

## 执行记录

### C00（2026-07-24）

- 建立 `third_party/taibu_bridge/` Node 22 ESM 测试骨架和 lockfile。
- 建立 `clock`、`true_solar`、`resolve_pillars`、`protocol_errors` 四类共享 fixture manifest。
- 增加 Python 边界测试，确认生产 Bazi 模块尚未创建且 capability catalog 尚未公开 `bazi`。
- 验证：Node 1 项、Bazi 骨架 3 项、runtime/AgentSpec 43 项、Knowledge 75 项全部通过。

### C02-C03（2026-07-24）

- 实现 v1 单行 JSON 协议、三 action 映射、固定 engine/result schema 和 canonical `structuredContent`。
- 实现 `1901-2100`、公历/农历、历史 `Asia/Shanghai` civil time、DST 跳跃/歧义和 UTC+8 有效时间。
- 实现 birth/resolve canonical fingerprint，chart/dayun 共用出生事实标识，过滤 1900 反查候选。
- 修正 Taibu Dayun 近似天数显示，使用同一 Yun 返回精确 `8年9月10天` 与 `2030-12-19 20:51`。
- 验证：完整 Node suite 29 项全部通过，包含三个调用方宿主时区的一致性测试。

### C05（2026-07-24）

- 实现 `BaziBridgeManager` 的绝对 Node/bridge 路径、10 秒 deadline、stdout/stderr 字节上限和 child env allowlist。
- 实现单行 JSON、protocol/request/engine/schema、normalizedTime 和 canonical fingerprint 精确复算校验。
- timeout、取消和输出超限会终止整个进程组；非零、信号、空、多行、损坏输出均返回稳定错误与受限诊断。
- 实现 stderr 出生字段、地点、API Key 与代理凭据脱敏，并验证首次 provider 调用后移除高德 Key。
- 验证：C05 聚焦测试 14/14、RuntimeLoop 回归 98/98、Node 全量 42/42、`compileall` 与 `git diff --check` 通过。

### C06（2026-07-24）

- 实现 `bazi` builtin 的 Draft 2020-12 schema、出生输入校验、三 action 映射、Marten envelope 与坐标隐私投影。
- 接入 capability、ToolRegistry、HTTP runtime state、按 agent 过滤的 capability catalog 与 Bazi readiness diagnostics。
- 增加通用 `sensitive_bazi` observation policy，覆盖 Langfuse、RunHistory、tool summary 和 self-improve evidence。
- 验证：builtin/registration/capability 42/42、敏感观测与 diagnostics 21/21、C05/C06 回归 17/17、Node 全量 42/42 通过。
