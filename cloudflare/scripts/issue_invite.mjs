#!/usr/bin/env node

import { createHash, randomBytes } from "node:crypto";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const projectDirectory = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const databaseName = process.argv[2] ?? "sift";
const configFile = process.argv[3];
const executionMode = process.argv[4] ?? "--remote";
if (!/^[a-z0-9-]+$/.test(databaseName)) {
  throw new Error("Database name is invalid.");
}
if (!["--local", "--remote"].includes(executionMode)) {
  throw new Error("D1 execution mode must be --local or --remote.");
}
const inviteCode = randomBytes(18).toString("base64url");
const codeHash = createHash("sha256").update(inviteCode).digest("hex");
const statement =
  `INSERT INTO beta_invites (code_hash) VALUES ('${codeHash}')`;

const result = spawnSync(
  "pnpm",
  [
    "exec",
    "wrangler",
    "d1",
    "execute",
    databaseName,
    executionMode,
    ...(configFile ? ["--config", configFile] : []),
    ...(executionMode === "--local"
      ? ["--persist-to", ".wrangler/ai-sdk-staging-state"]
      : []),
    "--command",
    statement,
  ],
  {
    cwd: projectDirectory,
    encoding: "utf8",
    env: process.env,
    stdio: ["ignore", "pipe", "pipe"],
  },
);

if (result.error) {
  throw result.error;
}
if (result.status !== 0) {
  process.stderr.write(result.stderr);
  process.exit(result.status ?? 1);
}

process.stdout.write(`Invite code: ${inviteCode}\n`);
