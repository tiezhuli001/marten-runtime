import { Lunar } from "lunar-javascript";
import { resolveTrueSolarDateTime } from "../node_modules/taibu-core/dist/domains/shared/true-solar.js";

import { BridgeError } from "./errors.mjs";
import { resolvePlace, validateResolvedPlace } from "../place-resolution.mjs";

const SHANGHAI_TIMEZONE = "Asia/Shanghai";
const BEIJING_OFFSET_MINUTES = 480;

function integer(value, field) {
  if (!Number.isInteger(value)) {
    throw new BridgeError("bazi_bridge_invalid_request", `${field} must be an integer`);
  }
  return value;
}

function sourceSolarComponents(args) {
  const year = integer(args.birthYear, "birthYear");
  const month = integer(args.birthMonth, "birthMonth");
  const day = integer(args.birthDay, "birthDay");
  const hour = integer(args.birthHour, "birthHour");
  const minute = integer(args.birthMinute ?? 0, "birthMinute");
  if (year < 1901 || year > 2100) {
    throw new BridgeError("bazi_birth_year_unsupported", "birthYear must be between 1901 and 2100");
  }
  if (hour < 0 || hour > 23 || minute < 0 || minute > 59) {
    throw new BridgeError("bazi_bridge_invalid_request", "birth time is outside its valid range");
  }

  const calendarType = args.calendarType ?? "solar";
  const isLeapMonth = args.isLeapMonth ?? false;
  if (calendarType === "lunar") {
    let solar;
    try {
      const lunarMonth = isLeapMonth ? -Math.abs(month) : month;
      solar = Lunar.fromYmdHms(year, lunarMonth, day, hour, minute, 0).getSolar();
    } catch {
      throw new BridgeError("bazi_bridge_invalid_request", "birth date is not a valid lunar date");
    }
    return {
      year: solar.getYear(),
      month: solar.getMonth(),
      day: solar.getDay(),
      hour,
      minute,
      sourceCalendarType: "lunar",
      sourceIsLeapMonth: Boolean(isLeapMonth),
    };
  }
  if (calendarType !== "solar" || isLeapMonth) {
    throw new BridgeError("bazi_bridge_invalid_request", "calendarType or isLeapMonth is invalid");
  }
  const check = new Date(Date.UTC(year, month - 1, day, hour, minute, 0));
  if (
    check.getUTCFullYear() !== year
    || check.getUTCMonth() + 1 !== month
    || check.getUTCDate() !== day
  ) {
    throw new BridgeError("bazi_bridge_invalid_request", "birth date is not a valid solar date");
  }
  return {
    year,
    month,
    day,
    hour,
    minute,
    sourceCalendarType: "solar",
    sourceIsLeapMonth: false,
  };
}

