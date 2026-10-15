import json

import narovva.publishers.audio_probe as probe
from narovva.config.schema import BrandKitConfig, ChannelConfig, GenreSetting


def _channel():
    return ChannelConfig(id="c", platform="instagram", ig_business_account_id="123",
                         genres=[GenreSetting(genre="tech")], brand=BrandKitConfig(name="T"))


class _Resp:
    def __init__(self, status, payload):
        self.status_code, self.text = status, json.dumps(payload)


def test_probe_queries_both_audio_types_and_redacts_tokens(monkeypatch):
    calls = []
    secret = "IG" + "A" * 60

    def fake_get(url, params, timeout):
        calls.append((url, dict(params)))
        if params["audio_type"] == "music":
            return _Resp(200, {"data": [{"id": "1", "title": "Song", "link": f"https://x/?access_token={secret}"}]})
        return _Resp(400, {"error": {"message": "(#100) unsupported for Instagram Login"}})

    monkeypatch.setattr(probe, "get_valid_token", lambda ch: secret)
    monkeypatch.setattr(probe.httpx, "get", fake_get)
    out = probe.probe_audio_api(_channel(), "tech")
    assert [c[1]["audio_type"] for c in calls] == ["music", "original_sound"]
    assert all(c[0].endswith("/ig_audio") and c[1]["search_query"] == "tech" for c in calls)
    assert [r["status"] for r in out] == [200, 400]
    assert all(secret not in r["body"] for r in out)
