#!/usr/bin/env node

import { existsSync, readFileSync } from "node:fs";
import { homedir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const projectDirectory = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const managedInfoPath = resolve(
  projectDirectory,
  "..",
  "ios",
  "Sift",
  "ManagedRelease-Info.plist",
);
const requestTimeoutMs = 20_000;
const browserRunRetryCount = 2;
const browserRunDefaultRetryMs = 10_500;
let directUnavailable = false;

function managedBaseURL() {
  const override = process.env.SIFT_PRODUCTION_BASE_URL?.trim();
  if (override) {
    return normalizedBaseURL(override);
  }
  const contents = readFileSync(managedInfoPath, "utf8");
  const match = contents.match(
    /<key>SIFTBackendBaseURL<\/key>\s*<string>([^<]+)<\/string>/,
  );
  if (!match) {
    throw new Error("ManagedRelease-Info.plist has no SIFTBackendBaseURL.");
  }
  return normalizedBaseURL(match[1]);
}

function normalizedBaseURL(value) {
  const url = new URL(value);
  if (url.protocol !== "https:" || url.username || url.password) {
    throw new Error("The production endpoint must be an HTTPS URL without credentials.");
  }
  url.pathname = url.pathname.replace(/\/$/, "");
  url.search = "";
  url.hash = "";
  return url.toString().replace(/\/$/, "");
}

function credentialPaths() {
  const configuredHome = process.env.WRANGLER_HOME?.trim();
  return [
    configuredHome && resolve(configuredHome, "config", "default.toml"),
    join(homedir(), "Library", "Preferences", ".wrangler", "config", "default.toml"),
    join(homedir(), ".config", ".wrangler", "config", "default.toml"),
  ].filter(Boolean);
}

function cloudflareToken() {
  const environmentToken = process.env.CLOUDFLARE_API_TOKEN?.trim();
  if (environmentToken) {
    return environmentToken;
  }
  for (const path of credentialPaths()) {
    if (!existsSync(path)) {
      continue;
    }
    const match = readFileSync(path, "utf8").match(
      /^oauth_token\s*=\s*"([^"]+)"/m,
    );
    if (match) {
      return match[1];
    }
  }
  throw new Error(
    "Direct production access failed and no Wrangler OAuth or CLOUDFLARE_API_TOKEN was available for the Browser Run fallback.",
  );
}

function retryAfterMilliseconds(response) {
  const seconds = Number(response.headers.get("retry-after"));
  return Number.isFinite(seconds) && seconds > 0
    ? Math.ceil(seconds * 1_000)
    : browserRunDefaultRetryMs;
}

function cloudflareErrorMessage(payload) {
  if (!Array.isArray(payload?.errors)) {
    return "";
  }
  return payload.errors
    .map((error) => error?.message)
    .filter((message) => typeof message === "string")
    .join(" ");
}

async function cloudflareJSON(path, token, options = {}) {
  for (let attempt = 0; attempt <= browserRunRetryCount; attempt += 1) {
    const response = await fetch(`https://api.cloudflare.com/client/v4${path}`, {
      ...options,
      headers: {
        Authorization: `Bearer ${token}`,
        ...(options.body ? { "Content-Type": "application/json" } : {}),
        ...options.headers,
      },
      signal: AbortSignal.timeout(requestTimeoutMs),
    });
    const payload = await response.json();
    if (response.ok && payload.success === true) {
      return payload;
    }

    const message = cloudflareErrorMessage(payload);
    const dailyLimitExceeded = message.includes("time limit exceeded for today");
    if (
      response.status !== 429 ||
      dailyLimitExceeded ||
      attempt === browserRunRetryCount
    ) {
      const detail = message ? ` ${message}` : "";
      throw new Error(
        `Cloudflare API request failed with status ${response.status}.${detail}`,
      );
    }

    const delayMs = retryAfterMilliseconds(response);
    process.stdout.write(
      `Cloudflare Browser Run rate limited; retrying in ${Math.ceil(delayMs / 1_000)}s.\n`,
    );
    await new Promise((resolveDelay) => setTimeout(resolveDelay, delayMs));
  }
}

async function cloudflareAccountID(token) {
  const configured = process.env.CLOUDFLARE_ACCOUNT_ID?.trim();
  if (configured) {
    return configured;
  }
  const payload = await cloudflareJSON("/accounts?per_page=50", token);
  if (!Array.isArray(payload.result) || payload.result.length !== 1) {
    throw new Error(
      "Set CLOUDFLARE_ACCOUNT_ID when the current token can access more than one account.",
    );
  }
  return payload.result[0].id;
}

async function directProbe(url) {
  const response = await fetch(url, {
    headers: { Accept: "application/json" },
    signal: AbortSignal.timeout(requestTimeoutMs),
  });
  return {
    transport: "direct",
    status: response.status,
    payload: await response.json(),
  };
}

function decodeHTML(value) {
  return value
    .replaceAll("&quot;", '"')
    .replaceAll("&#39;", "'")
    .replaceAll("&lt;", "<")
    .replaceAll("&gt;", ">")
    .replaceAll("&amp;", "&");
}

async function browserRunProbe(url) {
  const token = cloudflareToken();
  const accountID = await cloudflareAccountID(token);
  const payload = await cloudflareJSON(
    `/accounts/${accountID}/browser-rendering/content`,
    token,
    {
      method: "POST",
      body: JSON.stringify({
        url,
        gotoOptions: { waitUntil: "networkidle2", timeout: requestTimeoutMs },
      }),
    },
  );
  const html = payload.result;
  const match = typeof html === "string" && html.match(/<pre>([\s\S]*?)<\/pre>/i);
  if (!match) {
    throw new Error("Browser Run returned no JSON response body.");
  }
  return {
    transport: "browser-run",
    status: Number(payload.meta?.status),
    payload: JSON.parse(decodeHTML(match[1])),
  };
}

async function productionProbe(url) {
  if (directUnavailable) {
    return browserRunProbe(url);
  }
  try {
    return await directProbe(url);
  } catch {
    directUnavailable = true;
    process.stdout.write(
      "Direct production probe unavailable; using Cloudflare Browser Run.\n",
    );
    return browserRunProbe(url);
  }
}

function requireCondition(condition, message) {
  if (!condition) {
    throw new Error(message);
  }
}

async function main() {
  const baseURL = managedBaseURL();
  const health = await productionProbe(`${baseURL}/health`);
  requireCondition(health.status === 200, `/health returned ${health.status}.`);
  requireCondition(
    health.payload?.status === "ok" &&
      health.payload?.env === "production" &&
      health.payload?.runtime === "cloudflare-workers",
    "/health did not identify the production Cloudflare Workers runtime.",
  );
  process.stdout.write(
    `OK ${health.transport} GET /health -> 200 production/cloudflare-workers\n`,
  );

  const appStatus = await productionProbe(`${baseURL}/v1/app-status`);
  requireCondition(
    appStatus.status === 401,
    `/v1/app-status returned ${appStatus.status} without authentication.`,
  );
  requireCondition(
    appStatus.payload?.error?.code === "authentication_required" &&
      typeof appStatus.payload?.error?.requestId === "string",
    "/v1/app-status did not return the stable authentication_required contract.",
  );
  process.stdout.write(
    `OK ${appStatus.transport} GET /v1/app-status -> 401 authentication_required\n`,
  );
}

try {
  await main();
} catch (error) {
  process.stderr.write(`Production verification failed: ${error.message}\n`);
  process.exitCode = 1;
}
