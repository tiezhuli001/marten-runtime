# init.sh Design Spec

## Goal

Add a repo-root `init.sh` that gets a new operator or agent from fresh checkout to a verified local runtime baseline quickly, without turning the script into a long-lived process manager.

The script should optimize for the narrow active chain in this repository:

`local setup -> runtime boot -> /healthz -> /readyz -> /diagnostics/runtime`

## Why This Exists

`marten-runtime` already documents install, config, and run steps, but a new agent still has to manually stitch together:

- Python environment creation
- dependency install
- template config copy
- minimum config readiness judgment
- canonical startup command discovery
- first local smoke verification

The missing piece is a harness-style executable entry path that proves “this repo can run here” instead of only describing how it should run.

## Non-Goals

This script does **not**:

- provision secrets or external accounts
- rewrite committed runtime config under `config/*.toml`
- manage a long-lived dev server session
- prove live Feishu or live MCP integrations
- replace deeper verification suites or operator runbooks

## User Experience

From repo root:

```bash
./init.sh
```

Expected flow:

1. create or reuse `.venv`
2. install Python dependencies
3. create missing local templates (`.env`, `mcps.json`)
4. check whether minimum provider config exists
5. print the canonical startup command
6. if minimum config is ready, boot the runtime briefly and probe local diagnostics endpoints
7. stop the temporary runtime process and print next actions

## Functional Requirements

### 1. Environment bootstrap

The script must:

- require `python3`
- create `.venv` if missing
- upgrade `pip`
- install `requirements.txt`
- install the package in editable mode (`pip install -e .`)

The script should be safe to rerun.

### 2. Local template bootstrap

The script must create missing local files by copying public-safe templates:

- `.env.example -> .env`
- `mcps.example.json -> mcps.json`

If the destination already exists, leave it untouched and report reuse.

### 3. Minimal readiness classification

The script must classify local readiness into two levels:

- **blocking**: required to perform local runtime smoke
- **non-blocking**: optional for richer integrations, but not required for minimum local boot

Blocking for this script:

- at least one provider API key exists in `.env` or the current shell environment:
  - `OPENAI_API_KEY`
  - `MINIMAX_API_KEY`

Non-blocking examples:

- Feishu credentials
- GitHub MCP token
- local config override files under `config/*.toml`

If no provider key is found, the script must skip smoke and exit non-zero with an actionable message.

### 4. Canonical startup command

The script must print the main supported startup command using the repo’s current runtime entrypoint:

```bash
source .venv/bin/activate
PYTHONPATH=src python -m marten_runtime.interfaces.http.serve
```

The script may also print the equivalent `uvicorn` command as secondary reference if useful, but only one command should be presented as canonical.

### 5. Local smoke run

If blocking config is ready, the script must:

- start the runtime in the background on a local port
- wait for the HTTP listener to come up
- probe:
  - `/healthz`
  - `/readyz`
  - `/diagnostics/runtime`
- validate that the probes return successful HTTP responses and expected basic payload markers
- terminate the background runtime before exit

The smoke is a local harness check, not a live integration proof.

## Operational Design

### Port selection

The script should prefer a deterministic local smoke port that does not mutate the user’s config. Recommended behavior:

- default smoke port: `18000`
- allow override with `INIT_SMOKE_PORT`
- pass `SERVER_PORT` only to the temporary process environment

This keeps smoke isolated from any operator-default local port such as `8000`.

### Process cleanup

The script must trap shell exit and always attempt to stop the background runtime process. A failed smoke must not leave a stray server process behind.

### Diagnostics checks

The diagnostics probe should only validate a narrow minimum contract, such as:

- endpoint reachable
- JSON decodes successfully
- payload contains top-level runtime metadata like `app_id`, `llm_profile`, or equivalent resolved runtime fields

The script should avoid overfitting to large diagnostics payload details.

## Output Contract

The script output should stay short and scan-friendly, grouped into five sections:

1. `Environment`
2. `Config`
3. `Startup Command`
4. `Smoke Check`
5. `Next Actions`

Each line should clearly show one of:

- `OK`
- `WARN`
- `BLOCKED`

## Failure Model

### Exit 0

Return success only when:

- environment bootstrap completed
- required local templates exist
- blocking readiness is satisfied
- local smoke probes passed

### Exit non-zero

Return failure when any of these happens:

- `python3` missing
- dependency installation failed
- required template copy failed
- no provider key is available
- temporary runtime failed to start
- any required smoke endpoint check failed

When failing, the script must print the exact next corrective action.

## Verification Strategy

Implementation should be verified in two layers:

1. **Automated tests** for script behavior and output classification
2. **Local execution smoke** against the real repo runtime

Suggested automated coverage:

- template copy behavior when files are absent vs already present
- provider-readiness pass/fail classification
- startup command emission
- diagnostics smoke pass path and failure path
- cleanup behavior on background process termination

## File Impact

Expected repo changes:

- create `init.sh`
- create or extend tests covering the script
- update `README.md` and `README_CN.md` to reference `./init.sh` as the fastest local bootstrap path
- update `STATUS.md`

## Acceptance Criteria

This design is complete when:

1. `./init.sh` can be run from repo root on a fresh local checkout
2. it creates/reuses `.venv`, `.env`, and `mcps.json`
3. it clearly reports whether minimum provider config is ready
4. it prints the canonical startup command
5. it performs a temporary local boot and successfully checks `/healthz`, `/readyz`, and `/diagnostics/runtime`
6. it exits non-zero with actionable guidance if minimum provider config is missing or smoke fails
7. repo docs point new agents/operators to `./init.sh` as the fastest startup path