function formatter() {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: SHANGHAI_TIMEZONE,
    hourCycle: "h23",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function zonedComponents(timestamp, format = formatter()) {
  const values = Object.fromEntries(
    format.formatToParts(new Date(timestamp))
      .filter((part) => part.type !== "literal")
      .map((part) => [part.type, Number(part.value)]),
  );
  return {
    year: values.year,
    month: values.month,
    day: values.day,
    hour: values.hour,
    minute: values.minute,
    second: values.second,
  };
}

function sameCivil(a, b) {
  return a.year === b.year
    && a.month === b.month
    && a.day === b.day
    && a.hour === b.hour
    && a.minute === b.minute
    && (b.second ?? 0) === 0;
}

function resolveRecordedCivil(components) {
  const desiredUtc = Date.UTC(
    components.year,
    components.month - 1,
    components.day,
    components.hour,
    components.minute,
    0,
  );
  const format = formatter();
  const offsets = new Set();
  let sawFractionalOffset = false;
  for (let deltaHours = -36; deltaHours <= 36; deltaHours += 6) {
    const probe = desiredUtc + deltaHours * 3_600_000;
    const local = zonedComponents(probe, format);
    const localAsUtc = Date.UTC(
      local.year,
      local.month - 1,
      local.day,
      local.hour,
      local.minute,
      local.second,
    );
    const offsetSeconds = (localAsUtc - probe) / 1000;
    if (offsetSeconds % 60 !== 0) {
      sawFractionalOffset = true;
      continue;
    }
    offsets.add(offsetSeconds / 60);
  }

  const matches = [];
  for (const offsetMinutes of offsets) {
    const timestamp = desiredUtc - offsetMinutes * 60_000;
    if (sameCivil(components, zonedComponents(timestamp, format))) {
      matches.push({ timestamp, offsetMinutes });
    }
  }
  if (matches.length === 0) {
    if (offsets.size === 0 && sawFractionalOffset) {
      throw new BridgeError(
        "bazi_birth_year_unsupported",
        "historical timezone offset cannot be represented at minute precision",
      );
    }
    throw new BridgeError("bazi_source_time_invalid", "source civil time does not exist");
  }
  if (matches.length > 1) {
    throw new BridgeError("bazi_source_time_ambiguous", "source civil time is ambiguous");
  }
  return matches[0];
}

function utc8Components(timestamp) {
  const date = new Date(timestamp + BEIJING_OFFSET_MINUTES * 60_000);
  return {
    year: date.getUTCFullYear(),
    month: date.getUTCMonth() + 1,
    day: date.getUTCDate(),
    hour: date.getUTCHours(),
    minute: date.getUTCMinutes(),
  };
}

function formatEffective(components) {
  const pad = (value) => String(value).padStart(2, "0");
  return `${components.year}-${pad(components.month)}-${pad(components.day)}T${pad(components.hour)}:${pad(components.minute)}:00`;
}

export function normalizeBirthTime(args) {
  if ((args.timezone ?? SHANGHAI_TIMEZONE) !== SHANGHAI_TIMEZONE) {
    throw new BridgeError("bazi_timezone_unsupported", "timezone must be Asia/Shanghai");
  }
  const timeBasis = args.timeBasis ?? "clock";
  if (timeBasis !== "clock") {
    throw new BridgeError("bazi_bridge_invalid_request", "timeBasis must be clock");
  }
  const source = sourceSolarComponents(args);
  const sourceTimeStandard = args.sourceTimeStandard ?? "recorded_civil";
  let timestamp;
  let sourceUtcOffsetMinutes;
  if (sourceTimeStandard === "recorded_civil") {
    ({ timestamp, offsetMinutes: sourceUtcOffsetMinutes } = resolveRecordedCivil(source));
  } else if (sourceTimeStandard === "beijing_standard") {
    sourceUtcOffsetMinutes = BEIJING_OFFSET_MINUTES;
    timestamp = Date.UTC(
      source.year,
      source.month - 1,
      source.day,
      source.hour,
      source.minute,
      0,
    ) - BEIJING_OFFSET_MINUTES * 60_000;
  } else {
    throw new BridgeError("bazi_bridge_invalid_request", "sourceTimeStandard is invalid");
  }
  const effective = utc8Components(timestamp);
  return {
    engineArguments: {
      gender: args.gender,
      birthYear: effective.year,
      birthMonth: effective.month,
      birthDay: effective.day,
      birthHour: effective.hour,
      birthMinute: effective.minute,
      calendarType: "solar",
      isLeapMonth: false,
    },
    normalizedTime: {
      requested: "clock",
      timezone: SHANGHAI_TIMEZONE,
      sourceTimeStandard,
      sourceUtcOffsetMinutes,
      dstAdjustmentMinutes: BEIJING_OFFSET_MINUTES - sourceUtcOffsetMinutes,
      placeResolution: null,
      sourceCalendarType: source.sourceCalendarType,
      sourceIsLeapMonth: source.sourceIsLeapMonth,
      effectiveCalendarType: "solar",
      effectiveBirthDateTime: formatEffective(effective),
      trueSolarAlgorithm: null,
      dayBoundaryPolicy: "lunar_javascript_sect1",
      qiyunMethod: "lunar_javascript_yun_sect1",
    },
  };
}

export async function normalizeBirthTimeWithPlace(
  args,
  { action, resolvedPlace, placeOptions } = {},
) {
  const timeBasis = args.timeBasis ?? "clock";
  if (timeBasis === "clock") {
    return normalizeBirthTime(args);
  }
  if (timeBasis !== "true_solar") {
    throw new BridgeError("bazi_bridge_invalid_request", "timeBasis is invalid");
  }

  const clock = normalizeBirthTime({ ...args, timeBasis: "clock" });
  const place = resolvedPlace === undefined
    ? await resolvePlace(args.birthPlace, placeOptions)
    : validateResolvedPlace(resolvedPlace);
  const corrected = resolveTrueSolarDateTime(
    clock.engineArguments,
    place.resolvedLongitude,
  );
  const effective = {
    year: corrected.year,
    month: corrected.month,
    day: corrected.day,
    hour: corrected.hour,
    minute: corrected.minute,
  };
  const effectiveArguments = {
    ...clock.engineArguments,
    birthYear: effective.year,
    birthMonth: effective.month,
    birthDay: effective.day,
    birthHour: effective.hour,
    birthMinute: effective.minute,
  };
  const engineArguments = action === "chart"
    ? {
      ...clock.engineArguments,
      birthPlace: place.formattedAddress,
      longitude: place.resolvedLongitude,
    }
    : effectiveArguments;
  return {
    engineArguments,
    normalizedTime: {
      ...clock.normalizedTime,
      requested: "true_solar",
      placeResolution: place,
      effectiveBirthDateTime: formatEffective(effective),
      trueSolarAlgorithm: "taibu_true_solar_v1",
    },
  };
}
