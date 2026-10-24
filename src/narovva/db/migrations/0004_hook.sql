-- The hook package each post opened with, so results can be compared by formula.
ALTER TABLE post_history ADD COLUMN IF NOT EXISTS hook_text TEXT;
ALTER TABLE post_history ADD COLUMN IF NOT EXISTS hook_formula TEXT;
ALTER TABLE post_history ADD COLUMN IF NOT EXISTS hook_score INTEGER;
ALTER TABLE post_history ADD COLUMN IF NOT EXISTS cover_text TEXT;
