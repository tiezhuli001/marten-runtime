import { stdin, stdout } from "node:process";

import { BridgeError } from "./lib/errors.mjs";
import { executeBridgeRequest } from "./lib/execute.mjs";
import { makeErrorEnvelope, parseRequestLine } from "./lib/protocol.mjs";

process.env.TZ = "UTC";

export async function runBridge(input) {
  const lines = input.split(/\r?\n/);
  if (lines.at(-1) === "") {
    lines.pop();
  }
  if (lines.length !== 1 || lines[0].length === 0) {
    return makeErrorEnvelope(
      null,
      new BridgeError(
        "bazi_bridge_invalid_request",
        "Bridge stdin must contain exactly one non-empty JSON line",
      ),
    );
  }

  let request = null;
  try {
    request = parseRequestLine(lines[0]);
    return await executeBridgeRequest(request);
  } catch (error) {
    return makeErrorEnvelope(request, error);
  }
}

async function main() {
  stdin.setEncoding("utf8");
  let input = "";
  for await (const chunk of stdin) {
    input += chunk;
  }
  stdout.write(`${JSON.stringify(await runBridge(input))}\n`);
}

if (process.argv[1] === new URL(import.meta.url).pathname) {
  await main();
}
