ALTER TABLE note_revisions
    ADD COLUMN snapshot_schema_version INTEGER NOT NULL DEFAULT 1;

ALTER TABLE note_revisions
    ADD COLUMN restored_from_revision INTEGER;
