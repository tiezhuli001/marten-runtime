# Marten Taibu Bridge Protocol v1

The bridge accepts exactly one UTF-8 JSON line on stdin and emits exactly one UTF-8 JSON line on stdout. Diagnostics use stderr.

## Request

Required fields are `protocolVersion="1"`, non-empty `requestId`, `tool`, and object `arguments`. `tool` is one of `chart`, `dayun`, or `resolve_pillars`. Optional `detailLevel` is `default` or `full`. Optional `resolvedPlace` is reserved for the Marten-internal place cache contract.

## Response

Every response contains `ok`, `protocolVersion`, `requestId`, `action`, `resultSchemaVersion`, `engine`, `inputFingerprint`, and `degradedDiagnostics`.

Successful responses contain canonical `structuredContent` and nullable `normalizedTime`. C03 makes birth-action `inputFingerprint` and `normalizedTime` non-null after time normalization. Error responses contain `error.code`, `error.message`, and `error.retryable`.

For `dayun`, the bridge replaces Taibu's approximate day-difference display with the exact `lunar-javascript` Yun `startYear/startMonth/startDay` values and adds `起运信息.起运时间` from `getStartSolar()`.

| Action | Taibu tool | Result schema |
| --- | --- | --- |
| `chart` | `bazi` | `bazi.chart.v1` |
| `dayun` | `bazi_dayun` | `bazi.dayun.v1` |
| `resolve_pillars` | `bazi_pillars_resolve` | `bazi.resolve_pillars.v1` |

`engine` is fixed to `taibu-core-marten`, `3.4.0-marten.1`, source commit `1f7f8920ef2c2b032401427623ac0b9a7496c68d`, and patch `sect1-v1`.
