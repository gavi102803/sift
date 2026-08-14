#!/usr/bin/env node

import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { spawn, spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const projectDirectory = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const keychainService = "app.sift.ai-sdk-staging-engine";
const keychainAccount = "sift-staging";
const keychainResult = spawnSync(
  "security",
  [
    "find-generic-password",
    "-s",
    keychainService,
    "-a",
    keychainAccount,
    "-w",
  ],
  { encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] },
);
if (keychainResult.status !== 0 || !keychainResult.stdout.trim()) {
  process.stderr.write(
    "The Sift AI SDK staging engine token is missing from macOS Keychain.\n",
  );
  process.exit(1);
}

const temporaryDirectory = mkdtempSync(join(tmpdir(), "sift-ai-sdk-proxy-"));
const environmentPath = join(temporaryDirectory, ".env");
writeFileSync(
  environmentPath,
  `SIFT_ENGINE_TOKEN=${keychainResult.stdout.trim()}\n`,
  { mode: 0o600 },
);

const pywrangler = resolve(projectDirectory, ".venv", "bin", "pywrangler");
const cleanup = () =>
  rmSync(temporaryDirectory, { recursive: true, force: true });
const children = [];
let shuttingDown = false;

function wireWorker(child, label, onReady) {
  children.push(child);
  let output = "";
  const forward = (destination) => (chunk) => {
    destination.write(chunk);
    output = `${output}${chunk}`.slice(-4_096);
    if (output.includes("Ready on http://127.0.0.1:")) {
      output = "";
      onReady();
    }
  };
  child.stdout.on("data", forward(process.stdout));
  child.stderr.on("data", forward(process.stderr));
  child.on("exit", (status) => {
    if (shuttingDown) return;
    process.stderr.write(`${label} exited before the staging proxy stopped.\n`);
    shutdown(status ?? 1);
  });
}

function shutdown(status) {
  if (shuttingDown) return;
  shuttingDown = true;
  for (const child of children) child.kill("SIGTERM");
  cleanup();
  setTimeout(() => process.exit(status), 250);
}

const engineDirectory = resolve(projectDirectory, "..", "cloudflare-ai-sdk-shadow");
const engineWrangler = resolve(engineDirectory, "node_modules", ".bin", "wrangler");
const engine = spawn(
  engineWrangler,
  [
    "dev",
    "--config",
    "wrangler.engine.toml",
    "--ip",
    "127.0.0.1",
    "--port",
    "8789",
    "--env-file",
    environmentPath,
  ],
  { cwd: engineDirectory, stdio: ["inherit", "pipe", "pipe"] },
);

let backendStarted = false;
wireWorker(engine, "AI SDK engine", () => {
  if (backendStarted) return;
  backendStarted = true;
  const backend = spawn(
    pywrangler,
    [
      "dev",
      "--config",
      "wrangler.ai-sdk-staging.toml",
      "--ip",
      "127.0.0.1",
      "--port",
      "8788",
      "--persist-to",
      ".wrangler/ai-sdk-staging-state",
      "--env-file",
      environmentPath,
    ],
    { cwd: projectDirectory, stdio: ["inherit", "pipe", "pipe"] },
  );
  wireWorker(backend, "Sift staging backend", () => {
    setTimeout(cleanup, 1_000);
  });
});

for (const signal of ["SIGINT", "SIGTERM"]) {
  process.on(signal, () => shutdown(0));
}
