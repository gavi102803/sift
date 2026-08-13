ALTER TABLE model_runs ADD COLUMN lease_owner TEXT;
ALTER TABLE model_runs ADD COLUMN lease_expires_at TEXT;
ALTER TABLE model_runs ADD COLUMN cancel_requested_at TEXT;
ALTER TABLE model_runs ADD COLUMN started_at TEXT;
ALTER TABLE model_runs ADD COLUMN completed_at TEXT;
ALTER TABLE model_runs ADD COLUMN step_count INTEGER NOT NULL DEFAULT 0;

CREATE INDEX idx_model_runs_recoverable
    ON model_runs (status, lease_expires_at);
