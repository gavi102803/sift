import type { EngineErrorCode } from "./contracts.ts";

export class EngineError extends Error {
  constructor(
    readonly code: EngineErrorCode,
    readonly retryable: boolean,
  ) {
    super(code);
    this.name = "EngineError";
  }
}

export class RequestError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
  ) {
    super(message);
    this.name = "RequestError";
  }
}
