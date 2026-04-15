#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO_ROOT"

VENV_DIR="${REPO_ROOT}/.venv"
PYTHON_BIN="${VENV_DIR}/bin/python"
SMOKE_PORT="${INIT_SMOKE_PORT:-18000}"
SMOKE_LOG="${REPO_ROOT}/.init-smoke.log"
SERVER_PID=""
SKIP_INSTALL=0
SMOKE_ONLY=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --skip-install)
      SKIP_INSTALL=1
      shift
      ;;
    --smoke-only)
      SMOKE_ONLY=1
      SKIP_INSTALL=1
      shift
      ;;
    *)
      blocked "unknown argument: $1"
      printf 'Usage: ./init.sh [--skip-install] [--smoke-only]\n'
      exit 1
      ;;
  esac
done

section() {
  printf '\n[%s]\n' "$1"
}

ok() {
  printf 'OK  %s\n' "$1"
}

warn() {
  printf 'WARN %s\n' "$1"
}

blocked() {
  printf 'BLOCKED %s\n' "$1"
}

cleanup() {
  if [[ -n "$SERVER_PID" ]] && kill -0 "$SERVER_PID" >/dev/null 2>&1; then
    kill "$SERVER_PID" >/dev/null 2>&1 || true
    wait "$SERVER_PID" 2>/dev/null || true
  fi
}

trap cleanup EXIT

require_python() {
  if ! command -v python3 >/dev/null 2>&1; then
    blocked 'python3 is required'
    exit 1
  fi
}

copy_if_missing() {
  local source="$1"
  local target="$2"
  if [[ -e "$target" ]]; then
    ok "reuse ${target}"
    return 0
  fi
  cp "$source" "$target"
  ok "created ${target} from ${source}"
}

env_value_from_file() {
  local key="$1"
  local env_file="$2"
  if [[ ! -f "$env_file" ]]; then
    return 0
  fi
  python3 - "$key" "$env_file" <<'PY'
import sys
from pathlib import Path

key = sys.argv[1]
env_path = Path(sys.argv[2])
for raw_line in env_path.read_text(encoding="utf-8").splitlines():
    line = raw_line.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    left, right = line.split("=", 1)
    if left.strip() != key:
        continue
    value = right.strip().strip('"').strip("'")
    if value:
        print(value)
    break
PY
}

has_provider_key() {
  local env_file="$1"
  local key=""
  for key in OPENAI_API_KEY MINIMAX_API_KEY; do
    if [[ -n "${!key:-}" ]]; then
      return 0
    fi
    if [[ -n "$(env_value_from_file "$key" "$env_file")" ]]; then
      return 0
    fi
  done
  return 1
}

print_startup_command() {
  section 'Startup Command'
  cat <<'CMD'
source .venv/bin/activate
PYTHONPATH=src python -m marten_runtime.interfaces.http.serve
CMD
}

probe_json_endpoint() {
  local path="$1"
  local mode="$2"
  local url="http://127.0.0.1:${SMOKE_PORT}${path}"
  "$PYTHON_BIN" - "$url" "$mode" <<'PY'
import json
import sys
import urllib.error
import urllib.request

url = sys.argv[1]
mode = sys.argv[2]
with urllib.request.urlopen(url, timeout=2) as response:
    payload = json.load(response)
if mode == "status_ok" and payload.get("status") != "ok":
    raise SystemExit("expected status=ok")
if mode == "status_ready" and payload.get("status") != "ready":
    raise SystemExit("expected status=ready")
if mode == "runtime_diag" and not any(key in payload for key in ("app_id", "llm_profile", "app")):
    raise SystemExit("expected runtime diagnostics markers")
PY
}

wait_for_server() {
  local url="http://127.0.0.1:${SMOKE_PORT}/healthz"
  local _
  for _ in $(seq 1 40); do
    if "$PYTHON_BIN" - "$url" <<'PY'
import sys
import urllib.request
url = sys.argv[1]
try:
    with urllib.request.urlopen(url, timeout=1) as response:
        raise SystemExit(0 if response.status == 200 else 1)
except Exception:
    raise SystemExit(1)
PY
    then
      return 0
    fi
    sleep 0.25
  done
  return 1
}

