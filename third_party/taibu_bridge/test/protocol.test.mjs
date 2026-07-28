import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import test from "node:test";

const bridgePath = new URL("../index.mjs", import.meta.url);

function invoke(input) {
  const result = spawnSync(process.execPath, [bridgePath.pathname], {
    encoding: "utf8",
    env: { ...process.env, TZ: "UTC" },
    input,
  });
  assert.equal(result.status, 0, result.stderr);
  assert.equal(result.stderr, "");
  assert.match(result.stdout, /^[^\r\n]+\n$/);
  return JSON.parse(result.stdout);
}

test("protocol preserves requestId and returns fixed engine metadata", () => {
  const response = invoke(`${JSON.stringify({
    protocolVersion: "1",
    requestId: "req_protocol_1",
    tool: "chart",
    arguments: {
      gender: "male",
      birthYear: 1988,
      birthMonth: 2,
      birthDay: 15,
      birthHour: 23,
      birthMinute: 30,
      calendarType: "solar",
    },
  })}\n`);

  assert.equal(response.ok, true);
  assert.equal(response.requestId, "req_protocol_1");
  assert.equal(response.action, "chart");
  assert.equal(response.resultSchemaVersion, "bazi.chart.v1");
  assert.deepEqual(response.engine, {
    name: "taibu-core-marten",
    version: "3.4.0-marten.1",
    sourceCommit: "1f7f8920ef2c2b032401427623ac0b9a7496c68d",
    patchId: "sect1-v1",
  });
  assert.match(response.inputFingerprint, /^sha256:[0-9a-f]{64}$/);
  assert.equal(response.normalizedTime.dayBoundaryPolicy, "lunar_javascript_sect1");
  assert.equal(typeof response.structuredContent, "object");
  assert.equal(Object.hasOwn(response, "content"), false);
});

test("protocol mismatch returns a stable error envelope", () => {
  const response = invoke(`${JSON.stringify({
    protocolVersion: "2",
    requestId: "req_protocol_2",
    tool: "chart",
    arguments: {},
  })}\n`);

  assert.equal(response.ok, false);
  assert.equal(response.requestId, "req_protocol_2");
  assert.equal(response.error.code, "bazi_bridge_protocol_mismatch");
  assert.equal(response.error.retryable, false);
  assert.equal(response.inputFingerprint, null);
});

test("invalid JSON, empty input, and multiple lines stay single-line errors", () => {
  assert.equal(invoke("{\n").error.code, "bazi_bridge_invalid_json");
  assert.equal(invoke("").error.code, "bazi_bridge_invalid_request");
  assert.equal(invoke("{}\n{}\n").error.code, "bazi_bridge_invalid_request");
});

test("unsupported actions have null action schema identity", () => {
  const response = invoke(`${JSON.stringify({
    protocolVersion: "1",
    requestId: "req_protocol_3",
    tool: "unknown",
    arguments: {},
  })}\n`);

  assert.equal(response.ok, false);
  assert.equal(response.action, null);
  assert.equal(response.resultSchemaVersion, null);
  assert.equal(response.error.code, "bazi_action_unsupported");
});

test("upstream validation errors use a stable engine error", () => {
  const response = invoke(`${JSON.stringify({
    protocolVersion: "1",
    requestId: "req_protocol_4",
    tool: "resolve_pillars",
    arguments: {
      yearPillar: "invalid",
      monthPillar: "甲寅",
      dayPillar: "辛丑",
      hourPillar: "戊子",
    },
  })}\n`);
  assert.equal(response.ok, false);
  assert.equal(response.error.code, "bazi_engine_error");
  assert.equal(response.inputFingerprint, null);
});
