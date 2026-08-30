"""Pure-unit coverage for the shared At a Glance catalog and web shell."""
from __future__ import annotations

import inspect
from types import SimpleNamespace

import pytest

from backend.models.terminal import TerminalSettings
from backend.routers.terminal import display_frame_png, display_html
from backend.services.terminal.catalog import (
    CatalogError,
    DesignDefinition,
    DisplayProfile,
    ViewDefinition,
    resolve_design,
    resolve_profile,
    resolve_view,
    web_display_definitions,
    web_display_options,
)
from backend.services.terminal.web_display import build_display_html, render_web_frame


def test_catalog_defaults_follow_display_orientation():
    landscape = resolve_profile(None)
    portrait = resolve_profile("portrait")

    assert landscape.key == "landscape_16_9"
    assert resolve_view(None, profile=landscape).key == "home"
    assert resolve_view("", profile=portrait).key == "day_ahead"

    home = resolve_view("home", profile=landscape)
    assert resolve_design(home, None).key == "editorial"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("landscape", "landscape_16_9"),
        (" 16X9 ", "landscape_16_9"),
        ("16:9", "landscape_16_9"),
        ("portrait", "portrait_9_16"),
        ("9X16", "portrait_9_16"),
        ("9:16", "portrait_9_16"),
    ],
)
def test_profile_aliases(raw, expected):
    assert resolve_profile(raw).key == expected


@pytest.mark.parametrize(
    ("raw", "profile", "expected"),
    [
        ("dashboard", "landscape", "home"),
        ("eink_dashboard", "16:9", "home"),
        ("day-ahead", "portrait", "day_ahead"),
    ],
)
def test_view_aliases(raw, profile, expected):
    assert resolve_view(raw, profile=resolve_profile(profile)).key == expected


def test_catalog_rejects_unknown_and_unsupported_combinations():
    landscape = resolve_profile("landscape")
    portrait = resolve_profile("portrait")

    with pytest.raises(CatalogError, match="Unknown display profile"):
        resolve_profile("square")
    with pytest.raises(CatalogError, match="Unknown view"):
        resolve_view("mailbox", profile=landscape)
    with pytest.raises(CatalogError, match="does not support"):
        resolve_view("home", profile=portrait)
    with pytest.raises(CatalogError, match="does not support"):
        resolve_view("day_ahead", profile=landscape)

    day_ahead = resolve_view("day_ahead", profile=portrait)
    with pytest.raises(CatalogError, match="not available"):
        resolve_design(day_ahead, "swiss")

    clock = resolve_view("clock", profile=landscape)
    assert resolve_design(clock, None) is None
    with pytest.raises(CatalogError, match="does not use a design"):
        resolve_design(clock, "editorial")


def test_web_display_options_cover_every_supported_combination():
    records = [
        SimpleNamespace(
            id=index,
            token=f"scoped-display-token-{index:02d}",
            view_key=definition["view"],
            design_key=definition["design"] or "",
            profile_key=definition["profile"],
        )
        for index, definition in enumerate(web_display_definitions(), start=1)
    ]
    options = web_display_options(records)

    assert len(options) == 5
    assert len({option["key"] for option in options}) == len(options)
    assert {
        (option["view"], option["design"], option["profile"])
        for option in options
    } == {
        ("home", "editorial", "landscape_16_9"),
        ("home", "swiss", "landscape_16_9"),
        ("day_ahead", "editorial", "portrait_9_16"),
        ("clock", None, "landscape_16_9"),
        ("clock", None, "portrait_9_16"),
    }
    assert len({option["url"] for option in options}) == len(options)
    assert all(
        option["url"].startswith("/terminal/display/scoped-display-token-")
        and option["url"].endswith(".html")
        and "?" not in option["url"]
        for option in options
    )


def test_public_display_routes_do_not_accept_view_overrides():
    for endpoint in (display_html, display_frame_png):
        parameters = inspect.signature(endpoint).parameters
        assert "token" in parameters
        assert "code" not in parameters
        assert "view" not in parameters
        assert "design" not in parameters
        assert "profile" not in parameters


@pytest.mark.parametrize(
    ("profile_key", "width", "height"),
    [
        ("landscape_16_9", 16, 9),
        ("portrait_9_16", 9, 16),
    ],
)
def test_display_html_sizes_the_stage_to_the_selected_profile(
    profile_key, width, height
):
    profile = resolve_profile(profile_key)
    view = resolve_view(None, profile=profile)
    design = resolve_design(view, None)

    body = build_display_html(
        token="scoped-display-token-01",
        view=view,
        design=design,
        profile=profile,
        refresh_sec=300,
    )

    assert f"--display-ratio: {width} / {height}" in body
    assert f"calc(100vh * {width} / {height})" in body
    assert f"calc(100vw * {height} / {width})" in body
    assert 'content="300"' in body
    assert f'data-profile="{profile_key}"' in body


def test_display_html_builds_an_owned_frame_url_without_raw_markup():
    view = ViewDefinition(
        key='home"><img src=x onerror=alert(1)>',
        label='Home <script>alert("x")</script>',
        content_type="eink_dashboard",
        design_keys=("editorial",),
        profile_keys=("landscape_16_9",),
        default_design="editorial",
    )
    design = DesignDefinition(
        key='editorial&mode="unsafe"',
        label='Editorial <img src=x onerror="alert(1)">',
    )
    profile = DisplayProfile(
        key='landscape_16_9" onload="alert(1)',
        label="Landscape 16:9",
        orientation="landscape",
        aspect_width=16,
        aspect_height=9,
    )

    body = build_display_html(
        token='unit"><script>alert(1)</script>',
        view=view,
        design=design,
        profile=profile,
        refresh_sec=300,
    )

    assert "<script>alert" not in body
    assert "<img src=x onerror" not in body
    assert "Home &lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt;" in body
    assert (
        "/terminal/display/unit&quot;&gt;&lt;script&gt;alert(1)&lt;/script&gt;/frame.png"
        in body
    )


def test_clock_frame_url_omits_an_empty_design_parameter():
    profile = resolve_profile("portrait")
    view = resolve_view("clock", profile=profile)

    body = build_display_html(
        token="scoped-display-token-05",
        view=view,
        design=None,
        profile=profile,
        refresh_sec=60,
    )

    assert 'src="/terminal/display/scoped-display-token-05/frame.png"' in body
    assert "?" not in body


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("profile_key", "expected_size"),
    [
        ("landscape", (1280, 720)),
        ("portrait", (720, 1280)),
    ],
)
async def test_clock_web_frame_uses_the_profile_geometry(profile_key, expected_size):
    profile = resolve_profile(profile_key)
    view = resolve_view("clock", profile=profile)
    settings = TerminalSettings(
        user_id=1,
        code="unit-code",
        timezone="America/New_York",
    )

    frame = await render_web_frame(
        settings=settings,
        view=view,
        design=None,
        profile=profile,
    )

    assert (frame.width, frame.height) == expected_size
    assert frame.body.startswith(b"\x89PNG\r\n\x1a\n")
