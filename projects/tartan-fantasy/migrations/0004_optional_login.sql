CREATE TABLE IF NOT EXISTS manager_logins (
    manager_id TEXT PRIMARY KEY REFERENCES managers(id) ON DELETE CASCADE,
    code_hash TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS manager_sessions (
    token_hash TEXT PRIMARY KEY,
    manager_id TEXT NOT NULL REFERENCES managers(id) ON DELETE CASCADE,
    expires_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_manager_sessions_manager ON manager_sessions(manager_id);

CREATE TABLE IF NOT EXISTS login_attempts (
    bucket TEXT PRIMARY KEY,
    window_start INTEGER NOT NULL,
    attempts INTEGER NOT NULL
);
