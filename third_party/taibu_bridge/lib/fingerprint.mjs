import { createHash } from "node:crypto";

function digest(payload) {
  return `sha256:${createHash("sha256").update(JSON.stringify(payload)).digest("hex")}`;
}

export function fingerprintBirth(args, normalizedTime) {
  const place = normalizedTime.placeResolution;
  return digest({
    schemaVersion: "bazi.input.v1",
    gender: args.gender,
    sourceCalendarType: normalizedTime.sourceCalendarType,
    sourceIsLeapMonth: normalizedTime.sourceIsLeapMonth,
    sourceTimeStandard: normalizedTime.sourceTimeStandard,
    sourceUtcOffsetMinutes: normalizedTime.sourceUtcOffsetMinutes,
    dstAdjustmentMinutes: normalizedTime.dstAdjustmentMinutes,
    effectiveBirthDateTime: normalizedTime.effectiveBirthDateTime,
    timeBasis: normalizedTime.requested,
    timezone: normalizedTime.timezone,
    placeProvider: place?.provider ?? null,
    placeResolverVersion: place?.resolverVersion ?? null,
    placeAdcode: place?.adcode ?? null,
    placeLevel: place?.level ?? null,
    coordinateSystem: place?.coordinateSystem ?? null,
    resolvedLongitude: place?.resolvedLongitude ?? null,
    trueSolarAlgorithm: normalizedTime.trueSolarAlgorithm,
    dayBoundaryPolicy: normalizedTime.dayBoundaryPolicy,
    qiyunMethod: normalizedTime.qiyunMethod,
  });
}

export function fingerprintResolve(args) {
  return digest({
    schemaVersion: "bazi.resolve-input.v1",
    yearPillar: args.yearPillar,
    monthPillar: args.monthPillar,
    dayPillar: args.dayPillar,
    hourPillar: args.hourPillar,
  });
}
