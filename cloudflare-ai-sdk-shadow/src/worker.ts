import { AiSdkAgentEngine } from "./ai-sdk-engine.ts";
import { evalRequestSchema, type EvalKind, type SiftAgentEvent } from "./contracts.ts";
import { RequestError } from "./errors.ts";
import {
  generateInternal,
  internalErrorCode,
  internalGenerateRequestSchema,
  internalToolCallRequestSchema,
  requestInternalToolCalls,
  streamInternal,
  type InternalStreamEvent,
} from "./internal-engine.ts";
import {
  createProviderModel,
  readProviderRequest,
  type ProviderEnvironment,
} from "./providers.ts";

export interface Env extends ProviderEnvironment {
  SIFT_SHADOW_TOKEN?: string;
  SIFT_ENGINE_TOKEN?: string;
}

const JSON_HEADERS = {
  "cache-control": "no-store",
  "content-type": "application/json; charset=utf-8",
  "x-content-type-options": "nosniff",
};

const STREAM_HEADERS = {
  "cache-control": "no-store, no-transform",
  "content-type": "application/x-ndjson; charset=utf-8",
  "x-content-type-options": "nosniff",
};

export async function handleRequest(request: Request, env: Env): Promise<Response> {
  try {
    const url = new URL(request.url);

    if (url.pathname.startsWith("/internal/v1/")) {
      return await handleInternalRequest(request, env, url.pathname);
    }

    assertConfigured(env);
    assertAuthorized(request, env);

    if (url.pathname === "/health") {
      if (request.method !== "GET") return methodNotAllowed("GET");
      return jsonResponse({
        status: "ok",
        service: "sift-ai-sdk-shadow",
        production: false,
        persistence: false,
      });
    }

    const kind = evalKind(url.pathname);
    if (!kind) return problem(404, "not_found", "Shadow endpoint not found.");
    if (request.method !== "POST") return methodNotAllowed("POST");
    requireJSON(request);

    const providerRequest = readProviderRequest(request.headers);
    const model = createProviderModel(providerRequest, env);
    const input = evalRequestSchema.safeParse(await readJSON(request));
    if (!input.success) {
      return problem(400, "invalid_request", "Shadow evaluation request is invalid.", {
        issues: input.error.issues.map((issue) => ({ path: issue.path, message: issue.message })),
      });
    }
    if (kind === "initial" && input.data.budget.maxModelCalls < 2) {
      return problem(
        400,
        "invalid_budget",
        "Initial evaluation requires at least two model calls.",
      );
    }

    const responseAbort = new AbortController();
    const onRequestAbort = () => responseAbort.abort(request.signal.reason);
    request.signal.addEventListener("abort", onRequestAbort, { once: true });
    if (request.signal.aborted) responseAbort.abort(request.signal.reason);

    const engine = new AiSdkAgentEngine();
    const events = engine.execute({
      kind,
      request: input.data,
      model,
      abortSignal: responseAbort.signal,
    });
    return ndjsonResponse(events, responseAbort, () =>
      request.signal.removeEventListener("abort", onRequestAbort),
    );
  } catch (error) {
    if (error instanceof RequestError) {
      return problem(error.status, error.code, error.message);
    }
    return problem(500, "internal_error", "The shadow Worker could not start the evaluation.");
  }
}

async function handleInternalRequest(
  request: Request,
  env: Env,
  pathname: string,
): Promise<Response> {
  assertEngineAuthorized(request, env);
  if (request.method !== "POST") return methodNotAllowed("POST");
  requireJSON(request);

  const providerRequest = readProviderRequest(request.headers);
  const model = createProviderModel(providerRequest, env);
  const body = await readJSON(request);
  const abort = createRequestAbort(request.signal, 45_000);
  try {
    if (pathname === "/internal/v1/generate") {
      const input = internalGenerateRequestSchema.safeParse(body);
      if (!input.success) return problem(400, "invalid_request", "Engine request is invalid.");
      return jsonResponse(await generateInternal(input.data, model, abort.signal));
    }
    if (pathname === "/internal/v1/tool-calls") {
      const input = internalToolCallRequestSchema.safeParse(body);
      if (!input.success) return problem(400, "invalid_request", "Engine request is invalid.");
      return jsonResponse(await requestInternalToolCalls(input.data, model, abort.signal));
    }
    if (pathname === "/internal/v1/stream") {
      const input = internalGenerateRequestSchema.safeParse(body);
      if (!input.success) return problem(400, "invalid_request", "Engine request is invalid.");
      return internalNdjsonResponse(streamInternal(input.data, model, abort.signal), abort);
    }
    return problem(404, "not_found", "Engine endpoint not found.");
  } catch (error) {
    const code = internalErrorCode(error, abort.signal);
    if (code === "invalid_provider_key") {
      return problem(401, code, "Check the provider API key.");
    }
    if (code === "provider_quota_exhausted") {
      return problem(429, code, "The provider quota is exhausted.");
    }
    return problem(502, code, "The model provider request failed.");
  } finally {
    if (pathname !== "/internal/v1/stream") abort.dispose();
  }
}

