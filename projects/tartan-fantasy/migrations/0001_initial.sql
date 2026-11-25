PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS managers (
    id TEXT PRIMARY KEY,
    token TEXT NOT NULL UNIQUE,
    manager_name TEXT NOT NULL,
    team_name TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS leagues (
    id TEXT PRIMARY KEY,
    code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    owner_manager_id TEXT NOT NULL REFERENCES managers(id),
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS league_members (
    league_id TEXT NOT NULL REFERENCES leagues(id) ON DELETE CASCADE,
    manager_id TEXT NOT NULL REFERENCES managers(id) ON DELETE CASCADE,
    joined_at TEXT NOT NULL,
    PRIMARY KEY (league_id, manager_id)
);

CREATE TABLE IF NOT EXISTS squads (
    manager_id TEXT NOT NULL REFERENCES managers(id) ON DELETE CASCADE,
    gameweek INTEGER NOT NULL,
    players_json TEXT NOT NULL,
    bench_json TEXT NOT NULL DEFAULT '[]',
    captain TEXT NOT NULL,
    vice_captain TEXT NOT NULL,
    chip TEXT,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (manager_id, gameweek)
);

CREATE INDEX IF NOT EXISTS idx_league_members_manager ON league_members(manager_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_squads_one_chip
    ON squads(manager_id, chip) WHERE chip IS NOT NULL;
