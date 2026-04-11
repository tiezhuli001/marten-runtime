# Documentation Slimming Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 收敛 `marten-runtime` 的公开阅读路径，归档阶段性设计/执行文档，减少 README / docs index / architecture summaries / STATUS 的重复与冲突。

**Architecture:** Active docs 只保留长期 source-of-truth；阶段性设计、执行计划、审计和 closure 资产进入 archive；本地 continuity 与公开架构事实分离。

**Tech Stack:** Markdown、repo-local docs archive、existing ADR/changelog structure

---

## Unified Kickoff Prompt For Coding Agents

This plan is about making documentation truth clearer and smaller, not about preserving every artifact ever written.

Protect these project goals:
- **LLM + agent + MCP + skill first**
- **harness-thin, policy-hard, workflow-light**
- **厚 ChangeLog，薄 Archive，极简 Active Docs**

Your allowed moves:
- tighten active reading paths
- summarize durable truth into changelog/evolution docs
- remove or archive redundant process documents
- make source-of-truth boundaries explicit

Your forbidden moves:
- do not blanket-archive every historical doc
- do not delete historical docs before preserving durable truth
- do not remove `README_CN.md` or `docs/ARCHITECTURE_EVOLUTION_CN.md`
- do not treat `STATUS.md` as a public architecture source
- do not let archive become a graveyard for every plan/execution note

Execution discipline:
- summary first, archive/delete second
- preserve timeline truth in `ARCHITECTURE_CHANGELOG.md`
- preserve current-architecture readability in `ARCHITECTURE_EVOLUTION*.md`
- keep archive intentionally small
- if a historical doc no longer adds unique value after summarization, remove it

---

## Documentation Strategy Decision

This plan follows one explicit repo policy:

> **厚 ChangeLog，薄 Archive，极简 Active Docs**

Interpretation:
- the primary carrier for architecture evolution truth is `docs/ARCHITECTURE_CHANGELOG.md`
- `docs/ARCHITECTURE_EVOLUTION*.md` remains the reader-first summary of the current architecture
- archive is allowed only as a narrow evidence backstop, not as the default home for every historical branch document
- a historical doc should be absorbed into changelog / evolution first, then deleted unless it still carries unique decision context that cannot be reasonably compressed

### Decision Rules For Historical Docs

For every dated design / execution / branch document, apply these checks in order:

1. **Does it contain key decision rationale that is not already preserved in `ARCHITECTURE_CHANGELOG.md`?**
2. **Did it define a boundary that is still active in the current architecture?**
3. **Could a future maintainer still understand this evolution using only `README` + `docs/README.md` + `ARCHITECTURE_EVOLUTION*.md` + `ARCHITECTURE_CHANGELOG.md` + ADRs?**

Decision policy:
- if **(1 = no)** and **(2 = no)** and **(3 = yes)**:
  - delete after updating references
- if **(1 = yes)** or **(2 = yes)**:
  - first summarize the durable truth into `ARCHITECTURE_CHANGELOG.md`
  - then either:
    - archive only if the original still carries unique evidence value
    - or delete if the summary is sufficient

### Target End State

**Active docs should converge toward:**
- `README.md`
- `README_CN.md` (only if Chinese entry remains intentionally supported)
- `docs/README.md`
- `docs/ARCHITECTURE_EVOLUTION.md`
- `docs/ARCHITECTURE_EVOLUTION_CN.md` (only if bilingual maintenance is still intentional)
- `docs/ARCHITECTURE_CHANGELOG.md`
- `docs/CONFIG_SURFACES.md`
- `docs/LIVE_VERIFICATION_CHECKLIST.md`
- `docs/architecture/adr/`

**Archive should be minimal, not comprehensive.**

Preferred archive contents:
- a very small number of first-wave or turning-point design docs
- documents whose detailed rationale would be too lossy if collapsed into changelog bullets

The repo should **not** keep large numbers of:
- stage execution plans
- closure notes
- branch evolution plans
- superseded implementation plans
- historical docs that only restate conclusions already captured in changelog/evolution

---

## Active docs target surface

