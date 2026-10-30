-- EmoEdit 视频标注台 · D1 结构（全新库用这份）
CREATE TABLE IF NOT EXISTS config (k TEXT PRIMARY KEY, v TEXT);

CREATE TABLE IF NOT EXISTS items (
  id INTEGER PRIMARY KEY,
  ord INTEGER UNIQUE,
  subset TEXT,              -- single | grad | trans
  emotion TEXT,             -- 目标情绪：happy/sad/worried/angry
  intensity TEXT,           -- L | M | H（trans 为空）
  trans_from TEXT,          -- 过渡起点情绪（仅 trans）
  origin_id TEXT,           -- MER2025 源视频 id
  duration REAL,            -- 目标时长（秒）
  prompt TEXT,              -- 使用的编辑 prompt（原文）
  origin_asset TEXT,        -- vid/origin/<src>.mp4
  edited_asset TEXT,        -- vid/edit/<stem>.mp4
  kind TEXT DEFAULT 'video'
);

CREATE TABLE IF NOT EXISTS labels (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  item_id INTEGER UNIQUE,
  annotator TEXT,
  verdict TEXT,             -- ok | bad
  -- 分项维度
  emo_clarity INTEGER,      -- 情绪可辨识度 1..5
  intensity_fit TEXT,       -- weaker | good | stronger
  identity_keep INTEGER,    -- 身份保持 1..5
  comp_keep INTEGER,        -- 构图/动作保持 1..5
  audio_keep TEXT,          -- yes | no | na
  trans_smooth TEXT,        -- yes | no | na
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
