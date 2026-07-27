import { access, readFile } from "node:fs/promises";

import {
  bridgeRoot,
  loadUpstreamLock,
  packageUrl,
  readPackageJson,
  readPackageLock,
  sha256,
} from "./upstream-support.mjs";

const upstream = await loadUpstreamLock();
const packageLock = await readPackageLock();

for (const dependency of [upstream.engine, upstream.calendar]) {
  const packageJson = await readPackageJson(dependency.package);
  if (packageJson.version !== dependency.version) {
    throw new Error(`${dependency.package} version mismatch`);
  }
  const lockEntry = packageLock.packages[`node_modules/${dependency.package}`];
  if (lockEntry?.version !== dependency.version || lockEntry?.integrity !== dependency.integrity) {
    throw new Error(`${dependency.package} lockfile integrity mismatch`);
  }
}

for (const license of [
  "LICENSE-taibu-core",
  "LICENSE-lunar-javascript",
  "LICENSE-taibu-mcp-server",
]) {
  await access(new URL(license, bridgeRoot));
}

const states = [];
for (const target of upstream.targets) {
  const content = await readFile(packageUrl(upstream.engine.package, target.path));
  const digest = sha256(content);
  if (digest !== target.beforeSha256 && digest !== target.afterSha256) {
    throw new Error(`unexpected upstream digest for ${target.path}: ${digest}`);
  }
  states.push(digest === target.beforeSha256 ? "original" : "patched");
}

if (new Set(states).size !== 1) {
  throw new Error(`mixed engine patch state: ${states.join(",")}`);
}

process.stdout.write(`verified taibu-core ${upstream.engine.version} (${states[0]})\n`);
