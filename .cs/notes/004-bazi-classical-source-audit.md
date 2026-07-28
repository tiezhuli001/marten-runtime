# Bazi 古籍语料来源审计

## 审计范围

- `ml8s/liki`：`f1b35076fa799312d052696b6e226abf52089918`
- README“参考”列出的 10 个项目
- 审计日期：2026-07-26

## 结论

第三方 skill 适合作为选题线索。古籍正文从固定 revision 的公共古籍来源独立核验后进入 `bazi-theory`，并采用“古籍原文短引 + Marten 释义 + 来源元数据”的结构。

| 项目 | 发现 | 许可或来源状态 | 处理 |
| --- | --- | --- | --- |
| `ml8s/liki` | `bazi/knowledge` 含格局、调候、旺衰等现代方法文档，缺少逐条篇章与原文链接 | MIT | 仅作主题线索 |
| `weizeW/mingli-skills` | 八字目录以流程和 harness 为主 | 仓库根目录未发现许可证 | 仅作流程线索 |
| `jinchenma94/bazi-skill` | `references/classical-texts.md` 含九书摘要和若干疑似口诀，缺少版本、篇章与原文链接 | MIT | 仅作选题线索 |
| `dzcmemory-web/bazi-ziwei-skill` | 以综合分析 prompt 为主 | MIT | 无古籍候选 |
| `shizhilya/yuan` | 八字参考以结构化分析配置为主 | 仓库根目录未发现许可证 | 无古籍候选 |
| `hhszzzz/taibu` | divination skill 以工具工作流为主 | skill 位于仓库 AGPL 范围 | 无古籍候选 |
| `ai-freer/fortune-skill` | vendored `china-testing/bazi` 含《子平真诠》《穷通宝鉴》等长文本 | PolyForm Noncommercial；上游 `china-testing/bazi` 未声明许可证 | 仅作来源线索 |
| `yanouyuan-bit/bazi-roundtable` | 格局、调候、盲派文档属于现代方法整理 | MIT | 仅作方法线索 |
| `DestinyLinker/MingLi-Bench` | 评测数据为主 | MIT | 无古籍候选 |
| `2021291696/high-confidence-mingli-skill` | 置信度与分析工作流为主 | MIT | 无古籍候选 |

## 已纳入材料

| 古籍 | 篇章 | 固定来源 | 内容边界 |
| --- | --- | --- | --- |
| 《穷通宝鉴》 | 论甲木·三春甲木 | Chinese Wikisource `oldid=2294674` | 一句调候原文；原文吉凶措辞不转写为现实事实 |
| 《滴天髓》 | 格局论；贵贱贫富吉凶寿夭论 | Chinese Wikisource `oldid=844363` / `844408` | 格局与财气流通短引；Marten 释义补足适用条件 |
| 《神峰通考》 | 病药说类 | Chinese Wikisource `oldid=1378606` | 病药歌诀短引；Marten 释义说明同篇定义与现实边界 |
| 《渊海子平》 | 论日为主；论月令 | Chinese Wikisource `oldid=2593607` | 规范化精选原文与 Marten 释义 |
| 《子平真诠评注》 | 论用神 | Chinese Text Project `ctp:wb631975` | 固定本地 digest 的精选原文，不宣称版本完整 |
| 《三命通会》 | 卷十·看命口诀 | Chinese Wikisource `oldid=761703` | 四库全书转录的精选短引与 Marten 释义 |

当前 release 已覆盖六本子平核心书目，但每本只有已审核篇章的 Markdown 精选短引，不是全书 TXT，也不宣称全文覆盖。

## 2026-07-28 全文资源复核

### 用户提供的 GitHub 仓库

| 仓库或文件 | 核验结果 | 入库判断 |
| --- | --- | --- |
| `mymmsc/books` 中上海会文堂印局民国十二年《子平真诠》扫描本 | 仓库没有 LICENSE，README 说明文件来自网络收集；仓库公开不构成开源授权。该 1923 年古籍版本本身可按公版扫描底本处理，但 PDF 是无文本层的竖排影印本 | 可从扫描底本重新 OCR 并审核后入库，不能直接沿用仓库中未授权的现代整理文本 |
| `liang996-tech/Bazi-Books/06-盲派` | 仓库没有 LICENSE，也没有随仓库提供的生产再发布授权；目录主要是段建业、杨清娟、夏仲奇等近现代资料 | 不进入 production corpus；用户另行确认允许本地非商用测试后，可隔离导入 sandbox |

