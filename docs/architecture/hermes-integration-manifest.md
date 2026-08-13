# Hermes Integration Manifest

Date: 2026-06-27

Pinned upstream:

- Repository: `NousResearch/hermes-agent`
- Commit: `bb6a4d2a57f3f239a2a6d74cb2dec9534a20e607`
- Commit date: 2026-06-26T17:17:43Z

This manifest is a pinned upstream reference catalog, not the executable Sift registry. It does
not mean Sift vendors Hermes runtime code. For Managed production, the only executable provider
registry is `cloudflare/src/sift_worker/runtime.py::PROVIDER_PROFILES`, and only Worker tests and
Worker live/app conformance can promote a provider. The older `backend/` registry remains a
Personal/Local Companion compatibility surface.

Current decision: Sift is Hermes-informed, not Hermes-integrated. Every row currently has `Sift current upstream reuse = No`. Any provider-specific behavior Sift adopts must be implemented as a ported behavior with an upstream path, pinned commit, Sift implementation path, and parity test as defined in [Hermes Reuse Decision Record](/Users/jerry/sift/docs/architecture/hermes-reuse-decision-record.md).

## Exposure Tiers

- Planned Stable: intended for normal Sift Profile exposure, but not yet fully cleared by live conformance and app E2E.
- Stable: passed production Worker live provider conformance and Managed app E2E for the configured default model.
- Advanced: available behind advanced provider configuration.
- Hidden: present only for internal/test/migration use.
- Deferred: not exposed in current Sift Profile.

## Model Providers

| Provider | Hermes upstream path at pinned SHA | Hermes `api_mode` | Native protocol adapter in Hermes | Auth | Suitable for Sift backend | Sift current upstream reuse | Intended protocol mapping; Worker support still requires conformance | User exposure |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| OpenAI | No plugin under `plugins/model-providers`; Sift preset uses Hermes base `ProviderProfile` contract | `chat_completions` for current Sift preset | Standard OpenAI-compatible transport, not provider plugin | API key | Yes | No | `ChatCompletionsDriver`; later `ResponsesDriver` for OpenAI Responses preset | Planned Stable |
| Anthropic | `plugins/model-providers/anthropic/__init__.py` | `anthropic_messages` | Yes, native Messages protocol | API key; Hermes profile also lists Anthropic token aliases | Yes | No | `AnthropicMessagesDriver` | Planned Stable |
| Gemini | `plugins/model-providers/gemini/__init__.py` | Hermes reports `chat_completions`; Sift maps to native `gemini` driver | Yes, Hermes comments state Gemini uses a custom native client while reporting `chat_completions` | API key: `GOOGLE_API_KEY` or `GEMINI_API_KEY` | Yes | No | `GeminiDriver`; local native driver implemented, live conformance pending | Planned Stable target |
| DeepSeek | `plugins/model-providers/deepseek/__init__.py` | `chat_completions` by base default | Standard Chat Completions plus DeepSeek profile hooks | API key: `DEEPSEEK_API_KEY` | Yes | No | `ChatCompletionsDriver` with DeepSeek capability policy | Planned Stable |
| OpenRouter | `plugins/model-providers/openrouter/__init__.py` | `chat_completions` by base default | Standard Chat Completions plus OpenRouter profile hooks | API key: `OPENROUTER_API_KEY`; model catalog fetch is public | Yes | No | `ChatCompletionsDriver` with routed-model capability resolution | Planned Stable |
| Kimi / Moonshot | `plugins/model-providers/kimi-coding/__init__.py` | `chat_completions` by base default | Standard Chat Completions plus Kimi hooks | API key: `KIMI_API_KEY` or `KIMI_CODING_API_KEY` | Yes | No | `ChatCompletionsDriver` with Kimi policy | Planned Stable |
| Nous | `plugins/model-providers/nous/__init__.py` | `chat_completions` by base default | Standard Chat Completions plus Nous tags/reasoning hooks | Hermes profile lists `NOUS_API_KEY` and `auth_type="oauth_device_code"` | Yes if Sift uses API-key/server token mode; device-code flow is not part of Sift backend MVP | No | `ChatCompletionsDriver` with Nous policy | Planned Stable |
| Custom OpenAI-compatible | `plugins/model-providers/custom/__init__.py` | `chat_completions` by base default | Standard Chat Completions plus custom/Ollama hooks | User-provided base URL and optional API key | Yes | No | `ChatCompletionsDriver` with probe-derived capability policy | Planned Stable |
| Alibaba DashScope | `plugins/model-providers/alibaba/__init__.py` | `chat_completions` by base default | Standard Chat Completions profile | API key: `DASHSCOPE_API_KEY` | Yes | No | `ChatCompletionsDriver` | Advanced |
| Azure Foundry | `plugins/model-providers/azure-foundry/__init__.py` | `chat_completions` by base default | Standard Chat Completions profile | API key plus user-supplied resource base URL | Yes, but deployment URL is user/resource scoped | No | `ChatCompletionsDriver` | Advanced |
| Hugging Face Router | `plugins/model-providers/huggingface/__init__.py` | `chat_completions` by base default | Standard Chat Completions profile | API key: `HF_TOKEN` | Yes, but capabilities vary by routed model | No | `ChatCompletionsDriver` with model-family policy | Advanced |
| NVIDIA NIM | `plugins/model-providers/nvidia/__init__.py` | `chat_completions` by base default | Standard Chat Completions profile | API key: `NVIDIA_API_KEY` | Yes, but model capability must be probed | No | `ChatCompletionsDriver` | Advanced |
| Ollama Cloud | `plugins/model-providers/ollama-cloud/__init__.py` | `chat_completions` by base default | Standard Chat Completions plus Ollama reasoning hook | API key: `OLLAMA_API_KEY` | Yes | No | `ChatCompletionsDriver` | Advanced |
| MiniMax | `plugins/model-providers/minimax/__init__.py` | `anthropic_messages` | Anthropic-compatible Messages profile; optional OpenAI-compatible M3 route has hooks | API key: `MINIMAX_API_KEY`; OAuth variant exists upstream | Yes for API-key Messages route | No | `AnthropicMessagesDriver` initially | Advanced |
| Bedrock | `plugins/model-providers/bedrock/__init__.py` | `bedrock_converse` | Yes, Bedrock Converse/AWS SDK class | AWS SDK credentials | Yes later, but not MVP due AWS auth/deployment surface | No | `BedrockDriver` | Deferred |
| xAI model provider | `plugins/model-providers/xai/__init__.py` | `codex_responses` | Responses/Codex-style profile | API key: `XAI_API_KEY` | Not until `ResponsesDriver` is implemented | No | `ResponsesDriver` | Deferred |
| OpenAI Codex | `plugins/model-providers/openai-codex/__init__.py` | `codex_responses` | Responses/Codex-style profile | External OAuth, no API key env var | No; binds Sift to ChatGPT/Codex auth semantics | No | None in MVP | Deferred |
| Copilot | `plugins/model-providers/copilot/__init__.py` | Per-model routing: `codex_responses`, `anthropic_messages`, `chat_completions` | Mixed protocol provider with Copilot auth and headers | Copilot/GitHub token | No for current Profile; depends on Copilot product semantics | No | None in MVP | Deferred |
| Copilot ACP | `plugins/model-providers/copilot-acp/__init__.py` | `chat_completions` in profile, but handled by external ACP subprocess | External ACP process | External process auth | No; CLI/subprocess dependent | No | None in MVP | Deferred |
| Qwen OAuth | `plugins/model-providers/qwen-oauth/__init__.py` | `chat_completions` by base default | Chat Completions plus Qwen portal hooks | OAuth external; profile also lists `QWEN_API_KEY` | No for MVP; OAuth portal semantics | No | None in MVP | Deferred |

