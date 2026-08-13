# Sift Local-First MVP Runbook

This runbook is for personal development and iOS Simulator testing:

```text
iOS Simulator / iPhone
→ local Mac backend
→ local SQLite
→ external model API
```

## Start The Local Companion

From the repository root:

```bash
scripts/run_local_companion.sh
```

The iOS Simulator should use:

```text
http://127.0.0.1:8000
```

For iPhone + Tailscale personal dogfood, keep the backend on Mac loopback and
publish it privately through Tailscale Serve:

```bash
scripts/run_local_companion.sh
```

In another terminal:

```bash
tailscale serve --bg http://127.0.0.1:8000
tailscale serve status
```

Then configure the Debug/Personal iOS build with your Tailscale HTTPS name:

```text
https://<mac-machine>.<tailnet>.ts.net
```

Do not treat a failed backend connection as mock mode. If the app says it cannot connect, start or restart the local companion and run the doctor below.

## Run Doctor

```bash
scripts/local_mvp_doctor.py
```

For Tailnet dogfood:

```bash
scripts/local_mvp_doctor.py --backend-url https://<mac-machine>.<tailnet>.ts.net
```

The doctor checks:

- backend reachability at `127.0.0.1:8000`;
- local SQLite writability;
- whether the app is using mock or a real provider;
- configured provider, model, base URL, and web provider.

It does not print API keys, Authorization headers, or full credential values.
It also redacts credentials accidentally embedded in diagnostic URLs.

## Provider Expectations

For realistic hand testing, Profile should show a real provider and model, not mock. If the doctor reports `provider=mock`, configure a provider and API key in the app Profile page, then rerun the doctor.

## SQLite

The default local database is:

```text
backend/.data/sift.db
```

The doctor writes and deletes a tiny `_sift_doctor_write_check` row to verify local write access.

## Real iPhone Note

The Simulator can use `127.0.0.1:8000` because it shares the Mac development
loopback behavior. A physical iPhone should use the Phase 0 Personal Tailnet
Dogfood path:

```text
iPhone + Mac
→ Tailscale private network
→ https://<mac-machine>.<tailnet>.ts.net
→ Sift backend running on the Mac
```

The shared Debug scheme intentionally does not set `SIFT_BACKEND_BASE_URL`.
Simulator builds therefore use the built-in localhost default, while a
physical iPhone can use the Personal backend URL saved in Profile > Developer.

Do not expose the local backend publicly for this MVP. See
`docs/contracts/personal-tailnet-dogfood.md` for the Debug/Personal build
contract and acceptance checks.
