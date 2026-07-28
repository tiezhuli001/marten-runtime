import assert from "node:assert/strict";
import test from "node:test";

import { executeBridgeRequest } from "../lib/execute.mjs";
import { fingerprintBirth } from "../lib/fingerprint.mjs";
import { normalizeBirthTime } from "../lib/time-normalization.mjs";

const arguments_ = {
  gender: "male",
  birthYear: 1988,
  birthMonth: 2,
  birthDay: 15,
  birthHour: 23,
  birthMinute: 30,
  calendarType: "solar",
  timezone: "Asia/Shanghai",
  sourceTimeStandard: "recorded_civil",
  timeBasis: "clock",
};

async function execute(tool, detailLevel = "default") {
  return executeBridgeRequest({
    protocolVersion: "1",
    requestId: `req_${tool}_${detailLevel}`,
    tool,
    arguments: arguments_,
    detailLevel,
  });
}

test("chart and dayun share one birth-fact fingerprint", async () => {
  const [chart, dayun] = await Promise.all([execute("chart"), execute("dayun")]);
  assert.equal(chart.inputFingerprint, dayun.inputFingerprint);
  assert.deepEqual(chart.normalizedTime, dayun.normalizedTime);
});

test("action and detailLevel are excluded from birth fingerprint", async () => {
  const [defaultResult, fullResult] = await Promise.all([
    execute("chart", "default"),
    execute("chart", "full"),
  ]);
  assert.equal(defaultResult.inputFingerprint, fullResult.inputFingerprint);
  assert.notDeepEqual(defaultResult.structuredContent, fullResult.structuredContent);
});

test("algorithm identity changes the fingerprint", () => {
  const time = normalizeBirthTime(arguments_).normalizedTime;
  const original = fingerprintBirth(arguments_, time);
  const changed = fingerprintBirth(arguments_, {
    ...time,
    dayBoundaryPolicy: "test_policy_v2",
  });
  assert.notEqual(original, changed);
});

test("resolve fingerprint is stable and independent from requestId", async () => {
  const resolveArguments = {
    yearPillar: "戊辰",
    monthPillar: "甲寅",
    dayPillar: "辛丑",
    hourPillar: "戊子",
  };
  const first = await executeBridgeRequest({
    protocolVersion: "1",
    requestId: "req_resolve_1",
    tool: "resolve_pillars",
    arguments: resolveArguments,
  });
  const second = await executeBridgeRequest({
    protocolVersion: "1",
    requestId: "req_resolve_2",
    tool: "resolve_pillars",
    arguments: resolveArguments,
  });
  assert.equal(first.inputFingerprint, second.inputFingerprint);
  assert.equal(first.normalizedTime, null);
});

test("resolve candidates are restricted to 1901-2100", async () => {
  const result = await executeBridgeRequest({
    protocolVersion: "1",
    requestId: "req_resolve_range",
    tool: "resolve_pillars",
    arguments: {
      yearPillar: "庚子",
      monthPillar: "戊寅",
      dayPillar: "甲子",
      hourPillar: "甲子",
    },
  });
  assert.equal(result.structuredContent.候选数量, 2);
  for (const candidate of result.structuredContent.候选列表) {
    const year = Number(candidate.公历.slice(0, 4));
    assert.ok(year >= 1901 && year <= 2100);
  }
});
