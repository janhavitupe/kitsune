-- Kitsune schema. Applied at startup; every statement is idempotent.
-- Tables used by later milestones are created now so the schema never needs a migration mid-hackathon.

CREATE TABLE IF NOT EXISTS repos (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  created_at TEXT NOT NULL,
  private_mode INTEGER NOT NULL DEFAULT 0       -- 1: captions and query reading on open weights only
);

CREATE TABLE IF NOT EXISTS blobs (
  sha256 TEXT PRIMARY KEY,
  path TEXT NOT NULL,          -- relative to DATA_DIR
  width INTEGER NOT NULL,
  height INTEGER NOT NULL,
  mime TEXT NOT NULL,
  thumb_path TEXT NOT NULL     -- relative to DATA_DIR
);

CREATE TABLE IF NOT EXISTS branches (
  id INTEGER PRIMARY KEY,
  repo_id INTEGER NOT NULL REFERENCES repos(id),
  name TEXT NOT NULL,
  head_commit_id INTEGER REFERENCES commits(id),
  kind TEXT NOT NULL DEFAULT 'normal',          -- normal | explore
  created_at TEXT NOT NULL,
  UNIQUE (repo_id, name)
);

CREATE TABLE IF NOT EXISTS commits (
  id INTEGER PRIMARY KEY,
  repo_id INTEGER NOT NULL REFERENCES repos(id),
  seq INTEGER NOT NULL,                          -- v-number, repo-wide: v1, v2, ...
  branch_id INTEGER NOT NULL REFERENCES branches(id),
  parent_id INTEGER REFERENCES commits(id),
  merge_parent_id INTEGER REFERENCES commits(id),
  blob_sha TEXT NOT NULL REFERENCES blobs(sha256),
  message TEXT,
  auto_message TEXT,
  origin TEXT NOT NULL DEFAULT 'upload',         -- upload | cherry_pick | merge | explore | assistant
  origin_meta_json TEXT,
  analysis_status TEXT NOT NULL DEFAULT 'pending', -- pending | running | done | failed
  created_at TEXT NOT NULL,
  UNIQUE (repo_id, seq)
);
CREATE INDEX IF NOT EXISTS idx_commits_repo ON commits(repo_id, seq);

CREATE TABLE IF NOT EXISTS regions (
  id INTEGER PRIMARY KEY,
  blob_sha TEXT NOT NULL REFERENCES blobs(sha256),
  label TEXT NOT NULL,
  mask_path TEXT NOT NULL,
  bbox_json TEXT,
  area_px INTEGER,
  score REAL,
  source TEXT
);
CREATE INDEX IF NOT EXISTS idx_regions_blob ON regions(blob_sha);

CREATE TABLE IF NOT EXISTS diffs (
  id INTEGER PRIMARY KEY,
  from_commit INTEGER NOT NULL REFERENCES commits(id),
  to_commit INTEGER NOT NULL REFERENCES commits(id),
  changed_regions_json TEXT,
  change_mask_path TEXT,
  summary TEXT,
  UNIQUE (from_commit, to_commit)
);

CREATE TABLE IF NOT EXISTS voice_notes (
  id INTEGER PRIMARY KEY,
  commit_id INTEGER NOT NULL REFERENCES commits(id),
  kind TEXT NOT NULL DEFAULT 'artist',           -- artist | client
  audio_path TEXT,
  transcript TEXT,
  summary TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS captions (
  blob_sha TEXT NOT NULL REFERENCES blobs(sha256),
  caption TEXT NOT NULL,
  model TEXT NOT NULL,
  PRIMARY KEY (blob_sha, model)
);

CREATE TABLE IF NOT EXISTS merges (
  id INTEGER PRIMARY KEY,
  repo_id INTEGER NOT NULL REFERENCES repos(id),
  source_branch INTEGER NOT NULL REFERENCES branches(id),
  target_branch INTEGER NOT NULL REFERENCES branches(id),
  base_commit INTEGER REFERENCES commits(id),
  plan_json TEXT,
  status TEXT NOT NULL DEFAULT 'open'            -- open | resolved | aborted
);

CREATE TABLE IF NOT EXISTS ai_cache (
  key TEXT PRIMARY KEY,                          -- sha256(model + canonical inputs)
  model TEXT NOT NULL,
  response_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE VIRTUAL TABLE IF NOT EXISTS search_index USING fts5(
  commit_id UNINDEXED, message, auto_message, caption, voice, region_labels
);
