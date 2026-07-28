export const PROTOCOL_VERSION = "1";

export const ENGINE = Object.freeze({
  name: "taibu-core-marten",
  version: "3.4.0-marten.1",
  sourceCommit: "1f7f8920ef2c2b032401427623ac0b9a7496c68d",
  patchId: "sect1-v1",
});

export const ACTIONS = Object.freeze({
  chart: Object.freeze({
    toolName: "bazi",
    resultSchemaVersion: "bazi.chart.v1",
  }),
  dayun: Object.freeze({
    toolName: "bazi_dayun",
    resultSchemaVersion: "bazi.dayun.v1",
  }),
  resolve_pillars: Object.freeze({
    toolName: "bazi_pillars_resolve",
    resultSchemaVersion: "bazi.resolve_pillars.v1",
  }),
});

export const REQUEST_FIELDS = new Set([
  "protocolVersion",
  "requestId",
  "tool",
  "arguments",
  "detailLevel",
  "resolvedPlace",
]);
