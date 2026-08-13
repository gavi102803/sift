import {
  generateText,
  NoObjectGeneratedError,
  NoOutputGeneratedError,
  Output,
  stepCountIs,
  streamText,
  ToolLoopAgent,
  type LanguageModelUsage,
  type ModelMessage,
  type StreamTextResult,
  type ToolSet,
} from "ai";

import {
  conceptCardSchema,
  type ConceptCard,
  type EngineErrorCode,
  type EngineExecution,
  type EvalRequest,
  type SiftAgentEngine,
  type SiftAgentEvent,
  type UsageSummary,
} from "./contracts.ts";
import { EngineError } from "./errors.ts";
import { createEvidenceTools } from "./evidence-tools.ts";

const TELEMETRY_DISABLED = {
  isEnabled: false,
  recordInputs: false,
  recordOutputs: false,
} as const;

type WithoutEventBase<T> = T extends unknown ? Omit<T, "runId" | "sequence"> : never;
type EventPayload = WithoutEventBase<SiftAgentEvent>;

export class AiSdkAgentEngine implements SiftAgentEngine {
  async *execute(execution: EngineExecution): AsyncIterable<SiftAgentEvent> {
    const { kind, request, model } = execution;
    const runId = request.runId ?? crypto.randomUUID();
    let sequence = 0;
    const event = <T extends EventPayload>(value: T) =>
      ({ ...value, runId, sequence: sequence++ }) as unknown as SiftAgentEvent;

    yield event({ type: "run_started", mode: request.mode, kind });
    yield event({
      type: "sources",
      citations: request.evidence.map((source, index) => ({
        index: index + 1,
        id: source.id,
        title: source.title,
        url: source.url,
      })),
    });

    const timeout = createRunAbortSignal(execution.abortSignal, request.budget.timeoutMs);
    try {
      const reservedCardCalls = kind === "initial" ? 1 : 0;
      const answerStepLimit = Math.min(
        request.budget.maxSteps,
        request.budget.maxModelCalls - reservedCardCalls,
      );
      if (answerStepLimit < 1) {
        throw new EngineError("budget_exceeded", false);
      }

      const evidenceTools = createEvidenceTools(
        request.evidence,
        request.allowedTools,
        request.budget,
      );
      const result = await this.startAnswerStream(
        execution,
        evidenceTools.tools,
        answerStepLimit,
        timeout.signal,
      );

      let answer = "";
      let finishReason = "other";
      let modelCalls = 0;
      let usage: LanguageModelUsage | undefined;

      for await (const part of result.fullStream) {
        switch (part.type) {
          case "start-step":
            modelCalls += 1;
            if (modelCalls > answerStepLimit) {
              throw new EngineError("budget_exceeded", false);
            }
            yield event({ type: "step_started", step: modelCalls });
            break;
          case "tool-call":
            yield event({
              type: "tool_call",
              toolCallId: part.toolCallId,
              toolName: part.toolName,
              input: part.input,
            });
            break;
          case "tool-result":
            yield event({
              type: "tool_result",
              toolCallId: part.toolCallId,
              toolName: part.toolName,
              output: part.output,
            });
            break;
          case "tool-error":
            if (part.error instanceof EngineError) {
              throw part.error;
            }
            throw new EngineError("tool_execution_failed", false);
          case "text-delta":
            answer += part.text;
            yield event({ type: "delta", delta: part.text });
            break;
          case "finish":
            finishReason = part.finishReason;
            usage = part.totalUsage;
            break;
          case "abort":
            throw timeout.toEngineError();
          case "error":
            throw new EngineError("provider_error", false);
        }
      }

      assertCitations(answer, request);

      let card: ConceptCard | undefined;
      if (kind === "initial") {
        if (modelCalls >= request.budget.maxModelCalls) {
          throw new EngineError("budget_exceeded", false);
        }
        const cardResult = await generateText({
          model,
          maxRetries: 0,
          maxOutputTokens: request.budget.maxOutputTokensPerCall,
          abortSignal: timeout.signal,
          telemetry: TELEMETRY_DISABLED,
          output: Output.object({
            schema: conceptCardSchema,
            name: "sift_concept_card",
            description: "A validated, non-durable concept card for shadow evaluation.",
          }),
          prompt: buildCardPrompt(answer, request),
        });
        modelCalls += 1;
        const parsedCard = conceptCardSchema.safeParse(cardResult.output);
        if (!parsedCard.success) {
          throw new EngineError("schema_validation_failed", false);
        }
        card = parsedCard.data;
        assertCardSources(card, request);
        usage = addUsage(usage, cardResult.usage);
        yield event({ type: "card", card });
      }

      const summary = summarizeUsage(usage, modelCalls, evidenceTools.state.physicalCalls);
      yield event({ type: "usage", usage: summary });
      yield event({ type: "terminal", status: "succeeded", finishReason });
    } catch (error) {
      const normalized = normalizeError(error, timeout);
      yield event({
        type: "error",
        code: normalized.code,
        message: publicErrorMessage(normalized.code),
        retryable: normalized.retryable,
      });
    } finally {
      timeout.dispose();
    }
  }

