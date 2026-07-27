import { BridgeError } from "../lib/errors.mjs";

export const AMAP_GEOCODE_ENDPOINT = "https://restapi.amap.com/v3/geocode/geo";
export const AMAP_DEADLINE_MS = 2500;

const INVALID_CREDENTIAL_CODES = new Set([
  "10001", "10002", "10007", "10008", "10009", "10012",
]);

function providerUnavailable(reason, retryable) {
  return new BridgeError(
    "bazi_place_resolver_unavailable",
    "Birth-place resolver is unavailable",
    { retryable, details: { reason } },
  );
}

export async function fetchAmapGeocodes(
  place,
  {
    fetchImpl = globalThis.fetch,
    key = process.env.AMAP_WEB_SERVICE_KEY?.trim(),
    deadlineMs = AMAP_DEADLINE_MS,
  } = {},
) {
  if (!key) {
    throw providerUnavailable("credential_missing", false);
  }
  const url = new URL(AMAP_GEOCODE_ENDPOINT);
  url.searchParams.set("key", key);
  url.searchParams.set("address", place);

  let response;
  try {
    response = await fetchImpl(url, {
      method: "GET",
      cache: "no-store",
      redirect: "error",
      signal: AbortSignal.timeout(deadlineMs),
    });
  } catch (error) {
    if (error?.name === "AbortError" || error?.name === "TimeoutError") {
      throw new BridgeError(
        "bazi_place_resolution_timeout",
        "Birth-place resolution timed out",
        { retryable: true },
      );
    }
    throw providerUnavailable("network_error", true);
  }

  if (response.status === 401 || response.status === 403) {
    throw providerUnavailable("credential_invalid", false);
  }
  if (response.status === 429 || response.status >= 500) {
    throw providerUnavailable(response.status === 429 ? "rate_limited" : "provider_error", true);
  }
  if (!response.ok) {
    throw providerUnavailable("provider_error", false);
  }

  let payload;
  try {
    payload = await response.json();
  } catch {
    throw providerUnavailable("invalid_response", true);
  }
  if (payload?.status !== "1") {
    const infoCode = String(payload?.infocode ?? "");
    if (INVALID_CREDENTIAL_CODES.has(infoCode)) {
      throw providerUnavailable("credential_invalid", false);
    }
    throw providerUnavailable("provider_error", true);
  }
  return Array.isArray(payload.geocodes) ? payload.geocodes : [];
}
