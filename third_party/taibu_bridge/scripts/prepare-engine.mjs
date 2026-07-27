import { readFile, writeFile } from "node:fs/promises";

import {
  loadUpstreamLock,
  packageUrl,
  sha256,
} from "./upstream-support.mjs";

const upstream = await loadUpstreamLock();
const pendingWrites = [];
const states = [];

for (const target of upstream.targets) {
  const url = packageUrl(upstream.engine.package, target.path);
  const content = await readFile(url, "utf8");
  const digest = sha256(content);
  if (digest === target.afterSha256) {
    states.push("patched");
    continue;
  }
  if (digest !== target.beforeSha256) {
    throw new Error(`refusing to patch unexpected digest for ${target.path}: ${digest}`);
  }
  let patched = content;
  const replacements = target.replacements ?? [
    { before: target.before, after: target.after },
  ];
  for (const replacement of replacements) {
    const occurrences = patched.split(replacement.before).length - 1;
    if (occurrences !== 1) {
      throw new Error(`expected one patch target in ${target.path}, found ${occurrences}`);
    }
    patched = patched.replace(replacement.before, replacement.after);
  }
  if (sha256(patched) !== target.afterSha256) {
    throw new Error(`patched digest mismatch for ${target.path}`);
  }
  pendingWrites.push([url, patched]);
  states.push("original");
}

if (new Set(states).size !== 1) {
  throw new Error(`mixed engine patch state: ${states.join(",")}`);
}

for (const [url, content] of pendingWrites) {
  await writeFile(url, content, "utf8");
}

process.stdout.write(
  states[0] === "patched"
    ? `engine patch ${upstream.engine.patchId} already applied\n`
    : `engine patch ${upstream.engine.patchId} applied\n`,
);
