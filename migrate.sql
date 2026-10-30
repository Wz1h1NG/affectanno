-- 在已有图片版库上就地升级为视频版（ALTER TABLE ADD COLUMN）
ALTER TABLE items ADD COLUMN intensity TEXT;
ALTER TABLE items ADD COLUMN trans_from TEXT;
ALTER TABLE items ADD COLUMN duration REAL;

ALTER TABLE labels ADD COLUMN emo_clarity INTEGER;
ALTER TABLE labels ADD COLUMN intensity_fit TEXT;
ALTER TABLE labels ADD COLUMN identity_keep INTEGER;
ALTER TABLE labels ADD COLUMN comp_keep INTEGER;
ALTER TABLE labels ADD COLUMN audio_keep TEXT;
ALTER TABLE labels ADD COLUMN trans_smooth TEXT;