## Stable Provider Notes

- DeepSeek, OpenRouter, Kimi, Nous, and Custom must not grow separate full adapters. They map to `ChatCompletionsDriver`; policy and payload mappers handle differences.
- Gemini becomes Stable only after `GeminiDriver` live conformance passes. The OpenAI-compatible Gemini profile has been removed from Sift's primary preset.
- OpenAI Planned Stable starts as `ChatCompletionsDriver` to preserve the current app path. A separate OpenAI Responses preset can be introduced after `ResponsesDriver` exists.
- Stable is a test result, not a product intention. Until live conformance and app E2E pass, these rows remain Planned Stable.

## Web Research Providers

Sift must split Search and Extract. A search result snippet is discovery evidence, not verified source text.

| Provider | Hermes upstream path | Hermes capability | Auth | Sift use | Exposure |
| --- | --- | --- | --- | --- | --- |
| DDGS | `plugins/web/ddgs` | Search only | No API key; optional `ddgs` package | Default Search Provider | Planned Stable |
| Sift Built-in Readability | Sift-owned, no Hermes plugin | Extract only | No API key | Default Extract Provider | Planned Stable |
| Tavily | `plugins/web/tavily` | Search + Extract | `TAVILY_API_KEY`; optional `TAVILY_BASE_URL` | Advanced Search or Extract | Advanced |
| Exa | `plugins/web/exa` | Search + Extract | `EXA_API_KEY` | Advanced Search or Extract | Advanced |
| Brave Search | `plugins/web/brave_free` | Search only | `BRAVE_SEARCH_API_KEY` | Advanced Search | Advanced |
| Firecrawl | `plugins/web/firecrawl` | Search + Extract | `FIRECRAWL_API_KEY` or self-hosted/gateway config | Advanced Extract; Search optional | Advanced |
| SearXNG | `plugins/web/searxng` | Search only | `SEARXNG_URL` self-hosted endpoint | Not MVP | Deferred |
| Parallel | `plugins/web/parallel` | Search + async Extract | `PARALLEL_API_KEY` | Not MVP | Deferred |
| xAI web search | `plugins/web/xai` | Search-like Grok Responses output | XAI key or OAuth | Not MVP | Deferred |

Default research stack:

```text
Search Provider: DDGS
Extract Provider: Sift Built-in Readability Extractor
```

If search succeeds but extraction fails, the answer source status is `searchDiscovered`, not `sourceVerified`. Sift must not cite snippets as verified source text.

DDGS and Sift Built-in Readability become Stable only after Research Stack Conformance and extractor security tests pass.

## Credential And Environment Constraints

- Test, dev, and prod must not share settings paths.
- Tests must not read real `.env`.
- Tests must not write real provider profile files.
- Provider credentials must not be stored as plaintext in ordinary JSON.
- Runtime Profile settings must become user-scoped.
- Credentials must be stored as secure references or encrypted values.
- API responses must return only masked previews and never raw keys.
- Conformance tests must use explicit test credential injection and skip live tests when credentials are unavailable.

Release gate: before any real user can configure an API key through Sift Profile, credential isolation must be implemented. Local development and controlled tests may use temporary plaintext settings only under explicit dev/test paths.
