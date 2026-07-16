# Phase A Trusted Baseline

Date: 2026-07-15

## Source of Truth

The repository owner confirmed on 2026-07-15 that `codex/sift-mvp` is the authoritative product and
release history. Its baseline commit is `8700404076faa8711643aeee6f30c64c901c9945`, plus reviewed
changes based on it. The local `main` branch is unrelated legacy history and is not a release source.

This decision establishes the source of truth but does not itself rewrite the remote `main` ref.
Repointing or replacing `main`, deleting the legacy branch, or pushing a release tag remains a
separate external Git operation and must preserve a recoverable backup ref.

## Reproducible Gate

From the repository root:

```bash
scripts/check.sh all
```

CI calls the same script with `backend` and `ios` targets. A release candidate is not valid unless
both targets pass from a clean checkout.

CI installs the Python 3.12 dependency set from `backend/requirements.lock`, then installs the
backend package without resolving a second dependency graph. Regenerate the lock only when
changing `backend/pyproject.toml`, and verify it from a clean virtual environment.

## Product Modes

### Personal Dogfood

- Debug/Personal iOS build.
- User-editable localhost, Tailnet, or developer HTTPS backend URL.
- Backend runs on the owner's Mac with local SQLite.
- Provider credentials may be stored in the Mac Keychain by the local backend.
- Development principal is permitted only in this mode.

The authoritative contract is `docs/contracts/personal-tailnet-dogfood.md`.

### Managed Closed Beta

- Release/Managed iOS build with a compiled HTTPS endpoint.
- No user-editable backend URL or infrastructure UI.
- Invite activation and bearer authentication are required.
- Owner identity is derived only from the bearer token.
- Provider credentials live in iOS Keychain and are relayed only for requests that need them.
- The backend must not persist relayed provider credentials.

The authoritative contract is `docs/contracts/managed-byok-beta.md`.

## Baseline Gates

- Backend lint, tests, and Alembic upgrade pass through `scripts/check.sh backend`.
- iOS build and unit tests pass through `scripts/check.sh ios`.
- Personal and Managed behavior remain separate build/runtime modes.
- Planned Managed gates are never represented as completed until their contract tests pass.
