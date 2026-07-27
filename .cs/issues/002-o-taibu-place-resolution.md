---
type: issue
status: open
title: Taibu 出生地点解析内置适配
created: 2026-07-24
epic: ".cs/epics/001-o-bazi-agent/spec.md"
---

# Taibu 出生地点解析内置适配

## 可观察目标

Marten builtin `bazi` 的 `true_solar` 输入只接收出生地点文本。Bundled Node bridge 复用 Taibu `14860a2` 的 MIT `place-resolution` 模块，通过首个高德 provider 自动得到内部经纬度；地点解析成功后进入真太阳时计算，失败时返回稳定、可修正或可重试的错误。

## 范围

- 在 `third_party/taibu_bridge/` 复用并适配 Taibu `packages/mcp-server/src/place-resolution.ts`，记录固定上游 commit、原文件摘要、适配点和 MIT 许可证。
- 建立可替换 provider adapter，首版实现 `amap`，通过 `AMAP_WEB_SERVICE_KEY` 和受控 outbound HTTPS 调用。
- 增加代码默认值、runtime state、bridge manager 和脱敏 diagnostics；高德 Key 使用 Web 服务 Key 类型并从 resolved runtime env 注入。
- Builtin schema 只公开 `birthPlace`，拒绝 `longitude`、`latitude` 和其他坐标字段。
- 首版地域固定为中国大陆；港澳台与海外、普通省级精度、同名歧义、无结果、非法坐标、provider 不可用和超时映射为稳定 Bazi 错误码。北京、天津、上海、重庆四个直辖市 adcode 作为城市等价精度通过。
- 解析失败时保持用户选择的 `true_solar` 口径并停止排盘；用户通过补充城市/区县或稍后重试继续流程。
- Bridge 内部地点结果包含 provider、resolver version、标准化地点、adcode、level、coordinate system 与经纬度；精确坐标只用于计算、fingerprint 和一致性校验。
- RuntimeLoop 提供 run-scoped `turn_tool_state`；`chart` 与 `dayun` 复用同一地点解析事实和 fingerprint 字段，同一标准化地点每个 run 只请求 provider 一次。
- Python bridge manager 显式构造 child env，只传播 `TZ=UTC`、必要运行变量和 resolved `AMAP_WEB_SERVICE_KEY`，并保护命令行、stderr、异常与 diagnostics。

## 执行 Chunk

- `C04`：地点 resolver、Amap adapter、地域与直辖市精度。
- `C05`：Python manager 中的 run-scoped 地点 cache、child env 和 `resolvedPlace` 复用。
- 权威步骤、测试命令与完成条件见 `.cs/epics/001-o-bazi-agent/spec.md` 的 `C04-C05`。

## Design

`place-resolution.mjs` 保留 Taibu 的高德 endpoint 与响应解析。Marten 适配层移除上游的手动坐标优先和 fallback 继续执行路径，并增加普通省级精度拒绝、四个直辖市城市等价精度、多候选检测、中国大陆行政区门槛、独立 deadline、稳定错误 envelope、provider version、坐标系声明和敏感观测投影。Endpoint、provider、timeout 与直辖市 adcode 表固定为代码常量，并启用 outbound allowlist 与 redirect 拒绝策略。Provider contract 固定为地点文本输入与 canonical resolution result 输出，后续 provider 通过同一 contract 和 fixture 替换。

`BaziBridgeManager` 以代码常量固定 bridge timeout、地点 timeout、输出上限和首版 provider。高德 adapter 固定使用 `AMAP_WEB_SERVICE_KEY`，避免配置选择其他 runtime secret。Manager 接收 runtime `resolved_env` 并构造最小 child env。run-scoped cache 以 provider、resolver version 和标准化地点为键，缓存成功或失败结果；后续 bridge 请求通过 Marten-internal `resolvedPlace` 复用已校验结果。

## 质量目标

