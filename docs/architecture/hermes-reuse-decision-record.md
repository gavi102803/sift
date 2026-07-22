# Hermes Reuse Decision Record

Date: 2026-07-21

Decision: Sift is Hermes-informed, not Hermes-integrated.

Sift does not currently import, vendor, submodule, or execute Hermes provider/runtime code. Hermes is a pinned upstream reference for provider catalog boundaries, `api_mode` classification, and specific provider behavior that Sift may port into Sift-owned implementation and tests.

Pinned upstream:

- Repository: `NousResearch/hermes-agent`
- Commit: `bb6a4d2a57f3f239a2a6d74cb2dec9534a20e607`

## Reuse Categories

- Direct code reuse: Sift imports or vendors upstream code as executable dependency.
- Port behavior / hook: Sift reimplements a pinned upstream behavior in Sift-owned code with parity tests.
- Design reference only: Sift follows the same boundary or vocabulary, but no behavior parity is claimed.
- Not adopted: Sift explicitly excludes the component.

## Decisions

| Hermes component | Decision | Status | Upstream path | Sift implementation path | Parity test | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| ProviderProfile schema fields | Port behavior / hook | Implemented partially | `providers/base.py` | `backend/src/sift_backend/runtime/provider_presets.py`, `backend/src/sift_backend/runtime/providers.py` | `backend/tests/test_provider_presets.py`, `backend/tests/test_health.py` | Current registry ports identity, `api_mode`, protocol driver name, auth requirement, base URL, model list flag, and exposure tier. |
| Provider plugin catalog | Port behavior / hook | Implemented partially | `plugins/model-providers/*/__init__.py` | `backend/src/sift_backend/runtime/provider_presets.py` | `backend/tests/test_provider_presets.py` | Pinned manifest rows become Sift presets. Sift does not dynamically load Hermes plugins. |
| DeepSeek thinking/reasoning hook | Port behavior / hook | Implemented partially | `plugins/model-providers/deepseek/__init__.py` | `backend/src/sift_backend/runtime/capability_policies.py`, `backend/src/sift_backend/runtime/payload_mappers.py` | `backend/tests/test_capability_policy.py`, `backend/tests/test_capability_probe.py` | Current Sift policy ports V4/R1 thinking detection and structured-output strategy probing. `reasoning_effort` parity is planned. |
| Kimi temperature/reasoning hook | Port behavior / hook | Implemented partially | `plugins/model-providers/kimi-coding/__init__.py` | `backend/src/sift_backend/runtime/capability_policies.py`, `backend/src/sift_backend/runtime/payload_mappers.py` | `backend/tests/test_capability_policy.py` | Current Sift policy omits temperature and emits thinking. Mutually exclusive reasoning-effort parity is planned. |
| OpenRouter reasoning/router hook | Port behavior / hook | Planned | `plugins/model-providers/openrouter/__init__.py` | `backend/src/sift_backend/runtime/capability_policies.py`, `backend/src/sift_backend/runtime/payload_mappers.py` | Planned: `backend/tests/test_capability_policy.py` | Sift must route OpenRouter through `ChatCompletionsDriver`; routed-model capability probing remains required. |
| Nous tags/reasoning hook | Port behavior / hook | Implemented partially | `plugins/model-providers/nous/__init__.py` | `backend/src/sift_backend/runtime/capability_policies.py`, `backend/src/sift_backend/runtime/payload_mappers.py` | Planned: `backend/tests/test_capability_policy.py` | Current Sift policy emits `tags=["sift"]`. Reasoning behavior parity is planned. |
| Gemini native API and thinking config hook | Port behavior / hook | Implemented locally; thinking parity pending | `plugins/model-providers/gemini/__init__.py` | `backend/src/sift_backend/runtime/gemini_driver.py` | `backend/tests/test_gemini_driver.py` | Sift now maps Gemini to native `generateContent` / `streamGenerateContent`. It is Planned Stable until live conformance passes; thinking config parity remains pending. |
| Anthropic model listing/auth behavior | Port behavior / hook | Implemented partially | `plugins/model-providers/anthropic/__init__.py` | `backend/src/sift_backend/runtime/anthropic_messages_driver.py` | `backend/tests/test_runtime_provider.py` | Current implementation uses Anthropic Messages headers, `/v1/messages`, streaming deltas, and `/v1/models`. Full live conformance remains required before Stable. |
| Responses/Codex-style transport | Design reference only | Implemented locally | `plugins/model-providers/xai/__init__.py`, `plugins/model-providers/openai-codex/__init__.py` | `backend/src/sift_backend/runtime/responses_driver.py` | `backend/tests/test_responses_driver.py` | Sift has a local ResponsesDriver boundary and factory support. No Responses provider is exposed in Sift Profile until product auth and live conformance gates pass. |
| Web provider capability labels | Port behavior / hook | Implemented partially | `plugins/web/*/__init__.py`, `plugins/web/*/provider.py` | `backend/src/sift_backend/runtime/tools.py`, `backend/src/sift_backend/runtime/research_stack.py` | `backend/tests/test_runtime_web_provider.py`, `backend/tests/test_readability_extractor.py` | Sift ports the search/extract split and owns the default DDGS/Search + Readability/Extract behavior. |
| Provider/profile boundary naming | Design reference only | Implemented in docs | `providers/base.py` | `docs/architecture/*.md` | None | Boundary vocabulary is shared, not code parity. |
| Protocol driver boundary | Design reference only | Implemented in docs | `agent/transports/*` | `docs/architecture/protocol-driver-contract.md` | None | Sift drivers are local contracts. |
| Hermes CLI | Not adopted | Final | CLI package and entrypoints | None | None | Sift is not a CLI agent runtime. |
| Hermes gateway / API server semantics | Not adopted | Final | Gateway/API server paths | None | None | Sift backend owns its API. |
| Hermes agent loop and harness patterns | Design reference only | Harness v1 implemented locally | Agent runtime paths | `backend/src/sift_backend/model_runtime/harness/`, `backend/src/sift_backend/runtime/execution_observer.py` | `backend/tests/test_agent_harness.py`, `backend/tests/test_model_runs_and_revisions.py` | Sift does not import Hermes' general-purpose loop. It ports bounded execution ideas into Sift-owned AgentSpecs, budgets, tool policy, steps, and durable ModelRun events. |
| Hermes memory | Not adopted | Final | Memory provider paths | None | None | Sift owns Knowledge Mutation Layer, Card, Patch, Proposal, and LearningState. |
| Hermes OAuth flows | Not adopted | Final | Auth/OAuth provider paths | None | None | Current Sift Profile avoids OAuth-dependent providers. |
| Hermes auxiliary model semantics | Not adopted | Final | Auxiliary model config paths | None | None | Sift default model eligibility is Sift-owned. |
| Copilot ACP / external process providers | Not adopted | Final | `plugins/model-providers/copilot-acp` | None | None | External process runtime is outside current product boundary. |

## Sift Agent Harness v1 Boundary

The Sift Agent Harness is a bounded execution layer above the model runtime and below durable
concept commits. It currently defines a versioned `AgentSpec` for initial card generation,
follow-up, continuity summary, and periodic knowledge review. The harness enforces model/tool/step
budgets before calls, restricts tools per workflow, and records step, usage, prompt-version, and
termination metadata on the durable `ModelRun`.

The harness does not own Concept, Note, Revision, or Proposal truth. Model output still passes schema
validation and is committed through the existing Concept and Knowledge Mutation application rules.
This preserves recovery and idempotency while avoiding a general-purpose shell, MCP, or arbitrary
tool loop in the dogfood product.

## Release Rule

Any future claim that "Sift supports Hermes provider X" must state one of:

- direct code reuse, with dependency path and version;
- ported behavior, with upstream path, Sift path, and parity test;
- design reference only, with no behavior compatibility claim.
