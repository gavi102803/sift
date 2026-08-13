PRAGMA foreign_keys = ON;

CREATE TABLE concept_continuity_summaries (
    concept_id TEXT PRIMARY KEY,
    owner_id TEXT NOT NULL,
    summary TEXT NOT NULL,
    through_turn_count INTEGER NOT NULL,
    source_turns_hash TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    generated_at TEXT NOT NULL,
    FOREIGN KEY (concept_id) REFERENCES concepts (id) ON DELETE CASCADE
);

CREATE TABLE concept_maintenance_state (
    concept_id TEXT PRIMARY KEY,
    owner_id TEXT NOT NULL,
    reviewed_user_turn_count INTEGER NOT NULL DEFAULT 1,
    review_due INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (concept_id) REFERENCES concepts (id) ON DELETE CASCADE
);
