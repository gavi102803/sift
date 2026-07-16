# Phase A/B Acceptance Matrix

Date: 2026-07-15

Branch under review: `codex/sift-mvp`
Status: repository implementation complete; external release evidence pending

This matrix separates evidence reproducible from the repository from evidence that requires the
repository owner, managed infrastructure, a signed TestFlight build, or elapsed dogfood time. Phase
A/B must not be called release-complete until every exit item is green.

## Repository evidence

| Gate | Status | Reproducible evidence |
| --- | --- | --- |
| One-command backend + iOS gate | Pass | `scripts/check.sh all` |
| Backend lint and tests | Pass | Ruff clean; 177 passed, 1 PostgreSQL-only skipped |
| iOS unit tests | Pass | 62 tests on iPhone 17 Pro Simulator |
| Managed onboarding UI journey | Pass | `SiftUITests`: clean state → invite activation → Provider connection → capture → streamed first concept |
| Python dependency reproduction | Pass | Python 3.12 lock file and clean-environment installation |
| Auth lifecycle | Pass | Invite activation, installation binding, 30-day token, refresh window, token/owner revoke |
| Owner isolation | Pass | Token-derived owner, cross-owner concept/proposal 404, owner-scoped idempotency |
| Managed BYOK persistence boundary | Pass | Provider key excluded from database, API bodies, responses, logs, and safe upstream errors |
| Managed iOS credential boundary | Pass at unit level | Session/provider key storage code uses Keychain; provider key header appears only on provider-test/runtime requests |
| Managed release endpoint | Pass at build level | Release plist contains a fixed HTTPS endpoint and never falls back to localhost |
| Production database contract | Pass at code/config level | psycopg URL validation, Alembic migrations, CI PostgreSQL service, backup/restore scripts |
| Operations contract | Pass at documentation level | Deploy, rollback, revoke, backup/restore, edge logging and incident controls documented |

The UI test uses an in-memory credential store behind a DEBUG-only launch flag because the
repository's unsigned simulator build cannot reliably exercise the system Keychain. It validates
the user journey and HTTP contracts, but it is not evidence that a signed Release build persists
credentials correctly on a physical device.

## External exit evidence

| Exit item | Status | Owner action / proof required |
| --- | --- | --- |
| Confirm the release source of truth | Pass | Repository owner confirmed `codex/sift-mvp` on 2026-07-15; recorded in `phase-a-baseline.md` |
| Align the remote default branch | Pending external Git operation | Preserve the legacy `main` as a backup ref, then make the confirmed history the review/release default |
| Green checks from clean PR checkout | Pending | Push branch and capture GitHub Actions result, including PostgreSQL service migration smoke |
| Real managed domain and TLS | Pending | Replace `https://beta.sift.example`, deploy, and verify public health/auth paths |
| Production PostgreSQL migration | Pending | Run `alembic upgrade head` on the target service and retain logs/schema evidence |
| Backup and restore drill | Pending | Restore a real backup into an isolated database and verify representative owner data |
| Signed iPhone/TestFlight onboarding | Pending | Fresh install, activation, Keychain persistence, relaunch, Provider connection, first concept |
| Real Provider secret redaction | Pending | Inspect host, edge, error, and trace systems while exercising success/failure paths |
| Seven-day no-loss dogfood | Pending | Real iPhone + real Provider, continuous use, no lost capture/follow-up, incidents recorded |
| Closed Beta cohort evidence | Pending | Invite 20–50 users only after operational gates; measure activation, first card, failure and retention |

## Decision

The codebase is a **Managed Closed Beta Candidate**, not yet an approved Closed Beta release. Do not
start feature expansion or broad structural migration before the external exit evidence is closed.
The next engineering work should be deployment evidence and dogfood reliability fixes discovered by
that evidence; FSD/DDD extraction remains incremental and demand-driven.
