---
kind: issue
title: "Bazi 生产封装与完整评测"
type: feature
status: open
created: 2026-07-24
epic: ".cs/epics/001-o-bazi-agent/spec.md"
---

# Bazi 生产封装与完整评测

## 目标

固定 Docker 镜像、供应链材料、真实 provider smoke、完整 Bazi/Knowledge eval 和数据删除路径共同证明该变化可以进入共享生产 rollout。

## 范围

- 包含：多阶段 Docker、固定 digest/Node major、lockfile、许可证、SBOM、bootstrap、自检、真实高德 smoke、完整 eval、session 删除与运行手册。
- 不包含：Knowledge Console UI、生产 corpus 扩容和长驻 Node worker。

## 归属

- 隶属 Epic：`.cs/epics/001-o-bazi-agent/spec.md`
- 依赖：`001-005` 的实现与 focused tests。

## 质量目标

- 可靠性：镜像启动、自检、bridge/provider/Knowledge 降级与 session 删除路径可重复；以 compose smoke 和故障演练验证。
- 可维护性：engine/place 来源、全部 npm 传递依赖、许可证与 SBOM 可追溯；以构建检查验证。
- 性能效率：记录逐调用 Node 进程延迟、并发与上传资源预算，为 worker 升级提供证据。
- 信息安全性：生产镜像和运行手册保护两个 secret、敏感日志、session 保留与备份删除；以扫描和演练验证。

## 执行 Chunk

- `C11`：Docker、许可证、SBOM 与启动自检。
- `C12`：完整 eval、真实 provider/Operator smoke 与发布质量门。
- 权威步骤、测试命令与完成条件见 `.cs/epics/001-o-bazi-agent/spec.md` 的 `C11-C12`。

## 一步步怎么改

1. 固定 Python/Node Debian family 与 release digest，复制 bridge、Node runtime、依赖和许可证。
2. 生成 SPDX 或 CycloneDX SBOM，校验 engine/place 来源和 lockfile 完整性。
3. 增加 bridge/ICU/timezone/Knowledge/operator startup diagnostics 与 compose health smoke。
4. 扩展 Bazi 与 Knowledge eval，覆盖所有固定边界和高风险失败。
5. 使用真实高德 Key 跑一次受控地点解析 smoke，验证 outbound allowlist 和脱敏。
6. 完成 session 删除、保留周期与备份清理运行手册。
7. 执行 release quality gate，记录逐调用 worker 的性能基线与升级触发。

## 验证

- 干净环境 `docker compose up` 后 health、ready、diagnostics、Bazi clock、true_solar、Knowledge upload/search 全部通过。
- 镜像离线运行排盘无需 npm 下载；许可证和 SBOM 包含所有直接与传递依赖。
- 完整 eval 可以发现 sect、时间、地点、权限、上传恢复、引用、隐私和高风险表达回归。
- session 删除覆盖消息、assistant、tool outcome、compaction、binding 和规定的备份周期。

## 执行记录

