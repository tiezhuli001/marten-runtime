---
type: issue
status: open
title: Taibu 子初换日窄补丁
created: 2026-07-24
epic: ".cs/epics/001-o-bazi-agent/spec.md"
---

# Taibu 子初换日窄补丁

## 可观察目标

Marten builtin `bazi` 的 `chart`、`dayun` 与 `resolve_pillars` 固定采用 `lunar-javascript` EightChar sect 1：23:00 起使用次日日柱，23:00-00:59 整个子时口径一致。

## 范围

- 在锁定的 `taibu-core@3.4.0` 上维护 `sect1-v1` 窄补丁。
- `bazi` 命盘 EightChar、`bazi_dayun` 原局 EightChar、`bazi_pillars_resolve` 最终候选强校验 EightChar 调用 `setSect(1)`；年、月、日午夜预筛选保持上游实现，最终候选枚举修正子时 `23:00/00:00` 的民用日期映射。
- Bridge engine metadata 使用 `taibu-core-marten@3.4.0-marten.1`，回传 npm `taibu-core@3.4.0` 的 `gitHead=1f7f8920ef2c2b032401427623ac0b9a7496c68d` 与 `patchId=sect1-v1`。
- normalizedTime 与 fingerprint 固定写入 `dayBoundaryPolicy=lunar_javascript_sect1`。
- 保持 `qiyunMethod=lunar_javascript_yun_sect1` 与 `trueSolarAlgorithm=taibu_true_solar_v1`。

## 执行 Chunk

- `C01`：Taibu 供应链与 sect 1 窄补丁。
- 权威步骤、测试命令与完成条件见 `.cs/epics/001-o-bazi-agent/spec.md` 的 `C01`。

## Design

补丁作为 `third_party/taibu_bridge/patches/taibu-core+3.4.0-sect1.patch` 随 Marten 源码和 Docker 构建产物管理。构建脚本校验补丁前文件摘要、应用补丁、校验补丁后摘要并运行边界 fixture。补丁改变三个实际参与 23:00 边界结果的 EightChar，并让反查最终候选把子时 `23:00` 映射到目标日柱前一民用日、`00:00` 映射到当日。午夜年/月/日预筛选由 fixture 证明 sect 1/2 结果一致。Taibu 的历法、真太阳时、神煞、关系和 canonical renderer 实现保持原样。

## 验证

- `1988-02-15 22:59` 保持当日日柱和亥时。
- `1988-02-15 23:00`、`23:30`、`23:59` 使用次日日柱和子时。
- `1988-02-16 00:00` 与前一晚子时使用同一日柱口径。
- `1988-02-15 23:30` 固定为日柱 `辛丑`、时柱 `戊子`。
- `chart` 四柱、`dayun` 原局与 `resolve_pillars` 候选在上述边界完全一致。
- `resolve_pillars` 年、月、日午夜预筛选在 sect 1/2 下产生相同候选集合；最终结果同时包含符合四柱的前一民用日 `23:00` 与当日 `00:00`。
- Bridge 返回 `patchId=sect1-v1`，上游原版结果无法被误标为 Marten patched engine。

## 关闭条件

- 窄补丁、bridge、builtin 映射与三 action fixture 完成并通过。
- 设计文档、计算契约和运行结果中的算法身份一致。
- 上游升级时补丁可重复应用，或由包含等价显式 sect 支持的固定上游版本替代。

## 执行记录

### C01（2026-07-24）

- 精确锁定 `taibu-core@3.4.0`、`lunar-javascript@1.7.7`、npm integrity、engine gitHead 和地点模块来源 commit。
- 增加 `verify:upstream`、`prepare:engine`、原始/补丁后 SHA-256、三份 MIT 许可证和可应用 unified patch。
- 三个 EightChar 行为点采用 sect 1；反查最终候选同时枚举前一民用日 `23:00` 与当日 `00:00`。
- 计划阶段发现的反查子时遗漏已同步修正到设计、Epic 和本 issue。
- 验证：干净 `npm ci` 安装链、幂等补丁、7 项 Node 测试、patch 正反检查和摘要漂移故障注入全部通过。
