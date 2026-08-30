"""Shared catalog for At a Glance views, designs, and display profiles.

The e-ink protocol, browser displays, and admin UI all consume this module so
adding a view or design does not require updating independent hard-coded lists.
Renderers remain responsible for pixels; this catalog describes which
combinations are valid and how they should be presented.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Optional, Protocol


class CatalogError(ValueError):
    """Raised when a requested view/design/profile combination is invalid."""


@dataclass(frozen=True)
class DesignDefinition:
    key: str
    label: str


@dataclass(frozen=True)
class DisplayProfile:
    key: str
    label: str
    orientation: str
    aspect_width: int
    aspect_height: int


@dataclass(frozen=True)
class ViewDefinition:
    key: str
    label: str
    content_type: str
    design_keys: tuple[str, ...]
    profile_keys: tuple[str, ...]
    default_design: Optional[str] = None


class WebDisplayRecord(Protocol):
    id: int
    token: str
    view_key: str
    design_key: str
    profile_key: str


DESIGNS: dict[str, DesignDefinition] = {
    "editorial": DesignDefinition(
        key="editorial",
        label="Editorial (newspaper / serif)",
    ),
    "swiss": DesignDefinition(
        key="swiss",
        label="Swiss (modular / mono)",
    ),
}


DISPLAY_PROFILES: dict[str, DisplayProfile] = {
    "landscape_16_9": DisplayProfile(
        key="landscape_16_9",
        label="Landscape 16:9",
        orientation="landscape",
        aspect_width=16,
        aspect_height=9,
    ),
    "portrait_9_16": DisplayProfile(
        key="portrait_9_16",
        label="Portrait 9:16",
        orientation="portrait",
        aspect_width=9,
        aspect_height=16,
    ),
}


VIEWS: dict[str, ViewDefinition] = {
    "home": ViewDefinition(
        key="home",
        label="Home Dashboard",
        content_type="eink_dashboard",
        design_keys=("editorial", "swiss"),
        profile_keys=("landscape_16_9",),
        default_design="editorial",
    ),
    "day_ahead": ViewDefinition(
        key="day_ahead",
        label="Day Ahead",
        content_type="day_ahead",
        design_keys=("editorial",),
        profile_keys=("portrait_9_16",),
        default_design="editorial",
    ),
    "clock": ViewDefinition(
        key="clock",
        label="Clock",
        content_type="clock",
        design_keys=(),
        profile_keys=("landscape_16_9", "portrait_9_16"),
    ),
}


_PROFILE_ALIASES = {
    "landscape": "landscape_16_9",
    "16:9": "landscape_16_9",
    "16x9": "landscape_16_9",
    "portrait": "portrait_9_16",
    "9:16": "portrait_9_16",
    "9x16": "portrait_9_16",
}

_VIEW_ALIASES = {
    "dashboard": "home",
    "eink_dashboard": "home",
    "day-ahead": "day_ahead",
}


def resolve_profile(value: Optional[str]) -> DisplayProfile:
    raw = (value or "landscape_16_9").strip().lower()
    key = _PROFILE_ALIASES.get(raw, raw)
    profile = DISPLAY_PROFILES.get(key)
    if profile is None:
        raise CatalogError(
            f"Unknown display profile {value!r}; choose one of {sorted(DISPLAY_PROFILES)}"
        )
    return profile


def resolve_view(value: Optional[str], *, profile: DisplayProfile) -> ViewDefinition:
    if value is None or not value.strip():
        key = "day_ahead" if profile.orientation == "portrait" else "home"
    else:
        raw = value.strip().lower()
        key = _VIEW_ALIASES.get(raw, raw)
    view = VIEWS.get(key)
    if view is None:
        raise CatalogError(f"Unknown view {value!r}; choose one of {sorted(VIEWS)}")
    if profile.key not in view.profile_keys:
        supported = ", ".join(view.profile_keys)
        raise CatalogError(
            f"View {view.key!r} does not support {profile.key!r}; choose {supported}"
        )
    return view


def resolve_design(view: ViewDefinition, value: Optional[str]) -> Optional[DesignDefinition]:
    if not view.design_keys:
        if value:
            raise CatalogError(f"View {view.key!r} does not use a design")
        return None
    key = (value or view.default_design or view.design_keys[0]).strip().lower()
    if key not in view.design_keys:
        raise CatalogError(
            f"Design {key!r} is not available for {view.key!r}; "
            f"choose one of {list(view.design_keys)}"
        )
    return DESIGNS[key]


def resolve_content_type(content_type: Optional[str]) -> ViewDefinition:
    raw = (content_type or "clock").strip().lower()
    for view in VIEWS.values():
        if view.content_type == raw:
            return view
    return VIEWS["clock"]


def content_type_options() -> list[dict]:
    options = [
        {
            "key": view.content_type,
            "label": view.label,
            "available": True,
            "view": view.key,
            "designs": list(view.design_keys),
        }
        for view in VIEWS.values()
    ]
    options.append(
        {
            "key": "calendar",
            "label": "Calendar (coming soon)",
            "available": False,
            "view": None,
            "designs": [],
        }
    )
    return options


def design_options() -> list[dict]:
    return [asdict(design) for design in DESIGNS.values()]


def view_options() -> list[dict]:
    return [
        {
            **asdict(view),
            "design_keys": list(view.design_keys),
            "profile_keys": list(view.profile_keys),
        }
        for view in VIEWS.values()
    ]


def display_profile_options() -> list[dict]:
    return [asdict(profile) for profile in DISPLAY_PROFILES.values()]


def web_display_definitions() -> list[dict]:
    """Return every supported browser-display combination without credentials."""
    options: list[dict] = []
    for view in VIEWS.values():
        designs: tuple[Optional[str], ...] = view.design_keys or (None,)
        for profile_key in view.profile_keys:
            profile = DISPLAY_PROFILES[profile_key]
            for design_key in designs:
                design = DESIGNS.get(design_key or "")
                options.append(
                    {
                        "key": "-".join(
                            part for part in (view.key, design_key, profile.key) if part
                        ),
                        "label": f"{view.label} · {design.label if design else profile.label}",
                        "view": view.key,
                        "design": design_key,
                        "profile": profile.key,
                        "orientation": profile.orientation,
                        "aspect_ratio": f"{profile.aspect_width}:{profile.aspect_height}",
                    }
                )
    return options


def web_display_options(displays: list[WebDisplayRecord]) -> list[dict]:
    """Join catalog metadata to scoped, revocable display credentials."""
    records = {
        (record.view_key, record.design_key or None, record.profile_key): record
        for record in displays
    }
    options: list[dict] = []
    for definition in web_display_definitions():
        identity = (
            definition["view"],
            definition["design"],
            definition["profile"],
        )
        record = records.get(identity)
        if record is None:
            continue
        options.append(
            {
                **definition,
                "id": record.id,
                "url": f"/terminal/display/{record.token}.html",
            }
        )
    return options
