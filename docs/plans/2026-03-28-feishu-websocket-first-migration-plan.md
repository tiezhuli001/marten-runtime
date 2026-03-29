# Feishu Websocket-First Migration Plan

> Status: completed on 2026-03-28.

**Goal:** realign the repo to the active docs by making Feishu `websocket-first`, removing webhook-first entry wording from active repo docs, and keeping MCP connection env authoritative in `mcps.json`.

**Architecture:** keep the runtime thin. Feishu inbound uses the official long connection endpoint plus a runtime-owned websocket service, inbound payloads normalize into the standard `InboundEnvelope`, outbound delivery continues through the Feishu message API, and the runtime event contract stays `progress` / `final` / `error`.

**Constraints:** do not re-open the top-level config split, do not add a second workflow layer, do not reintroduce webhook-first as the active baseline, and do not force MCP-specific tokens into `.env` when `mcps.json` already provides them.

## Completed Tasks

- [x] Switch the active Feishu config surface to `connection_mode = "websocket"` with reconnect policy in `config/channels.example.toml` plus optional local `config/channels.toml`.
- [x] Replace webhook-first Feishu entry logic with `FeishuWebsocketService` plus startup/shutdown integration in the HTTP app.
- [x] Keep the resolved Feishu config `[feishu].enabled` and `auto_start` authoritative for runtime startup.
- [x] Remove webhook-only secrets from `.env.example`; keep only `FEISHU_APP_ID`, `FEISHU_APP_SECRET`, and optional `FEISHU_BASE_URL`.
- [x] Lock MCP connection env precedence so literal `mcps.json.env` values beat process env and `$ENV_NAME` remains supported.
- [x] Rewrite Feishu, gateway, acceptance, contract-compatibility, and MCP tests to the websocket-first baseline.
- [x] Sync repo entry docs and config placement docs to the websocket-first baseline.
- [x] Mark the earlier webhook-first plan as historical only.

## Verification

- `PYTHONPATH=src python -m unittest tests.test_feishu tests.test_gateway tests.test_runtime_loop tests.test_acceptance tests.test_contract_compatibility tests.test_mcp -v`
- `PYTHONPATH=src python -m unittest -v`
- `PYTHONPATH=src python -m marten_runtime.interfaces.http.serve`
- `curl -sS http://127.0.0.1:8000/healthz`
- `curl -sS http://127.0.0.1:8000/diagnostics/runtime`

## Result

- Active repo docs and code now agree that Feishu MVP ingress is websocket-first.
- `config/platform.example.toml [server].public_base_url` is no longer presented as a Feishu prerequisite.
- `mcps.json` remains the live MCP connection layer, while `config/mcp.example.toml` remains the published governance template.