- **功能适宜性**：`true_solar` 仅在地点解析成功后使用已解析经度计算；以 builtin/bridge contract fixture 验证。
- **可靠性**：provider 缺 key、限流、网络故障、超时和非法响应均透明失败，错误码与 `retryable` 稳定；以故障注入测试验证。
- **信息安全性**：provider 请求只包含出生地点文本；日志、trace、history 和 self-improve evidence 不保存原始地点或精确坐标；以字段级观测测试验证。
- **灵活性**：高德实现通过 provider adapter 接入，替换 provider 保持 builtin schema 和 bridge canonical result 稳定；以 fake provider contract test 验证。
- **可维护性**：代码默认值、runtime state、child env、diagnostics 和文档形成单一可追踪链路；以 manager/diagnostics contract tests 验证。

## 验证

- Schema 接受 `birthPlace`，拒绝公开经纬度和未声明坐标字段。
- 城市/区县解析成功并把内部经度传入 `taibu-core`；普通省级结果返回 `bazi_place_precision_insufficient`；`110000/120000/310000/500000` 通过城市等价精度校验。
- 同名地点返回 `bazi_place_ambiguous` 和受限候选；无结果、非法坐标、provider 不可用、限流与超时分别命中稳定错误。
- 港澳台与海外地点返回 `bazi_birth_place_unsupported`，大陆城市和区县通过行政区门槛。
- Key 缺失和 key 无效返回 non-retryable unavailable；限流、网络与服务端故障按 fixture 返回 retryable unavailable。
- 任一地点解析失败都不会使用默认经度或切换到 `clock`。
- `chart` 与 `dayun` 在相同输入下共享 provider、resolver version、adcode、level、coordinate system、resolved longitude 和 fingerprint。
- 同一 run 的相同标准化地点只产生一次 provider 请求；新 run 重新解析；缓存停留在当前 run 内存边界。
- 固定 timeout/输出上限、resolved env 注入和 child env allowlist 通过 contract tests。
- `/diagnostics/runtime.bazi` 只展示脱敏配置状态；secret、地点与经纬度扫描为零命中。
- Outbound 请求体、日志、trace、RunHistory 与 self-improve evidence 通过敏感字段检查。
- `UPSTREAM.md`、许可证、SBOM 和 Docker 产物包含地点解析来源及其传递依赖边界。

## 关闭条件

- Provider adapter、高德实现、固定默认值、run-scoped cache、Builtin/Bridge 契约、稳定错误和隐私投影完成并通过测试。
- 真实主链完成一次出生地点解析、真太阳时排盘、`chart`/`dayun` fingerprint 对齐和脱敏诊断闭环。
- 设计文档、计算审计、运行协议、错误码与实现保持一致。

## 执行记录

### C04（2026-07-24）

- 固定 Taibu 地点源 commit、原文件 SHA-256、MIT 许可证和 Marten 适配边界。
- 实现 NFKC 地点规范化、高德 adapter、GCJ-02 canonical result、大陆 adcode、普通省级拒绝和四直辖市等价精度。
- 实现无结果、歧义、非法坐标、地域越界、凭据、限流、网络、服务端和 deadline 稳定错误。
- 实现内部 `resolvedPlace` 完整复验，以及 true-solar chart/dayun 相同 fingerprint。
- 验证：地点聚焦测试 13/13、Node 全量 42/42 通过。

### C05（2026-07-24）

- 在 `RuntimeLoop.run()` 中创建每个 run 独立、run 内共享的 `turn_tool_state`。
- Python manager 使用 provider、resolver version 与 NFKC/空白规范化地点作为缓存键，缓存成功和地点失败。
- 后续 chart/dayun 通过内部 `resolvedPlace` 复用地点事实，child env 仅在首次 provider 调用时包含高德 Key。
- 验证：两个并发 run 各调用 provider 一次且缓存对象独立；C05 聚焦测试 14/14、Node 全量 42/42 通过。
