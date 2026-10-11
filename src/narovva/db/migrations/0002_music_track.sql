-- Remember which music track each Reel used so later posts pick a different one.
ALTER TABLE post_history ADD COLUMN IF NOT EXISTS music_track_id TEXT;
