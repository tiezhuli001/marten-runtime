# Bazi 排盘计算契约核对

## 结论

Marten 首版排盘以 `taibu-core-marten@3.4.0-marten.1`、`sect1-v1` 窄补丁和锁定的 `lunar-javascript@1.7.7` 为运行权威。真太阳时地点解析复用 Taibu `14860a2` 的 MIT `place-resolution` 模块，由 bundled bridge 通过可替换 provider adapter 调用。外部项目适合发现口径差异；同源 6tail 实现无法形成独立算法多数票。

实现必须固定以下契约：

- 中国出生记录时间通过 `sourceTimeStandard` 区分 `recorded_civil` 与 `beijing_standard`，历史民用时间先归一为 UTC+8。
- 真太阳时有效年月日时从 Taibu 的 `trueSolarTime + dayOffset` 取得，`correctionMinutes` 只用于展示诊断。
- 用户和模型只提交出生地点文本；Bridge 内部解析经纬度，Builtin schema 拒绝公开坐标字段。
- 首版地点 provider 为高德，部署者提供高德 Web 服务 Key。中国大陆行政区是首版地域范围；港澳台与海外、普通省级精度、同名歧义、无结果、非法坐标、provider 不可用和超时均透明失败，保持 `true_solar` 口径并停止排盘。北京、天津、上海、重庆的省级 adcode 作为城市等价精度。
- Bazi timeout、输出上限与 provider 使用代码默认值，secret 从 runtime resolved env 进入显式 child env；子进程采用严格环境 allowlist。
- 同一 run 的 `chart` 与 `dayun` 通过 `turn_tool_state` 复用 canonical 地点解析结果；新 run 重新解析，缓存停留在受控内存边界。
- Node bridge 子进程固定 `TZ=UTC`，消除宿主机历史 DST 对 Taibu 本地 `Date` 运算的影响。
- 日柱固定使用 `lunar_javascript_sect1` 子初换日，起运使用 `lunar_javascript_yun_sect1`；两个算法标识进入 normalizedTime、fingerprint 和 fixture。
- 首版出生与四柱反查范围固定为 `1901-2100`；1900 年上海本地平均时的秒级 UTC offset 超出分钟精度审计字段，统一返回范围错误。
- 四柱、起运和大运序列属于日历事实；五行权重、神煞和关系属于带 engine/version 的派生标注；旺衰、格局与喜用进入理论解释层。

## 触发场景

- 实现或评审 builtin `bazi`、Taibu bridge、时间归一化和 fingerprint。
- 实现或替换地点 provider、变更地点解析版本、坐标系、精度门槛或错误映射。
- 升级 `taibu-core`、`lunar-javascript`、Node runtime 或 Docker 基础镜像。
- 引入命理 README、口诀、案例或外部排盘结果作为 RAG 语料。
- 排查节气边界、历史夏令时、23 点附近、真太阳时跨日和起运日期差异。

## 证据和细节