  private async startAnswerStream(
    execution: EngineExecution,
    tools: ToolSet,
    answerStepLimit: number,
    abortSignal: AbortSignal,
  ): Promise<StreamTextResult<ToolSet, never, never>> {
    const { request, model } = execution;
    const messages = buildModelMessages(request, request.mode === "core");
    const shared = {
      model,
      messages,
      maxRetries: 0,
      maxOutputTokens: request.budget.maxOutputTokensPerCall,
      abortSignal,
      telemetry: TELEMETRY_DISABLED,
    } as const;

    if (request.mode === "core") {
      return streamText({
        ...shared,
        instructions: coreInstructions(request),
        stopWhen: stepCountIs(1),
      }) as unknown as StreamTextResult<ToolSet, never, never>;
    }

    const agent = new ToolLoopAgent({
      model,
      tools,
      instructions: agentInstructions(request),
      stopWhen: stepCountIs(answerStepLimit),
      maxRetries: 0,
      maxOutputTokens: request.budget.maxOutputTokensPerCall,
      telemetry: TELEMETRY_DISABLED,
    });
    return (await agent.stream({ messages, abortSignal })) as StreamTextResult<
      ToolSet,
      never,
      never
    >;
  }
}

function buildModelMessages(request: EvalRequest, includeEvidence: boolean): ModelMessage[] {
  const messages: ModelMessage[] = request.messages.map((message) => ({
    role: message.role,
    content: message.content,
  }));
  if (!includeEvidence || request.evidence.length === 0) {
    return messages;
  }

  const last = messages.at(-1);
  if (!last || last.role !== "user" || typeof last.content !== "string") {
    return messages;
  }
  last.content = `${last.content}\n\nEvidence universe:\n${formatEvidence(request, true)}`;
  return messages;
}

function coreInstructions(request: EvalRequest): string {
  return [
    "You are the deterministic Sift Core evaluator.",
    "Answer only from the supplied evidence universe.",
    citationInstructions(request),
  ].join(" ");
}

function agentInstructions(request: EvalRequest): string {
  return [
    "You are the bounded Sift Agent evaluator.",
    "Use only the injected tools and evidence universe.",
    "When web_search is available, search before answering; use extract_url for the most relevant result.",
    citationInstructions(request),
    `Evidence catalog:\n${formatEvidence(request, false)}`,
  ].join("\n");
}

function citationInstructions(request: EvalRequest): string {
  if (request.evidence.length === 0) {
    return "Do not invent citations or URLs.";
  }
  return `Cite claims with numeric markers [1] through [${request.evidence.length}]. Do not add a Sources section or raw URLs.`;
}

function formatEvidence(request: EvalRequest, includeContent: boolean): string {
  return request.evidence
    .map((source, index) =>
      [
        `[${index + 1}] ${source.title}`,
        source.url,
        source.excerpt,
        includeContent ? source.content : "",
      ]
        .filter(Boolean)
        .join("\n"),
    )
    .join("\n\n");
}

function buildCardPrompt(answer: string, request: EvalRequest): string {
  return [
    "Create a concise Sift concept card from the answer.",
    "sourceIds must contain only ids from the evidence universe and only when the card relies on them.",
    `Answer:\n${answer}`,
    `Evidence:\n${request.evidence.map((source) => `${source.id}: ${source.title}`).join("\n")}`,
  ].join("\n\n");
}

