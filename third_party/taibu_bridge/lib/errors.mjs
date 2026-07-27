export class BridgeError extends Error {
  constructor(code, message, { retryable = false, details } = {}) {
    super(message);
    this.name = "BridgeError";
    this.code = code;
    this.retryable = retryable;
    this.details = details;
  }
}

export function toErrorPayload(error) {
  if (error instanceof BridgeError) {
    return {
      code: error.code,
      message: error.message,
      retryable: error.retryable,
      ...(error.details === undefined ? {} : { details: error.details }),
    };
  }
  return {
    code: "bazi_engine_error",
    message: "Bazi engine rejected the request",
    retryable: false,
  };
}
