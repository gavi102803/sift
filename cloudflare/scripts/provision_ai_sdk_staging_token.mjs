#!/usr/bin/env node

import { randomBytes } from "node:crypto";
import { spawnSync } from "node:child_process";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const projectDirectory = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const shadowDirectory = resolve(projectDirectory, "..", "cloudflare-ai-sdk-shadow");
const token = randomBytes(32).toString("hex");

run(
  "security",
  [
    "add-generic-password",
    "-s",
    "app.sift.ai-sdk-staging-engine",
    "-a",
    "sift-staging",
    "-w",
    token,
    "-U",
  ],
  projectDirectory,
);
for (const [directory, config] of [
  [shadowDirectory, "wrangler.engine.toml"],
  [projectDirectory, "wrangler.ai-sdk-staging.toml"],
]) {
  run(
    "pnpm",
    ["exec", "wrangler", "secret", "put", "SIFT_ENGINE_TOKEN", "--config", config],
    directory,
    `${token}\n`,
  );
}
process.stdout.write(
  "Provisioned the shared staging engine token in Cloudflare Secrets and macOS Keychain.\n",
);

function run(command, arguments_, cwd, input) {
  const result = spawnSync(command, arguments_, {
    cwd,
    input,
    encoding: "utf8",
    stdio: [input ? "pipe" : "ignore", "inherit", "inherit"],
  });
  if (result.error) throw result.error;
  if (result.status !== 0) process.exit(result.status ?? 1);
}
