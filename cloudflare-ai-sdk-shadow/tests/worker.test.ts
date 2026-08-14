import { describe, expect, it } from "vitest";

import { handleRequest, type Env } from "../src/worker.ts";

const env: Env = {
  SIFT_SHADOW_TOKEN: "shadow-test-token-with-enough-entropy",
  SIFT_ENGINE_TOKEN: "engine-test-token-with-enough-entropy",
};

describe("shadow Worker boundary", () => {
  it("protects health and evaluation endpoints with the shadow-only token", async () => {
    const unauthorized = await handleRequest(new Request("https://shadow.test/health"), env);
    const authorized = await handleRequest(
      new Request("https://shadow.test/health", {
        headers: { authorization: `Bearer ${env.SIFT_SHADOW_TOKEN}` },
      }),
      env,
    );

    expect(unauthorized.status).toBe(401);
    expect(authorized.status).toBe(200);
    expect(await authorized.json()).toEqual({
      status: "ok",
      service: "sift-ai-sdk-shadow",
      production: false,
      persistence: false,
    });
  });

  it("returns stable validation errors without echoing the provider key", async () => {
    const providerKey = "test-provider-key-that-must-not-be-returned";
    const response = await handleRequest(
      new Request("https://shadow.test/v1/eval/initial", {
        method: "POST",
        headers: {
          authorization: `Bearer ${env.SIFT_SHADOW_TOKEN}`,
          "content-type": "application/json",
          "x-sift-provider": "openai",
          "x-sift-model": "gpt-5-mini",
          "x-sift-provider-key": providerKey,
        },
        body: JSON.stringify({ messages: [{ role: "assistant", content: "invalid" }] }),
      }),
      env,
    );
    const body = await response.text();

    expect(response.status).toBe(400);
    expect(body).not.toContain(providerKey);
    expect(body).toContain("invalid_request");
  });

  it("rejects unsupported methods, media types, and unknown routes", async () => {
    const authorization = { authorization: `Bearer ${env.SIFT_SHADOW_TOKEN}` };
    expect(
      (await handleRequest(new Request("https://shadow.test/health", { method: "POST", headers: authorization }), env)).status,
    ).toBe(405);
    expect(
      (
        await handleRequest(
          new Request("https://shadow.test/v1/eval/follow-up", {
            method: "POST",
            headers: {
              ...authorization,
              "x-sift-provider": "openai",
              "x-sift-model": "gpt-5-mini",
              "x-sift-provider-key": "test-provider-key",
            },
            body: "{}",
          }),
          env,
        )
      ).status,
    ).toBe(415);
    expect(
      (await handleRequest(new Request("https://shadow.test/production", { headers: authorization }), env)).status,
    ).toBe(404);
  });

  it("requires a configured high-entropy shadow token", async () => {
    const response = await handleRequest(new Request("https://shadow.test/health"), {
      SIFT_SHADOW_TOKEN: "short",
    });
    expect(response.status).toBe(503);
  });

  it("keeps internal engine endpoints inaccessible without the service token", async () => {
    const response = await handleRequest(
      new Request("https://shadow.test/internal/v1/generate", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: "{}",
      }),
      env,
    );

    expect(response.status).toBe(503);
    expect(await response.text()).not.toContain(String(env.SIFT_ENGINE_TOKEN));
  });
});
