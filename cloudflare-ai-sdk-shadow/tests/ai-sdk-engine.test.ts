import { MockLanguageModelV4 } from "ai/test";
import { describe, expect, it } from "vitest";

import { AiSdkAgentEngine } from "../src/ai-sdk-engine.ts";
import type { EvalKind, SiftAgentEvent } from "../src/contracts.ts";
import {
  cardResult,
  collectEvents,
  evidence,
  mockModel,
  request,
  textStream,
  textThenErrorStream,
  toolCallStream,
  validCard,
} from "./fixtures.ts";

describe("AiSdkAgentEngine", () => {
  it("keeps the core event contract ordered and emits sources before deltas", async () => {
    const model = mockModel({ streams: textStream("Durability prevents duplicate work [1].") });
    const events = await execute(model, "initial", request());
    const types = events.map((event) => event.type);

    expect(types).toEqual([
      "run_started",
      "sources",
      "step_started",
      "delta",
      "card",
      "usage",
      "terminal",
    ]);
    expect(types.indexOf("sources")).toBeLessThan(types.indexOf("delta"));
    expect(events.map((event) => event.sequence)).toEqual([0, 1, 2, 3, 4, 5, 6]);
    expect(events.find((event) => event.type === "card")).toMatchObject({ card: validCard });
    expect(events.find((event) => event.type === "usage")).toMatchObject({
      usage: { modelCalls: 2, toolCalls: 0, inputTokens: 20, outputTokens: 10 },
    });
  });

  it("runs the upstream bounded agent loop through search, extract, answer, and card", async () => {
    const model = mockModel({
      streams: [
        toolCallStream("call-search", "web_search", { query: "durable state", limit: 3 }),
        toolCallStream("call-extract", "extract_url", { sourceId: "source-1" }),
        textStream("Checkpointed work can resume safely [1]."),
      ],
    });
    const events = await execute(
      model,
      "initial",
      request({ mode: "agent" }),
    );

    expect(events.filter((event) => event.type === "step_started")).toHaveLength(3);
    expect(
      events.filter((event) => event.type === "tool_call").map((event) => event.toolName),
    ).toEqual(["web_search", "extract_url"]);
    expect(events.at(-1)).toMatchObject({ type: "terminal", status: "succeeded" });
    expect(events.find((event) => event.type === "usage")).toMatchObject({
      usage: { modelCalls: 4, toolCalls: 2 },
    });
  });

  it("caches duplicate tool inputs instead of repeating physical work", async () => {
    const model = mockModel({
      streams: [
        toolCallStream("call-1", "web_search", { query: "durable state", limit: 3 }),
        toolCallStream("call-2", "web_search", { query: "durable state", limit: 3 }),
        textStream("Checkpointing matters [1]."),
      ],
    });
    const events = await execute(
      model,
      "follow-up",
      request({
        mode: "agent",
        budget: {
          maxModelCalls: 3,
          maxSteps: 3,
          maxToolCalls: 1,
          maxOutputTokensPerCall: 1_200,
          timeoutMs: 45_000,
        },
      }),
    );
    const toolResults = events.filter((event) => event.type === "tool_result");

    expect(toolResults).toHaveLength(2);
    expect(toolResults[0]).toMatchObject({ output: { cached: false } });
    expect(toolResults[1]).toMatchObject({ output: { cached: true } });
    expect(events.find((event) => event.type === "usage")).toMatchObject({
      usage: { toolCalls: 1 },
    });
  });

  it("terminates when a unique tool call exceeds the Sift-owned budget", async () => {
    const model = mockModel({
      streams: [
        toolCallStream("call-1", "web_search", { query: "durable state", limit: 3 }),
        toolCallStream("call-2", "extract_url", { sourceId: "source-1" }),
      ],
    });
    const events = await execute(
      model,
      "follow-up",
      request({
        mode: "agent",
        budget: {
          maxModelCalls: 3,
          maxSteps: 3,
          maxToolCalls: 1,
          maxOutputTokensPerCall: 1_200,
          timeoutMs: 45_000,
        },
      }),
    );

    expect(events.at(-1)).toMatchObject({ type: "error", code: "budget_exceeded" });
    expect(events.some((event) => event.type === "terminal")).toBe(false);
  });

  it("rejects citations outside the run evidence universe", async () => {
    const events = await execute(
      mockModel({ streams: textStream("This citation is not available [2].") }),
      "follow-up",
      request(),
    );

    expect(events.at(-1)).toMatchObject({ type: "error", code: "citation_violation" });
  });

  it("rejects structured cards that cite unknown source ids", async () => {
    const events = await execute(
      mockModel({
        streams: textStream("Durability matters [1]."),
        cards: cardResult({ ...validCard, sourceIds: ["unknown-source"] }),
      }),
      "initial",
      request(),
    );

    expect(events.at(-1)).toMatchObject({ type: "error", code: "citation_violation" });
  });

  it("maps invalid structured output to a stable redacted schema error", async () => {
    const events = await execute(
      mockModel({
        streams: textStream("Durability matters [1]."),
        cards: cardResult({ title: "missing required fields" }),
      }),
      "initial",
      request(),
    );

    expect(events.at(-1)).toMatchObject({
      type: "error",
      code: "schema_validation_failed",
      message: "The structured concept card did not pass validation.",
    });
  });

  it("does not retry or leak provider errors after the first delta", async () => {
    const secret = "sk-live-secret-that-must-never-appear";
    const model = mockModel({
      streams: textThenErrorStream("partial", new Error(`provider rejected ${secret}`)),
    });
    const events = await execute(model, "follow-up", request());

    expect(model.doStreamCalls).toHaveLength(1);
    expect(events.filter((event) => event.type === "delta")).toHaveLength(1);
    expect(events.at(-1)).toMatchObject({ type: "error", code: "provider_error" });
    expect(JSON.stringify(events)).not.toContain(secret);
  });

  it("propagates Sift cancellation without starting a retry", async () => {
    const controller = new AbortController();
    controller.abort("test-cancel");
    const model = mockModel({ streams: textStream("should not complete") });
    const events = await execute(model, "follow-up", request(), controller.signal);

    expect(events.at(-1)).toMatchObject({ type: "error", code: "cancelled" });
    expect(model.doStreamCalls.length).toBeLessThanOrEqual(1);
  });

  it("applies one total timeout owned by the Sift execution envelope", async () => {
    const model = new MockLanguageModelV4({
      provider: "sift-shadow-test",
      modelId: "timeout-model",
      doStream: async ({ abortSignal }) =>
        await new Promise((_, reject) => {
          const rejectAbort = () => reject(new DOMException("aborted", "AbortError"));
          abortSignal?.addEventListener("abort", rejectAbort, { once: true });
        }),
    });
    const events = await execute(
      model,
      "follow-up",
      {
        ...request(),
        budget: { ...request().budget, timeoutMs: 5 },
      },
    );

    expect(events.at(-1)).toMatchObject({ type: "error", code: "timeout", retryable: true });
    expect(model.doStreamCalls).toHaveLength(1);
  });

  it.each(Array.from({ length: 30 }, (_, index) => index))(
    "completes mock initial/follow-up scenario %i",
    async (index) => {
      const kind: EvalKind = index % 2 === 0 ? "initial" : "follow-up";
      const model = mockModel({ streams: textStream(`Scenario ${index} is grounded [1].`) });
      const events = await execute(model, kind, request());

      expect(events.at(-1)).toMatchObject({ type: "terminal", status: "succeeded" });
      expect(events.filter((event) => event.type === "card")).toHaveLength(
        kind === "initial" ? 1 : 0,
      );
    },
  );
});

async function execute(
  model: MockLanguageModelV4,
  kind: EvalKind,
  input: ReturnType<typeof request>,
  abortSignal?: AbortSignal,
): Promise<SiftAgentEvent[]> {
  return collectEvents(
    new AiSdkAgentEngine().execute({ kind, request: input, model, abortSignal }),
  );
}