export default {
  fetch: handleRequest,
} satisfies ExportedHandler<Env>;

function evalKind(pathname: string): EvalKind | undefined {
  if (pathname === "/v1/eval/initial") return "initial";
  if (pathname === "/v1/eval/follow-up") return "follow-up";
  return undefined;
}

function assertConfigured(env: Env): void {
  if (!env.SIFT_SHADOW_TOKEN || env.SIFT_SHADOW_TOKEN.length < 24) {
    throw new RequestError(503, "shadow_not_configured", "Shadow authentication is unavailable.");
  }
}

function assertAuthorized(request: Request, env: Env): void {
  const authorization = request.headers.get("authorization") ?? "";
  const expected = `Bearer ${env.SIFT_SHADOW_TOKEN}`;
  if (!constantTimeEqual(authorization, expected)) {
    throw new RequestError(401, "unauthorized", "Shadow authorization failed.");
  }
}

function assertEngineAuthorized(request: Request, env: Env): void {
  const supplied = request.headers.get("x-sift-engine-token") ?? "";
  const expected = env.SIFT_ENGINE_TOKEN ?? "";
  if (expected.length < 24 || !constantTimeEqual(supplied, expected)) {
    throw new RequestError(503, "engine_unavailable", "Engine authorization failed.");
  }
}

interface RequestAbort {
  signal: AbortSignal;
  dispose(): void;
}

function createRequestAbort(parent: AbortSignal, timeoutMs: number): RequestAbort {
  const controller = new AbortController();
  const onAbort = () => controller.abort(parent.reason);
  parent.addEventListener("abort", onAbort, { once: true });
  if (parent.aborted) controller.abort(parent.reason);
  const timer = setTimeout(() => controller.abort("sift-engine-timeout"), timeoutMs);
  return {
    signal: controller.signal,
    dispose() {
      clearTimeout(timer);
      parent.removeEventListener("abort", onAbort);
    },
  };
}

function internalNdjsonResponse(
  events: AsyncIterable<InternalStreamEvent>,
  abort: RequestAbort,
): Response {
  const encoder = new TextEncoder();
  const stream = new ReadableStream<Uint8Array>({
    async start(controller) {
      try {
        for await (const event of events) {
          controller.enqueue(encoder.encode(`${JSON.stringify(event)}\n`));
        }
        controller.close();
      } catch {
        controller.error(new Error("engine_stream_failed"));
      } finally {
        abort.dispose();
      }
    },
    cancel() {
      abort.dispose();
    },
  });
  return new Response(stream, { status: 200, headers: STREAM_HEADERS });
}

function constantTimeEqual(left: string, right: string): boolean {
  const length = Math.max(left.length, right.length);
  let difference = left.length ^ right.length;
  for (let index = 0; index < length; index += 1) {
    difference |= (left.charCodeAt(index) || 0) ^ (right.charCodeAt(index) || 0);
  }
  return difference === 0;
}

function requireJSON(request: Request): void {
  if (!request.headers.get("content-type")?.toLowerCase().startsWith("application/json")) {
    throw new RequestError(415, "unsupported_media_type", "Content-Type must be application/json.");
  }
}

async function readJSON(request: Request): Promise<unknown> {
  const declaredLength = Number(request.headers.get("content-length") ?? "0");
  if (declaredLength > 1_048_576) {
    throw new RequestError(413, "request_too_large", "Shadow request exceeds 1 MiB.");
  }
  const body = await request.text();
  if (new TextEncoder().encode(body).byteLength > 1_048_576) {
    throw new RequestError(413, "request_too_large", "Shadow request exceeds 1 MiB.");
  }
  try {
    return JSON.parse(body) as unknown;
  } catch {
    throw new RequestError(400, "invalid_json", "Request body is not valid JSON.");
  }
}

function ndjsonResponse(
  events: AsyncIterable<SiftAgentEvent>,
  abortController: AbortController,
  dispose: () => void,
): Response {
  const encoder = new TextEncoder();
  const stream = new ReadableStream<Uint8Array>({
    async start(controller) {
      try {
        for await (const event of events) {
          controller.enqueue(encoder.encode(`${JSON.stringify(event)}\n`));
        }
        controller.close();
      } catch {
        controller.error(new Error("shadow_stream_failed"));
      } finally {
        dispose();
      }
    },
    cancel() {
      abortController.abort("shadow-client-disconnected");
      dispose();
    },
  });
  return new Response(stream, { status: 200, headers: STREAM_HEADERS });
}

function methodNotAllowed(allow: string): Response {
  return problem(405, "method_not_allowed", "Method is not allowed.", undefined, {
    allow,
  });
}

function jsonResponse(body: unknown, init: ResponseInit = {}): Response {
  return new Response(JSON.stringify(body), {
    ...init,
    headers: { ...JSON_HEADERS, ...init.headers },
  });
}

function problem(
  status: number,
  code: string,
  message: string,
  details?: unknown,
  headers?: HeadersInit,
): Response {
  return jsonResponse(
    { error: { code, message, ...(details === undefined ? {} : { details }) } },
    { status, headers },
  );
}
