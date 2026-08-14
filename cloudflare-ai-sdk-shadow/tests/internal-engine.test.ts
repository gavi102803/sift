import { APICallError, RetryError } from "ai";
import { MockLanguageModelV4 } from "ai/test";
import { describe, expect, it } from "vitest";

import {
  generateInternal,
  internalErrorCode,
  requestInternalToolCalls,
  streamInternal,
} from "../src/internal-engine.ts";
import { cardResult, mockModel, textStream } from "./fixtures.ts";

describe("internal AI SDK engine contract", () => {
  it("generates schema-validated JSON with SDK retries disabled", async () => {
    const model = mockModel({
      streams: textStream("unused"),
      cards: cardResult({ answer: "Structured answer" }),
    });
    const result = await generateInternal(
      {
        messages: [{ role: "user", content: "Return a structured answer." }],
        maxOutputTokens: 1_024,
        responseSchema: {
          type: "object",
          additionalProperties: false,
          required: ["answer"],
          properties: { answer: { type: "string" } },
        },
      },
      model,
    );

    expect(JSON.parse(result.content)).toEqual({ answer: "Structured answer" });
    expect(result).toMatchObject({
      model: "shadow-test-model",
      input_tokens: 8,
      output_tokens: 4,
    });
    expect(model.doGenerateCalls).toHaveLength(1);
  });

  it("normalizes tool calls and replays checkpointed native SDK messages", async () => {
    const model = new MockLanguageModelV4({
      provider: "sift-shadow-test",
      modelId: "shadow-test-model",
      doGenerate: [
        toolCallResult("call-search", "web_search", { query: "Sift runtime" }),
        cardResult({}),
      ],
    });
    const input = {
      messages: [{ role: "user" as const, content: "Search for Sift runtime." }],
      maxOutputTokens: 512,
      tools: [
        {
          providerName: "web_search",
          description: "Search the public web.",
          inputSchema: {
            type: "object",
            required: ["query"],
            properties: { query: { type: "string" } },
          },
        },
      ],
      observations: [],
    };

    const first = await requestInternalToolCalls(input, model);
    expect(first.tool_calls).toHaveLength(1);
    expect(first.tool_calls[0]).toMatchObject({
      id: "call-search",
      name: "web_search",
      arguments: { query: "Sift runtime" },
    });

    await requestInternalToolCalls(
      {
        ...input,
        observations: [
          {
            callId: "call-search",
            providerName: "web_search",
            arguments: { query: "Sift runtime" },
            result: [{ title: "Sift", url: "https://example.com/sift" }],
            providerContext: first.tool_calls[0]?.provider_context,
          },
        ],
      },
      model,
    );

    const replayed = model.doGenerateCalls[1]?.prompt ?? [];
    expect(replayed.some((message) => message.role === "assistant")).toBe(true);
    expect(replayed.some((message) => message.role === "tool")).toBe(true);
    expect(model.doGenerateCalls).toHaveLength(2);
  });

  it("streams normalized deltas, usage, and one terminal event", async () => {
    const model = mockModel({ streams: textStream("Streaming answer") });
    const events = [];
    for await (const event of streamInternal(
      {
        messages: [{ role: "user", content: "Answer." }],
        maxOutputTokens: 1_024,
      },
      model,
    )) {
      events.push(event);
    }

    expect(events).toEqual([
      { type: "delta", delta: "Streaming answer" },
      {
        type: "completed",
        content: "Streaming answer",
        model: "shadow-test-model",
        input_tokens: 12,
        output_tokens: 6,
      },
    ]);
    expect(model.doStreamCalls).toHaveLength(1);
  });

  it("maps provider status through the SDK retry error envelope", () => {
    const providerError = new APICallError({
      message: "redacted by the engine boundary",
      url: "https://provider.example/v1",
      requestBodyValues: {},
      statusCode: 401,
      isRetryable: false,
    });
    const retryError = new RetryError({
      message: "retry envelope",
      reason: "errorNotRetryable",
      errors: [providerError],
    });

    expect(internalErrorCode(retryError)).toBe("invalid_provider_key");
  });
});

function toolCallResult(
  toolCallId: string,
  toolName: string,
  input: Record<string, unknown>,
): Awaited<ReturnType<MockLanguageModelV4["doGenerate"]>> {
  return {
    content: [
      {
        type: "tool-call",
        toolCallId,
        toolName,
        input: JSON.stringify(input),
      },
    ],
    finishReason: { unified: "tool-calls", raw: "tool-calls" },
    usage: {
      inputTokens: { total: 10, noCache: 10, cacheRead: 0, cacheWrite: 0 },
      outputTokens: { total: 3, text: 3, reasoning: 0 },
    },
    warnings: [],
  };
}
