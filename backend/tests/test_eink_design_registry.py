"""Registry and visual-compatibility checks for At a Glance designs."""
from __future__ import annotations

import hashlib
from types import SimpleNamespace

import pytest

from backend.services.eink.pillow.day_ahead import render_day_ahead_image
from backend.services.eink.pillow.palette import (
    PaletteRegistryError,
    get_palette,
    registered_palette_designs,
)
from backend.services.eink.pillow.registry import (
    DesignRegistryError,
    get_design_renderer,
    registered_designs_by_content,
    registered_profiles_by_content_design,
)
from backend.services.eink.pillow.render import render_eink_image
from backend.services.terminal.catalog import (
    CatalogError,
    CatalogImplementationError,
    resolve_content_type,
    validate_catalog_content_implementations,
    validate_catalog_design_implementations,
)
from backend.services.terminal.renderer import _resolve_design


_HOME_SHAPE = {"fetchedAt": "2026-06-05T12:00:00+00:00"}

_EMPTY_DAY = {
    "tz": "UTC",
    "now_utc": "2026-06-01T10:00:00+00:00",
    "nowMin": 600,
    "asOf": "10:00 AM",
    "date": {
        "weekday": "MONDAY",
        "monthDay": "JUNE 1",
        "year": "2026",
        "dow3": "MON",
    },
    "weather": {
        "now": {"temp": None, "code": "cloudy", "label": ""},
        "hi": None,
        "lo": None,
        "sunrise": None,
        "sunset": None,
        "forecast": [],
    },
    "events": [],
    "mail": {
        "needsReply": {"count": 0, "top": []},
        "awaiting": 0,
        "unread": 0,
    },
    "priorities": {"items": []},
    "house": {"temps": {}, "people": [], "advisory": ""},
    "tomorrow": {"first": None},
}


def _pixels_sha256(image) -> str:
    return hashlib.sha256(image.tobytes()).hexdigest()


def test_catalog_designs_have_exact_renderer_and_palette_registration():
    implementations = registered_designs_by_content()
    profiles = registered_profiles_by_content_design()
    palettes = registered_palette_designs()

    assert implementations == {
        "eink_dashboard": frozenset({"editorial", "swiss"}),
        "day_ahead": frozenset({"editorial"}),
    }
    assert palettes == frozenset({"editorial", "swiss"})
    assert profiles == {
        ("eink_dashboard", "editorial"): frozenset({"landscape_16_9"}),
        ("eink_dashboard", "swiss"): frozenset({"landscape_16_9"}),
        ("day_ahead", "editorial"): frozenset(
            {"landscape_16_9", "portrait_9_16"}
        ),
    }
    validate_catalog_design_implementations(
        design_implementations=implementations,
        profile_implementations=profiles,
        palette_designs=palettes,
    )


def test_catalog_completeness_checks_fail_closed_on_missing_or_hidden_code():
    with pytest.raises(CatalogImplementationError, match="Pillow registry"):
        validate_catalog_design_implementations(
            design_implementations={
                "eink_dashboard": {"editorial"},
                "day_ahead": {"editorial"},
            },
            profile_implementations=registered_profiles_by_content_design(),
            palette_designs={"editorial", "swiss"},
        )

    with pytest.raises(CatalogImplementationError, match="palette registry"):
        validate_catalog_design_implementations(
            design_implementations=registered_designs_by_content(),
            profile_implementations=registered_profiles_by_content_design(),
            palette_designs={"editorial"},
        )

    with pytest.raises(CatalogImplementationError, match="profile registry"):
        validate_catalog_design_implementations(
            design_implementations=registered_designs_by_content(),
            profile_implementations={
                ("eink_dashboard", "editorial"): {"landscape_16_9"},
                ("eink_dashboard", "swiss"): {"landscape_16_9"},
                ("day_ahead", "editorial"): {"portrait_9_16"},
            },
            palette_designs=registered_palette_designs(),
        )

    with pytest.raises(CatalogImplementationError, match="device content registry"):
        validate_catalog_content_implementations(
            {"clock", "eink_dashboard"},
            surface="device",
        )