- Taibu 默认分支截至 2026-07-24 的最新 commit 为 `14860a26e3c428bb9c0a3eee3ba88e7cb57b1e6c`。其中 `packages/mcp-server/src/place-resolution.ts` 属于 MIT `taibu-mcp-server@3.0.0` 源码，使用 `AMAP_WEB_SERVICE_KEY` 调用高德 geocode API，返回标准化地点、行政区编码、级别和经纬度，并把省级结果判为精度不足。
- 高德地理编码使用 Web 服务 Key；请求中的 `key` 为必填参数。Marten 将 endpoint、provider、timeout 与 secret 环境变量名 `AMAP_WEB_SERVICE_KEY` 固定在 provider adapter，不新增 Bazi provider 配置面。
- `taibu-mcp-server` npm 当前发布版本为 `2.0.0`，仓库源码版本为 `3.0.0`。Marten 从固定 commit 复用并适配该模块，记录原文件摘要、来源许可证和本地变更，避免依赖尚未发布的 npm 源码版本。
- 上游地点模块允许手动经纬度优先，并在解析失败后返回 fallback。Marten 产品契约删除公开坐标输入和 fallback 继续计算：用户只提供 `birthPlace`，解析失败返回稳定错误。
- Taibu commit `14860a26e3c428bb9c0a3eee3ba88e7cb57b1e6c` 的真太阳时实现使用 `(longitude - 120) * 4 + equationOfTime`，实际位移按整数分钟执行，返回的 `correctionMinutes` 只保留到 0.1 分钟。
- npm `taibu-core@3.4.0` 的 engine 来源标识为 `gitHead=1f7f8920ef2c2b032401427623ac0b9a7496c68d`。旧设计值 `160fb0eefc495c098237dd3be7afe42d3c590f75` 只修改桌面侧边栏，不能承担 engine provenance。
- Node 目标运行时将 `1900-01-01T00:00:00 Asia/Shanghai` 解析为 `1899-12-31T15:54:17Z`，而 `Date.getTimezoneOffset()` 只能返回 `-485` 分钟；从 1901 年开始使用整分钟 UTC+8。历史 fixture 还需覆盖 1919、1940-1949 与 1986-1991 时制变化。
- Taibu 地点模块把 `省` 判为精度不足。北京 `110000`、天津 `120000`、上海 `310000`、重庆 `500000` 属于省级行政区和城市语义的同一层级，Marten adapter 需要显式作为城市等价精度。
- `lunar-javascript@1.7.7` 默认 EightChar sect 2。固定样例 `1988-02-15 23:30` 在默认口径下得到日柱 `庚子`、时柱 `戊子`；产品确认采用 sect 1 子初换日，结果固定为日柱 `辛丑`、时柱 `戊子`。
- `eightChar.getYun(gender)` 默认 Yun sect 1。固定样例 `2022-03-09 20:51` 男命起运为 `8年9月10天`、`2030-12-19 20:51`；sect 2 为 `8年9月2天`、`2030-12-12 06:51`。
- `lunar-python` 对上述换日和起运样例与 `lunar-javascript@1.7.7` 一致；`china-testing/bazi` 使用 `lunar-python` 的 EightChar/Yun，并自行生成同方向的大运序列。
- `fortune-skill` 锁定 `lunar-javascript@1.7.7`，其时间脚本包含经度差与 DST，当前没有均时差；其 `references/shichen-table.md` 采用 23:00 换日，当前脚本仍使用默认 sect 2。
- Taibu 的 `bazi`、`bazi_dayun` 与 `bazi_pillars_resolve` 都直接取得默认 `EightChar`，当前上游没有调用 `setSect(1)`；Marten 在命盘 EightChar、Dayun 原局 EightChar、四柱反查最终候选强校验 EightChar 三个实际运行点应用 `sect1-v1`。年、月、日午夜预筛选保持上游实现，并由 fixture 证明 sect 1/2 结果一致。
- 真太阳时公式固定为 `taibu_true_solar_v1`，算法标识只承担结果审计与兼容升级识别，不作为用户可选项。
- 地点 fingerprint 固定包含 provider、resolver version、adcode、level、coordinate system 与实际参与计算的经度；原始地点文本和纬度不进入 fingerprint。
- 地点 provider 请求只发送出生地点文本。出生年月日时、性别、咨询内容、session/user 标识和命盘结果保留在 Marten 边界。
- 当前 `build_http_runtime()` 支持独立 `resolved_env`，因此 bridge manager 必须从该映射取 key 并显式构造 child env，保证 `.env`、测试注入和嵌入式启动使用同一配置语义。
- 当前 `RuntimeLoop` 每次工具调用都会创建新的 `tool_context` 字典；共享地点事实需要在 `run()` 局部创建一个 mutable `turn_tool_state`，再把同一对象传入每次调用。
- Taibu 的日序计算使用本地 `Date`。`1988-07-01` 在 `TZ=UTC` 下日序为 183，在 `TZ=Asia/Shanghai` 下受历史 DST 影响得到 182，因此 bridge 需要固定进程时区。
- Taibu 与 `china-testing/bazi`/`fortune-skill` 使用不同的五行权重，数值只能在对应 engine 方法内解释。

## 相关位置

- `docs/2026-07-23-bazi-agent-design.md`
- `STATUS.md`
- `.cs/notes/002-docs-lifecycle-inventory.md`
- `.cs/issues/002-o-taibu-place-resolution.md`
