const required = [
  "SIFT_SHADOW_URL",
  "SIFT_SHADOW_TOKEN",
  "SIFT_PROVIDER",
  "SIFT_MODEL",
  "SIFT_PROVIDER_API_KEY",
];
const missing = required.filter((name) => !process.env[name]);
if (missing.length > 0) {
  throw new Error(`missing environment variables: ${missing.join(", ")}`);
}

const headers = {
  authorization: `Bearer ${process.env.SIFT_SHADOW_TOKEN}`,
  "content-type": "application/json",
  "x-sift-provider": process.env.SIFT_PROVIDER,
  "x-sift-model": process.env.SIFT_MODEL,
  "x-sift-provider-key": process.env.SIFT_PROVIDER_API_KEY,
};
if (process.env.SIFT_PROVIDER_BASE_URL) {
  headers["x-sift-provider-base-url"] = process.env.SIFT_PROVIDER_BASE_URL;
}

const response = await fetch(
  new URL("/v1/eval/follow-up", process.env.SIFT_SHADOW_URL),
  {
    method: "POST",
    headers,
    body: JSON.stringify({
      mode: "agent",
      messages: [{ role: "user", content: "Explain why durable agent state matters." }],
      evidence: [
        {
          id: "live-evidence-1",
          title: "Sift live evaluation fixture",
          url: "https://example.com/sift-live-eval",
          excerpt: "Durable state lets an interrupted run resume without duplicating work.",
          content:
            "A durable control plane checkpoints progress and preserves idempotency across disconnects.",
        },
      ],
    }),
  },
);

if (!response.ok || !response.body) {
  throw new Error(`shadow evaluation failed with HTTP ${response.status}`);
}

const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
let buffer = "";
let terminal;
let usage;
for (;;) {
  const { done, value } = await reader.read();
  buffer += value ?? "";
  const lines = buffer.split("\n");
  buffer = lines.pop() ?? "";
  for (const line of lines) {
    if (!line) continue;
    const event = JSON.parse(line);
    if (event.type === "usage") usage = event.usage;
    if (event.type === "terminal" || event.type === "error") terminal = event;
  }
  if (done) break;
}

console.log(JSON.stringify({ provider: process.env.SIFT_PROVIDER, usage, terminal }, null, 2));
if (terminal?.type !== "terminal") process.exitCode = 1;
