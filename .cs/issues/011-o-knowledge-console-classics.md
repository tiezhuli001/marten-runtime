---
kind: issue
title: "经典书籍 Knowledge Console"
type: feature
status: open
created: 2026-07-28
epic: ".cs/epics/002-o-knowledge-corpus-quality/spec.md"
---

# 经典书籍 Knowledge Console

## 目标

Operator 不需要手工拼装 Bearer、multipart 或 reindex 请求，即可通过浏览器完成经典书籍层的上传预览、草稿导入、内容审核、正式发布、job 观察、检索试查、reindex 和显式删除。

## 为什么现在做

当前 `/knowledge/**` API 已经是稳定管理后端，但它只适合测试和脚本。生产语料需要频繁检查来源、许可、篇章、chunk 和索引状态；缺少 UI 会把正确性依赖于手工 API 操作，也难以让非开发者承担内容审核。

## 实现边界

- 使用 FastAPI server-rendered HTML 与少量原生 JavaScript，复用 `eval_routes.py` 已有页面模式；不新增 React/Vue/Vite 工程。
- UI 只调用 `010` 固定的 validate/preview/publish 与现有 list/delete/reindex/search contract，不直接访问 SQLite。
- 使用现有 `KNOWLEDGE_OPERATOR_TOKEN` 登录，服务端恒定时间校验后签发短时 HttpOnly、SameSite operator session；token 不进入 URL、HTML、localStorage、日志和 diagnostics。
- 写操作携带 CSRF token；删除和 namespace reindex 必须二次确认并展示影响范围。
- 首版只支持 `.txt/.md` 与当前 metadata contract，不加入 PDF/Word、网页抓取、多角色审批或富文本编辑。
- `bazi-theory-sandbox` 是经典书籍草稿箱，`bazi-theory` 是 Bazi Agent 检索的正式库；它们表示同一内容流程的两个状态。

## 页面与流程

1. 登录页：输入 Operator token，建立短时管理 session。
2. Namespace 总览：source/chunk/job 数、embedding hash、config mismatch、模型/vector/reranker 状态。
3. Source 列表与详情：title、uri、version、license、provenance、review status、chunk 数、更新时间和 chunk sample。
4. 导入向导：选择文件，可选填写标题和来源链接，确认 preview 与 chunk sample 后保存到草稿箱。
5. 草稿审核：来源详情展示完整 metadata 与 chunks；审核通过后迁移到正式库并从草稿箱移除。
6. 导入任务页面：展示文件读取、chunk、embedding 的进度、terminal status、error code、retryable 和 staging cleanup 状态。
7. 检索试查：输入 query，查看 retrieval mode、vector/rerank status、score parts、source/heading 与正文片段。
8. 运维操作：source reindex、namespace reindex、显式软删除和 drift 提示。

## 目标界面线框

```text
┌─ Knowledge Console ────────────────────────────────────────────────┐
│ Namespace [bazi-theory ▾]   Sources 6  Chunks 42  Jobs 1  [退出] │
├───────────────────────┬────────────────────────────────────────────┤
│ Sources               │ Namespace 状态                            │
│ • 穷通宝鉴 / 月令     │ embedding hash / config mismatch / job    │
│ • 滴天髓 / 通神论     ├────────────────────────────────────────────┤
│ • 神峰通考 / 五行     │ 导入经典                                  │
│                       │ file + 书名/篇章/来源/许可/审核 metadata   │
│ [查看 jobs]           │                         [生成 Preview]     │
│                       ├────────────────────────────────────────────┤
│                       │ 检索试查 [query________________] [Search] │
└───────────────────────┴────────────────────────────────────────────┘

Preview ready：digest、source identity、metadata、chunk sample 与 [Publish]
Source detail：metadata + chunks + [Reindex] + 二次确认后的 [Delete]
错误/降级：稳定 error code、missing model、config mismatch 与 retryable 原样可见
```

- 这是阶段一目标界面；桌面端使用双栏，窄屏按 Sources、状态、导入、检索顺序单栏排列。
- Preview 与 Publish 必须分步，Preview 页面不能产生 source/job；删除与 namespace reindex 必须服务端验证确认值。
- 文案、配色和精确尺寸属于示意，登录态、信息层级、动作共置与错误可见性是稳定约束。

## 验收标准

- 未配置 Operator token 时 Console 不注册；无效登录不能调用任何 KnowledgeService 方法。
- 登录 cookie 不包含原始 token，过期后失效；CSRF 缺失或错误时所有写操作被拒绝。
- Preview 不创建 source/job，publish 使用相同 digest 后才创建 ingest job；重复 publish 显示 unchanged/update 语义。
- UI 能完整展示成功、missing model、config mismatch、job interrupted、upload invalid 和 reindex failure，不吞掉稳定错误码。
- 删除前展示 source title/version/chunk count，并要求显式确认；不存在批量自动删除。
- 浏览器 acceptance 覆盖登录、上传预览、发布、job 完成、检索试查、reindex、删除和 session 过期。

## 依赖

- `.cs/issues/010-o-knowledge-corpus-baseline.md` 的 manifest、preview/publish 与 baseline contract。
- 当前 `/knowledge/**` Operator API、KnowledgeService 与 runtime diagnostics。

## 建议验证命令

```text
PYTHONPATH=src .venv/bin/python -m unittest tests.test_knowledge_console_auth -v
PYTHONPATH=src .venv/bin/python -m unittest tests.test_knowledge_console_routes -v
PYTHONPATH=src .venv/bin/python -m unittest tests.test_knowledge_operator_http tests.test_knowledge_uploads -v
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -p 'test_knowledge_*.py'
git diff --check
```

## 实施结果

- 已交付 `/knowledge/console`：Operator token 登录、短时签名 HttpOnly/SameSite session、CSRF、防 token 泄漏和显式 logout。
- 已交付 namespace/source/job/chunk 浏览、classic upload preview、digest/source identity/chunk sample 确认、publish、检索 diagnostics、source/namespace reindex 与显式删除。
- 经用户验收简化导入表单：仅文件必填，标题和来源链接可选；标题、URI、version、provenance、work、verification status 与 scope 由 Console 推导，License 不再要求用户输入。
- UI 将 Jobs 显示为“导入任务”；每次 Publish 创建一条任务记录，展示 queued/running/completed/failed 状态、进度和错误。
- 已将 `bazi-theory-sandbox` 固定为 UI 草稿箱，上传和 preview 只在草稿箱出现；`bazi-theory` 固定为正式库，Bazi Agent 只检索该 namespace。
- 草稿来源详情提供“审核通过并发布”：复用现有 chunks 和 embedding 写入正式库，追加 approval metadata，成功后从草稿箱移除；导入任务与审核动作各自含义明确。
- Preview 使用 runtime-owned TTL staging，不创建 active source；publish 复用同一 preview digest 和 Operator API/KnowledgeService 路径。
- 非法 namespace 直接返回 `422 KNOWLEDGE_NAMESPACE_INVALID`，回归测试证明不会调用或变更默认 `bazi-theory`。
- 实现与验证已完成，issue 保持 open，等待用户关闭授权。

## 验证证据

- Console auth/routes focused tests 通过，覆盖无效登录不调用 service、cookie/session/CSRF、preview/草稿导入/job/审核发布/正式检索/detail/reindex/delete 与非法 namespace。
- 真实 HTTP smoke 通过 `/healthz`、`/readyz`、Bearer 401 边界、Console 登录 cookie、Dashboard 和 hybrid search。
- In-app browser 已完成登录和检索验收；本地服务继续运行在 `http://127.0.0.1:18080` 供用户测试。
