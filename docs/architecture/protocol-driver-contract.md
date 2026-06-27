# Protocol Driver Contract

Date: 2026-06-27

Sift maintains drivers by protocol, not by provider. Provider presets resolve to a driver plus capability policy.

```text
Provider Preset -> Capability Resolver -> Protocol Driver -> Runtime Event Stream
```

Provider-specific request shaping has four layers:

```text
ResolvedCapabilityPolicy
-> Internal Request Extensions
-> Provider-specific Payload Mapper
-> Actual HTTP Body
```

`extra_body` is not a Sift wire contract. It is an internal compatibility term copied from OpenAI SDK/Hermes vocabulary. Sift drivers must never assume every OpenAI-compatible endpoint accepts a literal JSON object named `extra_body`.

## Wire-Level Extension Rule

Provider-specific request extensions are represented inside Sift as typed internal fields, not as provider payload.

Internal extension examples:

```text
InternalRequestExtensions
- thinking
- reasoningEffort
- reasoning
- providerPreferences
- tags
- ollamaOptions
```

The only valid path to the network is:

```text
ResolvedCapabilityPolicy
-> InternalRequestExtensions
-> Provider-specific Payload Mapper
-> Actual HTTP Body
```

Rules:

- A driver must not emit a literal top-level `extra_body`.
- A driver must not forward unknown internal extension keys.
- A mapper must explicitly choose the wire shape for each provider.
- If a provider expects flattened fields, the mapper emits flattened fields.
- If a provider expects a nested provider-specific object, the mapper emits that object.
- If no mapper rule exists, the extension is dropped and the capability should be marked unsupported or unimplemented.

Example:

```text
Internal: thinking={type: enabled}

DeepSeek mapper:
Actual HTTP body contains top-level "thinking": {"type": "enabled"}

Kimi mapper:
Actual HTTP body contains top-level "thinking": {"type": "enabled"}
and omits "temperature"

Unknown custom endpoint:
Actual HTTP body does not include "thinking" unless a connection probe or explicit profile marks that field supported.
```

## Shared Driver Input

All drivers accept the same normalized request object:

```text
RuntimeModelRequest
- provider_id
- connection_id
- model
- messages: ordered RuntimeMessage[]
- tools: RuntimeToolSpec[]
- structured_output: StructuredOutputRequest | none
- generation: temperature, max_output_tokens, stop, reasoning, vision flags
- stream: bool
- request_id
- idempotency_key
- capability_snapshot_id
```

Drivers do not decide whether a parameter is allowed. They receive a `ResolvedCapabilityPolicy` and build the wire payload from that.

## Shared Stream Events

Every driver normalizes to:

```text
RuntimeStreamEvent
- started(request_id)
- text_delta(text)
- tool_call_delta(call_id, name, arguments_delta)
- tool_call_completed(call_id, name, arguments_json)
- structured_delta(path, value_delta)       # optional; drivers may omit
- citation_delta(citation)
- usage_delta(input_tokens, output_tokens, reasoning_tokens)
- completed(RuntimeModelResponse)
- failed(RuntimeProviderError)
```

Initial capture and follow-up must always persist the user turn before model streaming begins. If a driver fails, the original query remains visible and retry uses the same idempotency key.

## Error Normalization

Drivers map provider errors to:

```text
RuntimeProviderError
- category: auth | rate_limit | invalid_request | unsupported_capability | timeout | network | provider_unavailable | malformed_response
- provider_status_code
- provider_error_code
- provider_error_param
- safe_message
- raw_provider_excerpt_redacted
- retryable
```

Raw errors may be kept in server logs with credentials redacted. API responses must not include keys or full provider payloads.

## Retry Boundary

Drivers may retry only transport-safe failures:

- network reset before any response body;
- HTTP 408, 429 with `Retry-After`, 500, 502, 503, 504;
- stream connection failure before first model delta.

Drivers must not retry:

- invalid request;
- unsupported capability;
- authentication failure;
- a stream after any text/tool/structured delta has been emitted.

Application-level retry must reuse the existing Concept and Turn idempotency key.

## ChatCompletionsDriver

Used by OpenAI Chat Completions, DeepSeek, OpenRouter, Kimi, Nous, Custom OpenAI-compatible endpoints, Alibaba, Azure Foundry, Hugging Face Router, NVIDIA NIM, Ollama Cloud, and other OpenAI-compatible providers.

Request wire shape:

```json
{
  "model": "...",
  "messages": [{"role": "system|user|assistant|tool", "content": "..."}],
  "tools": [],
  "tool_choice": "auto",
  "stream": true
}
```

Capability policy may add:

- `temperature`;
- `max_tokens` or provider-required token field;
- `response_format`;
- `reasoning_effort`;
- internal request extensions such as `thinking`, `reasoning`, `providerPreferences`, `tags`, `ollamaOptions.numCtx`;
- provider headers such as OpenRouter xAI conversation headers.

### Payload Mapper Boundary

The `ChatCompletionsDriver` produces a provider-neutral internal request. A provider-specific payload mapper converts extensions into actual HTTP fields.

Examples:

