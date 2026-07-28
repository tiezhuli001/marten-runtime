import assert from "node:assert/strict";
import test from "node:test";

import { executeBridgeRequest } from "../lib/execute.mjs";
import { normalizeBirthTimeWithPlace } from "../lib/time-normalization.mjs";
import { validateResolvedPlace } from "../place-resolution.mjs";

const resolvedPlace = {
  provider: "amap",
  resolverVersion: "taibu-14860a2-marten-v1",
  formattedAddress: "四川省成都市武侯区",
  adcode: "510107",
  level: "区县",
  coordinateSystem: "gcj02",
  resolvedLongitude: 104.04,
  resolvedLatitude: 30.64,
};

const arguments_ = {
  gender: "male",
  birthYear: 1988,
  birthMonth: 2,
  birthDay: 15,
  birthHour: 23,
  birthMinute: 30,
  calendarType: "solar",
  timezone: "Asia/Shanghai",
  sourceTimeStandard: "beijing_standard",
  timeBasis: "true_solar",
  birthPlace: "四川省成都市武侯区",
};

test("internal resolvedPlace is fully revalidated", () => {
  assert.deepEqual(validateResolvedPlace(resolvedPlace), resolvedPlace);
  for (const changed of [
    { ...resolvedPlace, provider: "other" },
    { ...resolvedPlace, resolverVersion: "old" },
    { ...resolvedPlace, coordinateSystem: "wgs84" },
    { ...resolvedPlace, resolvedLongitude: 999 },
  ]) {
    assert.throws(() => validateResolvedPlace(changed), { code: "bazi_place_invalid_result" });
  }
});

test("true solar uses exact corrected components and place audit fields", async () => {
  const result = await normalizeBirthTimeWithPlace(arguments_, {
    action: "dayun",
    resolvedPlace,
  });
  assert.equal(result.normalizedTime.requested, "true_solar");
  assert.equal(result.normalizedTime.trueSolarAlgorithm, "taibu_true_solar_v1");
  assert.deepEqual(result.normalizedTime.placeResolution, resolvedPlace);
  assert.equal(result.normalizedTime.effectiveBirthDateTime, "1988-02-15T22:12:00");
  assert.equal(result.engineArguments.birthHour, 22);
  assert.equal(result.engineArguments.birthMinute, 12);
});

test("chart and dayun reuse the same resolved place and fingerprint", async () => {
  const invoke = (tool) => executeBridgeRequest({
    protocolVersion: "1",
    requestId: `req_${tool}_true_solar`,
    tool,
    arguments: arguments_,
    resolvedPlace,
    detailLevel: "default",
  });
  const [chart, dayun] = await Promise.all([invoke("chart"), invoke("dayun")]);
  assert.equal(chart.inputFingerprint, dayun.inputFingerprint);
  assert.deepEqual(chart.normalizedTime, dayun.normalizedTime);
  assert.equal(chart.structuredContent.基本信息.真太阳时.真太阳时, "22:12");
});
