import { describe, expect, it } from "vitest";

import { createProviderModel, readProviderRequest } from "../src/providers.ts";
import { RequestError } from "../src/errors.ts";

describe("provider boundary", () => {
  it.each([
    ["openai", "gpt-5-mini"],
    ["anthropic", "claude-sonnet-4"],
    ["google", "gemini-2.5-flash"],
  ] as const)("creates an upstream %s model without a custom adapter", (provider, model) => {
    const result = createProviderModel(
      { provider, model, apiKey: "test-provider-key" },
      {},
    );

    expect(typeof result).not.toBe("string");
    if (typeof result !== "string") {
      expect(result.modelId).toBe(model);
      expect(result.provider).toContain(provider === "google" ? "google" : provider);
    }
  });

  it("requires compatible endpoints to be exact HTTPS allowlist entries", () => {
    const request = {
      provider: "openai-compatible" as const,
      model: "compatible-model",
      apiKey: "test-provider-key",
      baseURL: "https://models.example.com/v1/",
    };

    expect(() => createProviderModel(request, {})).toThrowError(RequestError);
    const compatible = createProviderModel(request, {
        SIFT_SHADOW_ALLOWED_BASE_URLS: "https://models.example.com/v1",
      });
    expect(typeof compatible).not.toBe("string");
    if (typeof compatible !== "string") {
      expect(compatible.modelId).toBe("compatible-model");
    }
    expect(() =>
      createProviderModel(
        { ...request, baseURL: "http://127.0.0.1:8080/v1" },
        { SIFT_SHADOW_ALLOWED_BASE_URLS: "http://127.0.0.1:8080/v1" },
      ),
    ).toThrowError(RequestError);
  });

  it("reads credentials from headers without accepting them in the body contract", () => {
    const parsed = readProviderRequest(
      new Headers({
        "x-sift-provider": "openai",
        "x-sift-model": "gpt-5-mini",
        "x-sift-provider-key": "test-provider-key",
      }),
    );

    expect(parsed).toEqual({
      provider: "openai",
      model: "gpt-5-mini",
      apiKey: "test-provider-key",
      baseURL: undefined,
    });
  });
});
