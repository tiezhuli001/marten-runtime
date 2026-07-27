import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const fixtureKinds = [
  "clock",
  "true_solar",
  "resolve_pillars",
  "protocol_errors",
];

const fixturesRoot = new URL("../../../tests/fixtures/bazi/", import.meta.url);

test("shared Bazi fixture manifests are loadable and versioned", async () => {
  for (const kind of fixtureKinds) {
    const manifestUrl = new URL(`${kind}/manifest.json`, fixturesRoot);
    const manifest = JSON.parse(await readFile(manifestUrl, "utf8"));

    assert.equal(manifest.schemaVersion, "bazi.fixture.v1");
    assert.equal(manifest.kind, kind);
    assert.ok(Array.isArray(manifest.cases));
  }
});
