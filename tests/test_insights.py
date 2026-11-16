from __future__ import annotations

from narovva.publishers import insights


def test_parse_insights_reads_values_and_total_values():
    body = {"data": [
        {"name": "reach", "values": [{"value": 120}]},
        {"name": "views", "total_value": {"value": 340}},
        {"name": "likes", "values": [{"value": "n/a"}]},
    ]}
    assert insights.parse_insights(body) == {"reach": 120, "views": 340}


def test_media_insights_falls_back_when_a_metric_is_unsupported(monkeypatch):
    calls = []

    def fake_get(path, token, **params):
        calls.append(params["metric"])
        if "views" in params["metric"].split(",") and "," in params["metric"]:
            raise insights.InsightsError("HTTP 400: metric views not supported")
        names = params["metric"].split(",")
        return {"data": [{"name": n, "values": [{"value": 5}]} for n in names]}

    monkeypatch.setattr(insights, "_get", fake_get)
    got = insights.media_insights("m1", "tok")
    assert got == {m: 5 for m in insights._SAFE_METRICS}
    assert calls[0].startswith("views,") and calls[1] == ",".join(insights._SAFE_METRICS)


def test_probe_reports_missing_permission(monkeypatch):
    def fake_get(path, token, **params):
        if path.endswith("/media"):
            return {"data": [{"id": "r1", "media_product_type": "REELS", "timestamp": "t", "permalink": "p"}]}
        raise insights.InsightsError("HTTP 403: missing permission")

    monkeypatch.setattr(insights, "_get", fake_get)
    lines = insights.probe("u", "tok")
    assert lines[0].startswith("token owner: unknown")
    assert lines[1].startswith("list posts: OK") and "no insights" in lines[-1]


def test_probe_names_the_token_owner(monkeypatch):
    def fake_get(path, token, **params):
        if path == "me":
            return {"id": "app-scoped", "user_id": "1784", "username": "someone"}
        if path.endswith("/media"):
            return {"data": []}
        raise AssertionError(path)

    monkeypatch.setattr(insights, "_get", fake_get)
    lines = insights.probe("u", "tok")
    assert "@someone" in lines[0] and "user_id 1784" in lines[0] and "is u" in lines[0]
    assert lines[1].startswith("list posts: OK (0 recent")
