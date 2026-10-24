-- Daily snapshots of each published post's Instagram insights (one row per post per
-- day), so a post can be judged at a fixed age against the channel's own median.
CREATE TABLE IF NOT EXISTS post_metrics (
    channel_id        TEXT        NOT NULL,
    platform_post_id  TEXT        NOT NULL,
    snapshot_date     DATE        NOT NULL,
    fetched_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    views             INTEGER,
    reach             INTEGER,
    likes             INTEGER,
    comments          INTEGER,
    saved             INTEGER,
    shares            INTEGER,
    total_interactions INTEGER,
    avg_watch_ms      INTEGER,
    total_watch_ms    BIGINT,
    PRIMARY KEY (channel_id, platform_post_id, snapshot_date)
);
