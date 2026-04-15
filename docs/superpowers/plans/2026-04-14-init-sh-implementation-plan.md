# init.sh Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a repo-root `init.sh` that bootstraps the local Python/runtime environment, checks minimum provider readiness, prints the canonical startup command, and runs a temporary local readiness/diagnostics smoke.

**Architecture:** Keep the harness thin and repo-local. `init.sh` owns only bootstrap + minimum smoke orchestration; it does not become a process manager or a config generator beyond copying safe templates. The smoke runs the existing HTTP runtime entrypoint in a temporary background process, probes `/healthz`, `/readyz`, and `/diagnostics/runtime`, and then always cleans up.

**Tech Stack:** POSIX shell (`bash`), Python 3.11+, pip/venv, unittest, FastAPI runtime endpoints, Markdown docs

---

## Chunk 1: Lock expected behavior with tests

### Task 1: Add script-behavior coverage before implementation

**Files:**
- Create: `tests/test_init_script.py`
- Inspect: `README.md`
- Inspect: `src/marten_runtime/interfaces/http/serve.py`
- Inspect: `src/marten_runtime/interfaces/http/app.py`

- [ ] **Step 1: Write a failing test for template bootstrap behavior**

Cover:
- missing `.env` copies from `.env.example`
- missing `mcps.json` copies from `mcps.example.json`
- existing destination files are preserved

- [ ] **Step 2: Run the targeted test and verify it fails for the expected reason**

Run:
```bash
cd /Users/litiezhu/workspace/github/marten-runtime && PYTHONPATH=src python -m unittest -v tests.test_init_script
```
Expected: FAIL because `init.sh` does not exist yet or required behavior is missing.

- [ ] **Step 3: Write a failing test for provider-readiness classification**

Cover:
- success when `OPENAI_API_KEY` is present
- success when `MINIMAX_API_KEY` is present
- failure when neither is present

- [ ] **Step 4: Write a failing test for startup command output**

Expected output must include:
```text
source .venv/bin/activate
PYTHONPATH=src python -m marten_runtime.interfaces.http.serve
```

- [ ] **Step 5: Write a failing test for smoke endpoints**

Cover:
- successful checks for `/healthz`, `/readyz`, `/diagnostics/runtime`
- non-zero exit if one required endpoint check fails

## Chunk 2: Implement the thin bootstrap script

### Task 2: Create `init.sh` with reusable shell helpers

**Files:**
- Create: `init.sh`
- Test: `tests/test_init_script.py`

- [ ] **Step 1: Add script header, strict shell options, and repo-root resolution**
- [ ] **Step 2: Add helper functions for `OK/WARN/BLOCKED` output**
- [ ] **Step 3: Add environment bootstrap helpers**

Implementation details:
- require `python3`
- create `.venv` when absent
- use `.venv/bin/python -m pip install --upgrade pip`
- install `requirements.txt`
- install editable package with `pip install -e .`

- [ ] **Step 4: Add template-copy helpers**

Behavior:
- copy `.env.example -> .env` only when `.env` is absent
- copy `mcps.example.json -> mcps.json` only when `mcps.json` is absent
- preserve existing files exactly

- [ ] **Step 5: Re-run targeted tests and make the new failures narrower**

Run:
```bash
cd /Users/litiezhu/workspace/github/marten-runtime && PYTHONPATH=src python -m unittest -v tests.test_init_script
```
Expected: remaining failures are now only on readiness/smoke behavior not yet implemented.

### Task 3: Add readiness classification and startup command output

**Files:**
- Modify: `init.sh`
- Test: `tests/test_init_script.py`

- [ ] **Step 1: Read `.env` plus current shell environment for provider keys**
- [ ] **Step 2: Mark missing provider keys as blocking for smoke**
- [ ] **Step 3: Print Feishu / MCP credentials as optional warnings, not blockers**
- [ ] **Step 4: Emit the canonical startup command block**
- [ ] **Step 5: Re-run targeted tests**

Run:
```bash
cd /Users/litiezhu/workspace/github/marten-runtime && PYTHONPATH=src python -m unittest -v tests.test_init_script
```
Expected: readiness and startup-command tests PASS; smoke-specific failures remain if smoke logic is still pending.

## Chunk 3: Implement the temporary local smoke

### Task 4: Add background boot, endpoint probes, and cleanup

**Files:**
- Modify: `init.sh`
- Test: `tests/test_init_script.py`

- [ ] **Step 1: Start the runtime in the background with a temporary `SERVER_PORT` override**

Recommended default:
- use `INIT_SMOKE_PORT` if provided
- otherwise use `18000`

- [ ] **Step 2: Poll the port / endpoint until the server is reachable or a short timeout expires**
- [ ] **Step 3: Probe `/healthz`, `/readyz`, and `/diagnostics/runtime` sequentially**
- [ ] **Step 4: Validate basic payload markers in diagnostics JSON**
- [ ] **Step 5: Add `trap`-based cleanup so the child process is always stopped**
- [ ] **Step 6: Re-run targeted tests to green**

Run:
```bash
cd /Users/litiezhu/workspace/github/marten-runtime && PYTHONPATH=src python -m unittest -v tests.test_init_script
```
Expected: PASS.

## Chunk 4: Document and verify the real path

### Task 5: Update entry docs to point at `./init.sh`

**Files:**
- Modify: `README.md`
- Modify: `README_CN.md`
- Modify: `STATUS.md`

- [ ] **Step 1: Add `./init.sh` as the fastest local bootstrap path in both READMEs**
- [ ] **Step 2: Keep the existing explicit install/run commands as the manual path**
- [ ] **Step 3: Record the implementation + verification result in `STATUS.md`**

### Task 6: Run real verification before claiming completion

**Files:**
- Modify: `STATUS.md`

- [ ] **Step 1: Run targeted automated coverage**

Run:
```bash
cd /Users/litiezhu/workspace/github/marten-runtime && PYTHONPATH=src python -m unittest -v tests.test_init_script tests.test_health_http
```
Expected: PASS.

- [ ] **Step 2: Run the real bootstrap script locally**

Run:
```bash
cd /Users/litiezhu/workspace/github/marten-runtime && ./init.sh
```
Expected: environment bootstrap completes; templates exist; blocking config is assessed; if provider key is configured locally, smoke endpoints pass.

- [ ] **Step 3: If local provider config exists, confirm the smoke reaches all three endpoints**

Expected:
- `/healthz` returns ok
- `/readyz` returns ready
- `/diagnostics/runtime` returns JSON successfully

- [ ] **Step 4: If local provider config is missing, verify the script exits non-zero with explicit corrective guidance**

- [ ] **Step 5: Sync final verification evidence into `STATUS.md`**