“可以下载”与“开源”不是同一授权状态。近现代资料即使托管在公开 GitHub 仓库，也不能据此进入可部署的 production RAG 语料；本地测试授权只适用于隔离的 sandbox。

### 《子平真诠》1923 年扫描本 OCR 验证

- 固定文件 SHA-256：`daaa92400e9234467b9d0b0396c631245c6f76d28362fc8bda5cb779d55d4031`
- 规模：92 个 PDF 页面，约 6.2 MB；每个 PDF 页面含两个竖排书页，无文本层。
- 验证过整页竖排 OCR、半页 OCR、macOS Vision OCR，以及单列裁切后旋转为横排的 Tesseract OCR。
- 最佳单列样本仍有明显漏字、错字和首尾误识别，不能满足“内容正确”的生产语料要求；未批量生成或导入未经审校的全文。

后续获得可靠 OCR 与逐章审核结果后，应建立新的 corpus release，通过 manifest 发布；不得直接修改 SQLite，也不得以现有精选短引冒充全文。

### 本地 sandbox 导入

用户于 2026-07-28 确认上述盲派资料允许下载并用于本地非商用测试。运行时据此建立独立 namespace `bazi-theory-sandbox`，不加入 `bazi-theory` manifest，也不进入 Bazi Agent 的 production namespace：

- `Bazi-Books/06-盲派` 固定 revision `58a9d4a2067f0f864d5d0d2c4d7267abb95b1afc`：15 条来源。
- `mymmsc/books` 固定 revision `588cbb0925dc7e19eaf1da5364706b9bffa6a397`：导入《子平真诠》本义 DOC 1 条；未重复导入该目录的《渊海子平》副本。
- Word 和有文本层的 PDF 采用文本提取；任付红 2017 笔记、杨清娟 244 页资料、段建业 2016 讲义采用 OCR，并标记 `ocr_unreviewed`。
- 原始导入产生 16 个 completed ingest jobs。整书去重后删除较短的《盲师断命轶例集》汇总版本，当前为 15 个 active sources、792 个 chunks；Console 保留 16 条 Jobs 作为导入历史。
- 三个检索样本分别命中《子平真诠》本义、杨清娟 244 页资料和夏仲奇命例，检索模式为 `hybrid_rerank`。

2026-07-28 增加 namespace 级检索评估后，sandbox 的量化结果为：

- 15 sources、792 chunks、约 68 万 indexed chunk characters；最大来源杨清娟资料占 35.61% chunks。
- 3 个未审校 OCR 来源共 429 chunks，占 54.17%；这是当前主要质量风险，语料总量本身不是风险。
- 0 对完全重复 chunks，跨来源相似度不低于 0.90 的近重复为 0。
- 23 个来源识别与自然语言查询：Recall@1 `0.9130`、Recall@3/5 `1.0`、MRR `0.9565`、引用 metadata 完整率 `1.0`，无空结果。
- 两个正确来源排第二的查询分别是“四墓库”与“十天干方位颜色”；第一名也是讲述同主题的相关盲派资料，属于来源竞争而非无关召回。
- 1 个 forbidden-source case 来自任付红同作者资料进入 Top 5；该查询的正确来源仍排第一。

评估入口为 `scripts/eval_knowledge_namespace.py`，gold set 为 `evals/cases/knowledge_corpus/bazi_theory_sandbox_v1.json`，报告为 `reports/knowledge/bazi-theory-sandbox-local-20260728/summary.md`。

### 六本核心古籍

