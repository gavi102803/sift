# Managed BYOK Beta Runbook

Status: deployable configuration; no production host or domain is claimed by this repository.

## Development-machine beta host

A development machine may serve as the Managed Closed Beta host for the Phase B validation window,
provided it is operated as a dedicated, always-on server rather than an interactive developer
process. This is acceptable for a small invite-only cohort and dogfood evidence; it is not the
recommended long-term production topology.

Required host profile:

- expose only a stable public HTTPS hostname through an outbound tunnel or managed reverse proxy;
  bind the Sift backend to loopback and do not port-forward the machine directly from the router;
- run the backend, tunnel connector, and PostgreSQL under supervised services that start after
  reboot and restart on failure; a terminal window is not a service manager;
- keep PostgreSQL private to the host, use a separate database account, and run encrypted backups
  to storage outside the machine;
- disable sleep, provide stable power/network, enable disk encryption and OS security updates, and
  do not use the host for routine browsing, downloads, or unrelated experimental services;
- ensure the edge drops `Authorization` and `X-Sift-Provider-Key` from request logging, applies the
  activation/runtime rate limits below, and exposes only the Sift API hostname;
- monitor process health, disk capacity, certificate/tunnel status, database backups, error rate,
  and latency from a second device or external monitor.

For testers who should not install a VPN, an outbound tunnel with a custom domain is the preferred
development-machine ingress. A Tailscale Funnel hostname can be used for a very small internal
trial, but its public endpoint and platform/bandwidth constraints make it less suitable as the
stable 20–50 user beta endpoint. Tailscale Serve or a normal Tailnet URL is private and therefore
tests the Personal/Tailnet path, not zero-setup Managed onboarding.

The following do not meet the Managed Beta gate: plain HTTP, a self-signed certificate, direct
public exposure of Uvicorn or PostgreSQL, SQLite as the managed database, a laptop that sleeps or
frequently changes networks, or a service that requires a developer to keep a shell session open.

## Release boundary

- Release/TestFlight uses the compiled `SIFTBackendBaseURL` and never reads a saved Personal URL.
- Replace the example `https://beta.sift.example` in `ios/Sift/ManagedRelease-Info.plist` with the assigned HTTPS domain
  before archiving. The fallback is `https://not-configured.invalid`, never localhost.
- Debug remains the Personal/Tailnet build and may use `SIFT_BACKEND_BASE_URL` or a saved URL.
- Managed mode stores the beta token, installation id, and provider key in iOS Keychain. The
  provider key is relayed only on provider-test and model-runtime requests.

## Required backend configuration

Supply these values through the hosting platform's secret/configuration service, not committed
files:

```text
SIFT_ENV=production
SIFT_AUTH_MODE=managed
SIFT_DATABASE_URL=postgresql+psycopg://sift:<password>@<host>:5432/sift
SIFT_BETA_INVITE_CODES=<single-use-code-1>,<single-use-code-2>
SIFT_BETA_TOKEN_TTL_DAYS=30
```

The managed deployment must not set a shared runtime provider API key. Each user's key remains an
ephemeral request header and is never persisted by the backend.

Validate configuration before migrating or starting:

```bash
backend/.venv/bin/python scripts/check_managed_deployment.py
cd backend && ../backend/.venv/bin/alembic upgrade head
```

Start the service behind a TLS-terminating managed load balancer or reverse proxy. Permit only
HTTPS public traffic; do not expose the database publicly. At the edge, drop request-header/body
logging, cap request bodies, rate-limit `/v1/beta/activate` by source IP, and rate-limit runtime
requests by authenticated owner. The application does not claim multi-instance distributed rate
limiting; the hosting layer is the release enforcement point for the closed beta.

## Deploy and rollback

1. Run the repository gate: `scripts/check.sh all`.
2. Create and verify a PostgreSQL backup.
3. Run `alembic upgrade head` as a one-off release task.
4. Deploy the backend artifact with the required environment.
5. Verify `/health`, then activate a dedicated smoke invite and run provider test, capture, read,
   and follow-up journeys.
6. Archive the iOS Release build with the assigned HTTPS endpoint and confirm the Backend URL UI is
   absent.

Application rollback means redeploying the previous artifact. Database rollback should normally
use a forward corrective migration. Restore a backup only for destructive/corrupting incidents,
because restore discards writes after the backup point.

## Backup and restore drill

Use a PostgreSQL DSN accepted by `pg_dump`/`pg_restore` (without the SQLAlchemy `+psycopg` suffix):

```bash
SIFT_POSTGRES_DSN='postgresql://...' scripts/backup_postgres.sh /secure/sift.dump
SIFT_POSTGRES_DSN='postgresql://...' SIFT_CONFIRM_RESTORE=yes \
  scripts/restore_postgres.sh /secure/sift.dump
```

For a release drill, restore into an empty, isolated database, run `alembic current`, and verify
table counts plus one owner-scoped read. Never test restore against the live database.

## Incident controls

- Revoke a compromised owner with
  `backend/.venv/bin/python scripts/revoke_beta_owner.py <owner-id> --confirm`; a public admin
  endpoint is intentionally not exposed.
- Rotate invite codes and database credentials in the host secret manager.
- Treat provider keys as potentially exposed if a hosting layer logs request headers. Configure
  proxy/APM request-header capture to drop `Authorization`, `X-Sift-Provider-Key`, and cookies.
- API errors expose only stable codes, safe messages, and request IDs. Use request IDs for support;
  never request a user's provider key.

## Evidence still required before external beta

- assigned domain and valid TLS certificate;
- successful PostgreSQL migration smoke in CI and on the target host;
- successful isolated backup/restore drill;
- clean-install TestFlight onboarding on a real device;
- at least one continuous internal dogfood cycle with crash, latency, and failure-recovery review.
