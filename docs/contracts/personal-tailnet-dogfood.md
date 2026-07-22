# Personal Tailnet Dogfood — Client ↔ Local Backend Contract

**Status: RATIFIED for Phase 0 personal dogfood.** This contract is for the
owner's own iPhone and Mac. It is not the Managed BYOK beta contract and must
not leak into Release/TestFlight user experience.

## Product Form

```text
iPhone + Mac
→ Tailscale private network
→ Sift backend running on the Mac
→ local SQLite on the Mac
→ external model provider API
```

The backend remains private to the tailnet. Phase 0 does not require a public
domain, public ingress, hosted backend, activation token, account system, or
Tailscale SDK integration.

## Endpoint Resolution

All iOS requests resolve the backend base URL through one centralized resolver.
Resolution order is:

1. `SIFT_BACKEND_BASE_URL` environment override.
2. User-saved Personal backend URL, **Debug/Personal builds only**.
3. Debug default `http://127.0.0.1:8000`.
4. Release/Managed compiled endpoint when that build flavor exists.

Debug/Personal may save:

- `http://127.0.0.1:8000`
- `http://localhost:8000`
- `https://*.ts.net`
- other `https://` URLs for developer testing

An empty or invalid URL must not override the current endpoint. Reset clears the
saved Personal URL and returns to the default resolution path.

## Build Boundaries

| Build | Backend URL UI | Editable | Default |
|---|---:|---:|---|
| Debug / Personal | visible in Developer / Local Companion | yes | `http://127.0.0.1:8000` |
| Release / Managed / TestFlight | hidden | no | compiled managed endpoint |

Release/TestFlight must not show backend URL fields, Tailscale setup copy, local
backend diagnostics, FastAPI details, or raw transport errors.

## Backend Expectations

Phase 0 keeps the local backend behavior:

- development principal is local-only;
- SQLite remains local to the Mac;
- provider credentials are still configured through the current local Profile
  flow;
- no owner isolation or beta activation is required for this contract;
- backend connection failure is a real failure, not silent mock mode.

## iPhone + Tailscale Manual Path

1. Install Tailscale on the Mac and iPhone and join the same tailnet.
2. Enable MagicDNS and HTTPS in Tailscale.
3. Run Sift backend on the Mac:

   ```bash
   scripts/run_local_companion.sh --tailnet
   ```

4. Confirm the Mac has a tailnet name such as:

   ```text
   https://<mac-machine>.<tailnet>.ts.net
   ```

5. In a Debug/Personal iOS build, set Backend URL to that HTTPS address.
6. Run Test Connection in the app, or run:

   ```bash
   scripts/local_mvp_doctor.py --backend-url https://<mac-machine>.<tailnet>.ts.net
   ```

7. Capture a concept and verify it is persisted in the Mac backend SQLite DB.
8. After a dogfood session, print the privacy-safe reliability summary:

   ```bash
   backend/.venv/bin/python scripts/model_run_metrics.py
   ```

   The report contains aggregate run counts, success rate, p50/p95 latency,
   recovery attempts, terminal-integrity checks, summaries, capture outcomes,
   follow-ups per concept, revision restores, and periodic Proposal decisions.
   `withFollowUpAfter7Days` is a conservative reuse proxy: it counts a concept
   only when a user follow-up was persisted at least seven days after the
   concept was created. It is not a page-view or cohort-retention metric. The
   report does not read or output captures, answers, deltas, Provider keys,
   owner IDs, or error messages.

9. Before the recovery milestone is closed, run the resumable 20-turn protocol:

   ```bash
   backend/.venv/bin/python scripts/recovery_dogfood.py
   ```

   If the Backend uses a real Provider, this command exits before creating a
   ModelRun. Live execution requires an explicit cost acknowledgement:

   ```bash
   backend/.venv/bin/python scripts/recovery_dogfood.py --confirm-live-cost
   ```

   The runner saves only IDs, counters, protocol hash, and progress under
   `.data/recovery-dogfood-state.json`; it does not persist questions or model
   answers. Re-running the same command resumes from that state and reuses
   deterministic idempotency keys. While it runs, stop and restart the Backend
   once, or interrupt the local connection, then confirm the final JSON has
   `passed=true`, `persistedTurns=42`, `eventIntegrityPassed=true`,
   `maintenancePassed=true`, `earlyContextRecallPassed=true`, and
   `transientNetworkFailures>0`. A crash
   during a Provider stream can legitimately cause one additional paid Provider
   call, while durable Concept and Turn writes must remain unique.

   Simulator UI automation separately terminates the app during both an
   initial run and a follow-up run. Relaunch acceptance requires one recovered
   question, one recovered answer, one submission request, and no false
   "previous follow-up was not sent" error. The explicitly authorized DeepSeek
   session completed this check on 2026-07-19: the Backend persisted one
   follow-up pair while the App was terminated, and the relaunched Simulator
   displayed the recovered answer once.

## Non-Goals

- No public DNS or public TLS ingress.
- No managed Sift backend.
- No invite / activation flow.
- No beta access token.
- No ephemeral BYOK relay.
- No Tailscale SDK or device enrollment automation.
- No changes to provider catalog, provider adapters, runtime, note UI, or
  follow-up UI.

## Acceptance Checks

- Simulator still works with `http://127.0.0.1:8000`.
- Debug/Personal can edit, save, test, and reset Backend URL.
- A fake `https://example.ts.net` reports unavailable without crashing.
- `SIFT_BACKEND_BASE_URL` remains the highest-priority override.
- Release/Managed builds do not expose editable backend URL controls.
- The ModelRun metrics report contains no capture content, model output,
  credentials, owner identifiers, or raw errors.
- Capture success excludes active attempts from its denominator, and product
  reuse metrics are derived only from IDs, timestamps, roles, and statuses.
- The recovery runner refuses a non-Mock Provider without
  `--confirm-live-cost`, survives connection errors and temporary 502/503/504
  responses, and a second run against the same state produces no duplicate
  initial or follow-up ModelRuns.
