from datetime import UTC, datetime, timedelta

import narovva.imagehost as imagehost
from narovva import cli
from narovva.imagehost import ImageHostError
from narovva.imagehost import cleanup as cleanup_module


def test_sweep_deletes_only_blobs_older_than_the_cutoff(monkeypatch):
    now = datetime.now(UTC)
    pages = [
        {"blobs": [{"url": "old1", "uploadedAt": (now - timedelta(hours=2)).isoformat()},
                   {"url": "new", "uploadedAt": now.isoformat()}],
         "hasMore": True, "cursor": "c2"},
        {"blobs": [{"url": "old2", "uploadedAt": (now - timedelta(minutes=45)).isoformat()},
                   {"url": "no-date"}],
         "hasMore": False},
    ]
    deleted = []
    monkeypatch.setattr(cleanup_module.vercel_blob, "list", lambda options: pages.pop(0))
    monkeypatch.setattr(cleanup_module.vercel_blob, "delete", lambda urls: deleted.extend(urls))
    assert cleanup_module.sweep_orphaned_blobs(30) == 2
    assert deleted == ["old1", "old2"]


def test_cli_sweep_blobs_reports_and_never_raises(monkeypatch, capsys):
    monkeypatch.setattr(imagehost, "sweep_orphaned_blobs", lambda minutes: 3)
    assert cli.main(["sweep-blobs"]) == 0
    assert "deleted 3" in capsys.readouterr().out

    def fail(minutes):
        raise ImageHostError("failed to list blobs for cleanup: no token")

    monkeypatch.setattr(imagehost, "sweep_orphaned_blobs", fail)
    assert cli.main(["sweep-blobs"]) == 1
    assert "no token" in capsys.readouterr().out
