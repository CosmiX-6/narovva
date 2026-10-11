-- Remember which voice narrated each Reel so later posts pick a different one.
ALTER TABLE post_history ADD COLUMN IF NOT EXISTS narration_voice TEXT;
