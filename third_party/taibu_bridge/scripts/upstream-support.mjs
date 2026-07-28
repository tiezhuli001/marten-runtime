import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";

export const bridgeRoot = new URL("../", import.meta.url);

export async function loadUpstreamLock() {
  return JSON.parse(await readFile(new URL("upstream-lock.json", bridgeRoot), "utf8"));
}

export function sha256(content) {
  return createHash("sha256").update(content).digest("hex");
}

export function packageUrl(packageName, relativePath = "") {
  return new URL(`node_modules/${packageName}/${relativePath}`, bridgeRoot);
}

export async function readPackageJson(packageName) {
  return JSON.parse(await readFile(packageUrl(packageName, "package.json"), "utf8"));
}

export async function readPackageLock() {
  return JSON.parse(await readFile(new URL("package-lock.json", bridgeRoot), "utf8"));
}
