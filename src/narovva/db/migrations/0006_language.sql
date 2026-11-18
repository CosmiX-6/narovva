-- The content language of each post ("en", "hi"), so results can be compared by language.
ALTER TABLE post_history ADD COLUMN IF NOT EXISTS language TEXT;
