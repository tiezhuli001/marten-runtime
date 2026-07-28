import assert from "node:assert/strict";
import test from "node:test";

import { fetchAmapGeocodes } from "../providers/amap.mjs";

function jsonResponse(payload, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "content-type": "application/json" },
  });
}

test("Amap request contains only address and key with redirects disabled", async () => {
  let captured;
  const records = await fetchAmapGeocodes("四川省成都市武侯区", {
    key: "secret-key",
    fetchImpl: async (url, options) => {
      captured = { url, options };
      return jsonResponse({ status: "1", geocodes: [{ adcode: "510107" }] });
    },
  });
  assert.equal(records.length, 1);
  assert.equal(captured.url.origin + captured.url.pathname, "https://restapi.amap.com/v3/geocode/geo");
  assert.deepEqual([...captured.url.searchParams.keys()].sort(), ["address", "key"]);
  assert.equal(captured.url.searchParams.get("address"), "四川省成都市武侯区");
  assert.equal(captured.url.searchParams.get("key"), "secret-key");
  assert.equal(captured.options.redirect, "error");
});

test("missing and invalid credentials are non-retryable", async () => {
  await assert.rejects(() => fetchAmapGeocodes("成都市", { key: "" }), {
    code: "bazi_place_resolver_unavailable",
    retryable: false,
  });
  for (const response of [
    jsonResponse({}, 401),
    jsonResponse({ status: "0", infocode: "10001" }),
  ]) {
    await assert.rejects(
      () => fetchAmapGeocodes("成都市", { key: "secret", fetchImpl: async () => response }),
      { code: "bazi_place_resolver_unavailable", retryable: false },
    );
  }
});

test("rate limits, server errors, and network errors are retryable", async () => {
  for (const response of [jsonResponse({}, 429), jsonResponse({}, 503)]) {
    await assert.rejects(
      () => fetchAmapGeocodes("成都市", { key: "secret", fetchImpl: async () => response }),
      { code: "bazi_place_resolver_unavailable", retryable: true },
    );
  }
  await assert.rejects(
    () => fetchAmapGeocodes("成都市", {
      key: "secret",
      fetchImpl: async () => { throw new Error("network secret-key full-url"); },
    }),
    (error) => {
      assert.equal(error.code, "bazi_place_resolver_unavailable");
      assert.equal(error.retryable, true);
      assert.doesNotMatch(error.message, /secret-key|full-url|成都市/);
      return true;
    },
  );
});

test("deadline errors use their dedicated stable code", async () => {
  await assert.rejects(
    () => fetchAmapGeocodes("成都市", {
      key: "secret",
      fetchImpl: async () => { throw new DOMException("timed out", "TimeoutError"); },
    }),
    { code: "bazi_place_resolution_timeout", retryable: true },
  );
});
