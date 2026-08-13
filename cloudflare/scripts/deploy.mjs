#!/usr/bin/env node

import { existsSync, readFileSync, writeFileSync } from "node:fs";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const projectDirectory = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const configPath = resolve(projectDirectory, "wrangler.toml");
const placeholderId = "00000000-0000-0000-0000-000000000000";

function run(command, args, { capture = false } = {}) {
  const result = spawnSync(command, args, {
    cwd: projectDirectory,
    encoding: "utf8",
    env: process.env,
    stdio: capture ? ["ignore", "pipe", "pipe"] : "inherit",
  });
  if (result.error) {
    throw result.error;
  }
  if (result.status !== 0) {
    if (capture) {
      process.stderr.write(result.stderr);
    }
    throw new Error(`${command} exited with status ${result.status}`);
  }
  return capture ? result.stdout : "";
}

function wrangler(args, options) {
  return run("pnpm", ["exec", "wrangler", ...args], options);
}

function configuredDatabaseId() {
  const config = readFileSync(configPath, "utf8");
  const match = config.match(/database_id\s*=\s*"([^"]+)"/);
  if (!match) {
    throw new Error("wrangler.toml has no D1 database_id.");
  }
  return match[1];
}

function remoteDatabases() {
  const output = wrangler(["d1", "list", "--json"], { capture: true });
  return JSON.parse(output);
}

function resolveDatabaseId() {
  const configured = configuredDatabaseId();
  if (configured !== placeholderId) {
    return configured;
  }

  let matches = remoteDatabases().filter((database) => database.name === "sift");
  if (matches.length === 0) {
    wrangler(["d1", "create", "sift", "--location", "apac"]);
    matches = remoteDatabases().filter((database) => database.name === "sift");
  }
  if (matches.length !== 1) {
    throw new Error(
      `Expected one remote D1 database named sift, found ${matches.length}.`,
    );
  }

  const databaseId = matches[0].uuid;
  const config = readFileSync(configPath, "utf8");
  writeFileSync(configPath, config.replace(placeholderId, databaseId));
  return databaseId;
}

function main() {
  const identity = wrangler(["whoami"], { capture: true });
  if (identity.includes("not authenticated")) {
    throw new Error(
      "Cloudflare login is required. Run `pnpm exec wrangler login` first.",
    );
  }

  const databaseId = resolveDatabaseId();
  process.stdout.write(`Using D1 sift (${databaseId}).\n`);
  wrangler(["d1", "migrations", "apply", "sift", "--remote"]);
  const venvPywrangler = resolve(projectDirectory, ".venv", "bin", "pywrangler");
  if (process.env.UV_BIN) {
    process.env.PATH = `${dirname(process.env.UV_BIN)}:${process.env.PATH ?? ""}`;
    run(process.env.UV_BIN, ["run", "pywrangler", "deploy"]);
  } else if (existsSync(venvPywrangler)) {
    run(venvPywrangler, ["deploy"]);
  } else {
    run("uv", ["run", "pywrangler", "deploy"]);
  }
  run("node", [resolve(projectDirectory, "scripts", "verify_production.mjs")]);
}

try {
  main();
} catch (error) {
  process.stderr.write(`${error.message}\n`);
  process.exitCode = 1;
}
