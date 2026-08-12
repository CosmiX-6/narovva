from __future__ import annotations

from datetime import datetime, timedelta, timezone

from narovva.config.schema import BrandKitConfig, ChannelConfig, GenreSetting
from narovva.orchestration import due


def _channel(**overrides) -> ChannelConfig:
    defaults = dict(
        id="chan",
        genres=[GenreSetting(genre="tech"), GenreSetting(genre="ai")],
        brand=BrandKitConfig(),
        rotation_minutes=120,
    )
    defaults.update(overrides)
    return ChannelConfig(**defaults)


class _FakeRepo:
    def __init__(self, last):
        self._last = last

    def last_successful_post(self, channel_id):
        return self._last

    def last_successful_post_at(self, channel_id, genre):
        raise AssertionError("legacy per-genre path should not run in rotation mode")


def _patch_repo(monkeypatch, last):
    monkeypatch.setattr(due, "get_settings", lambda: type("S", (), {"database_url": "postgres://x"})())
    monkeypatch.setattr(due, "get_connection", lambda: None)
    monkeypatch.setattr(due, "Repo", lambda conn: _FakeRepo(last))


def test_rotation_picks_first_genre_when_never_posted(monkeypatch):
    _patch_repo(monkeypatch, last=None)
    result = due.due_genres([_channel()])
    assert [d.genre for d in result] == ["tech"]


def test_rotation_advances_to_next_genre_after_cadence_elapses(monkeypatch):
    last_at = datetime.now(timezone.utc) - timedelta(minutes=130)
    _patch_repo(monkeypatch, last=("tech", last_at))
    result = due.due_genres([_channel()])
    assert [d.genre for d in result] == ["ai"]


def test_rotation_wraps_around_after_last_genre(monkeypatch):
    last_at = datetime.now(timezone.utc) - timedelta(minutes=130)
    _patch_repo(monkeypatch, last=("ai", last_at))
    result = due.due_genres([_channel()])
    assert [d.genre for d in result] == ["tech"]


def test_rotation_not_due_before_cadence_elapses(monkeypatch):
    last_at = datetime.now(timezone.utc) - timedelta(minutes=30)
    _patch_repo(monkeypatch, last=("tech", last_at))
    result = due.due_genres([_channel()])
    assert result == []


def test_rotation_recovers_if_last_posted_genre_was_removed_from_config(monkeypatch):
    last_at = datetime.now(timezone.utc) - timedelta(minutes=130)
    _patch_repo(monkeypatch, last=("gaming", last_at))
    result = due.due_genres([_channel()])
    assert [d.genre for d in result] == ["tech"]


def test_independent_mode_unaffected_when_rotation_minutes_unset(monkeypatch):
    tech_last = datetime.now(timezone.utc) - timedelta(minutes=200)

    class _LegacyRepo:
        def last_successful_post_at(self, channel_id, genre):
            return tech_last if genre == "tech" else None

    monkeypatch.setattr(due, "get_settings", lambda: type("S", (), {"database_url": "postgres://x"})())
    monkeypatch.setattr(due, "get_connection", lambda: None)
    monkeypatch.setattr(due, "Repo", lambda conn: _LegacyRepo())

    channel = _channel(
        rotation_minutes=None,
        genres=[
            GenreSetting(genre="tech", cadence_minutes=60),
            GenreSetting(genre="ai", cadence_minutes=60),
        ],
    )
    result = due.due_genres([channel])
    assert {d.genre for d in result} == {"tech", "ai"}
