-- Which renderer made each reel (characters | motion | plain), so the report can compare formats.
ALTER TABLE post_history ADD COLUMN IF NOT EXISTS reel_format TEXT;
