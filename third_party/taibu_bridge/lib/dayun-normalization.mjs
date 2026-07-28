import { Solar } from "lunar-javascript";

export function normalizeDayunResult(rawResult, engineArguments) {
  const lunar = Solar.fromYmdHms(
    engineArguments.birthYear,
    engineArguments.birthMonth,
    engineArguments.birthDay,
    engineArguments.birthHour,
    engineArguments.birthMinute ?? 0,
    0,
  ).getLunar();
  const eightChar = lunar.getEightChar();
  eightChar.setSect(1);
  const yun = eightChar.getYun(engineArguments.gender === "male" ? 1 : 0);
  const startSolar = yun.getStartSolar();
  const startSolarText = startSolar.toYmdHms().slice(0, 16);
  return {
    result: {
      ...rawResult,
      startAgeDetail: `${yun.getStartYear()}年${yun.getStartMonth()}月${yun.getStartDay()}天起运`,
    },
    startSolarText,
  };
}
