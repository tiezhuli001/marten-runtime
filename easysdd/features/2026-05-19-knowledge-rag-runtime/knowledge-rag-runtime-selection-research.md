# Knowledge RAG Runtime 技术选型调研

## 结论

第一版采用“低内存默认模型 + 本地模型目录 + 手动重建索引 + 模型可卸载”的方案。

推荐默认配置：

```text
Embedding: BAAI/bge-small-zh-v1.5
Reranker: BAAI/bge-reranker-base
Vector store: SQLite + sqlite-vec
Text index: SQLite FTS5
```

选择低内存默认组合的原因：个人助手需要长期运行，模型常驻内存成本优先级高。`BAAI/bge-small-zh-v1.5` 约 24M 参数、512 维，适合中文小说和个人知识库的第一版默认 embedding。`BAAI/bge-reranker-base` 约 278M 参数，是 BGE 系列中更轻的中英 reranker，作为可配置精排模型。

## 1. 已有调研输入

已有文档：`/Users/litiezhu/docs/ytsd/工作学习/AI学习/大模型基础概念/Embedding 嵌入模型解析.md`。

该文档给出的决策树：

- API 场景：`text-embedding-3-small`。
- 自托管预算优先：`bge-small-zh-v1.5`。
- 自托管效果优先：`Qwen3-Embedding-8B`。

本项目约束：

```text
自托管 + 中文优先 + 本地可运行 + 模型开源 + 可按 namespace 复用 + 个人助手长期运行
```

因此默认选择自托管低内存路线。

## 2. Embedding 模型

### 推荐默认：BAAI/bge-small-zh-v1.5

选择理由：

- MIT license。
- 中文优先，适合中文小说和个人知识库。
- 24M 参数，磁盘约 95.8MB。
- 512 维，向量存储和 sqlite-vec 检索成本低。
- 本地 CPU/MPS 运行压力明显低于 BGE-M3。

### 候选对比

| 模型 | 优势 | 成本 | 结论 |
|---|---|---|---|
| BAAI/bge-small-zh-v1.5 | 中文轻量、512 维、MIT | 效果上限低于大模型 | 推荐默认 |
| BAAI/bge-m3 | 多语言、长文本、dense/sparse/multi-vector | 569M 参数，内存压力高 | 质量优先候选 |
| Qwen3-Embedding-0.6B/4B/8B | 新一代多语言强模型，Apache 2.0 | 资源要求更高 | 效果优先候选 |
| text-embedding-3-small | API 稳定、价格低 | 闭源外部服务 | 当前默认排除 |

## 3. Reranker 模型

### 推荐默认：BAAI/bge-reranker-base

选择理由：

- MIT license。
- 中英双语，适合中文检索精排。
- 278M 参数，低于 bge-reranker-v2-m3。
- 与 BGE embedding 同生态。
- reranker 只处理 top 10~30 候选，作为可配置质量增强。

### 候选对比

| 模型 | 优势 | 成本 | 结论 |
|---|---|---|---|
| BAAI/bge-reranker-base | 中英可用，BGE 生态，约 278M 参数 | 比 MiniLM 大 | 推荐默认 |
| BAAI/bge-reranker-v2-m3 | 多语言更强 | 约 568M 参数，内存压力高 | 质量优先候选 |
| cross-encoder/ms-marco-MiniLM-L-6-v2 | 约 22M 参数，CPU 友好 | 英文 MS MARCO 场景为主 | 英文低内存候选 |
| weighted rerank | 无模型依赖，速度快 | 排序质量较弱 | 降级路径 |

## 4. 向量库 / FTS 边界

FTS5 是全文倒排索引，负责关键词召回。sqlite-vec 是 SQLite 向量检索扩展，负责 embedding 语义召回。

第一版检索链路：

```text
SQLite FTS5  -> keyword retrieve
sqlite-vec   -> vector retrieve
hybrid merge -> candidate merge
reranker     -> final ranking
```

### 推荐：SQLite + sqlite-vec

选择理由：

- 与项目现有 SQLite session、memory、eval store 风格一致。
- 本地嵌入式部署，运维成本低。
- `sqlite-vec` 支持 Python 安装。
- `sqlite-vec` 支持 float/int8/binary vectors、metadata、auxiliary、partition key columns。
- namespace 隔离可通过 SQLite 字段和 vec partition key 实现。

### 业界选型对比

| 方案 | 定位 | 优势 | 成本 | 本项目判断 |
|---|---|---|---|---|
| SQLite + sqlite-vec | 嵌入式 SQLite 向量扩展 | 轻量、本地、和现有 SQLite 路径一致 | pre-v1，有变更风险；集群能力弱 | 第一版默认 |
| Chroma | AI 应用向量库 | collection/metadata/hybrid 生态友好 | 引入独立 store 抽象 | 原型候选 |
| Qdrant | 生产级向量数据库 | HNSW、payload index、hybrid、HTTP/gRPC、snapshots、quantization | 需要服务或容器 | 服务化升级候选 |
| LanceDB | 嵌入式/云一体向量数据库 | vector/full-text/hybrid、多模态、Arrow/Lance 生态 | 新数据格式和表抽象 | 多模态候选 |

