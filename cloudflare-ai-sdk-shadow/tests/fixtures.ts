import { MockLanguageModelV4, simulateReadableStream } from "ai/test";

import {
  DEFAULT_AGENT_BUDGET,
  evalRequestSchema,
  type ConceptCard,
  type EvalRequest,
  type SiftAgentEvent,
} from "../src/contracts.ts";

type StreamResult = Awaited<ReturnType<MockLanguageModelV4["doStream"]>>;
type StreamPart = StreamResult["stream"] extends ReadableStream<infer Part> ? Part : never;
type GenerateResult = Awaited<ReturnType<MockLanguageModelV4["doGenerate"]>>;

export const evidence = [
  {
    id: "source-1",
    title: "Durable agent state",
    url: "https://example.com/durable-state",
    excerpt: "Durable state makes interrupted work recoverable.",
    content: "Checkpoints and idempotency prevent duplicated work after a disconnect.",
  },
];

export const validCard: ConceptCard = {
  title: "Durable agent state",
  summary: "A durable control plane can recover interrupted model work.",
  keyPoints: ["Checkpoint progress", "Preserve idempotency"],
  sourceIds: ["source-1"],
};

export function request(overrides: Partial<EvalRequest> = {}): EvalRequest {
  return evalRequestSchema.parse({
    runId: "00000000-0000-4000-8000-000000000001",
    mode: "core",
    messages: [{ role: "user", content: "Why should agent state be durable?" }],
    evidence,
    budget: DEFAULT_AGENT_BUDGET,
    ...overrides,
  });
}

export function textStream(text: string): StreamResult {
  return stream([
    { type: "stream-start", warnings: [] },
    { type: "text-start", id: "text-1" },
    { type: "text-delta", id: "text-1", delta: text },
    { type: "text-end", id: "text-1" },
    { type: "finish", usage: usage(12, 6), finishReason: finishReason("stop") },
  ]);
}

export function textThenErrorStream(text: string, error: unknown): StreamResult {
  return stream([
    { type: "stream-start", warnings: [] },
    { type: "text-start", id: "text-1" },
    { type: "text-delta", id: "text-1", delta: text },
    { type: "error", error },
  ]);
}

export function toolCallStream(
  toolCallId: string,
  toolName: string,
  input: Record<string, unknown>,
): StreamResult {
  return stream([
    { type: "stream-start", warnings: [] },
    { type: "tool-call", toolCallId, toolName, input: JSON.stringify(input) },
    { type: "finish", usage: usage(10, 3), finishReason: finishReason("tool-calls") },
  ]);
}

export function cardResult(card: unknown = validCard): GenerateResult {
  return {
    content: [{ type: "text", text: JSON.stringify(card) }],
    finishReason: finishReason("stop"),
    usage: usage(8, 4),
    warnings: [],
  };
}

export function mockModel(options: {
  streams: StreamResult | StreamResult[];
  cards?: GenerateResult | GenerateResult[];
}): MockLanguageModelV4 {
  return new MockLanguageModelV4({
    provider: "sift-shadow-test",
    modelId: "shadow-test-model",
    doStream: options.streams,
    doGenerate: options.cards ?? cardResult(),
  });
}

export async function collectEvents(
  events: AsyncIterable<SiftAgentEvent>,
): Promise<SiftAgentEvent[]> {
  const collected: SiftAgentEvent[] = [];
  for await (const event of events) collected.push(event);
  return collected;
}

function stream(chunks: StreamPart[]): StreamResult {
  return {
    stream: simulateReadableStream<StreamPart>({
      chunks,
      initialDelayInMs: null,
      chunkDelayInMs: null,
    }),
  };
}

function finishReason(unified: "stop" | "tool-calls") {
  return { unified, raw: unified } as const;
}

function usage(inputTokens: number, outputTokens: number) {
  return {
    inputTokens: {
      total: inputTokens,
      noCache: inputTokens,
      cacheRead: 0,
      cacheWrite: 0,
    },
    outputTokens: {
      total: outputTokens,
      text: outputTokens,
      reasoning: 0,
    },
  };
}
