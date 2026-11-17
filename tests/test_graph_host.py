"""Tokens of either kind reach the API that accepts them."""

from __future__ import annotations

import sys

import narovva.publishers.instagram  # noqa: F401
from narovva.tokens.instagram_token_store import graph_host


def test_each_kind_of_token_goes_to_its_own_host():
    assert graph_host("IGAAabc") == "https://graph.instagram.com"
    assert graph_host("EAAabc") == "https://graph.facebook.com"
    assert graph_host(" EAAabc\n") == "https://graph.facebook.com"
    assert graph_host(None) == "https://graph.instagram.com"


def test_the_publisher_calls_the_host_of_its_token(monkeypatch):
    ig = sys.modules["narovva.publishers.instagram"]
    seen = []

    class Resp:
        status_code = 200
        text = "{}"

        def json(self):
            return {"id": "1"}

    monkeypatch.setattr(ig.httpx, "request", lambda method, url, **kw: seen.append(url) or Resp())
    pub = ig.InstagramGraphPublisher.__new__(ig.InstagramGraphPublisher)
    pub._timeout = 5
    pub._request("POST", "/17841477345424555/media", {"access_token": "EAAxyz", "image_url": "u"})
    pub._request("POST", "/123/media", {"access_token": "IGAAxyz", "image_url": "u"})
    assert seen == ["https://graph.facebook.com/v21.0/17841477345424555/media", "https://graph.instagram.com/v21.0/123/media"]
