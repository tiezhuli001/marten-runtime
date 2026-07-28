import { BridgeError } from "./lib/errors.mjs";
import { fetchAmapGeocodes } from "./providers/amap.mjs";

export const PLACE_RESOLVER_VERSION = "taibu-14860a2-marten-v1";
const MUNICIPALITY_ADCODES = new Set(["110000", "120000", "310000", "500000"]);
const MAINLAND_PREFIXES = new Set([
  "11", "12", "13", "14", "15", "21", "22", "23", "31", "32", "33",
  "34", "35", "36", "37", "41", "42", "43", "44", "45", "46", "50",
  "51", "52", "53", "54", "61", "62", "63", "64", "65",
]);
const PROVINCE_LEVELS = new Set(["province", "省", "自治区", "特别行政区", "国家"]);

export function normalizePlaceText(value) {
  if (typeof value !== "string") {
    throw new BridgeError("bazi_birth_place_required", "birthPlace is required");
  }
  const normalized = value.normalize("NFKC").trim().replace(/\s+/g, " ");
  if (normalized.length < 2 || normalized.length > 200) {
    throw new BridgeError("bazi_birth_place_required", "birthPlace must contain 2-200 characters");
  }
  return normalized;
}

function parseCoordinate(location) {
  if (typeof location !== "string") {
    return null;
  }
  const parts = location.split(",");
  if (parts.length !== 2) {
    return null;
  }
  const longitude = Number(parts[0]);
  const latitude = Number(parts[1]);
  if (
    !Number.isFinite(longitude)
    || !Number.isFinite(latitude)
    || longitude < -180
    || longitude > 180
    || latitude < -90
    || latitude > 90
  ) {
    return null;
  }
  return { longitude, latitude };
}

function validateRegion(adcode) {
  if (typeof adcode !== "string" || !/^\d{6}$/.test(adcode) || !MAINLAND_PREFIXES.has(adcode.slice(0, 2))) {
    throw new BridgeError(
      "bazi_birth_place_unsupported",
      "Birth place is outside the supported mainland China region",
    );
  }
}

function canonicalize(record) {
  const coordinate = parseCoordinate(record.location);
  if (!coordinate) {
    throw new BridgeError("bazi_place_invalid_result", "Place resolver returned invalid coordinates");
  }
  const adcode = String(record.adcode ?? "");
  validateRegion(adcode);
  const level = String(record.level ?? "").trim();
  if (PROVINCE_LEVELS.has(level.toLowerCase()) && !MUNICIPALITY_ADCODES.has(adcode)) {
    throw new BridgeError(
      "bazi_place_precision_insufficient",
      "Birth place must resolve to city or district precision",
    );
  }
  return {
    provider: "amap",
    resolverVersion: PLACE_RESOLVER_VERSION,
    formattedAddress: String(record.formatted_address ?? "").trim(),
    adcode,
    level,
    coordinateSystem: "gcj02",
    resolvedLongitude: coordinate.longitude,
    resolvedLatitude: coordinate.latitude,
  };
}

export function validateResolvedPlace(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new BridgeError("bazi_place_invalid_result", "resolvedPlace is invalid");
  }
  if (value.provider !== "amap" || value.resolverVersion !== PLACE_RESOLVER_VERSION || value.coordinateSystem !== "gcj02") {
    throw new BridgeError("bazi_place_invalid_result", "resolvedPlace identity is invalid");
  }
  return canonicalize({
    formatted_address: value.formattedAddress,
    adcode: value.adcode,
    level: value.level,
    location: `${String(value.resolvedLongitude)},${String(value.resolvedLatitude)}`,
  });
}

export async function resolvePlace(place, options) {
  const normalizedPlace = normalizePlaceText(place);
  const records = await fetchAmapGeocodes(normalizedPlace, options);
  if (records.length === 0) {
    throw new BridgeError("bazi_place_resolution_failed", "Birth place could not be resolved");
  }

  const unique = [];
  const seen = new Set();
  for (const record of records) {
    const key = `${record.adcode ?? ""}|${record.location ?? ""}|${record.formatted_address ?? ""}`;
    if (!seen.has(key)) {
      seen.add(key);
      unique.push(record);
    }
  }
  if (unique.length > 1) {
    throw new BridgeError("bazi_place_ambiguous", "Birth place has multiple matches", {
      details: {
        candidates: unique.slice(0, 5).map((record) => ({
          formattedAddress: String(record.formatted_address ?? "").trim(),
          adcode: String(record.adcode ?? ""),
          level: String(record.level ?? "").trim(),
        })),
      },
    });
  }
  return canonicalize(unique[0]);
}
