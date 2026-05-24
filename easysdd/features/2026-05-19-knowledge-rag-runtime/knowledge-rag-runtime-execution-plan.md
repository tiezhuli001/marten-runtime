---
doc_type: feature-execution-plan
feature: 2026-05-19-knowledge-rag-runtime
status: draft
summary: 通用 Knowledge/RAG Runtime Capability 的实现推进计划
tags: [knowledge, rag, execution, testing]
---

# Knowledge/RAG Runtime Capability 执行计划

## 1. 完成目标

本计划完成一条可验证闭环：

```text
ingest text source -> chunk -> FTS index -> embedding vector index -> search -> rerank -> cited results -> eval report
```

整体完成标准：

- `knowledge` builtin tool 支持 `ingest_text/ingest_file/ingest_status/cancel_ingest/search/get_chunk/delete_source/reindex/stats`。
- `knowledge_management` skill 说明 Feishu/聊天场景下的知识库操作流程。
- RAG 能力按 `namespace` 隔离。
- Embedding 和 reranker 只从 `config/knowledge.toml` 读取。
- 模型文件不进入仓库，只从 `local_path` 懒加载。
- 切换 embedding 后通过 `knowledge.reindex --namespace xxx` 手动重建。
- 缺模型、缺 sqlite-vec、config mismatch 时有明确诊断和降级行为。
- 单元测试覆盖每个模块边界。
- `knowledge_retrieval` eval 覆盖关键词召回、语义召回、rerank 提升、namespace 隔离、config mismatch、大文件入库进度。
- README / CONFIG_SURFACES / ARCHITECTURE_CHANGELOG 已更新。

未满足任一完成标准时，继续迭代当前阶段；不进入完成汇报。

## 2. 架构原则

### 2.1 简洁边界

新增一个独立子系统：

```text
src/marten_runtime/knowledge/
```

只做通用 RAG Runtime Capability，不放任何领域逻辑。

模块划分：

```text
knowledge/config.py       解析 config/knowledge*.toml
knowledge/models.py       Pydantic 数据模型
knowledge/chunking.py     文本切分
knowledge/sqlite_store.py SQLite + FTS 持久化
knowledge/jobs.py         大文件异步入库 job 与进度
knowledge/embeddings.py   Embedding adapter
knowledge/rerankers.py    Reranker adapter
knowledge/retrieval.py    FTS/vector merge + rerank
knowledge/service.py      对外 service API
```

工具入口：

```text
src/marten_runtime/tools/builtins/knowledge_tool.py
skills/knowledge_management/SKILL.md
```

集成点保持最少：

- `runtime/capabilities.py`：新增 capability declaration。
- `interfaces/http/bootstrap_runtime.py`：初始化 `KnowledgeService`。
- `interfaces/http/runtime_tool_registration.py`：注册 `knowledge` tool。
- `config/knowledge.example.toml`：新增配置模板。

### 2.2 禁止扩散

本阶段不做：

- 领域 agent。
- 网页抓取。
- 外部向量数据库服务。
- 在线平滑切换 embedding（第一版不做）。
- 断点续跑 ingest job。
- host 侧知识库意图识别器。
- 后台 reindex job。
- 自动增量迁移。
- GraphRAG / 多模态 / PDF 复杂解析。

## 3. 实施 chunk 划分

### Chunk 1：配置与模型资产边界

目标：让 runtime 能读取 knowledge 配置，并明确模型文件只来自本地路径。

改动：

- 新建 `src/marten_runtime/knowledge/config.py`
- 新建 `config/knowledge.example.toml`
- `.gitignore` 增加 `data/models/`

边界：

- 只解析配置，不加载模型。
- `allow_remote_download=false` 为默认。
- 模型路径不存在只形成配置状态，不在启动时失败。

单元测试：

- 默认配置可解析。
- `model/local_path/dimension` 缺失时报配置错误。
- `allow_remote_download` 默认 false。
- 本地覆盖 `config/knowledge.toml` 优先于 example。

退出信号：

```text
PYTHONPATH=src .venv/bin/python -m unittest tests.test_knowledge_config -v
```

### Chunk 2：数据模型与 SQLite Store

目标：建立 namespace/source/chunk/embedding/search_run 的持久化基础。

改动：

- 新建 `knowledge/models.py`
- 新建 `knowledge/sqlite_store.py`
- 新增 SQLite schema：`knowledge_sources`、`knowledge_chunks`、`knowledge_namespaces`、`knowledge_embeddings`、`knowledge_search_runs`、`knowledge_chunks_fts`

边界：

- store 不做 embedding。
- store 不做 rerank。
- delete 是软删除。
- 所有查询必须带 namespace。

单元测试：

