PRAGMA foreign_keys = ON;

CREATE TABLE managed_provider_connections (
    owner_id TEXT PRIMARY KEY,
    provider_id TEXT NOT NULL,
    base_url TEXT NOT NULL,
    model TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE concepts (
    id TEXT PRIMARY KEY,
    owner_id TEXT NOT NULL,
    canonical_title TEXT NOT NULL,
    display_title TEXT NOT NULL,
    one_line_explanation TEXT NOT NULL,
    initial_answer TEXT,
    maturity TEXT NOT NULL,
    capture_status TEXT NOT NULL,
    note_revision INTEGER NOT NULL,
    answer_source_json TEXT,
    document_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX idx_concepts_owner_created
    ON concepts (owner_id, created_at);

CREATE TABLE note_blocks (
    id TEXT PRIMARY KEY,
    concept_id TEXT NOT NULL,
    block_type TEXT NOT NULL,
    content TEXT NOT NULL,
    source TEXT NOT NULL,
    is_user_locked INTEGER NOT NULL DEFAULT 0,
    revision INTEGER NOT NULL DEFAULT 1,
    supported_claim_ids_json TEXT NOT NULL DEFAULT '[]',
    position INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (concept_id) REFERENCES concepts (id) ON DELETE CASCADE,
    UNIQUE (concept_id, position)
);

CREATE INDEX idx_note_blocks_concept_position
    ON note_blocks (concept_id, position);

CREATE TABLE concept_tags (
    concept_id TEXT NOT NULL,
    name TEXT NOT NULL,
    PRIMARY KEY (concept_id, name),
    FOREIGN KEY (concept_id) REFERENCES concepts (id) ON DELETE CASCADE
);

CREATE TABLE concept_topics (
    concept_id TEXT NOT NULL,
    name TEXT NOT NULL,
    PRIMARY KEY (concept_id, name),
    FOREIGN KEY (concept_id) REFERENCES concepts (id) ON DELETE CASCADE
);

CREATE TABLE note_revisions (
    concept_id TEXT NOT NULL,
    revision INTEGER NOT NULL,
    snapshot_json TEXT NOT NULL,
    actor TEXT NOT NULL,
    event_type TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (concept_id, revision),
    FOREIGN KEY (concept_id) REFERENCES concepts (id) ON DELETE CASCADE
);

CREATE TABLE concept_turns (
    id TEXT PRIMARY KEY,
    concept_id TEXT NOT NULL,
    owner_id TEXT NOT NULL,
    operation_key TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    answer_source_json TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (concept_id) REFERENCES concepts (id) ON DELETE CASCADE,
    UNIQUE (concept_id, operation_key, role)
);

CREATE INDEX idx_concept_turns_concept_created
    ON concept_turns (concept_id, created_at);