| 古籍 | 可用全文来源 | 实测规模 | 入库判断 |
| --- | --- | ---: | --- |
| 《穷通宝鉴》 | [Chinese Wikisource](https://zh.wikisource.org/w/index.php?title=%E7%A9%B7%E9%80%9A%E5%AE%9D%E9%89%B4&oldid=2294674) | 1 页，约 100 KB wikitext | 可从固定 revision 采集并保留 CC BY-SA 归属 |
| 《滴天髓》 | [Chinese Wikisource](https://zh.wikisource.org/wiki/%E6%BB%B4%E5%A4%A9%E9%AB%93) | 42 个正文子页，约 57 KB wikitext | 可逐章固定 revision 采集 |
| 《神峰通考》 | [Chinese Wikisource](https://zh.wikisource.org/w/index.php?title=%E7%A5%9E%E5%B3%B0%E9%80%9A%E8%80%83&oldid=1378606) | 1 页，约 453 KB wikitext | 可从固定 revision 采集 |
| 《渊海子平》 | [Chinese Wikisource](https://zh.wikisource.org/w/index.php?title=%E6%B7%B5%E6%B5%B7%E5%AD%90%E5%B9%B3&oldid=2593607) | 1 页，约 173 KB wikitext | 可从固定 revision 采集 |
| 《三命通会》 | [Chinese Wikisource 四库全书本](https://zh.wikisource.org/wiki/%E4%B8%89%E5%91%BD%E9%80%9A%E6%9C%83_(%E5%9B%9B%E5%BA%AB%E5%85%A8%E6%9B%B8%E6%9C%AC)) | 12 卷，约 1.47 MB wikitext | 可逐卷固定 revision 采集 |
| 《子平真诠评注》 | [Chinese Text Project](https://ctext.org/wiki.pl?if=gb&chapter=974137&remap=gb) | 411 条正文行，约 27,455 字 | 全文可读，但 CText 站点条款不是全站统一的可再发布授权；全量入库前需获得许可或换用授权明确的公版底本 |

结论：不需要寻找来源不明的 TXT 或扫描 PDF。前五本可用 MediaWiki API 直接获取固定 revision，规范化为 Markdown 后建立新 corpus release；《子平真诠评注》暂不从无许可 GitHub 镜像或商业站点复制全文。

### 三套近现代盲派资料

| 资料 | 网上发现 | 授权判断 |
| --- | --- | --- |
| 《段氏理象学：盲派命理研究》 | 有正式出版物：段建业，中国商业出版社，2011-12，ISBN `9787504474575`；可购买纸书/电子书，也存在非官方扫描 PDF | 仍在版权期；非官方扫描不可入库，需版权方或作者授权 |
| 杨清娟盲派系列 | 可找到“六亲断法”PDF、案例集、课程视频和整理笔记，但主要来自资源售卖站、文档分享站和转载 | 未发现官方开放授权、可核验出版信息或允许 RAG 复制的条款；不可入库 |
| 夏仲奇盲派案例 | 可找到《命术轶闻——夏仲奇卜命遗例集》/《夏仲奇卜命遗例集》的 PDF、DOC 和大量转载，常归于段建业、邢铭芬整理 | 未找到可验证的开放授权，且网上版本存在内容真实性和版本差异争议；不可入库 |

近现代资料当前只保留书目和授权线索。购买个人阅读权不等于获得复制、向量化和部署权。

## 目标 production theory 书目

当前清单是后续完善 `bazi-theory` 的采集与审核范围，不表示这些材料已经入库，也不授予复制、扫描或保存正文的许可。

子平核心限定为六本：

- 《渊海子平》
- 《子平真诠》
- 《穷通宝鉴》
- 《滴天髓》及可追溯注本
- 《三命通会》
- 《神峰通考》

盲派目标资料限定为三套：

- 《段氏理象学》
- 杨清娟盲派系列资料
- 夏仲奇盲派系列资料

古籍采用可追溯的固定公共版本，原文、历代注释与 Marten 释义分开保存。近现代盲派资料入库前必须核验正式书名、作者、出版社或发布方、版次、章节或页码、授权依据和审核状态；命例还必须完成来源与隐私审核。无法确认授权时只保留书目记录，不保存正文、扫描件、网络整理本或第三方摘要。

## 语料规则

1. 古籍条目必须记录 `work`、`chapter`、`edition_or_source`、固定 `source_url`、`verification_status`、`license` 和 `provenance`。
2. 原文与 Marten 释义使用独立标题。
3. 现代摘要使用 Marten 标题，引用区明确显示其整理稿身份。
4. 第三方项目中的现代录入、注释和摘要按项目许可证处理；来源链含混的材料仅保留为线索。

## 相关位置

- `docs/2026-07-23-bazi-agent-design.md`：RAG 设计、namespace、目标书目与 source metadata 契约。
- `.cs/epics/001-o-bazi-agent/spec.md`：Bazi Agent 与 Knowledge 引用闭环的当前受管理变化。
- `.cs/issues/005-o-bazi-agent-rag-vertical-slice.md`：最小许可 theory fixture 与真实主链证据。
