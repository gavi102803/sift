CREATE TABLE concept_sources (
    id TEXT PRIMARY KEY,
    concept_id TEXT NOT NULL,
    owner_id TEXT NOT NULL,
    title TEXT NOT NULL,
    url TEXT,
    source_type TEXT NOT NULL,
    retrieved_at TEXT,
    published_at TEXT,
    content_hash TEXT,
    FOREIGN KEY (concept_id) REFERENCES concepts (id) ON DELETE CASCADE,
    UNIQUE (concept_id, url)
);

CREATE INDEX idx_concept_sources_concept
    ON concept_sources (concept_id, retrieved_at);
