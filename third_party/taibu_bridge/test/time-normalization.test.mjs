import assert from "node:assert/strict";
import test from "node:test";

import { normalizeBirthTime } from "../lib/time-normalization.mjs";

function normalize(overrides) {
  return normalizeBirthTime({
    gender: "male",
    birthYear: 1990,
    birthMonth: 5,
    birthDay: 15,
    birthHour: 12,
    birthMinute: 0,
    calendarType: "solar",
    timezone: "Asia/Shanghai",
    sourceTimeStandard: "recorded_civil",
    timeBasis: "clock",
    ...overrides,
  });
}

test("supported range starts at 1901 and ends at 2100", () => {
  assert.throws(() => normalize({ birthYear: 1900 }), { code: "bazi_birth_year_unsupported" });
  assert.equal(normalize({ birthYear: 1901, birthMonth: 1, birthDay: 1 }).normalizedTime.sourceUtcOffsetMinutes, 480);
  assert.equal(normalize({ birthYear: 2100 }).engineArguments.birthYear, 2100);
  assert.throws(() => normalize({ birthYear: 2101 }), { code: "bazi_birth_year_unsupported" });
});

test("historical China DST is normalized to UTC+8", () => {
  const cases = [
    [1919, 1, 1, 480, "1919-01-01T12:00:00"],
    [1940, 7, 1, 540, "1940-07-01T11:00:00"],
    [1949, 7, 1, 480, "1949-07-01T12:00:00"],
    [1986, 7, 1, 540, "1986-07-01T11:00:00"],
    [1991, 7, 1, 540, "1991-07-01T11:00:00"],
  ];
  for (const [year, month, day, offset, effective] of cases) {
    const result = normalize({ birthYear: year, birthMonth: month, birthDay: day });
    assert.equal(result.normalizedTime.sourceUtcOffsetMinutes, offset);
    assert.equal(result.normalizedTime.dstAdjustmentMinutes, 480 - offset);
    assert.equal(result.normalizedTime.effectiveBirthDateTime, effective);
  }
});

test("DST gaps and overlaps return distinct stable errors", () => {
  assert.throws(
    () => normalize({ birthYear: 1986, birthMonth: 5, birthDay: 4, birthHour: 2, birthMinute: 30 }),
    { code: "bazi_source_time_invalid" },
  );
  assert.throws(
    () => normalize({ birthYear: 1986, birthMonth: 9, birthDay: 14, birthHour: 1, birthMinute: 30 }),
    { code: "bazi_source_time_ambiguous" },
  );
});

test("beijing_standard bypasses historical civil offset conversion", () => {
  const result = normalize({
    birthYear: 1986,
    birthMonth: 7,
    birthDay: 1,
    sourceTimeStandard: "beijing_standard",
  });
  assert.equal(result.normalizedTime.sourceUtcOffsetMinutes, 480);
  assert.equal(result.normalizedTime.dstAdjustmentMinutes, 0);
  assert.equal(result.normalizedTime.effectiveBirthDateTime, "1986-07-01T12:00:00");
});

test("lunar input converts to a solar source date before civil normalization", () => {
  const result = normalize({
    birthYear: 1990,
    birthMonth: 4,
    birthDay: 21,
    calendarType: "lunar",
  });
  assert.equal(result.normalizedTime.sourceCalendarType, "lunar");
  assert.equal(result.normalizedTime.sourceIsLeapMonth, false);
  assert.equal(result.normalizedTime.effectiveCalendarType, "solar");
  assert.equal(result.engineArguments.calendarType, "solar");
});

test("timezone and time-basis boundaries return stable errors", () => {
  assert.throws(() => normalize({ timezone: "UTC" }), { code: "bazi_timezone_unsupported" });
  assert.throws(() => normalize({ timeBasis: "invalid" }), { code: "bazi_bridge_invalid_request" });
});
