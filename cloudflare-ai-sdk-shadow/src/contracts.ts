import { z } from "zod";

export const providerNameSchema = z.enum([
  "openai",
  "anthropic",
  "google",
  "openai-compatible",
]);

export type ProviderName = z.infer<typeof providerNameSchema>;

export const evidenceSourceSchema = z.object({
  id: z.string().min(1).max(128),
  title: z.string().min(1).max(300),
  url: z.url().max(2_048),
  excerpt: z.string().max(2_000).default(""),
  content: z.string().max(20_000),
});

export type EvidenceSource = z.infer<typeof evidenceSourceSchema>;

export const DEFAULT_AGENT_BUDGET = {
  maxModelCalls: 5,
  maxSteps: 4,
  maxToolCalls: 4,
  maxOutputTokensPerCall: 1_200,
  timeoutMs: 45_000,
} as const;

export const agentBudgetSchema = z.object({
  maxModelCalls: z.number().int().min(1).max(8).default(5),
  maxSteps: z.number().int().min(1).max(6).default(4),
  maxToolCalls: z.number().int().min(0).max(8).default(4),
  maxOutputTokensPerCall: z.number().int().min(64).max(4_096).default(1_200),
  timeoutMs: z.number().int().min(100).max(120_000).default(45_000),
});

export type AgentBudget = z.infer<typeof agentBudgetSchema>;

export const evalRequestSchema = z
  .object({
    runId: z.uuid().optional(),
    mode: z.enum(["core", "agent"]).default("agent"),
    messages: z
      .array(
        z.object({
          role: z.enum(["user", "assistant"]),
          content: z.string().min(1).max(20_000),
        }),
      )
      .min(1)
      .max(32),
    allowedTools: z
      .array(z.enum(["web_search", "extract_url"]))
      .max(2)
      .default(["web_search", "extract_url"]),
    evidence: z.array(evidenceSourceSchema).max(20).default([]),
    budget: agentBudgetSchema.default(DEFAULT_AGENT_BUDGET),
  })
  .superRefine((value, context) => {
    if (value.messages.at(-1)?.role !== "user") {
      context.addIssue({
        code: "custom",
        path: ["messages"],
        message: "the final message must be from the user",
      });
    }

    const messageCharacters = value.messages.reduce(
      (total, message) => total + message.content.length,
      0,
    );
    const evidenceCharacters = value.evidence.reduce(
      (total, source) => total + source.content.length + source.excerpt.length,
      0,
    );
    if (messageCharacters + evidenceCharacters > 200_000) {
      context.addIssue({
        code: "custom",
        message: "combined messages and evidence exceed the shadow evaluation limit",
      });
    }

    if (new Set(value.evidence.map((source) => source.id)).size !== value.evidence.length) {
      context.addIssue({
        code: "custom",
        path: ["evidence"],
        message: "evidence source ids must be unique",
      });
    }
  });

export type EvalRequest = z.infer<typeof evalRequestSchema>;
export type EvalMode = EvalRequest["mode"];
export type EvalKind = "initial" | "follow-up";
export type AllowedToolName = EvalRequest["allowedTools"][number];

export const conceptCardSchema = z.object({
  title: z.string().min(1).max(120),
  summary: z.string().min(1).max(1_200),
  keyPoints: z.array(z.string().min(1).max(400)).min(1).max(8),
  sourceIds: z.array(z.string().min(1).max(128)).max(20),
});

export type ConceptCard = z.infer<typeof conceptCardSchema>;

export interface UsageSummary {
  inputTokens?: number;
  outputTokens?: number;
  totalTokens?: number;
  modelCalls: number;
  toolCalls: number;
}

interface EventBase {
  runId: string;
  sequence: number;
}

export type SiftAgentEvent =
  | (EventBase & { type: "run_started"; mode: EvalMode; kind: EvalKind })
  | (EventBase & {
      type: "sources";
      citations: Array<{ index: number; id: string; title: string; url: string }>;
    })
  | (EventBase & { type: "step_started"; step: number })
  | (EventBase & {
      type: "tool_call";
      toolCallId: string;
      toolName: string;
      input: unknown;
    })
  | (EventBase & {
      type: "tool_result";
      toolCallId: string;
      toolName: string;
      output: unknown;
    })
  | (EventBase & { type: "delta"; delta: string })
  | (EventBase & { type: "card"; card: ConceptCard })
  | (EventBase & { type: "usage"; usage: UsageSummary })
  | (EventBase & {
      type: "terminal";
      status: "succeeded";
      finishReason: string;
    })
  | (EventBase & {
      type: "error";
      code: EngineErrorCode;
      message: string;
      retryable: boolean;
    });

export type EngineErrorCode =
  | "budget_exceeded"
  | "cancelled"
  | "citation_violation"
  | "provider_error"
  | "schema_validation_failed"
  | "timeout"
  | "tool_execution_failed";

export interface EngineExecution {
  kind: EvalKind;
  request: EvalRequest;
  model: import("ai").LanguageModel;
  abortSignal?: AbortSignal;
}

export interface SiftAgentEngine {
  execute(execution: EngineExecution): AsyncIterable<SiftAgentEvent>;
}
