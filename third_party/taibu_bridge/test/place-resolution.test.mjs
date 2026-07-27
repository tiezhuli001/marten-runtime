import assert from "node:assert/strict";
import test from "node:test";

import { normalizePlaceText, resolvePlace } from "../place-resolution.mjs";

function response(geocodes) {
  return new Response(JSON.stringify({ status: "1", geocodes }), {
    status: 200,
    headers: { "content-type": "application/json" },
  });
}

function resolve(records, place = " 四川省  成都市武侯区 ") {
  return resolvePlace(place, {
    key: "test-key",
    fetchImpl: async () => response(records),
  });
}

test("place text uses NFKC and whitespace normalization", () => {
  assert.equal(normalizePlaceText(" 上海市  浦东新区 "), "上海市 浦东新区");
  assert.equal(normalizePlaceText("ＡＢ市"), "AB市");
  assert.throws(() => normalizePlaceText("A"), { code: "bazi_birth_place_required" });
});

test("successful result is canonical and GCJ-02", async () => {
  const result = await resolve([{
    formatted_address: "四川省成都市武侯区",
    adcode: "510107",
    level: "区县",
    location: "104.04,30.64",
  }]);
  assert.deepEqual(result, {
    provider: "amap",
    resolverVersion: "taibu-14860a2-marten-v1",
    formattedAddress: "四川省成都市武侯区",
    adcode: "510107",
    level: "区县",
    coordinateSystem: "gcj02",
    resolvedLongitude: 104.04,
    resolvedLatitude: 30.64,
  });
});

test("no result and multiple distinct results have stable errors", async () => {
  await assert.rejects(() => resolve([]), { code: "bazi_place_resolution_failed" });
  await assert.rejects(
    () => resolve([
      { formatted_address: "河北省保定市朝阳区", adcode: "130600", level: "市", location: "115.4,38.8" },
      { formatted_address: "辽宁省朝阳市朝阳区", adcode: "211300", level: "市", location: "120.4,41.5" },
    ], "朝阳区"),
    (error) => {
      assert.equal(error.code, "bazi_place_ambiguous");
      assert.equal(error.details.candidates.length, 2);
      assert.equal(Object.hasOwn(error.details.candidates[0], "location"), false);
      return true;
    },
  );
});

test("ordinary provinces fail while four municipalities pass", async () => {
  await assert.rejects(
    () => resolve([{ formatted_address: "四川省", adcode: "510000", level: "省", location: "104,30" }], "四川省"),
    { code: "bazi_place_precision_insufficient" },
  );
  for (const [address, adcode, location] of [
    ["北京市", "110000", "116.4,39.9"],
    ["天津市", "120000", "117.2,39.1"],
    ["上海市", "310000", "121.5,31.2"],
    ["重庆市", "500000", "106.5,29.6"],
  ]) {
    const result = await resolve([{ formatted_address: address, adcode, level: "省", location }], address);
    assert.equal(result.adcode, adcode);
  }
});

test("Hong Kong, Macau, Taiwan, and overseas adcodes are outside v1", async () => {
  for (const [address, adcode] of [["香港", "810000"], ["澳门", "820000"], ["台湾", "710000"], ["东京", ""]]) {
    await assert.rejects(
      () => resolve([{ formatted_address: address, adcode, level: "市", location: "120,30" }], address),
      { code: "bazi_birth_place_unsupported" },
    );
  }
});

test("invalid coordinate payloads fail", async () => {
  for (const location of ["bad", "181,30", "120,91"] ) {
    await assert.rejects(
      () => resolve([{ formatted_address: "成都市", adcode: "510100", level: "市", location }]),
      { code: "bazi_place_invalid_result" },
    );
  }
});