**Keep as active path:**
- `README.md`
- `README_CN.md`（已确认长期保留）
- `docs/README.md`
- `docs/ARCHITECTURE_EVOLUTION.md`
- `docs/ARCHITECTURE_EVOLUTION_CN.md`（已确认长期保留）
- `docs/ARCHITECTURE_CHANGELOG.md`
- `docs/CONFIG_SURFACES.md`
- `docs/LIVE_VERIFICATION_CHECKLIST.md`
- `docs/architecture/adr/`

**Archive candidates:**
- `docs/2026-04-09-next-branch-evolution-design.md`
- `docs/2026-04-09-next-branch-evolution-execution-plan.md`
- `docs/2026-04-09-next-branch-evolution-stage-2-blueprint.md`
- `docs/2026-04-09-next-branch-evolution-stage-2-execution-plan.md`

**Likely keep-at-most-a-few historical originals:**
- `docs/2026-03-29-private-agent-harness-design.md`
- optionally one other turning-point design such as `docs/2026-03-31-progressive-disclosure-llm-first-capability-design.md`

Everything else should justify itself against the decision rules above.

Progress note (2026-04-11):
- active dated design docs were tightened further: conversation-lanes/provider-resilience and self-improve originals were deleted after summary-first consolidation
- the remaining active dated docs are now limited to turning-point/current-reference items such as private harness, progressive disclosure, and Feishu generic card protocol
- link drift checks passed after deleting the two absorbed historical docs; active docs now keep only three dated originals

**Decision-required item:**
- `STATUS.md`
  - confirmed policy: it is a **local ignored continuity file** for coding agents to recover project progress/context/state
  - it must not be treated as repository source of truth
  - public architectural truth must stay in changelog / evolution / ADR docs

---

## Chunk 1: Tighten the reading path first

### Task 1: Remove duplicated navigation and summary text from active entry docs

**Files:**
- Modify: `README.md`
- Modify: `README_CN.md`
- Modify: `docs/README.md`
- Modify: `docs/ARCHITECTURE_EVOLUTION.md`
- Modify: `docs/ARCHITECTURE_EVOLUTION_CN.md`
- Modify: `docs/ARCHITECTURE_CHANGELOG.md`

- [x] **Step 1: Identify repeated summary blocks**

Run:
```bash
cd /Users/litiezhu/workspace/github/marten-runtime && rg -n "thin harness|workflow platform|source of truth|current scope|Architecture Evolution|Docs Index" README.md README_CN.md docs/README.md docs/ARCHITECTURE_EVOLUTION.md docs/ARCHITECTURE_EVOLUTION_CN.md docs/ARCHITECTURE_CHANGELOG.md
```
Expected: 找到重复叙述区域。

- [x] **Step 2: Rewrite entry responsibilities**

Recommended responsibility split:
- `README.md`: 项目定位 + 快速开始 + docs 入口
- `docs/README.md`: active docs 索引 + reading order + archive policy
- `ARCHITECTURE_EVOLUTION*.md`: reader-first 架构故事
- `ARCHITECTURE_CHANGELOG.md`: append-only 时间序事实

- [x] **Step 3: Verify link integrity after rewriting**

Run:
```bash
cd /Users/litiezhu/workspace/github/marten-runtime && python - <<'PY'
from pathlib import Path
for path in ['README.md','README_CN.md','docs/README.md','docs/ARCHITECTURE_EVOLUTION.md','docs/ARCHITECTURE_EVOLUTION_CN.md','docs/ARCHITECTURE_CHANGELOG.md']:
    text = Path(path).read_text(encoding='utf-8')
    assert 'docs/' in text or 'README' in path
print('ok')
PY
```
Expected: `ok`

- [ ] **Step 4: Commit entry-path tightening**

```bash
git add README.md README_CN.md docs/README.md docs/ARCHITECTURE_EVOLUTION.md docs/ARCHITECTURE_EVOLUTION_CN.md docs/ARCHITECTURE_CHANGELOG.md
git commit -m "docs: tighten active reading path"
```

---

## Chunk 2: Archive branch-phase documents that no longer belong to the active path

### Task 2: Move dated evolution execution docs under `docs/archive/`

**Files:**
- Move: `docs/2026-04-09-next-branch-evolution-design.md`
- Move: `docs/2026-04-09-next-branch-evolution-execution-plan.md`
- Move: `docs/2026-04-09-next-branch-evolution-stage-2-blueprint.md`
- Move: `docs/2026-04-09-next-branch-evolution-stage-2-execution-plan.md`
- Modify: `docs/archive/README.md`
- Modify: `docs/README.md`

