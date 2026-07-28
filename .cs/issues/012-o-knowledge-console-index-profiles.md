---
kind: issue
title: "Knowledge Console 索引参数与预览"
type: feature
status: open
created: 2026-07-28
epic: ".cs/epics/002-o-knowledge-corpus-quality/spec.md"
---

# Knowledge Console 索引参数与预览

## 决策状态

- 2026-07-28 用户确认采用“上传级 chunk 参数 + namespace 级 embedding profile”。
- 同一 namespace 不允许混用不同 embedding dimension。

## 目标

参考 `rag-web-ui/rag-web-ui` 的上传、chunk size/overlap、chunk 预览和确认处理流程，让 Operator 在 Console 中安全调整基本 RAG 参数，不直接编辑 TOML 或 SQLite。

## 实现边界

- 上传 preview 支持 `target_chars`、`overlap_chars` 和 `max_chars`，实时返回 chunk 数、长度分布和完整样本。
- chunk 参数随 preview/publish 固定并写入 source 索引 profile，不影响已发布 source。
- embedding provider/model/dimension 属于 namespace 级 index profile，不允许同一 namespace 内按文件混用向量维度。
- embedding profile 变更必须显示影响的 source/chunk 数，经二次确认后对 namespace 全量 reindex；失败保留原可用索引。
- 检索试查支持 `top_k`、`candidate_pool`、FTS/vector/metadata/reranker weights 的临时对照，不立即修改生产默认值。
- 参数范围、overlap 小于 target、weight 归一化和 embedding dimension 一致性由后端校验。

## 验收

- 同一文档使用两组 chunk 参数可预览出可解释的差异，publish 严格使用确认的 profile。
- 非法参数不创建 preview/source/job；预览过期和 digest 不匹配仍被拒绝。
- embedding profile 变更不会产生混合维度或部分新旧索引。
- Console 浏览器验收覆盖参数编辑、chunk 预览、publish、试查和 reindex 失败。

## 不包含

- 任意自定义 Python splitter、在线下载未审核模型、同 namespace 多 embedding 索引、自动生产调参。
- 正式 provider p50/p95 压测；它继续延后到 corpus、索引、检索和输出契约稳定之后。

## 实施结果

- 上传表单支持 `target_chars`、`overlap_chars`、`max_chars`，preview 展示完整 chunks、长度分布和实际 profile。
- chunk profile 随 source metadata 保存，publish 使用 preview 固定的参数。
- 配置支持 `[knowledge.embedding_profiles.<profile_id>]`；namespace 保存 profile id 与 config hash。
- Console 可选择已配置 profile；已有 namespace 不允许通过单文件上传混入不同 profile。
- namespace profile 切换先生成全部向量，成功后一次性替换；失败保持原 profile 和向量。
- 检索试查支持临时 top K、candidate pool 与四项非负权重，后端归一化且不修改默认配置。
- 实现与验证完成，issue 保持 open，等待用户关闭授权。

## 验证证据

- 两组 chunk 参数对同一文档产生可解释的 chunk 数差异。
- profile 切换测试证明旧 hash 向量被替换且新维度一致；缺模型测试证明旧索引保持可用。
- Console/API 测试覆盖非法参数、preview、publish、搜索参数和 reindex profile。