| Provider | Internal extension | Actual HTTP body behavior |
| --- | --- | --- |
| DeepSeek | `thinking={type: enabled|disabled}` | Emit provider-recognized top-level `thinking` field when the DeepSeek policy enables it. |
| DeepSeek | `reasoningEffort=low|medium|high|max` | Emit top-level `reasoning_effort`. |
| Kimi | `thinking={type: enabled|disabled}` | Emit provider-recognized top-level `thinking`; never send alongside `reasoning_effort`. |
| Kimi | `reasoningEffort=low|medium|high` | Emit top-level `reasoning_effort`; omit `temperature`. |
| OpenRouter | `reasoning={...}` | Emit provider-recognized top-level `reasoning` field only when routed model policy allows it. |
| OpenRouter | `providerPreferences={...}` | Emit top-level `provider` field. |
| Nous | `tags=[...]` | Emit provider-recognized top-level `tags`. |
| Nous | `reasoning={...}` | Emit top-level `reasoning` when enabled; omit when disabled. |
| Custom/Ollama | `ollamaOptions.numCtx` | Emit `options.num_ctx` only for endpoints identified as Ollama-compatible. |

If a provider requires a nested object rather than flattened fields, that rule belongs in its payload mapper. The capability policy selects whether the extension is allowed; the mapper defines the wire shape.

Structured output:

- `jsonSchema`: send OpenAI `response_format.type=json_schema`.
- `jsonObject`: send `response_format.type=json_object` and validate locally.
- `promptAndValidate`: append a schema instruction and validate locally.
- `unsupported`: runtime request is rejected before provider call.

Tool calling:

- Sift tool specs map to OpenAI-style `tools`.
- Tool-call streaming normalizes `choices[].delta.tool_calls`.
- Tool result messages use the provider policy for vision/tool-content shape.

Usage:

- Read `usage.prompt_tokens`, `usage.completion_tokens`, and provider reasoning-token fields when present.

Model list:

- Use Provider Preset `models_url` or `{base_url}/models`.
- For routers, model list must be filtered by Sift default-model eligibility and capability policy before display.

## ResponsesDriver

Local driver boundary exists in `backend/src/sift_backend/runtime/responses_driver.py`.
It is not part of the current MVP stable provider set and no Responses provider is
exposed in Sift Profile yet.

Request wire shape:

```json
{
  "model": "...",
  "input": [],
  "tools": [],
  "stream": true,
  "text": {"format": "..."}
}
```

Structured output:

- Native Responses structured output where supported.
- Otherwise use policy-selected `jsonObject` or `promptAndValidate` only if the provider supports the request.

Tool calling:

- Tool specs map to Responses tools.
- Driver normalizes output items into the shared `tool_call_*` events.

Usage:

- Read Responses usage fields and normalize to input/output/reasoning tokens.

Model list:

- Provider specific. No generic list behavior until concrete OpenAI/xAI Responses provider support is implemented.

## AnthropicMessagesDriver

Used by Anthropic and MiniMax Messages-compatible routes.

Request wire shape:

```json
{
  "model": "...",
  "system": "...",
  "messages": [{"role": "user|assistant", "content": "..."}],
  "max_tokens": 4096,
  "stream": true
}
```

Headers:

- `x-api-key`;
- `anthropic-version`;
- provider-specific beta headers only when policy requires them.

Structured output:

- Anthropic Messages does not use OpenAI `response_format`.
- Use `promptAndValidate` unless a future native structured mode is added and policy enables it.

Tool calling:

- Sift tool specs map to Anthropic tool schema.
- Tool-use blocks normalize to shared tool-call events.

Usage:

- Read `usage.input_tokens` and `usage.output_tokens`.

Model list:

- Anthropic fetch uses `GET /v1/models` with `x-api-key` and `anthropic-version`.

## GeminiDriver

Used by the Stable Gemini preset.

Request wire shape:

- Native Gemini request with system instruction, contents, tools, generation config, and thinking config.

Structured output:

- Prefer native Gemini structured output when policy marks it supported.
- Otherwise use `jsonObject` or `promptAndValidate` with local validation.

Tool calling:

- Sift tool specs map to Gemini function declarations.
- Tool-call parts normalize to shared tool-call events.

Usage:

- Normalize Gemini usage metadata to input/output/reasoning tokens where available.

Model list:

- Gemini native model list, filtered by Sift capability policy.

## BedrockDriver

Deferred.

Request wire shape:

- AWS Bedrock Converse or ConverseStream via AWS SDK credentials.

Reason for deferral:

- AWS credentials, region, IAM, and model ID configuration are product-significant. This should not enter current Sift Profile until the core provider stack is stable.

## Research Tool Contract

Model drivers do not own web research. Tool calls target a separate Research Stack:

```text
Search Provider -> Extract Provider -> Source Classification
```

The model receives only normalized tool results:

- `searchDiscovered`: URL/title/snippet from search, no extracted body;
- `sourceVerified`: URL/title/extracted text from a successful extractor;
- `extractFailed`: URL/title/error class.

Search snippets must not be mapped to `sourceVerified`.
