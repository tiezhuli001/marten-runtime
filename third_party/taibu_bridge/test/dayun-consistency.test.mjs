import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import test from "node:test";

const bridgePath = new URL("../index.mjs", import.meta.url);
const arguments_ = {
  gender: "male",
  birthYear: 2022,
  birthMonth: 3,
  birthDay: 9,
  birthHour: 20,
  birthMinute: 51,
  calendarType: "solar",
  timezone: "Asia/Shanghai",
  sourceTimeStandard: "beijing_standard",
  timeBasis: "clock",
};

function invoke(tool, timezone) {
  const result = spawnSync(process.execPath, [bridgePath.pathname], {
    encoding: "utf8",
    env: { ...process.env, TZ: timezone },
    input: `${JSON.stringify({
      protocolVersion: "1",
      requestId: `req_${tool}_${timezone}`,
      tool,
      arguments: arguments_,
      detailLevel: "full",
    })}\n`,
  });
  assert.equal(result.status, 0, result.stderr);
  return JSON.parse(result.stdout);
}

test("bridge output is independent from the caller host timezone", () => {
  for (const tool of ["chart", "dayun"]) {
    const utc = invoke(tool, "UTC");
    const shanghai = invoke(tool, "Asia/Shanghai");
    const newYork = invoke(tool, "America/New_York");
    assert.equal(utc.inputFingerprint, shanghai.inputFingerprint);
    assert.equal(utc.inputFingerprint, newYork.inputFingerprint);
    assert.deepEqual(utc.structuredContent, shanghai.structuredContent);
    assert.deepEqual(utc.structuredContent, newYork.structuredContent);
  }
});

test("Yun uses the fixed sect 1 start date", () => {
  const dayun = invoke("dayun", "UTC");
  const serialized = JSON.stringify(dayun.structuredContent);
  assert.match(serialized, /8年9月10天/);
  assert.equal(dayun.structuredContent.起运信息.起运时间, "2030-12-19 20:51");
});
