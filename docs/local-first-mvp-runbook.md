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

Do not treat a failed backend connection as mock mode. If the app says it cannot connect, start or restart the local companion and run the doctor below.

## Run Doctor

```bash
scripts/local_mvp_doctor.py
```

The doctor checks:

- backend reachability at `127.0.0.1:8000`;
- local SQLite writability;
- whether the app is using mock or a real provider;
- configured provider, model, base URL, and web provider.

It does not print API keys, Authorization headers, or full credential values.

## Provider Expectations

For realistic hand testing, Profile should show a real provider and model, not mock. If the doctor reports `provider=mock`, configure a provider and API key in the app Profile page, then rerun the doctor.

## SQLite

The default local database is:

```text
backend/.data/sift.db
```

The doctor writes and deletes a tiny `_sift_doctor_write_check` row to verify local write access.

## Real iPhone Note

The Simulator can use `127.0.0.1:8000` because it shares the Mac development loopback behavior. A physical iPhone will need a Mac LAN address or a private network path such as Tailscale in a future step. Do not expose the local backend publicly for this MVP.
