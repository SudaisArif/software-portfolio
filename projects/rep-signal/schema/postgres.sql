-- PostgreSQL deployment schema (apply with a privileged migration role).
-- The runnable Engine currently uses SQLite; a PostgreSQL Store implementation
-- and concurrency/load verification are required before switching runtimes.
-- No public/anonymous table access is granted. Credentials stay server-side.
BEGIN;
CREATE TABLE IF NOT EXISTS settings (
    key text PRIMARY KEY,
    value jsonb NOT NULL
);
CREATE TABLE IF NOT EXISTS jobs (
    id text PRIMARY KEY,
    title text NOT NULL,
    concept text NOT NULL DEFAULT '',
    state text NOT NULL CHECK (state IN ('DISCOVERED','RESEARCHED','SCRIPTED','HUMAN_REVIEW','APPROVED','RENDERING','QC','SCHEDULED','PUBLISHED','ANALYZED','FAILED','RETRYING','CANCELLED')),
    revision integer NOT NULL DEFAULT 0 CHECK (revision >= 0),
    script text NOT NULL DEFAULT '',
    sources jsonb NOT NULL DEFAULT '[]',
    brief text NOT NULL DEFAULT '',
    approved_revision integer,
    script_approved_by text,
    render_path text,
    artifact_sha256 text,
    captions jsonb NOT NULL DEFAULT '[]',
    qc jsonb,
    release_sha256 text,
    release_approved_by text,
    created_at double precision NOT NULL,
    updated_at double precision NOT NULL,
    error text,
    render_lease_until double precision,
    retry_at double precision,
    render_token text
);
CREATE TABLE IF NOT EXISTS assets (
    id text PRIMARY KEY,
    job_id text NOT NULL REFERENCES jobs(id),
    kind text NOT NULL,
    path text NOT NULL,
    rights_status text NOT NULL CHECK (rights_status IN ('original','licensed','public_domain','unknown','preview_only')),
    license_url text NOT NULL,
    provenance text NOT NULL,
    sha256 text NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    job_id text REFERENCES jobs(id),
    event text NOT NULL,
    actor text NOT NULL,
    payload jsonb NOT NULL,
    at double precision NOT NULL
);
CREATE TABLE IF NOT EXISTS renders (
    id text PRIMARY KEY,
    job_id text NOT NULL REFERENCES jobs(id),
    day text NOT NULL,
    at double precision NOT NULL
);
CREATE TABLE IF NOT EXISTS deliveries (
    id text PRIMARY KEY,
    job_id text NOT NULL REFERENCES jobs(id),
    revision integer NOT NULL,
    platform text NOT NULL CHECK (platform IN ('youtube','instagram','tiktok')),
    fingerprint text NOT NULL,
    scheduled_at double precision NOT NULL,
    day text NOT NULL,
    status text NOT NULL CHECK (status IN ('SCHEDULED','IN_FLIGHT','SUBMITTED','UNKNOWN','RETRYING','FAILED','CANCELLED','PUBLISHED')),
    attempts integer NOT NULL DEFAULT 0,
    lease_until double precision,
    retry_at double precision,
    external_id text,
    url text,
    error text,
    account_id text,
    UNIQUE(job_id,revision,platform),
    UNIQUE(platform,fingerprint)
);
CREATE TABLE IF NOT EXISTS reservations (
    job_id text NOT NULL REFERENCES jobs(id),
    revision integer NOT NULL,
    day text NOT NULL,
    PRIMARY KEY(job_id,revision,day)
);
CREATE TABLE IF NOT EXISTS costs (
    id text PRIMARY KEY,
    provider text NOT NULL,
    reserved numeric(12,6) NOT NULL CHECK (reserved >= 0),
    actual numeric(12,6) CHECK (actual >= 0),
    status text NOT NULL CHECK (status IN ('RESERVED','SETTLED','RELEASED')),
    month text NOT NULL,
    at double precision NOT NULL
);
CREATE TABLE IF NOT EXISTS metrics (
    id text PRIMARY KEY,
    job_id text NOT NULL REFERENCES jobs(id),
    platform text NOT NULL,
    external_id text NOT NULL,
    observed_at double precision NOT NULL,
    source text NOT NULL,
    values_json jsonb NOT NULL
);
CREATE INDEX IF NOT EXISTS delivery_due ON deliveries(status,scheduled_at,retry_at);
CREATE INDEX IF NOT EXISTS job_events ON events(job_id,at);
ALTER TABLE deliveries ADD COLUMN IF NOT EXISTS account_id text;
-- Deny by default for Supabase client roles. Backend uses a dedicated privileged
-- connection. Add least-privilege RLS policies before exposing any client API.
ALTER TABLE settings ENABLE ROW LEVEL SECURITY;
ALTER TABLE jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE assets ENABLE ROW LEVEL SECURITY;
ALTER TABLE events ENABLE ROW LEVEL SECURITY;
ALTER TABLE renders ENABLE ROW LEVEL SECURITY;
ALTER TABLE deliveries ENABLE ROW LEVEL SECURITY;
ALTER TABLE reservations ENABLE ROW LEVEL SECURITY;
ALTER TABLE costs ENABLE ROW LEVEL SECURITY;
ALTER TABLE metrics ENABLE ROW LEVEL SECURITY;
-- Local review-artifact bridge migration. Prepared only; apply separately to a
-- cloud database after reviewing access. The live runtime remains SQLite.
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS audio_mode text NOT NULL DEFAULT 'narrated';
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS active_preview_id text;
CREATE TABLE IF NOT EXISTS preview_artifacts (
    id text PRIMARY KEY,
    job_id text NOT NULL REFERENCES jobs(id),
    revision integer NOT NULL,
    path text NOT NULL,
    artifact_sha256 text NOT NULL,
    manifest_path text NOT NULL,
    manifest_sha256 text NOT NULL,
    script_sha256 text NOT NULL,
    audio_mode text NOT NULL CHECK (audio_mode IN ('narrated','visual_essay','source_audio')),
    captions jsonb NOT NULL,
    assets jsonb NOT NULL,
    qc jsonb,
    created_at double precision NOT NULL,
    UNIQUE(job_id,revision,artifact_sha256,manifest_sha256)
);
CREATE INDEX IF NOT EXISTS preview_job ON preview_artifacts(job_id,revision);
ALTER TABLE preview_artifacts ENABLE ROW LEVEL SECURITY;
COMMIT;
