CREATE TABLE managed_web_provider_settings (
    owner_id TEXT PRIMARY KEY,
    provider_type TEXT NOT NULL DEFAULT 'ddgs',
    web_search_enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
