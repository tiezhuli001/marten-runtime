import { ACTIONS, ENGINE, PROTOCOL_VERSION, REQUEST_FIELDS } from "./contract.mjs";
import { BridgeError, toErrorPayload } from "./errors.mjs";

function isRecord(value) {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function parseRequestLine(line) {
  let request;
  try {
    request = JSON.parse(line);
  } catch {
    throw new BridgeError("bazi_bridge_invalid_json", "Bridge request is not valid JSON");
  }
  if (!isRecord(request)) {
    throw new BridgeError("bazi_bridge_invalid_request", "Bridge request must be an object");
  }
  return request;
}

export function validateRequest(request) {
  if (request.protocolVersion !== PROTOCOL_VERSION) {
    throw new BridgeError(
      "bazi_bridge_protocol_mismatch",
      `Unsupported bridge protocol version: ${String(request.protocolVersion)}`,
    );
  }
  if (typeof request.requestId !== "string" || request.requestId.length === 0) {
    throw new BridgeError("bazi_bridge_invalid_request", "requestId must be a non-empty string");
  }
  for (const key of Object.keys(request)) {
    if (!REQUEST_FIELDS.has(key)) {
      throw new BridgeError("bazi_bridge_invalid_request", `Unsupported request field: ${key}`);
    }
  }
  if (!Object.hasOwn(ACTIONS, request.tool)) {
    throw new BridgeError("bazi_action_unsupported", `Unsupported Bazi action: ${String(request.tool)}`);
  }
  if (!isRecord(request.arguments)) {
    throw new BridgeError("bazi_bridge_invalid_request", "arguments must be an object");
  }
  const detailLevel = request.detailLevel ?? "default";
  if (detailLevel !== "default" && detailLevel !== "full") {
    throw new BridgeError("bazi_bridge_invalid_request", "detailLevel must be default or full");
  }
  if (request.resolvedPlace !== undefined && !isRecord(request.resolvedPlace)) {
    throw new BridgeError("bazi_bridge_invalid_request", "resolvedPlace must be an object");
  }
  return { ...request, detailLevel };
}

export function makeEnvelopeContext(request) {
  const action = typeof request?.tool === "string" && Object.hasOwn(ACTIONS, request.tool)
    ? request.tool
    : null;
  return {
    protocolVersion: PROTOCOL_VERSION,
    requestId: typeof request?.requestId === "string" ? request.requestId : null,
    action,
    resultSchemaVersion: action === null ? null : ACTIONS[action].resultSchemaVersion,
    engine: ENGINE,
    inputFingerprint: null,
  };
}

export function makeErrorEnvelope(request, error) {
  return {
    ok: false,
    ...makeEnvelopeContext(request),
    error: toErrorPayload(error),
    degradedDiagnostics: [],
  };
}
