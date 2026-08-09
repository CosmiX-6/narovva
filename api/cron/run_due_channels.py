"""Vercel serverless entrypoint that runs every channel/genre currently due.

Triggered by an hourly GitHub Actions workflow (.github/workflows/hourly.yml)
rather than Vercel's own Cron Jobs, which cap at once/day on the Hobby plan.
Auth: `Authorization: Bearer $CRON_SECRET`.
"""

from __future__ import annotations

import json
import os
import sys
import traceback
from http.server import BaseHTTPRequestHandler
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

# Channel YAMLs use paths (e.g. assets/fonts/*.ttf) relative to the repo
# root, same as a local `narovva run-channel` invocation -- match that here
# regardless of whatever cwd Vercel's runtime happens to start us in.
os.chdir(_REPO_ROOT)

from narovva.config import load_all_channels  # noqa: E402
from narovva.orchestration import due_channels_with_genres, run_channel  # noqa: E402


class handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        self._handle()

    def do_POST(self) -> None:
        self._handle()

    def _handle(self) -> None:
        expected = os.environ.get("CRON_SECRET")
        provided = self.headers.get("Authorization", "")
        if not expected or provided != f"Bearer {expected}":
            self._respond(401, {"error": "unauthorized"})
            return

        try:
            channels = load_all_channels(_REPO_ROOT / "config" / "channels")
            due = due_channels_with_genres(channels)
            results = []
            for channel, genres in due:
                result = run_channel(channel, genres_filter=genres, max_posts_per_genre=1)
                results.append(
                    {
                        "channel_id": result.channel_id,
                        "considered": result.considered,
                        "posted": result.posted,
                        "failed": result.failed,
                        "skipped": result.skipped,
                        "errors": result.errors,
                    }
                )
            self._respond(200, {"due_channels": len(due), "results": results})
        except Exception as exc:
            self._respond(500, {"error": str(exc), "traceback": traceback.format_exc()})

    def _respond(self, status: int, body: dict) -> None:
        payload = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)
