CREATE TABLE update_proposals (
    id TEXT PRIMARY KEY,
    concept_id TEXT NOT NULL,
    owner_id TEXT NOT NULL,
    base_note_revision INTEGER NOT NULL,
    patch_operations_json TEXT NOT NULL,
    rationale TEXT NOT NULL,
    confidence REAL NOT NULL,
    status TEXT NOT NULL,
    origin TEXT NOT NULL,
    source_run_id TEXT,
    created_at TEXT NOT NULL,
    resolved_at TEXT,
    FOREIGN KEY (concept_id) REFERENCES concepts (id) ON DELETE CASCADE,
    FOREIGN KEY (source_run_id) REFERENCES model_runs (id) ON DELETE SET NULL
);

CREATE INDEX idx_update_proposals_concept_status
    ON update_proposals (concept_id, status, created_at);

CREATE INDEX idx_update_proposals_owner
    ON update_proposals (owner_id, created_at);

CREATE TABLE mutation_idempotency (
    owner_id TEXT NOT NULL,
    scope TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    response_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (owner_id, scope, idempotency_key)
);