@pytest.mark.parametrize(
    ("content_type", "design"),
    [
        ("eink_dashboard", "missing"),
        ("day_ahead", "swiss"),
        ("missing", "editorial"),
        ("", "editorial"),
    ],
)
def test_unknown_content_design_pairs_do_not_fall_back(content_type, design):
    with pytest.raises(DesignRegistryError):
        get_design_renderer(content_type, design)


@pytest.mark.parametrize(
    ("design", "palette"),
    [
        ("missing", "six"),
        ("editorial", "sepia"),
        ("editorial", ""),
    ],
)
def test_unknown_palette_pairs_do_not_fall_back(design, palette):
    with pytest.raises(PaletteRegistryError):
        get_palette(design, palette)


def test_public_render_entrypoints_fail_closed():
    with pytest.raises(DesignRegistryError):
        render_eink_image("missing", "six", _HOME_SHAPE, use_cache=False)
    with pytest.raises(PaletteRegistryError):
        render_eink_image("editorial", "sepia", _HOME_SHAPE, use_cache=False)
    with pytest.raises(DesignRegistryError):
        render_day_ahead_image("swiss", "six", _EMPTY_DAY)
    with pytest.raises(PaletteRegistryError):
        render_day_ahead_image("editorial", "sepia", _EMPTY_DAY)


def test_unknown_catalog_content_type_does_not_become_clock():
    assert resolve_content_type(None).key == "clock"
    with pytest.raises(CatalogError, match="Unknown content type"):
        resolve_content_type("typo")


def test_persisted_unknown_design_does_not_become_editorial():
    device = SimpleNamespace(content_config={"design": "typo"})

    with pytest.raises(ValueError, match="No catalog design"):
        _resolve_design(device)


@pytest.mark.parametrize(
    ("design", "palette", "expected_sha256"),
    [
        (
            "editorial",
            "six",
            "1ef57003e32d53d7142ed06b14d032b2321a1488011e285888cb23cb8e456043",
        ),
        (
            "editorial",
            "bw",
            "0b609d6423b2accd42bad1f5ad1712db16bc6c364ded42f8212f773f04e5c162",
        ),
        (
            "swiss",
            "six",
            "45d4e0a53118c57741390f8b1c1ddea96c0c8b0673a4fcee284256c823619230",
        ),
        (
            "swiss",
            "bw",
            "a0c5bbf97d5859e42c06f21494ec9ed5cac30cb7488b3348ca8f7bab36263008",
        ),
    ],
)
def test_home_registry_preserves_existing_pixels(design, palette, expected_sha256):
    image = render_eink_image(
        design,
        palette,
        _HOME_SHAPE,
        tz_name="America/New_York",
        use_cache=False,
    )

    assert image.size == (800, 480)
    assert _pixels_sha256(image) == expected_sha256


@pytest.mark.parametrize(
    ("palette", "expected_sha256"),
    [
        (
            "six",
            "cfdda9ca01d7e28fba8ae3363d0f9cc785e4302d56a5dd8927ffd6918759df0f",
        ),
        (
            "bw",
            "04e7cc74332077d5dcc65dc609fc3b9fea0ffb1e346ce3212120f43621e9a4b5",
        ),
    ],
)
def test_day_ahead_registry_preserves_existing_pixels(palette, expected_sha256):
    image = render_day_ahead_image("editorial", palette, _EMPTY_DAY, tz_name="UTC")

    assert image.size == (1200, 1600)
    assert _pixels_sha256(image) == expected_sha256


@pytest.mark.parametrize(
    ("palette", "expected_sha256"),
    [
        (
            "six",
            "c5b0d84fe8ed5edff870ea5f6d83654293e934ca6090f834eb8beb5b94c49577",
        ),
        (
            "bw",
            "4786373839ea15007a52c5e0e4f6c8b4a0c3f6d38bb25ccee9e325a2952cee1f",
        ),
    ],
)
def test_day_ahead_landscape_pixels_are_snapshot_pinned(palette, expected_sha256):
    image = render_day_ahead_image(
        "editorial",
        palette,
        _EMPTY_DAY,
        tz_name="UTC",
        profile_key="landscape_16_9",
    )

    assert image.size == (800, 480)
    assert _pixels_sha256(image) == expected_sha256
