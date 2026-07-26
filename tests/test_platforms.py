from __future__ import annotations

from poster_core import Platform as RenderPlatform

from narovva.platforms import PublishPlatform, render_platform_for


def test_every_publish_platform_has_a_render_platform():
    for platform in PublishPlatform:
        rendered = render_platform_for(platform)
        assert isinstance(rendered, RenderPlatform)


def test_instagram_maps_to_instagram_post_size():
    assert render_platform_for(PublishPlatform.INSTAGRAM) is RenderPlatform.INSTAGRAM_POST


def test_x_maps_to_x_size():
    assert render_platform_for(PublishPlatform.X) is RenderPlatform.X
