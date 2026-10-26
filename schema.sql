-- EmoEdit 标注台 · D1 结构
CREATE TABLE IF NOT EXISTS config (k TEXT PRIMARY KEY, v TEXT);

CREATE TABLE IF NOT EXISTS items (
  id INTEGER PRIMARY KEY,
  ord INTEGER UNIQUE,
  subset TEXT,
  emotion TEXT,
  origin_id TEXT,
  prompt TEXT,
  origin_asset TEXT,
  edited_asset TEXT,
  kind TEXT DEFAULT 'image'
);

CREATE TABLE IF NOT EXISTS labels (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  item_id INTEGER UNIQUE,
  annotator TEXT,
  verdict TEXT,
  new_prompt TEXT,
  note TEXT,
  ms INTEGER DEFAULT 0,
  created_at REAL
);

CREATE TABLE IF NOT EXISTS claims (
  item_id INTEGER PRIMARY KEY,
  annotator TEXT,
  expires REAL
);

CREATE TABLE IF NOT EXISTS skips (
  item_id INTEGER,
  annotator TEXT,
  created_at REAL,
  PRIMARY KEY (item_id, annotator)
);

CREATE INDEX IF NOT EXISTS idx_labels_ann ON labels(annotator);
