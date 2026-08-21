import { createAnthropic } from "@ai-sdk/anthropic";
import { createGoogle } from "@ai-sdk/google";
import { createOpenAI } from "@ai-sdk/openai";
import { createOpenAICompatible } from "@ai-sdk/openai-compatible";
import {
  extractJsonMiddleware,
  wrapLanguageModel,
  type LanguageModel,
} from "ai";

import { providerNameSchema, type ProviderName } from "./contracts.ts";
import { RequestError } from "./errors.ts";

export interface ProviderRequest {
  provider: ProviderName;
  model: string;
  apiKey: string;
  baseURL?: string;
}

export interface ProviderEnvironment {
  SIFT_SHADOW_ALLOWED_BASE_URLS?: string;
}

const MODEL_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}$/;

export function readProviderRequest(headers: Headers): ProviderRequest {
  const parsedProvider = providerNameSchema.safeParse(headers.get("x-sift-provider"));
  if (!parsedProvider.success) {
    throw new RequestError(400, "invalid_provider", "x-sift-provider is required");
  }

  const model = headers.get("x-sift-model")?.trim() ?? "";
  if (!MODEL_PATTERN.test(model)) {
    throw new RequestError(400, "invalid_model", "x-sift-model is invalid");
  }

  const apiKey = headers.get("x-sift-provider-key") ?? "";
  if (apiKey.length < 8 || apiKey.length > 4_096) {
    throw new RequestError(
      400,
      "invalid_provider_key",
      "x-sift-provider-key is required",
    );
  }

  const baseURL = headers.get("x-sift-provider-base-url")?.trim() || undefined;
  return { provider: parsedProvider.data, model, apiKey, baseURL };
}

export function createProviderModel(
  request: ProviderRequest,
  environment: ProviderEnvironment,
): LanguageModel {
  const baseURL = request.baseURL
    ? requireAllowlistedBaseURL(request.baseURL, environment)
    : undefined;

  switch (request.provider) {
    case "openai":
      return createOpenAI({ apiKey: request.apiKey, baseURL })(request.model);
    case "anthropic":
      return createAnthropic({ apiKey: request.apiKey, baseURL })(request.model);
    case "google":
      return createGoogle({ apiKey: request.apiKey, baseURL })(request.model);
    case "openai-compatible": {
      if (!baseURL) {
        throw new RequestError(
          400,
          "missing_base_url",
          "openai-compatible requires an allowlisted base URL",
        );
      }
      return wrapLanguageModel({
        model: createOpenAICompatible({
          name: "sift-shadow-compatible",
          apiKey: request.apiKey,
          baseURL,
          includeUsage: true,
        })(request.model),
        // OpenAI-compatible providers frequently wrap JSON in Markdown even
        // when response_format=json_object is requested. This public AI SDK
        // middleware keeps Output.object validation while removing only that
        // transport formatting; retries remain disabled in generateInternal.
        middleware: extractJsonMiddleware(),
      });
    }
  }
}

function requireAllowlistedBaseURL(
  value: string,
  environment: ProviderEnvironment,
): string {
  let normalized: string;
  try {
    const url = new URL(value);
    if (url.protocol !== "https:" || url.username || url.password || url.search || url.hash) {
      throw new Error("unsafe URL");
    }
    normalized = url.toString().replace(/\/$/, "");
  } catch {
    throw new RequestError(400, "invalid_base_url", "provider base URL is invalid");
  }

  const allowed = (environment.SIFT_SHADOW_ALLOWED_BASE_URLS ?? "")
    .split(",")
    .map((entry) => entry.trim().replace(/\/$/, ""))
    .filter(Boolean);
  if (!allowed.includes(normalized)) {
    throw new RequestError(400, "base_url_not_allowed", "provider base URL is not allowed");
  }
  return normalized;
}