- [x] **Step 1: Move files without editing content first**

Run:
```bash
cd /Users/litiezhu/workspace/github/marten-runtime && \
mkdir -p docs/archive/branch-evolution && \
mv docs/2026-04-09-next-branch-evolution-design.md docs/archive/branch-evolution/ && \
mv docs/2026-04-09-next-branch-evolution-execution-plan.md docs/archive/branch-evolution/ && \
mv docs/2026-04-09-next-branch-evolution-stage-2-blueprint.md docs/archive/branch-evolution/ && \
mv docs/2026-04-09-next-branch-evolution-stage-2-execution-plan.md docs/archive/branch-evolution/
```
Expected: 文件移动成功。

- [x] **Step 2: Update active index and archive index**

Required updates:
- `docs/README.md` 不再把这些文件列为 Start Here
- `docs/archive/README.md` 明确新增 `branch-evolution/` 分组

- [x] **Step 3: Preserve the essential conclusions in active docs**

Before finishing, confirm active docs still retain:
- explicit fast-path deviations / exit conditions（通过 `ARCHITECTURE_EVOLUTION*` + `ARCHITECTURE_CHANGELOG.md`）
- Stage 2 seam principles（若仍必要，可在 changelog/evolution 中保留摘要）
- enough timeline truth that future maintainers do not need the original branch docs for normal understanding

- [x] **Step 3.5: Apply the historical-doc decision rules instead of blanket archiving**

For each moved file, explicitly mark one result:
- `archive_kept_for_unique_context`
- `absorbed_then_delete`
- `delete_as_redundant_process_doc`

Expected: archive remains intentionally small rather than becoming a graveyard for every branch artifact.

- [x] **Step 4: Run docs path verification**

Run:
```bash
cd /Users/litiezhu/workspace/github/marten-runtime && python - <<'PY'
from pathlib import Path
for path in [
    'docs/README.md',
    'docs/archive/README.md',
    'docs/archive/branch-evolution/2026-04-09-next-branch-evolution-design.md',
    'docs/archive/branch-evolution/2026-04-09-next-branch-evolution-stage-2-blueprint.md',
]:
    assert Path(path).exists(), path
print('ok')
PY
```
Expected: `ok`

- [ ] **Step 5: Commit doc archiving**

```bash
git add docs
git commit -m "docs: archive branch evolution execution docs"
```

---

## Chunk 3: Resolve the `STATUS.md` source-of-truth conflict

### Task 3: Make continuity local-only or clearly archival

**Files:**
- Modify/Delete: `STATUS.md`
- Modify: `docs/README.md`
- Modify: `docs/ARCHITECTURE_CHANGELOG.md`
- Optional Create: `docs/archive/status/README.md`

- [x] **Step 1: Preserve any public-worthy facts before changing `STATUS.md`**

Check whether anything in `STATUS.md` is missing from:
- `docs/ARCHITECTURE_CHANGELOG.md`
- `docs/ARCHITECTURE_EVOLUTION.md`
- `docs/archive/README.md`

- [x] **Step 2: Apply the confirmed `STATUS.md` policy**

Confirmed:
- stop treating `STATUS.md` as active repo truth
- keep it as a local ignored continuity file for coding agents
- do not move its role into public docs except for a short policy note

- [x] **Step 3: Apply the chosen outcome**

Preferred commands:
```bash
cd /Users/litiezhu/workspace/github/marten-runtime && git rm STATUS.md
```
Or, if preserving snapshot:
```bash
cd /Users/litiezhu/workspace/github/marten-runtime && mkdir -p docs/archive/status
```
Expected: repo no longer presents `STATUS.md` as active source of truth.

Progress note (2026-04-11):
- repository tracking already moved away from `STATUS.md`
- `.gitignore` ignores `STATUS.md`
- public policy now lives in `docs/README.md` and `docs/ARCHITECTURE_CHANGELOG.md`
- local ignored `STATUS.md` remains allowed for coding-agent continuity only

- [x] **Step 3.5: Preserve the Chinese reading path**

Verify that slimming does **not** remove:
- `README_CN.md`
- `docs/ARCHITECTURE_EVOLUTION_CN.md`

Expected: bilingual docs remain part of the intentional active reading path.

- [x] **Step 4: Update the docs that mention STATUS policy**