function assertCitations(answer: string, request: EvalRequest): void {
  for (const match of answer.matchAll(/\[(\d+)]/g)) {
    const index = Number(match[1]);
    if (index < 1 || index > request.evidence.length) {
      throw new EngineError("citation_violation", false);
    }
  }
}

function assertCardSources(card: ConceptCard, request: EvalRequest): void {
  const allowed = new Set(request.evidence.map((source) => source.id));
  if (card.sourceIds.some((sourceId) => !allowed.has(sourceId))) {
    throw new EngineError("citation_violation", false);
  }
}

function addUsage(
  left: LanguageModelUsage | undefined,
  right: LanguageModelUsage,
): LanguageModelUsage {
  if (!left) return right;
  const add = (a: number | undefined, b: number | undefined) =>
    a === undefined && b === undefined ? undefined : (a ?? 0) + (b ?? 0);
  return {
    inputTokens: add(left.inputTokens, right.inputTokens),
    inputTokenDetails: {
      noCacheTokens: add(
        left.inputTokenDetails.noCacheTokens,
        right.inputTokenDetails.noCacheTokens,
      ),
      cacheReadTokens: add(
        left.inputTokenDetails.cacheReadTokens,
        right.inputTokenDetails.cacheReadTokens,
      ),
      cacheWriteTokens: add(
        left.inputTokenDetails.cacheWriteTokens,
        right.inputTokenDetails.cacheWriteTokens,
      ),
    },
    outputTokens: add(left.outputTokens, right.outputTokens),
    outputTokenDetails: {
      textTokens: add(left.outputTokenDetails.textTokens, right.outputTokenDetails.textTokens),
      reasoningTokens: add(
        left.outputTokenDetails.reasoningTokens,
        right.outputTokenDetails.reasoningTokens,
      ),
    },
    totalTokens: add(left.totalTokens, right.totalTokens),
  };
}

function summarizeUsage(
  usage: LanguageModelUsage | undefined,
  modelCalls: number,
  toolCalls: number,
): UsageSummary {
  return {
    inputTokens: usage?.inputTokens,
    outputTokens: usage?.outputTokens,
    totalTokens: usage?.totalTokens,
    modelCalls,
    toolCalls,
  };
}

interface RunAbortSignal {
  signal: AbortSignal;
  dispose(): void;
  toEngineError(): EngineError;
  timedOut(): boolean;
}

function createRunAbortSignal(parent: AbortSignal | undefined, timeoutMs: number): RunAbortSignal {
  const controller = new AbortController();
  let timeoutReached = false;
  const onParentAbort = () => controller.abort(parent?.reason);
  parent?.addEventListener("abort", onParentAbort, { once: true });
  if (parent?.aborted) controller.abort(parent.reason);
  const timer = setTimeout(() => {
    timeoutReached = true;
    controller.abort("sift-shadow-timeout");
  }, timeoutMs);

  return {
    signal: controller.signal,
    timedOut: () => timeoutReached,
    toEngineError: () =>
      new EngineError(timeoutReached ? "timeout" : "cancelled", timeoutReached),
    dispose: () => {
      clearTimeout(timer);
      parent?.removeEventListener("abort", onParentAbort);
    },
  };
}

function normalizeError(error: unknown, timeout: RunAbortSignal): EngineError {
  if (timeout.signal.aborted) return timeout.toEngineError();
  if (error instanceof EngineError) return error;
  if (
    NoOutputGeneratedError.isInstance(error) ||
    NoObjectGeneratedError.isInstance(error)
  ) {
    return new EngineError("schema_validation_failed", false);
  }
  if (error instanceof DOMException && error.name === "AbortError") {
    return timeout.toEngineError();
  }
  return new EngineError("provider_error", false);
}

function publicErrorMessage(code: EngineErrorCode): string {
  const messages: Record<EngineErrorCode, string> = {
    budget_exceeded: "The Sift execution budget was exceeded.",
    cancelled: "The Sift execution was cancelled.",
    citation_violation: "The generated output referenced evidence outside this run.",
    provider_error: "The model provider request failed.",
    schema_validation_failed: "The structured concept card did not pass validation.",
    timeout: "The Sift execution timed out.",
    tool_execution_failed: "An allowlisted tool failed.",
  };
  return messages[code];
}
