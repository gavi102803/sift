PRAGMA foreign_keys = ON;

CREATE TABLE beta_invites (
    code_hash TEXT PRIMARY KEY,
    owner_id TEXT,
    installation_id TEXT,
    consumed_at TEXT,
    revoked_at TEXT
);

CREATE TABLE beta_sessions (
    id TEXT PRIMARY KEY,
    token_hash TEXT NOT NULL UNIQUE,
    owner_id TEXT NOT NULL,
    installation_id TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    revoked_at TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX idx_beta_sessions_owner_id
    ON beta_sessions (owner_id);

CREATE TABLE owner_revocations (
    owner_id TEXT PRIMARY KEY,
    revoked_at TEXT NOT NULL
);

CREATE TABLE model_runs (
    id TEXT PRIMARY KEY,
    owner_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    status TEXT NOT NULL,
    concept_id TEXT,
    client_draft_id TEXT,
    idempotency_key TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    provider_snapshot_json TEXT NOT NULL DEFAULT '{}',
    agent_spec TEXT NOT NULL,
    agent_spec_version TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    budget_json TEXT NOT NULL DEFAULT '{}',
    current_step TEXT,
    model_call_count INTEGER NOT NULL DEFAULT 0,
    tool_call_count INTEGER NOT NULL DEFAULT 0,
    termination_reason TEXT,
    dependency_run_id TEXT,
    checkpoint TEXT,
    checkpoint_json TEXT,
    result_json TEXT,
    result_ref TEXT,
    error_code TEXT,
    error_message TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (owner_id, kind, idempotency_key)
);

CREATE INDEX idx_model_runs_owner_created
    ON model_runs (owner_id, created_at);

CREATE INDEX idx_model_runs_owner_status
    ON model_runs (owner_id, status);

CREATE TABLE model_run_events (
    run_id TEXT NOT NULL,
    sequence INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    data_json TEXT,
    created_at TEXT NOT NULL,
    PRIMARY KEY (run_id, sequence),
    FOREIGN KEY (run_id) REFERENCES model_runs (id) ON DELETE CASCADE
);

CREATE INDEX idx_model_run_events_run_sequence
    ON model_run_events (run_id, sequence);