Verify:
- `docs/README.md`
- `docs/ARCHITECTURE_CHANGELOG.md`
- root `README.md` if it references continuity

- [ ] **Step 5: Commit the continuity-policy change**

```bash
git add README.md docs STATUS.md .gitignore
git commit -m "docs: resolve status file source-of-truth conflict"
```

---

## Chunk 4: Final verification for documentation slimming

- [x] **Step 1: Rebuild the active docs inventory**

```bash
cd /Users/litiezhu/workspace/github/marten-runtime && find docs -maxdepth 2 -type f | sort
```
Expected: active docs 面更小，dated execution docs 已迁入 archive。

- [x] **Step 2: Verify archive index and active index are consistent**

Run:
```bash
cd /Users/litiezhu/workspace/github/marten-runtime && python - <<'PY'
from pathlib import Path
text = Path('docs/README.md').read_text(encoding='utf-8')
archive = Path('docs/archive/README.md').read_text(encoding='utf-8')
assert 'branch-evolution' in archive
assert '2026-04-09-next-branch-evolution-design.md' not in text
print('ok')
PY
```
Expected: `ok`

- [x] **Step 3: Do a final manual reading-path review**

Review order:
1. `README.md`
2. `docs/README.md`
3. `docs/ARCHITECTURE_EVOLUTION.md`
4. `docs/ARCHITECTURE_CHANGELOG.md`
5. `docs/archive/README.md`

Expected: 新读者无需阅读 dated branch docs 也能理解当前架构。

- [x] **Step 4: Verify that archive stayed minimal**

Run:
```bash
cd /Users/litiezhu/workspace/github/marten-runtime && find docs/archive -maxdepth 3 -type f | sort
```
Expected:
- archive contains only a narrow set of files with unique evidence value
- most historical process docs have either been summarized into changelog/evolution or removed

Progress note (2026-04-11):
- moved `/Users/litiezhu/workspace/github/marten-runtime/docs/2026-04-09-fast-path-inventory-and-exit-strategy.md` into `/Users/litiezhu/workspace/github/marten-runtime/docs/archive/branch-evolution/`
- deleted `/Users/litiezhu/workspace/github/marten-runtime/docs/2026-03-30-conversation-lanes-provider-resilience-design.md` after confirming its durable truth already lived in ADR 0001 + `ARCHITECTURE_CHANGELOG.md` + `ARCHITECTURE_EVOLUTION*.md`
- deleted `/Users/litiezhu/workspace/github/marten-runtime/docs/2026-03-30-self-improve-design.md` after confirming its durable truth already lived in ADR 0003 + `ARCHITECTURE_CHANGELOG.md` + `ARCHITECTURE_EVOLUTION*.md`
- updated active-doc references in `ARCHITECTURE_CHANGELOG.md` and `ARCHITECTURE_EVOLUTION*.md` so the document remains reachable as archive evidence but is no longer part of the active docs surface
- applied the branch-doc decision rules one step further:
  - kept `2026-04-09-next-branch-evolution-design.md` and `2026-04-09-next-branch-evolution-stage-2-blueprint.md` as the narrow unique-evidence set
  - deleted `2026-04-09-next-branch-evolution-execution-plan.md` and `2026-04-09-next-branch-evolution-stage-2-execution-plan.md` as redundant process docs after their durable truth had already been absorbed into active changelog/evolution docs


Progress note (2026-04-11 / final closure):
- re-checked the active docs entry path after the historical-doc deletions / moves and the result remained `missing=[]`
- active docs root remains reduced to three dated originals:
  - `docs/2026-03-29-private-agent-harness-design.md`
  - `docs/2026-03-31-progressive-disclosure-llm-first-capability-design.md`
  - `docs/2026-04-01-feishu-generic-card-protocol-design.md`
- historical truth continues to live primarily in `docs/ARCHITECTURE_CHANGELOG.md`, `docs/ARCHITECTURE_EVOLUTION*.md`, and ADRs, with `docs/archive/branch-evolution/` kept as a narrow evidence backstop rather than a bulk graveyard
- for the 2026-04-11 documentation-slimming baseline, no required cleanup item remains open

- closure re-check: fresh live `/messages` verification on port `8006` also passed for plain / builtin `time` / builtin `runtime` / MCP `get_me` / skill load.
