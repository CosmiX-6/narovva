-- narovva-owned tables. seen_content is created separately by
-- info_snipe's PostgresContentStore (phase 2) -- not managed here.

CREATE TABLE IF NOT EXISTS post_history (
    id BIGSERIAL PRIMARY KEY,
    channel_id TEXT NOT NULL,
    genre TEXT NOT NULL,
    content_id TEXT NOT NULL,
    article_url TEXT NOT NULL,
    article_title TEXT NOT NULL,
    platform TEXT NOT NULL,
    asset_types TEXT[] NOT NULL DEFAULT '{}',
    caption TEXT,
    hashtags TEXT[] NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'success', 'failed', 'skipped')),
    platform_post_id TEXT,
    attempt_count INT NOT NULL DEFAULT 0,
    last_error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    published_at TIMESTAMPTZ,
    UNIQUE (channel_id, content_id)
);

CREATE INDEX IF NOT EXISTS idx_post_history_channel_status ON post_history (channel_id, status);
CREATE INDEX IF NOT EXISTS idx_post_history_channel_genre_published ON post_history (channel_id, genre, published_at DESC);

CREATE TABLE IF NOT EXISTS channel_run_log (
    id BIGSERIAL PRIMARY KEY,
    channel_id TEXT NOT NULL,
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at TIMESTAMPTZ,
    status TEXT NOT NULL DEFAULT 'running' CHECK (status IN ('running', 'success', 'partial', 'failed')),
    genres_processed TEXT[] NOT NULL DEFAULT '{}',
    articles_considered INT NOT NULL DEFAULT 0,
    articles_posted INT NOT NULL DEFAULT 0,
    error TEXT
);

CREATE INDEX IF NOT EXISTS idx_channel_run_log_channel ON channel_run_log (channel_id, started_at DESC);

CREATE TABLE IF NOT EXISTS instagram_tokens (
    channel_id TEXT PRIMARY KEY,
    ig_business_account_id TEXT NOT NULL,
    page_id TEXT NOT NULL,
    access_token_encrypted BYTEA NOT NULL,
    token_type TEXT NOT NULL DEFAULT 'long_lived',
    issued_at TIMESTAMPTZ NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    last_refreshed_at TIMESTAMPTZ,
    refresh_status TEXT NOT NULL DEFAULT 'ok' CHECK (refresh_status IN ('ok', 'failed', 'needs_manual_reauth')),
    last_refresh_error TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
