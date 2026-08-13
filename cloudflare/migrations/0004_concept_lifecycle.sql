ALTER TABLE concepts
    ADD COLUMN archived_from_status TEXT;

CREATE TABLE concept_relations (
    id TEXT PRIMARY KEY,
    source_concept_id TEXT NOT NULL,
    target_concept_id TEXT NOT NULL,
    relation_type TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'accepted',
    confidence REAL NOT NULL DEFAULT 1,
    source TEXT NOT NULL DEFAULT 'user',
    created_at TEXT NOT NULL,
    FOREIGN KEY (source_concept_id) REFERENCES concepts (id) ON DELETE CASCADE,
    FOREIGN KEY (target_concept_id) REFERENCES concepts (id) ON DELETE CASCADE,
    UNIQUE (source_concept_id, target_concept_id, relation_type)
);

CREATE INDEX idx_concept_relations_source
    ON concept_relations (source_concept_id);

CREATE INDEX idx_concept_relations_target
    ON concept_relations (target_concept_id);
