import { describe, expect, it } from "vitest";

import { evalRequestSchema } from "../src/contracts.ts";
import { evidence } from "./fixtures.ts";

describe("shadow request contract", () => {
  it("applies bounded defaults", () => {
    const result = evalRequestSchema.parse({
      messages: [{ role: "user", content: "hello" }],
    });

    expect(result.budget).toEqual({
      maxModelCalls: 5,
      maxSteps: 4,
      maxToolCalls: 4,
      maxOutputTokensPerCall: 1_200,
      timeoutMs: 45_000,
    });
    expect(result.allowedTools).toEqual(["web_search", "extract_url"]);
  });

  it("rejects duplicate evidence ids and non-user terminal messages", () => {
    const result = evalRequestSchema.safeParse({
      messages: [{ role: "assistant", content: "hello" }],
      evidence: [evidence[0], evidence[0]],
    });

    expect(result.success).toBe(false);
    if (!result.success) {
      expect(result.error.issues.map((issue) => issue.message)).toEqual(
        expect.arrayContaining([
          "the final message must be from the user",
          "evidence source ids must be unique",
        ]),
      );
    }
  });

  it("rejects unregistered tools and unbounded budgets", () => {
    expect(
      evalRequestSchema.safeParse({
        messages: [{ role: "user", content: "hello" }],
        allowedTools: ["shell"],
        budget: { maxSteps: 99 },
      }).success,
    ).toBe(false);
  });
});