- source/chunk 写入和读取。
- namespace 隔离。
- soft delete 后 search/get 不返回 deleted chunk。
- FTS 查询只返回 active chunks。
- `knowledge_namespaces.embedding_config_hash` 可更新。

退出信号：

```text
PYTHONPATH=src .venv/bin/python -m unittest tests.test_knowledge_store -v
```

### Chunk 3：Chunking 与 chunk 参数调优

目标：实现中文友好的通用文本切分，并把 chunk size / overlap / batch_size 作为配置化调参入口。

改动：

- 新建 `knowledge/chunking.py`

边界：

- 输入纯文本和 metadata。
- 输出 chunks，不写库。
- 不做小说章节专用解析。
- chunk 参数变化后，用户需要重新 ingest 或 reindex 对应 namespace。
- 不做 PDF/HTML 解析。

单元测试：

- 标题 + 段落切分。
- target_chars / overlap_chars / max_chars / batch_size 从配置生效。
- 长段落按 `target_chars/max_chars` 切分。
- overlap 生效。
- ordinal 连续。
- source metadata 继承到 chunk metadata。
- 空文本返回错误。

退出信号：

```text
PYTHONPATH=src .venv/bin/python -m unittest tests.test_knowledge_chunking -v
```

### Chunk 4：Embedding Adapter

目标：实现 fake embedder 和 BGE adapter，模型懒加载，缺模型可诊断。

改动：

- 新建 `knowledge/embeddings.py`

边界：

- adapter 只负责文本到向量。
- 不写 SQLite。
- 不在 runtime 启动时加载模型。
- 不隐式下载模型。

单元测试：

- fake embedder deterministic。
- BGE adapter local_path 缺失返回 `missing_model`。
- `allow_remote_download=false` 时不触发下载。
- embedding_config_hash 随 model/dimension/local_path 变化。
- 批量 embedding 保持输入顺序。

退出信号：

```text
PYTHONPATH=src .venv/bin/python -m unittest tests.test_knowledge_embeddings -v
```

### Chunk 5：Vector Store Adapter

目标：接入 sqlite-vec，缺扩展时降级到 FTS-only。

改动：

- 在 `knowledge/sqlite_store.py` 增加 vector 写入/查询封装，或新建 `knowledge/vector_store.py`

边界：

- vector store 只存当前 embedding_config_hash 对应向量。
- sqlite-vec 不可用时，不影响 source/chunk/FTS。
- 不接入 Qdrant/Chroma/LanceDB。

单元测试：

- sqlite-vec available 路径：写入、查询 top_k，512 维向量进入 sqlite-vec 索引。
- sqlite-vec unavailable 路径：返回 `vector_status=disabled`。
- sqlite-vec 索引行缺失路径：返回 `vector_status=backend_error` 并提示 `knowledge.reindex --namespace xxx`。
- sqlite-vec 作为轻量嵌入式依赖进入 `pyproject.toml`；缺扩展时保留 FTS-only 诊断路径。
- config_hash 不匹配时不返回旧向量。
- namespace 过滤生效。

退出信号：

```text
PYTHONPATH=src .venv/bin/python -m unittest tests.test_knowledge_vector_store -v
```

### Chunk 6：Reranker Adapter

目标：实现 fake reranker 和 BGE reranker adapter，缺模型时降级 weighted rerank。

改动：

- 新建 `knowledge/rerankers.py`

边界：

- reranker 只对候选排序。
- 切换 reranker 不触发 reindex。
- 缺模型不阻塞 search。

单元测试：

- fake reranker 排序稳定。
- BGE reranker local_path 缺失返回 `missing_model`。
- disabled 时使用 weighted rerank。
- top_n 只重排候选池前 N 条。

退出信号：

```text
PYTHONPATH=src .venv/bin/python -m unittest tests.test_knowledge_rerankers -v
```

### Chunk 7：Retrieval Pipeline

目标：实现 search 主链：FTS + vector + merge + rerank。

改动：

- 新建 `knowledge/retrieval.py`

边界：

- retrieval 不写 source/chunk。
- retrieval 只记录 search_run。
- search 返回引用结果，不生成最终回答。

单元测试：

- FTS-only 正常返回。
- vector-only 正常返回。
- hybrid merge 去重。
- metadata filter 生效。
- config mismatch 返回 `vector_status=config_mismatch`。
- reranker 提升正确候选排名。
- search_run 记录 degraded_reason。

退出信号：

```text
PYTHONPATH=src .venv/bin/python -m unittest tests.test_knowledge_retrieval -v
```

### Chunk 8：KnowledgeService、异步 Ingest Job、Tool 与 Skill

