import { createHash } from "node:crypto";
import { readFile, writeFile } from "node:fs/promises";
import { resolve } from "node:path";

const PATCHED_VERSION = "3.4.0-marten.1";
const PATCH_ID = "sect1-v1";
const PATCH_FILE = "patches/taibu-core+3.4.0-sect1.patch";
const PATCHED_FILES = [
  "node_modules/taibu-core/dist/domains/bazi/calculate.js",
  "node_modules/taibu-core/dist/domains/bazi-dayun/calculate.js",
  "node_modules/taibu-core/dist/domains/bazi-pillars-resolve/calculate.js",
];

function sha256(content) {
  return createHash("sha256").update(content).digest("hex");
}

function findComponent(components, name) {
  for (const component of components ?? []) {
    if (component?.name === name) return component;
    const nested = findComponent(component?.components, name);
    if (nested) return nested;
  }
  return null;
}

const target = resolve(process.argv[2] ?? "");
if (!process.argv[2]) throw new Error("SBOM path is required");

const document = JSON.parse(await readFile(target, "utf8"));
const component = findComponent(document.components, "taibu-core");
if (!component) throw new Error("taibu-core component is missing from SBOM");

const properties = new Map(
  (component.properties ?? []).map((item) => [item.name, item.value]),
);
properties.set("marten:patched-version", PATCHED_VERSION);
properties.set("marten:patch-id", PATCH_ID);
properties.set(
  "marten:patch-sha256",
  sha256(await readFile(resolve(PATCH_FILE))),
);
for (const file of PATCHED_FILES) {
  properties.set(`marten:patched-file-sha256:${file}`, sha256(await readFile(resolve(file))));
}
component.properties = [...properties.entries()]
  .sort(([left], [right]) => left.localeCompare(right))
  .map(([name, value]) => ({ name, value }));

await writeFile(target, `${JSON.stringify(document, null, 2)}\n`, "utf8");