## 5. 重建向量成本与成熟做法

### 成本判断

重建向量成本与 chunk 数量、模型大小、硬件、batch size 成正相关。

粗略公式：

```text
reindex_time ≈ chunk_count / embedding_throughput_per_second
```

对个人知识库，成本可接受；对小说库、批量资料库，重建可能从分钟级增长到小时级。

### 成熟做法

1. **早期选长期模型**：项目第一版直接使用 bge-small-zh-v1.5，降低后续更换 embedding 空间的概率。
2. **模型版本化**：`knowledge_embeddings` 记录 `model_id + dimension + embedding_config_hash`。
3. **namespace 记录 embedding_config_hash**：namespace 创建或首次 ingest 时记录 当前 embedding 配置。
4. **手动 reindex**：切换 embedding 模型后显式执行 `knowledge.reindex --namespace xxx`。
5. **查询时明确提示**：当前 namespace 记录 embedding_config_hash 与配置目标不一致时，search 返回 `vector_status=config_mismatch` 和 reindex 命令提示。
6. **第一版控制复杂度**：不做双索引在线迁移、不做后台 reindex job、不做自动增量迁移、不混用旧模型向量。
7. **维度截断/Matryoshka**：作为后续优化候选；第一版不实现。
8. **量化**：作为后续向量库优化候选；第一版不实现。

### 结论

当前阶段推荐一步到位使用 bge-small-zh-v1.5 作为默认 embedding 模型。它比 bge-small 成本更高，但可降低未来模型迁移和 reindex 概率。第一版只支持手动 reindex，不支持在线平滑切换。

## 6. 模型资产加载策略

模型文件不进入代码库。仓库只提交配置模板、adapter 代码和 fake 模型测试实现。

推荐目录：

```text
data/models/embeddings/BAAI/bge-small-zh-v1.5/
data/models/rerankers/BAAI/bge-reranker-base/
```

`.gitignore` 增加：

```text
data/models/
```

配置示例：

```toml
[knowledge.embedding]
enabled = true
provider = "flag_embedding"
model = "BAAI/bge-small-zh-v1.5"
local_path = "data/models/embeddings/BAAI/bge-small-zh-v1.5"
dimension = 512
allow_remote_download = false

[knowledge.reranker]
enabled = true
provider = "flag_embedding"
model = "BAAI/bge-reranker-base"
local_path = "data/models/rerankers/BAAI/bge-reranker-base"
allow_remote_download = false

缺失处理：

| 场景 | 行为 |
|---|---|
| embedding 未配置 | 写 source/chunks/FTS，返回 `embedding_status=disabled` |
| embedding 本地路径缺失 | 返回 `embedding_status=missing_model`，提示配置 `local_path` 或关闭 embedding |
| search 需要 vector 且模型缺失 | 退化为 `retrieval_mode=fts_only`，结果带 `degraded_reason` |
| reranker 未配置 | 使用 weighted rerank，返回 `rerank_status=disabled` |
| reranker 本地路径缺失 | 使用 weighted rerank，返回 `rerank_status=missing_model` |
| 用户显式要求 vector-only 且模型缺失 | 返回 `KNOWLEDGE_EMBEDDING_MODEL_MISSING` |

第一版 `allow_remote_download=false`，避免 runtime 请求中隐式下载大模型。后续可增加显式下载命令。

## 7. 设计修订建议

- `knowledge_embeddings` 记录 `model_id`、`dimension`、`embedding_config_hash`。
- `knowledge.search` 返回 `embedding_status`、`vector_status`、`rerank_status`、`retrieval_mode`、`degraded_reason`。
- 增加手动命令 `knowledge.reindex --namespace xxx`。
- namespace 记录当前 `embedding_config_hash`。
- eval 覆盖关键词召回、语义召回、rerank 排序提升、namespace 隔离、config mismatch 提示。
- 第一版不做双索引在线迁移、后台 reindex job、自动增量迁移。

## 8. 来源

- BAAI/bge-small-zh-v1.5 model card: https://huggingface.co/BAAI/bge-small-zh-v1.5
- BAAI/bge-reranker-base model card: https://huggingface.co/BAAI/bge-reranker-base
- BAAI/bge-small-zh-v1.5 model card: https://huggingface.co/BAAI/bge-small-zh-v1.5
- BAAI/bge-reranker-base model card: https://huggingface.co/BAAI/bge-reranker-base
- Qwen3 Embedding/Reranker official blog: https://qwenlm.github.io/blog/qwen3-embedding/
- sqlite-vec GitHub: https://github.com/asg017/sqlite-vec
- Qdrant optimizer docs: https://qdrant.tech/documentation/concepts/optimizer/
- Qdrant quantization docs: https://qdrant.tech/documentation/guides/quantization/
- OpenAI embedding shortening docs: https://openai.com/index/new-embedding-models-and-api-updates/
- Matryoshka Representation Learning paper: https://arxiv.org/abs/2205.13147