目标：把知识库操作变成 builtin tool，并新增轻量 skill 指导 LLM 在 Feishu/聊天场景正确使用。

改动：

- 新建 `knowledge/jobs.py`
- 新建 `knowledge/service.py`
- 新建 `tools/builtins/knowledge_tool.py`
- 新建 `skills/knowledge_management/SKILL.md`
- 更新 `runtime/capabilities.py`
- 更新 `interfaces/http/bootstrap_runtime.py`
- 更新 `interfaces/http/runtime_tool_registration.py`

边界：

- service 编排 store/chunking/embedding/retrieval；jobs 负责大文件异步入库进度。
- tool 只做参数校验和结果封装。
- skill 只说明操作流程，不执行持久化。
- host 不做知识库意图识别。
- 默认 agent 是否暴露 `knowledge` 由 `config/agents.toml allowed_tools` 控制。

单元测试：

- ingest_text 正常闭环。
- ingest_file 返回 job_id。
- ingest_status 返回 reading/chunking/embedding/completed 进度。
- cancel_ingest 可取消 queued/running job。
- search 正常闭环。
- get_chunk namespace 校验。
- delete_source soft delete。
- reindex 使用当前 `[knowledge.embedding]`。
- missing model 的错误提示可读。
- tool 未在 allowed_tools 时不可见。
- skill 可被加载，正文包含 namespace 缺失追问、引用来源、删除/reindex 确认规则。

退出信号：

```text
PYTHONPATH=src .venv/bin/python -m unittest tests.test_knowledge_service tests.test_knowledge_tool tests.test_runtime_capabilities -v
```

### Chunk 9：Eval Suite

目标：建立 knowledge retrieval 的回归评测。

改动：

- 新增 `evals/suites/knowledge_retrieval.toml`
- 新增 `evals/cases/knowledge_retrieval/*.toml`
- 需要时新增 knowledge family grader

边界：

- eval 使用 fake embedding/reranker 或小型 fixture，避免依赖真实模型下载。
- eval 评估检索行为，不评估最终 LLM 文案。

单元测试 / eval cases：

- 关键词召回。
- 语义召回。
- rerank 顺序提升。
- namespace 隔离。
- config mismatch 提示。
- 大文件入库 job 状态流转。
- delete 后不召回。

退出信号：

```text
PYTHONPATH=src .venv/bin/python -m unittest tests.evals.test_knowledge_retrieval -v
PYTHONPATH=src .venv/bin/python scripts/run_eval.py --suite knowledge_retrieval --mode scripted
```

### Chunk 10：文档与最终验证

目标：让使用者能从 README 找到配置和使用路径。

改动：

- 更新 `README.md`
- 更新 `docs/CONFIG_SURFACES.md`
- 更新 `docs/ARCHITECTURE_CHANGELOG.md`
- 视情况更新 `docs/ARCHITECTURE_EVOLUTION.md`

单元测试 / 验证：

- 配置示例可解析。
- 文档命令与实际 tool action 一致。
- `data/models/` 被 gitignore 忽略。

退出信号：

```text
PYTHONPATH=src .venv/bin/python -m compileall -q src tests scripts/run_eval.py
PYTHONPATH=src .venv/bin/python -m unittest discover -v tests
PYTHONPATH=src .venv/bin/python scripts/run_eval.py --suite knowledge_retrieval --mode scripted
git diff --check
```

## 4. 完成判定

完成必须同时满足：

- 10 个 chunk 退出信号全部达成。
- `knowledge_retrieval` eval 通过。
- 缺模型场景不会导致 runtime 启动失败。
- `knowledge.reindex --namespace xxx` 明确使用当前 `[knowledge.embedding]`。
- 大文件 ingest_file 有 job_id、进度查询、取消和完成/失败状态。
- 第一版 ingest job 不承诺断点续跑。
- chunk size / overlap / batch_size 可配置并有测试。
- 默认路径不下载模型。
- 没有领域 agent 逻辑进入 runtime。
- 不把模型文件提交到代码库。
- 没有 host 侧知识库意图识别器。
- `knowledge_management` skill 只做流程说明，状态变更全部走 builtin tool。
- 没有模型文件进入 git。

任何一项未达成，继续迭代对应 chunk。


## Model unload policy update

- Local embedding/reranker models use lazy loading. Service startup creates adapters only.
- `knowledge.model_status` returns `not_loaded` / `loaded`, `model_id`, `last_used_at`, and `idle_ttl_seconds`.
- `knowledge.unload_models` manually releases embedding and reranker model objects and runs Python/accelerator cache cleanup.
- `model_idle_ttl_seconds` controls automatic unload at knowledge tool boundaries.
- Each knowledge operation checks idle TTL before and after model work.
