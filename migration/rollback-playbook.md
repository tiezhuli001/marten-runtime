# Rollback Playbook

## Trigger

- Feishu inbound unavailable
- acceptance suite fails after cutover
- blocking regression in core case

## Actions

1. Stop expanding new traffic
2. Switch primary traffic back to old system
3. Preserve logs, failed cases, `run_id`, `trace_id`, and external trace refs
4. Update STATUS.md

## Verification

- old system takes new traffic
- failed case reproducible
- new incidents stop growing
