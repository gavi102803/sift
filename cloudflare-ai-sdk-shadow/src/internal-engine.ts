import {
  APICallError,
  generateText,
  jsonSchema,
  Output,
  RetryError,
  streamText,
  tool,
  type LanguageModel,
  type ModelMessage,
  type ToolSet,
} from "ai";
import { z } from "zod";

const jsonObjectSchema = z.record(z.string(), z.unknown());

const messageSchema = z.object({
  role: z.enum(["system", "user", "assistant"]),
  content: z.string().min(1).max(100_000),
});

const toolSpecSchema = z.object({
  providerName: z.string().min(1).max(128),
  description: z.string().min(1).max(2_000),
  inputSchema: jsonObjectSchema,
});

const toolObservationSchema = z.object({
  callId: z.string().min(1).max(256),
  providerName: z.string().min(1).max(128),
  arguments: jsonObjectSchema.default({}),
  result: z.unknown(),
  providerContext: jsonObjectSchema.optional(),
});

const baseRequestSchema = z.object({
  messages: z.array(messageSchema).min(1).max(64),
  maxOutputTokens: z.number().int().min(1).max(4_096),
});

export const internalGenerateRequestSchema = baseRequestSchema.extend({
  responseSchema: jsonObjectSchema.optional(),
});

export const internalToolCallRequestSchema = baseRequestSchema.extend({
  tools: z.array(toolSpecSchema).min(1).max(8),
  observations: z.array(toolObservationSchema).max(8).default([]),
  forcedToolName: z.string().min(1).max(128).optional(),
});

export type InternalGenerateRequest = z.infer<typeof internalGenerateRequestSchema>;
export type InternalToolCallRequest = z.infer<typeof internalToolCallRequestSchema>;

export interface InternalGenerationResult {
  content: string;
  model: string;
  input_tokens?: number;
  output_tokens?: number;
}

export interface InternalToolCallResult {
  tool_calls: Array<{
    id: string;
    name: string;
    arguments: unknown;
    provider_context: { assistantMessages: ModelMessage[] };
  }>;
  input_tokens?: number;
  output_tokens?: number;
}

export type InternalStreamEvent =
  | { type: "delta"; delta: string }
  | {
      type: "completed";
      content: string;
      model: string;
      input_tokens?: number;
      output_tokens?: number;
    }
  | { type: "error"; code: InternalErrorCode };

export type InternalErrorCode =
  | "invalid_provider_key"
  | "provider_quota_exhausted"
  | "provider_error"
  | "cancelled"
  | "timeout";

const TELEMETRY_DISABLED = {
  isEnabled: false,
  recordInputs: false,
  recordOutputs: false,
} as const;

export async function generateInternal(
  input: InternalGenerateRequest,
  model: LanguageModel,
  abortSignal?: AbortSignal,
): Promise<InternalGenerationResult> {
  const messages = textMessages(input.messages);
  if (input.responseSchema) {
    const result = await generateText({
      model,
      messages,
      maxRetries: 0,
      maxOutputTokens: input.maxOutputTokens,
      abortSignal,
      telemetry: TELEMETRY_DISABLED,
      output: Output.object({ schema: jsonSchema(input.responseSchema) }),
    });
    return {
      content: JSON.stringify(result.output),
      model: result.response.modelId,
      input_tokens: result.usage.inputTokens,
      output_tokens: result.usage.outputTokens,
    };
  }

  const result = await generateText({
    model,
    messages,
    maxRetries: 0,
    maxOutputTokens: input.maxOutputTokens,
    abortSignal,
    telemetry: TELEMETRY_DISABLED,
  });
  return {
    content: result.text,
    model: result.response.modelId,
    input_tokens: result.usage.inputTokens,
    output_tokens: result.usage.outputTokens,
  };
}

export async function requestInternalToolCalls(
  input: InternalToolCallRequest,
  model: LanguageModel,
  abortSignal?: AbortSignal,
): Promise<InternalToolCallResult> {
  const tools = Object.fromEntries(
    input.tools.map((spec) => [
      spec.providerName,
      tool({
        description: spec.description,
        inputSchema: jsonSchema(spec.inputSchema),
      }),
    ]),
  ) satisfies ToolSet;
  const messages = [...textMessages(input.messages), ...observationMessages(input.observations)];
  const result = await generateText({
    model,
    messages,
    tools,
    toolChoice: input.forcedToolName
      ? { type: "tool", toolName: input.forcedToolName }
      : "auto",
    maxRetries: 0,
    maxOutputTokens: input.maxOutputTokens,
    abortSignal,
    telemetry: TELEMETRY_DISABLED,
  });
  const assistantMessages = result.response.messages;
  return {
    tool_calls: result.toolCalls.map((call) => ({
      id: call.toolCallId,
      name: call.toolName,
      arguments: call.input,
      provider_context: { assistantMessages },
    })),
    input_tokens: result.usage.inputTokens,
    output_tokens: result.usage.outputTokens,
  };
}

