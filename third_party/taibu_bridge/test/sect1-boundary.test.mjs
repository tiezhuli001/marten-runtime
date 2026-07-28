import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import { calculateBazi } from "taibu-core/bazi";
import { resolveBaziPillars } from "taibu-core/bazi-pillars-resolve";
import { Solar } from "lunar-javascript";

const clockFixturesUrl = new URL(
  "../../../tests/fixtures/bazi/clock/manifest.json",
  import.meta.url,
);

function getPillars(eightChar) {
  return [
    eightChar.getYear(),
    eightChar.getMonth(),
    eightChar.getDay(),
    eightChar.getTime(),
  ];
}

test("sect 1 changes the day pillar at 23:00", async () => {
  const manifest = JSON.parse(await readFile(clockFixturesUrl, "utf8"));

  for (const fixture of manifest.cases) {
    const [year, month, day] = fixture.birthDate.split("-").map(Number);
    const [hour, minute] = fixture.birthTime.split(":").map(Number);
    const eightChar = Solar.fromYmdHms(year, month, day, hour, minute, 0)
      .getLunar()
      .getEightChar();
    eightChar.setSect(1);
    assert.deepEqual(getPillars(eightChar), fixture.pillars, fixture.id);
  }
});

test("patched Bazi chart uses sect 1", () => {
  const result = calculateBazi({
    gender: "male",
    birthYear: 1988,
    birthMonth: 2,
    birthDay: 15,
    birthHour: 23,
    birthMinute: 30,
    calendarType: "solar",
  });

  assert.equal(`${result.fourPillars.day.stem}${result.fourPillars.day.branch}`, "辛丑");
  assert.equal(`${result.fourPillars.hour.stem}${result.fourPillars.hour.branch}`, "戊子");
});

test("reverse-pillar prefilters are equivalent at midnight", () => {
  const years = [1901, 1919, 1940, 1949, 1986, 1991, 2026, 2100];
  for (const year of years) {
    for (let month = 1; month <= 12; month += 1) {
      for (const day of [1, 15]) {
        const solar = Solar.fromYmdHms(year, month, day, 0, 0, 0);
        const sect1 = solar.getLunar().getEightChar();
        const sect2 = solar.getLunar().getEightChar();
        sect1.setSect(1);
        sect2.setSect(2);
        assert.equal(sect1.getYear(), sect2.getYear());
        assert.equal(sect1.getMonth(), sect2.getMonth());
        assert.equal(sect1.getDay(), sect2.getDay());
      }
    }
  }
});

test("reverse pillars returns both valid Zi-hour civil dates", async () => {
  const result = await resolveBaziPillars({
    yearPillar: "戊辰",
    monthPillar: "甲寅",
    dayPillar: "辛丑",
    hourPillar: "戊子",
  });
  const matching = result.candidates
    .map((candidate) => candidate.solarText)
    .filter((value) => value.startsWith("1988-02"));

  assert.deepEqual(matching, ["1988-02-15 23:00", "1988-02-16 00:00"]);
});
