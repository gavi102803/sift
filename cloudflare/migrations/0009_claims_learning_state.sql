CREATE TABLE concept_claims (
    id TEXT PRIMARY KEY,
    concept_id TEXT NOT NULL,
    owner_id TEXT NOT NULL,
    statement TEXT NOT NULL,
    claim_type TEXT NOT NULL,
    evidence_status TEXT NOT NULL,
    time_sensitivity TEXT NOT NULL,
    source_ids_json TEXT NOT NULL DEFAULT '[]',
    verified_at TEXT,
    superseded_by_claim_id TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (concept_id) REFERENCES concepts (id) ON DELETE CASCADE,
    UNIQUE (concept_id, statement)
);

CREATE INDEX idx_concept_claims_concept
    ON concept_claims (concept_id, created_at);

CREATE TABLE learning_state_entries (
    id TEXT PRIMARY KEY,
    concept_id TEXT NOT NULL,
    owner_id TEXT NOT NULL,
    field TEXT NOT NULL,
    content TEXT NOT NULL,
    origin TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (concept_id) REFERENCES concepts (id) ON DELETE CASCADE,
    UNIQUE (concept_id, field, content)
);

CREATE INDEX idx_learning_state_concept_field
    ON learning_state_entries (concept_id, field, created_at);
