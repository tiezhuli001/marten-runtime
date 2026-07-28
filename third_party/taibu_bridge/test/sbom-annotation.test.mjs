import assert from "node:assert/strict";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { spawnSync } from "node:child_process";
import test from "node:test";

test("SBOM annotation records the shipped Taibu patch identity and file hashes", async () => {
  const directory = await mkdtemp(join(tmpdir(), "marten-sbom-"));
  try {
    const target = join(directory, "taibu.cdx.json");
    await writeFile(
      target,
      `${JSON.stringify({ components: [{ name: "taibu-core", version: "3.4.0" }] })}\n`,
      "utf8",
    );

    const result = spawnSync(
      process.execPath,
      ["scripts/annotate-sbom.mjs", target],
      { cwd: process.cwd(), encoding: "utf8" },
    );
    assert.equal(result.status, 0, result.stderr);

    const document = JSON.parse(await readFile(target, "utf8"));
    const properties = Object.fromEntries(
      document.components[0].properties.map(({ name, value }) => [name, value]),
    );
    assert.equal(properties["marten:patched-version"], "3.4.0-marten.1");
    assert.equal(properties["marten:patch-id"], "sect1-v1");
    assert.match(properties["marten:patch-sha256"], /^[a-f0-9]{64}$/);
    const fileHashes = Object.entries(properties).filter(([name]) =>
      name.startsWith("marten:patched-file-sha256:"),
    );
    assert.equal(fileHashes.length, 3);
    for (const [, digest] of fileHashes) assert.match(digest, /^[a-f0-9]{64}$/);
  } finally {
    await rm(directory, { recursive: true, force: true });
  }
});