export async function* streamInternal(
  input: InternalGenerateRequest,
  model: LanguageModel,
  abortSignal?: AbortSignal,
): AsyncIterable<InternalStreamEvent> {
  try {
    const result = streamText({
      model,
      messages: textMessages(input.messages),
      maxRetries: 0,
      maxOutputTokens: input.maxOutputTokens,
      abortSignal,
      telemetry: TELEMETRY_DISABLED,
    });
    let content = "";
    let modelId = typeof model === "string" ? model : model.modelId;
    let inputTokens: number | undefined;
    let outputTokens: number | undefined;
    for await (const part of result.fullStream) {
      if (part.type === "text-delta") {
        content += part.text;
        yield { type: "delta", delta: part.text };
      } else if (part.type === "finish") {
        inputTokens = part.totalUsage.inputTokens;
        outputTokens = part.totalUsage.outputTokens;
      } else if (part.type === "finish-step") {
        modelId = part.response.modelId;
      } else if (part.type === "abort") {
        yield { type: "error", code: abortCode(abortSignal) };
        return;
      } else if (part.type === "error") {
        yield { type: "error", code: internalErrorCode(part.error, abortSignal) };
        return;
      }
    }
    yield {
      type: "completed",
      content,
      model: modelId,
      input_tokens: inputTokens,
      output_tokens: outputTokens,
    };
  } catch (error) {
    yield { type: "error", code: internalErrorCode(error, abortSignal) };
  }
}

export function internalErrorCode(
  error: unknown,
  abortSignal?: AbortSignal,
): InternalErrorCode {
  if (
    abortSignal?.aborted ||
    (error instanceof DOMException && error.name === "AbortError")
  ) {
    return abortCode(abortSignal);
  }
  const apiError = findApiCallError(error);
  if (apiError?.statusCode === 401 || apiError?.statusCode === 403) {
    return "invalid_provider_key";
  }
  if (apiError?.statusCode === 402 || apiError?.statusCode === 429) {
    return "provider_quota_exhausted";
  }
  return "provider_error";
}

function findApiCallError(error: unknown) {
  const pending: unknown[] = [error];
  const visited = new Set<unknown>();
  while (pending.length > 0) {
    const current = pending.shift();
    if (current == null || visited.has(current)) continue;
    visited.add(current);
    if (APICallError.isInstance(current)) return current;
    if (RetryError.isInstance(current)) {
      pending.push(current.lastError, ...current.errors);
    }
    if (current instanceof Error && current.cause != null) {
      pending.push(current.cause);
    }
  }
  return undefined;
}

function abortCode(abortSignal?: AbortSignal): "cancelled" | "timeout" {
  return abortSignal?.reason === "sift-engine-timeout" ? "timeout" : "cancelled";
}

function textMessages(messages: Array<z.infer<typeof messageSchema>>): ModelMessage[] {
  return messages.map((message) => ({ role: message.role, content: message.content }));
}

function observationMessages(
  observations: Array<z.infer<typeof toolObservationSchema>>,
): ModelMessage[] {
  const messages: ModelMessage[] = [];
  const groups = new Map<string, typeof observations>();

  for (const observation of observations) {
    const assistantMessages = observation.providerContext?.assistantMessages;
    const key = Array.isArray(assistantMessages)
      ? JSON.stringify(assistantMessages)
      : `fallback:${observation.callId}`;
    const group = groups.get(key) ?? [];
    group.push(observation);
    groups.set(key, group);
  }

  for (const group of groups.values()) {
    const assistantMessages = group[0]?.providerContext?.assistantMessages;
    if (isModelMessageArray(assistantMessages)) {
      messages.push(...assistantMessages);
    } else {
      messages.push({
        role: "assistant",
        content: group.map((observation) => ({
          type: "tool-call" as const,
          toolCallId: observation.callId,
          toolName: observation.providerName,
          input: observation.arguments,
        })),
      });
    }
    messages.push({
      role: "tool",
      content: group.map((observation) => ({
        type: "tool-result" as const,
        toolCallId: observation.callId,
        toolName: observation.providerName,
        output: { type: "json" as const, value: jsonValue(observation.result) },
      })),
    });
  }
  return messages;
}

function isModelMessageArray(value: unknown): value is ModelMessage[] {
  return (
    Array.isArray(value) &&
    value.length > 0 &&
    value.every(
      (message) =>
        typeof message === "object" &&
        message !== null &&
        ["assistant", "tool"].includes(String((message as { role?: unknown }).role)),
    )
  );
}

function jsonValue(value: unknown) {
  return JSON.parse(JSON.stringify(value ?? null)) as never;
}
