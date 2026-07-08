CREATE TABLE IF NOT EXISTS feedbacks (
  id TEXT PRIMARY KEY,
  content TEXT NOT NULL,
  display_name TEXT NOT NULL DEFAULT '匿名用户',
  like_count INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  deleted_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_feedbacks_visible_created
ON feedbacks (deleted_at, created_at DESC);
