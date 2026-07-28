---
kind: issue
title: "Knowledge 生产语料清单与检索基线"
type: feature
status: open
created: 2026-07-28
epic: ".cs/epics/002-o-knowledge-corpus-quality/spec.md"
---

# Knowledge 生产语料清单与检索基线

## 目标

用 `bazi-theory` 建立第一套领域无关、可审计、可重复的 corpus release 与 validate/preview/publish contract，并在不先改模型或检索算法的前提下产出真实 corpus retrieval baseline，为 Knowledge Console 和后续调优提供稳定后端。

## 范围

- 包含：manifest contract、source digest、metadata validator、validate/preview、dry-run/publish、coverage matrix、gold query set、离线 retrieval report。
- 包含：复用 Operator API/KnowledgeService、幂等更新、drift 报告、现有 synthetic eval 回归。
- 不包含：Console UI 实现（由 issue `011` 承接）、自动删除、case corpus、模型迁移、正式 live provider p50/p95。

## 现状如何工作

当前 Operator upload 接受 reviewed `.txt/.md` 与通用 metadata，KnowledgeService 按 namespace、`uri + version` 和 source id 完成入库；chunker识别 Markdown 标题，retriever使用 FTS/vector/hybrid rerank。现有 fixture 与 eval 证明能力 contract，但没有 production corpus release 标识、全量 digest 清单、真实查询集和逐版本质量报告。

## 最小设计

1. 先定义 manifest 与报告 contract，不新增数据库表；release id、digest 和扩展 metadata 优先保存在受版本控制的 manifest 与现有 source metadata 中。
2. Validator、preview 与 publisher 作为 operator workflow，调用现有 HTTP/service contract，不直接写 SQLite。
3. Import 默认 additive/idempotent；manifest 缺失的线上 source 只报告 drift，删除必须显式执行。
4. Baseline 固定当前 BGE/sqlite-vec/FTS 配置；先测量，再决定是否调整 chunking、candidate pool、weights 或 reranker。

## 执行步骤

1. 盘点 `bazi-theory` 目标书目与当前 fixture，建立 source/篇章/许可/审核覆盖矩阵。
2. 固定 manifest required/optional 字段、release id、digest 和 source identity 规则。
3. 实现 validator、preview、dry-run 与幂等 publish，并覆盖错误、重复、preview digest 和 drift 行为。
4. 建立真实 corpus gold set，固定 expected source/heading、替代证据与禁止来源。
5. 扩展 retrieval grader/report，输出版本绑定的 Recall@K、MRR、首条命中、引用完整率和失败样本。
6. 在空数据库重放一次 approved fixture release，重复执行验证无漂移，并运行现有 Knowledge/Bazi 回归。

## 验收标准

- 同一 manifest 连续 dry-run/publish 两次，第二次全部为 unchanged，source/chunk/digest 统计一致。
- Preview 返回 encoding、digest、metadata、source identity、chunk count 与有限 chunk sample，但不创建 active source；publish 必须匹配 preview digest。
- 缺 metadata、非 reviewed、digest mismatch、重复 identity、非法 namespace 和不可读取文本均在写库前失败。
- Manifest 不会导致隐式删除；drift 项提供 source id、uri/version 与明确 Operator 后续动作。
- 每个 gold case 都能在报告中看到 query、expected evidence、actual rank、retrieval mode、vector/rerank status 和 source/heading 证据。
- Baseline 报告绑定 corpus release id、Knowledge config hash、model ids 和代码 commit。
- 现有 `knowledge_retrieval` scripted eval、Knowledge 单元测试与 Bazi 引用回归保持通过。

## 产品确认

- 第一 release 的具体篇章范围和 completeness 表述。
- corpus owner、reviewer 与 release approver。
- 近现代材料的授权依据；未确认材料只保留书目，不进入 active source。

## 建议验证命令

```text
PYTHONPATH=src .venv/bin/python -m unittest tests.test_knowledge_corpus_manifest -v
PYTHONPATH=src .venv/bin/python -m unittest tests.evals.test_knowledge_corpus_grader -v
PYTHONPATH=src .venv/bin/python scripts/run_eval.py --suite knowledge_retrieval --mode scripted --profile openai_gpt_5_4
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -p 'test_knowledge_*.py'
PYTHONPATH=src .venv/bin/python -m unittest tests.test_bazi_theory_fixture tests.evals.test_bazi_family_grader -v
git diff --check
```

## 实施结果

- 已实现 manifest schema、digest/metadata validator、plan/publish、drift 报告和基于现有 KnowledgeService 的幂等发布；manifest 外 source 不自动删除。
- 已实现 publisher 缺向量检测：新增或更新 source 若 embedding 未完成则发布失败；内容 unchanged 但当前 embedding 缺失时自动 reindex 修复。
- 已固定 `bazi-theory-classics-selected-v1`：六个 reviewed selected source、12 chunks、12 个 gold cases；不宣称六本经典全文覆盖。
- 已生成候选代码树绑定报告 `reports/knowledge/bazi-theory-classics-selected-v1/summary.md`；评测拒绝 manifest 外 drift，报告同时记录 base commit、候选树 SHA256、逻辑数据库快照、manifest/gold digest、模型与 config hash。
- 实现与验证已完成，issue 保持 open，等待 production owner/reviewer/approver 明确和用户关闭授权。

## 验证证据

- 隔离真实 BGE/sqlite-vec/hybrid-rerank：12/12 cases，Recall@1/3/5、MRR、首来源、引用完整率和 heading match 全部 1.0；空结果和禁止来源命中为 0。
- 空库 publish：6 sources、12 chunks、12 embeddings；第二次全部 unchanged；清空 embedding 后全部通过 reindex 恢复；显式删除后 manifest republish 恢复。
- 2026-07-28 经用户授权，通过 Operator API 显式删除本地 `bazi-theory` 的 9 个 manifest 外旧 source；当前 release plan 为 6 unchanged、0 drift，namespace 为 6 sources / 12 chunks。
- Corpus focused tests、Knowledge regression、Bazi fixture/grader 与 scripted `knowledge_retrieval` eval 均通过；最终全量回归记录在 `STATUS.md`。

## 完成后的下一步

先执行 `.cs/issues/011-o-knowledge-console-classics.md`，让 UI 只调用本 issue 固定的 contract。随后基于 baseline 失败切片决定是否建立检索调优 issue；若当前配置已满足质量门，则直接进入 release/reindex/rollback 演练。
