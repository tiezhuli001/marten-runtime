import { executeTool, renderToolResult } from "taibu-core/mcp";

import { ACTIONS } from "./contract.mjs";
import { normalizeDayunResult } from "./dayun-normalization.mjs";
import { fingerprintBirth, fingerprintResolve } from "./fingerprint.mjs";
import { makeEnvelopeContext, validateRequest } from "./protocol.mjs";
import { normalizeBirthTimeWithPlace } from "./time-normalization.mjs";

export async function executeBridgeRequest(rawRequest) {
  const request = validateRequest(rawRequest);
  const action = ACTIONS[request.tool];
  const time = request.tool === "resolve_pillars"
    ? null
    : await normalizeBirthTimeWithPlace(request.arguments, {
      action: request.tool,
      resolvedPlace: request.resolvedPlace,
    });
  const engineArguments = {
    ...(time?.engineArguments ?? request.arguments),
    detailLevel: request.detailLevel,
  };
  let rawResult = await executeTool(action.toolName, engineArguments);
  let dayunStartSolar = null;
  if (request.tool === "resolve_pillars") {
    const candidates = rawResult.candidates.filter((candidate) => {
      const year = Number(candidate.solarText.slice(0, 4));
      return year >= 1901 && year <= 2100;
    });
    rawResult = { ...rawResult, count: candidates.length, candidates };
  }
  if (request.tool === "dayun") {
    const normalizedDayun = normalizeDayunResult(rawResult, engineArguments);
    rawResult = normalizedDayun.result;
    dayunStartSolar = normalizedDayun.startSolarText;
  }
  const rendered = renderToolResult(action.toolName, rawResult, {
    detailLevel: request.detailLevel,
  });
  if (rendered.structuredContent === undefined) {
    throw new Error(`Canonical renderer missing for ${action.toolName}`);
  }

  const structuredContent = request.tool === "dayun"
    ? {
      ...rendered.structuredContent,
      起运信息: {
        ...rendered.structuredContent.起运信息,
        起运时间: dayunStartSolar,
      },
    }
    : rendered.structuredContent;
  return {
    ok: true,
    ...makeEnvelopeContext(request),
    inputFingerprint: request.tool === "resolve_pillars"
      ? fingerprintResolve(request.arguments)
      : fingerprintBirth(request.arguments, time.normalizedTime),
    structuredContent,
    normalizedTime: time?.normalizedTime ?? null,
    degradedDiagnostics: [],
  };
}
