# Knowledge/RAG Runtime 选型与演进记录

## 结论

Knowledge 第一版选择本地低内存模型、SQLite FTS5、sqlite-vec、懒加载和显式 reindex。该方案已经进入当前 runtime；现行行为以 `.cs/spec/knowledge-runtime.md`、代码、配置和测试为准。

原 `easysdd/features/2026-05-19-knowledge-rag-runtime/` 的设计、执行计划和选型调研已于 2026-07-28 压缩到本 note、Project Spec 与 Architecture Changelog，旧目录随后删除。

## 初始约束

- 自托管、中文优先、本地可运行。
- 模型文件不进入仓库，默认不在请求中下载模型。
- 任意 agent 通过 namespace 复用同一套入库、检索、引用和诊断能力。
- Knowledge 保存可检索文档；Memory 保存用户偏好与稳定事实。
- Host 负责能力声明、执行、持久化、权限和诊断；何时检索仍由 LLM 决定。
- 第一版不建设 GraphRAG、多模态、网页抓取或外部向量数据库服务。

## 模型选择

### Embedding

默认选择 `BAAI/bge-small-zh-v1.5`：MIT、中文优先、约 24M 参数、512 维，适合长期运行的个人知识库。

评估过但未作为默认值：

| 模型 | 价值 | 未选为默认的原因 |
| --- | --- | --- |
| `BAAI/bge-m3` | 多语言、长文本与多种检索表示 | 约 569M 参数，常驻资源成本高 |
| `Qwen3-Embedding` | 多语言效果上限较高 | 模型与运行资源要求更高 |
| `text-embedding-3-small` | 托管 API 成熟 | 不符合默认自托管边界 |

### Reranker

默认选择 `BAAI/bge-reranker-base`：MIT、中英可用、约 278M 参数，并与 BGE embedding 处于同一生态。只对有限候选做精排。

评估过但未作为默认值：

| 模型 | 价值 | 未选为默认的原因 |
| --- | --- | --- |
| `BAAI/bge-reranker-v2-m3` | 多语言能力更强 | 约 568M 参数 |
| `cross-encoder/ms-marco-MiniLM-L-6-v2` | CPU 成本低 | 英文 MS MARCO 场景优先 |
| weighted rerank | 无模型依赖 | 作为缺模型时的降级路径 |

## 存储与检索选择

默认链路：

```text
SQLite FTS5 -> keyword candidates
sqlite-vec  -> semantic candidates
merge       -> candidate set
reranker    -> final ranking
```

选择 SQLite + sqlite-vec 是因为它与现有 session、memory 和 eval store 的嵌入式部署方式一致，适合本地单实例。曾评估：

| 方案 | 适用升级场景 | 当前未采用的原因 |
| --- | --- | --- |
| Chroma | 快速原型与 collection 生态 | 会增加独立 store 抽象 |
| Qdrant | 服务化、HNSW、快照与量化 | 需要独立服务或容器 |
| LanceDB | 多模态与 Arrow/Lance 数据 | 引入新的数据格式和表抽象 |

## 索引与模型资产边界

- `knowledge_embeddings` 保存 `model_id + dimension + embedding_config_hash`。
- namespace 保存当前 embedding profile 与 config hash，同一 namespace 不混用向量空间。
- Console 允许从配置声明的命名 profile 中选择；切换 profile 时先生成全部新向量，成功后一次性替换，失败保留原索引。
- chunk 参数按上传保存到 source `index_profile`，不会静默改变既有来源。
- 模型位于被忽略的 `data/models/`，adapter 懒加载；`allow_remote_download=false` 是默认值。
- `model_status`、`unload_models` 与 idle TTL 提供模型状态和释放能力。

## 降级策略

- embedding 模型不可用：返回稳定状态；已有 FTS 数据仍可检索。
- sqlite-vec 不可用：向量检索标记 disabled，继续使用 FTS。
- reranker 不可用：使用 weighted rerank。
- profile/config hash 不匹配：返回 config mismatch，并要求 namespace reindex。
- ingest job 中断：进入可诊断的失败终态，不承诺断点续跑。

## 后续演进

第一版只有 TOML 全局参数和手动 reindex。阶段一语料治理迭代随后增加：

- corpus manifest、digest、幂等发布与 drift 报告；
- 真实语料 retrieval eval；
- Knowledge Console、上传预览和全部 chunk 检查；
- 草稿箱、审核发布与正式库；
- 上传级 chunk profile、namespace embedding profile 和单次检索参数试查；
- profile 变更失败时保留原可用索引。

这些演进继续保持通用 KnowledgeService 边界，Bazi 领域逻辑不进入 retriever。

## 外部来源

- [BAAI/bge-small-zh-v1.5](https://huggingface.co/BAAI/bge-small-zh-v1.5)
- [BAAI/bge-reranker-base](https://huggingface.co/BAAI/bge-reranker-base)
- [Qwen3 Embedding/Reranker](https://qwenlm.github.io/blog/qwen3-embedding/)
- [sqlite-vec](https://github.com/asg017/sqlite-vec)
- [Qdrant optimizer](https://qdrant.tech/documentation/concepts/optimizer/)
- [Qdrant quantization](https://qdrant.tech/documentation/guides/quantization/)
- [Matryoshka Representation Learning](https://arxiv.org/abs/2205.13147)

## 当前证据

- `.cs/spec/knowledge-runtime.md`
- `.cs/epics/002-o-knowledge-corpus-quality/spec.md`
- `docs/ARCHITECTURE_CHANGELOG.md`
- `config/knowledge.example.toml`
- `src/marten_runtime/knowledge/`
- `tests/test_knowledge_*.py`
