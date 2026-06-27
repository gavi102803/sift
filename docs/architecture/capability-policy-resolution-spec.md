# Capability Policy Resolution Spec

Date: 2026-06-27

Capability policy is Sift-owned. Hermes profiles inform it, but do not replace it.

## Resolution Order

```text
Protocol Default
-> Provider Override
-> Model Family Policy
-> Connection Probe Result
```

Later layers override earlier layers. The resolved policy is cached per user, provider connection, base URL, model, and probe version.

## Capability Dimensions

| Capability | Values |
| --- | --- |
| `temperature` | `omit`, `allowed`, `fixed(value)` |
| `structured_output` | ordered list of `jsonSchema`, `jsonObject`, `promptAndValidate`, `unsupported` |
| `max_token_field` | `max_tokens`, `max_completion_tokens`, `max_output_tokens`, `none`, `provider_native` |
| `tool_calling` | `none`, `basic`, `streaming`, `provider_native` |
| `streaming` | `unsupported`, `text`, `textAndTools` |
| `reasoning` | `unsupported`, `topLevelReasoningEffort`, `extraBodyThinking`, `extraBodyReasoning`, `nativeThinkingConfig`, `adaptiveOnly` |
| `vision` | `unsupported`, `userImages`, `toolResultImages`, `providerNative` |
| `sift_default_allowed` | `true` or `false` |

## Protocol Defaults

| Driver | Temperature | Structured output | Max token field | Tool calling | Streaming | Reasoning | Vision |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `ChatCompletionsDriver` | `allowed` | `jsonSchema`, `jsonObject`, `promptAndValidate` | `max_tokens` | `basic` | `textAndTools` | `unsupported` | `userImages` when provider/model allows |
| `ResponsesDriver` | `allowed` | native Responses format, `jsonObject`, `promptAndValidate` | `max_output_tokens` | `provider_native` | `textAndTools` | provider-native | provider-native |
| `AnthropicMessagesDriver` | `allowed` | `promptAndValidate` | `max_tokens` | `provider_native` | `textAndTools` | provider-native when enabled by model | `userImages` and selected tool-result images |
| `GeminiDriver` | `allowed` | native Gemini structured output, `jsonObject`, `promptAndValidate` | `provider_native` | `provider_native` | `textAndTools` | `nativeThinkingConfig` | `providerNative` |
| `BedrockDriver` | `allowed` | provider/model-specific | `provider_native` | `provider_native` | `textAndTools` | provider/model-specific | provider/model-specific |

## Provider Overrides

| Provider | Overrides |
| --- | --- |
| OpenAI | Current Sift preset uses `ChatCompletionsDriver`; `jsonSchema` is allowed only for models that pass structured-output policy. |
| Anthropic | `AnthropicMessagesDriver`; no OpenAI `response_format`; fixed requirement to send `max_tokens`. |
| Gemini | `GeminiDriver`; reasoning maps to `thinking_config`. |
| DeepSeek | `ChatCompletionsDriver`; V4/R1 reasoning resolves to internal `thinking` extension and top-level `reasoning_effort`; payload mapper defines the final HTTP body; `jsonSchema` is marked failed for `deepseek-v4-flash` until probe proves otherwise. |
| OpenRouter | Router provider; no provider-wide structured-output guarantee. Capability must resolve against routed model family and probe result. |
| Kimi | `temperature=omit`; default max tokens from Hermes profile is 32000; reasoning resolves to mutually exclusive internal `thinking` or top-level `reasoning_effort`, then mapper emits provider wire fields. |
| Nous | Adds internal `tags`; reasoning is omitted when disabled and otherwise emitted by the mapper as provider-recognized reasoning fields. |
| Custom | Router/unknown endpoint. Use safe defaults until connection probe completes. |
| Bedrock | Deferred; AWS SDK policy applies only when driver exists. |

## Model Family Policy

Model family policy refines router and provider defaults.

Examples:

- OpenRouter `anthropic/*` models use Anthropic reasoning rules, not generic OpenRouter reasoning rules.
- OpenRouter `x-ai/grok-*` models may need xAI conversation header handling.
- DeepSeek `deepseek-v4-*` and `deepseek-reasoner` support thinking controls; `deepseek-chat` does not get those fields.
- Kimi K2/Moonshot models omit temperature.
- Unknown Custom models default to `temperature=omit`, `structured_output=[promptAndValidate]`, `tool_calling=none` until probe succeeds.

## Connection Probe Result

Probe results are collected when the user configures or tests a provider connection. Runtime must not perform a blind chain of provider calls:

```text
json_schema -> json_object -> prompt-only
```

Instead:

1. Probe once under user action or controlled background validation.
2. Cache the resolved policy.
3. Runtime builds the first request from the cached policy.
4. Unknown Custom endpoints may run a controlled probe sequence because there is no reliable catalog.

Probe cache key:

```text
user_id + provider_id + base_url + model + driver + probe_version
```

Probe results must expire when provider, base URL, model, driver, or Sift probe version changes.

## DeepSeek Structured Output Record

The real failing request used Sift's current Chat Completions path:

```http
POST https://api.deepseek.com/v1/chat/completions
Authorization: Bearer <redacted>
Content-Type: application/json
```

Payload class:

```json
{
  "model": "deepseek-v4-flash",
  "messages": [
    {"role": "system", "content": "..."},
    {"role": "user", "content": "..."}
  ],
  "response_format": {
    "type": "json_schema",
    "json_schema": {
      "name": "concept_initial_result",
      "strict": true,
      "schema": {"type": "object"}
    }
  }
}
```

Raw 400:

```json
{
  "message": "This response_format type is unavailable now",
  "type": "invalid_request_error",
  "param": null,
  "code": "invalid_request_error"
}
```

Policy interpretation:

| Strategy | Status |
| --- | --- |
| `json_schema` | Failed for `deepseek-v4-flash` with the raw 400 above. |
| `json_object` | Must be probed. It is not disproven by the `json_schema` failure. |
| prompt-only JSON | Works as fallback, but must be locally schema validated. |

If DeepSeek supports `json_object`, Sift must use:

```text
json_object -> local schema validation -> candidate update validation
```

Only if `json_object` fails or is unavailable should Sift use:

```text
promptAndValidate -> local schema validation -> candidate update validation
```

## Validation Layers

Structured output validation has three layers:

1. JSON parse and schema validation.
2. Sift domain validation for Concept, Turn, CandidateUpdate, Proposal, LearningState.
3. Mutation safety validation before applying any card patch or proposal.

Driver success is not enough. A provider can return valid JSON that still fails Sift domain rules.

## Default Model Eligibility

A model may be used as Sift's default knowledge-card model only if:

- streaming works;
- structured output resolves to `jsonSchema`, `jsonObject`, or stable `promptAndValidate`;
- it can complete initial capture and follow-up continuity;
- it does not require interactive OAuth, local CLI processes, or user machine state;
- it passes source/citation and candidate-update conformance tests;
- it is not a pure coding-agent runtime model.