section 'Environment'
require_python
ok 'python3 detected'

if [[ "$SMOKE_ONLY" -eq 1 ]]; then
  if [[ ! -x "$PYTHON_BIN" ]]; then
    blocked '.venv is required for --smoke-only; run ./init.sh first or provide an existing virtualenv'
    exit 1
  fi
  ok 'reuse .venv'
  ok 'smoke-only mode: skipped bootstrap and install steps'
else
  if [[ ! -d "$VENV_DIR" ]]; then
    python3 -m venv "$VENV_DIR"
    ok 'created .venv'
  else
    ok 'reuse .venv'
  fi

  if [[ "$SKIP_INSTALL" -eq 1 ]]; then
    ok 'skipped dependency installation'
  else
    "$PYTHON_BIN" -m pip install --upgrade pip
    ok 'pip upgraded'
    "$PYTHON_BIN" -m pip install -r requirements.txt
    ok 'installed requirements.txt'
    "$PYTHON_BIN" -m pip install -e .
    ok 'installed editable package'
  fi
fi

section 'Config'
if [[ "$SMOKE_ONLY" -eq 1 ]]; then
  ok 'smoke-only mode: skipped template bootstrap'
else
  copy_if_missing '.env.example' '.env'
  copy_if_missing 'mcps.example.json' 'mcps.json'
fi

if has_provider_key '.env'; then
  ok 'provider credential detected'
else
  blocked 'provider credential missing: set OPENAI_API_KEY or MINIMAX_API_KEY in .env or shell environment'
  print_startup_command
  section 'Next Actions'
  printf '1. Edit .env and set OPENAI_API_KEY or MINIMAX_API_KEY.\n'
  printf '2. Re-run ./init.sh to execute the local smoke check.\n'
  exit 1
fi

if [[ -n "${FEISHU_APP_ID:-}" || -n "$(env_value_from_file FEISHU_APP_ID .env)" ]]; then
  ok 'Feishu credentials present'
else
  warn 'Feishu credentials not configured; live Feishu checks are skipped'
fi

if [[ -n "${GITHUB_PERSONAL_ACCESS_TOKEN:-}" ]]; then
  ok 'GitHub MCP token present in shell environment'
else
  warn 'GitHub MCP token not configured; MCP integrations may stay inactive'
fi

print_startup_command

section 'Smoke Check'
: > "$SMOKE_LOG"
SERVER_PORT="$SMOKE_PORT" PYTHONPATH=src "$PYTHON_BIN" -m marten_runtime.interfaces.http.serve >"$SMOKE_LOG" 2>&1 &
SERVER_PID="$!"

if ! wait_for_server; then
  blocked "runtime failed to start on port ${SMOKE_PORT}; see ${SMOKE_LOG}"
  exit 1
fi
ok "runtime listening on 127.0.0.1:${SMOKE_PORT}"

if probe_json_endpoint '/healthz' 'status_ok'; then
  ok '/healthz'
else
  blocked "/healthz check failed; see ${SMOKE_LOG}"
  exit 1
fi

if probe_json_endpoint '/readyz' 'status_ready'; then
  ok '/readyz'
else
  blocked "/readyz check failed; see ${SMOKE_LOG}"
  exit 1
fi

if probe_json_endpoint '/diagnostics/runtime' 'runtime_diag'; then
  ok '/diagnostics/runtime'
else
  blocked "/diagnostics/runtime check failed; see ${SMOKE_LOG}"
  exit 1
fi

section 'Next Actions'
printf '1. Start the runtime with the command above when you want a long-lived session.\n'
printf '2. Edit .env, mcps.json, and local config/*.toml overrides only as needed.\n'
printf '3. Use /diagnostics/runtime for follow-up local checks.\n'
