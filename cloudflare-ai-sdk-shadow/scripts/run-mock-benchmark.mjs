import { AiSdkAgentEngine } from "../src/ai-sdk-engine.ts";
import { collectEvents, mockModel, request, textStream } from "../tests/fixtures.ts";

const samples = [];
for (let index = 0; index < 30; index += 1) {
  const model = mockModel({ streams: textStream(`Benchmark ${index} is grounded [1].`) });
  const before = process.cpuUsage();
  const events = await collectEvents(
    new AiSdkAgentEngine().execute({
      kind: "follow-up",
      request: request(),
      model,
    }),
  );
  const cpu = process.cpuUsage(before);
  if (events.at(-1)?.type !== "terminal") throw new Error(`benchmark case ${index} failed`);
  samples.push((cpu.user + cpu.system) / 1_000);
}

samples.sort((left, right) => left - right);
const p95 = samples[Math.ceil(samples.length * 0.95) - 1];
const result = {
  scenarios: samples.length,
  p50CpuMs: Number(samples[14].toFixed(3)),
  p95CpuMs: Number(p95.toFixed(3)),
  targetCpuMs: 8,
};
console.log(JSON.stringify(result));
if (p95 >= result.targetCpuMs) {
  throw new Error(`mock p95 CPU ${p95.toFixed(3)}ms exceeds the ${result.targetCpuMs}ms target`);
}