- `C11-C12` 实现与自动化验证已完成。最终镜像 ID 为 `sha256:66f8dadf0eeb1b64f8398b6a9d3592655c75a4ddafd39688959c9c9d4be7412d`。
- 构建内 Node bridge 测试 42/42 通过；启动自检确认 `sect1-v1`、历史时区、Knowledge schema 与脱敏配置状态。
- 镜像包含 npm lockfile、三份上游许可证、第三方声明、25 组件 npm CycloneDX SBOM 与 111 组件 Python CycloneDX SBOM。
- 无 Amap/Operator secret 启动时 health/ready/diagnostics 通过，clock 成功，true-solar 返回 `credential_missing`，Operator router 返回 404。
- 测试 Operator token 下鉴权、上传、terminal job 与 hybrid retrieval 通过；默认缺模型配置的可重试失败也已验证。
- `--network none` 的 clock 排盘成功；运行时 provider/operator canary 值未出现在镜像 `/app` 内容中。
- 完整 Python discovery 1441/1441、Bazi 41/41、Knowledge 98/98、runtime/acceptance 52/52、session 生命周期 27/27 通过；Node 42/42、`compileall` 与 `git diff --check` 通过。
- Scripted eval `eval_bazi_agent_20260724143542948036_c7a21d4_0000` 为 5/5、100 分、`passed`。
- 性能基准完成 1 次 warm-up、50 次顺序调用和 8 路并发：顺序 p50/p95 为 `284.94/299.73 ms`，并发 p50/p95 为 `759.49/773.35 ms`，Node 启动 p50/p95 为 `32.98/36.77 ms`，启动占 chart p95 `12.3%`，timeout/orphan 均为 0；长驻 worker 升级条件未触发。
- Session CLI 支持 90 天 preview/apply 清理，精确删除目标 session 及后代的消息、assistant、tool outcome、compaction、binding 与 job；主存储删除后 30 天内清理备份的运行责任已写入部署文档。
- 2026-07-25 使用真实 `AMAP_WEB_SERVICE_KEY` 完成成都武侯区 true-solar smoke：Amap 返回 `adcode=510107`、`level=区县`，bridge 使用 `taibu-core-marten 3.4.0-marten.1` 成功排盘；输出未包含 Key，既有 outbound projection 与敏感观测测试继续通过。
- 真实飞书入站 run `run_dd0651bc` 成功：WebSocket receipt、main agent、企业 `qwen3.6-plus` 与飞书最终回复全部通过。
- 真实合成 Bazi 飞书 run `run_8580caed` 发现 Qwen 将后续工具调用输出为 `<invoke>` 文本；runtime finalization 新增未解析工具标记检测、一次重试与安全恢复，`feishu_card` 协议保持兼容。
- 修复后真实合成 run `run_6029afae` 成功：Bazi、真实 Amap、2 个已向量化 theory chunk、Knowledge `source_id/chunk_id` 引用与飞书投递全部通过，最终文本不含 `<invoke>`。
- 修复后 Python 全量 1444/1444、Node 42/42、runtime recovery 100/100、飞书/Bazi 94/94、`compileall` 与 `git diff --check` 通过。
- 工具效率修复后的历史四柱链为 1 次 Bazi + 1 次 Knowledge search；当前完整四柱分析契约固定为 `resolve_pillars -> dayun -> knowledge.search`，每个 action 一次。
- 最新完整回归为 Python 1451/1451、Node 42/42，`compileall`、`pip check` 与 `git diff --check` 通过。
- 2026-07-26 最终完整回归更新为 Python 1456/1456、Node 42/42；`compileall`、`pip check` 与 `git diff --check` 通过。
- 最终 scripted eval `eval_bazi_agent_20260725161342122313_c7a21d4_0000` 为 5/5、100 分、pass rate 1.0。
- Scripted eval 固定工具参数，用于验证 runtime 编排、计算契约、Knowledge 引用、降级和 grader；出生信息自然语言提取由真实 provider 的农历出生与四柱输入链路验证。
- 变更文件、未跟踪交付文件、报告、日志和 `STATUS.md` 共扫描 1,743 个文件；本地已配置密钥值与通用凭据模式均为 0 命中。

## C12 验收证据矩阵

设计第 10 节共 36 条标准，以下编号按原文顺序：

| 标准 | 验收主题 | 通过证据 |
| --- | --- | --- |
| 1-3 | selected-agent 直达、binding、隔离与共享权限 | `test_agent_specs`、`test_bazi_agent_assets`、`test_runtime_capabilities`、`test_knowledge_runtime_capabilities`；main 自然语言 handoff 由 issue `009` 验证 |
| 4-7 | builtin 来源、action mapping、schema、年份与历史 fixture | Node 42/42；Bazi 41/41；`test_bazi_tool`、`test_bazi_bridge_manager` |
| 8-13 | 地点文本、Amap adapter、稳定错误、地域、secret、run cache | fake Amap contract、直辖市/境外/timeout fixture、child-env 与 provider-call-count 测试 |
| 14-17 | host validation、renderer、bridge envelope、fingerprint | bridge protocol/renderer tests 与 Bazi schema/manager tests |
| 18-22 | civil time、真太阳时、sect/Yun、跨时区、离线运行 | 历史时间 corpus、22:59-00:00 fixture、跨 `TZ` 测试、断网容器自检 |
| 23-24 | Skill 顺序、Theory 引用与案例标识 | `test_bazi_agent_assets`、`test_bazi_acceptance`、Bazi grader 与 5/5 scripted eval |
| 25-26 | Knowledge action/namespace scope 与 readiness | scope denial、family-level `None` readiness、共享 agent 配置测试 |
| 27-30 | Operator API、上传边界、job 恢复、service 复用 | Knowledge 98/98；Operator 镜像 smoke；上传、认证、migration、恢复与并发测试 |
| 31 | session 边界、保留与删除 | session 生命周期 27/27；精确删除演练；90 天保留与 30 天备份清理契约 |
| 32-34 | provider 数据最小化、敏感观测与诊断 | place request projection、Langfuse/history/self-improve 敏感扫描、镜像 secret canary 零匹配 |
| 35 | Docker、Node、依赖、许可证与 SBOM | 镜像自检；三份直接许可证；npm 25/Python 111 组件 SBOM；lockfile 存在 |
| 36 | 回归检测能力 | scripted 编排 eval 5/5、100 分；真实 provider 农历出生与四柱参数提取链路；完整 Python discovery 1456/1456；Node 42/42 |

## 发布质量门

- 结果：`PASS_WITH_RISKS`
- P0/P1：0。
- P2：真实 Bazi run 已降为固定 2 次工具执行和约 35k-36k tokens，端到端仍为 85-92 秒；由 `.cs/issues/007-o-qwen-bazi-tool-efficiency.md` 继续跟踪模型延迟。
- P3：0。
- Operator API 已使用测试 token 完成容器内真实 HTTP 主链，生产 token 只承担部署时 secret 注入。
