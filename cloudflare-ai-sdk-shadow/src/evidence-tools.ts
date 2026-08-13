import { tool, type ToolSet } from "ai";
import { z } from "zod";

import type { AllowedToolName, AgentBudget, EvidenceSource } from "./contracts.ts";
import { EngineError } from "./errors.ts";

interface ToolState {
  physicalCalls: number;
}

export interface EvidenceTools {
  tools: ToolSet;
  state: ToolState;
}

export function createEvidenceTools(
  evidence: EvidenceSource[],
  allowedTools: AllowedToolName[],
  budget: AgentBudget,
): EvidenceTools {
  const state: ToolState = { physicalCalls: 0 };
  const cache = new Map<string, unknown>();
  const byId = new Map(evidence.map((source, index) => [source.id, { source, index }]));

  function executeOnce<T>(key: string, operation: () => T): T & { cached: boolean } {
    if (cache.has(key)) {
      return { ...(cache.get(key) as T & object), cached: true };
    }
    if (state.physicalCalls >= budget.maxToolCalls) {
      throw new EngineError("budget_exceeded", false);
    }
    state.physicalCalls += 1;
    const value = operation();
    cache.set(key, value);
    return { ...(value as T & object), cached: false };
  }

  const available: ToolSet = {
    web_search: tool({
      description:
        "Search only the Sift-provided evidence universe. Results include the numeric citation index.",
      inputSchema: z.object({
        query: z.string().min(1).max(500),
        limit: z.number().int().min(1).max(8).default(5),
      }),
      execute: async ({ query, limit }) =>
        executeOnce(`web_search:${JSON.stringify({ query, limit })}`, () => {
          const terms = query
            .toLocaleLowerCase()
            .split(/[^\p{L}\p{N}]+/u)
            .filter((term) => term.length > 1);
          const ranked = evidence
            .map((source, index) => {
              const haystack = `${source.title} ${source.excerpt} ${source.content}`.toLocaleLowerCase();
              const score = terms.reduce(
                (total, term) => total + (haystack.includes(term) ? 1 : 0),
                0,
              );
              return { source, index, score };
            })
            .sort((left, right) => right.score - left.score || left.index - right.index)
            .slice(0, limit);
          return {
            results: ranked.map(({ source, index }) => ({
              sourceId: source.id,
              citationIndex: index + 1,
              title: source.title,
              url: source.url,
              snippet: source.excerpt || source.content.slice(0, 500),
            })),
          };
        }),
    }),
    extract_url: tool({
      description:
        "Read one source from the Sift-provided evidence universe by sourceId. Arbitrary URL fetching is forbidden.",
      inputSchema: z.object({ sourceId: z.string().min(1).max(128) }),
      execute: async ({ sourceId }) =>
        executeOnce(`extract_url:${JSON.stringify({ sourceId })}`, () => {
          const match = byId.get(sourceId);
          if (!match) {
            throw new EngineError("tool_execution_failed", false);
          }
          return {
            sourceId,
            citationIndex: match.index + 1,
            title: match.source.title,
            url: match.source.url,
            content: match.source.content,
          };
        }),
    }),
  };

  return {
    tools: Object.fromEntries(
      allowedTools.filter((name) => name in available).map((name) => [name, available[name]]),
    ),
    state,
  };
}
