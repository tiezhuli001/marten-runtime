import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import {
  loadUpstreamLock,
  packageUrl,
  readPackageJson,
  readPackageLock,
  sha256,
} from "../scripts/upstream-support.mjs";

test("locked upstream packages and patched file digests match", async () => {
  const upstream = await loadUpstreamLock();
  const packageLock = await readPackageLock();

  for (const dependency of [upstream.engine, upstream.calendar]) {
    const packageJson = await readPackageJson(dependency.package);
    const lockEntry = packageLock.packages[`node_modules/${dependency.package}`];
    assert.equal(packageJson.version, dependency.version);
    assert.equal(lockEntry.version, dependency.version);
    assert.equal(lockEntry.integrity, dependency.integrity);
  }

  assert.equal(
    upstream.engine.sourceCommit,
    "1f7f8920ef2c2b032401427623ac0b9a7496c68d",
  );
  assert.equal(
    upstream.placeResolver.sourceCommit,
    "14860a26e3c428bb9c0a3eee3ba88e7cb57b1e6c",
  );

  for (const target of upstream.targets) {
    const content = await readFile(packageUrl(upstream.engine.package, target.path));
    assert.equal(sha256(content), target.afterSha256, target.path);
  }
});

test("sect1-v1 remains limited to the documented behavior sites", async () => {
  const upstream = await loadUpstreamLock();
  const contents = await Promise.all(
    upstream.targets.map((target) =>
      readFile(packageUrl(upstream.engine.package, target.path), "utf8"),
    ),
  );

  assert.equal(
    contents.reduce(
      (count, content) => count + (content.match(/\.setSect\(1\)/g) ?? []).length,
      0,
    ),
    3,
  );
  assert.match(contents[2], /const jan = Solar\.fromYmd\(year, 1, 15\).*getEightChar\(\)/);
  assert.match(contents[2], /const jun = Solar\.fromYmd\(year, 6, 15\).*getEightChar\(\)/);
  assert.match(contents[2], /Solar\.fromYmd\(year, month, day\).*getEightChar\(\)/);
  assert.match(contents[2], /pillars\.hour\.branch === '子' && hour === 23/);
  assert.match(
    contents[2],
    /solarText: toSolarText\(solar\.getYear\(\), solar\.getMonth\(\), solar\.getDay\(\), hour, 0\)/,
  );
});
