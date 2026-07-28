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
| 《滴天髓》 | 格局论 | Chinese Wikisource `oldid=844363` | 一句格局原文；Marten 释义补足适用条件 |
| 《神峰通考》 | 病药说类 | Chinese Wikisource `oldid=1378606` | 病药歌诀短引；Marten 释义说明同篇定义与现实边界 |

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
