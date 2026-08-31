"""Explicit registry for Pillow-backed At a Glance designs.

The product catalog declares which ``(content_type, design)`` pairs users may
select. This module is the corresponding implementation registry: adding a
catalog option without a renderer is an import-time configuration error, and
asking for an unknown pair fails instead of quietly drawing another design.

Renderer imports stay inside the tiny adapters so importing registry metadata
does not eagerly load every layout module.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Optional

from PIL import Image

from .palette import Palette


class DesignRegistryError(ValueError):
    """Raised when no exact Pillow renderer is registered for a request."""


@dataclass(frozen=True)
class DesignRenderer:
    """One concrete content/design implementation."""

    content_type: str
    design_key: str
    canvas_size: tuple[int, int]
    render: Callable[..., None]


def _render_editorial(
    image: Image.Image,
    shape: dict,
    palette: Palette,
    *,
    tz_name: Optional[str] = None,
) -> None:
    from . import editorial

    editorial.render_dashboard(image, shape, palette, tz_name=tz_name)


def _render_swiss(
    image: Image.Image,
    shape: dict,
    palette: Palette,
    *,
    tz_name: Optional[str] = None,
) -> None:
    from . import swiss

    swiss.render_dashboard(image, shape, palette, tz_name=tz_name)


def _render_day_ahead_editorial(
    image: Image.Image,
    shape: dict,
    palette: Palette,
    *,
    tz_name: Optional[str] = None,
) -> None:
    from . import dayahead_editorial

    dayahead_editorial.render_dashboard(image, shape, palette, tz_name=tz_name)


_REGISTRY = {
    "eink_dashboard": MappingProxyType(
        {
            "editorial": DesignRenderer(
                content_type="eink_dashboard",
                design_key="editorial",
                canvas_size=(800, 480),
                render=_render_editorial,
            ),
            "swiss": DesignRenderer(
                content_type="eink_dashboard",
                design_key="swiss",
                canvas_size=(800, 480),
                render=_render_swiss,
            ),
        }
    ),
    "day_ahead": MappingProxyType(
        {
            "editorial": DesignRenderer(
                content_type="day_ahead",
                design_key="editorial",
                canvas_size=(1200, 1600),
                render=_render_day_ahead_editorial,
            ),
        }
    ),
}

DESIGN_RENDERERS: Mapping[str, Mapping[str, DesignRenderer]] = MappingProxyType(
    _REGISTRY
)


def _validate_registry() -> None:
    for content_type, designs in DESIGN_RENDERERS.items():
        if not designs:
            raise DesignRegistryError(
                f"Pillow registry content type {content_type!r} has no designs"
            )
        for design_key, renderer in designs.items():
            if (renderer.content_type, renderer.design_key) != (
                content_type,
                design_key,
            ):
                raise DesignRegistryError(
                    "Pillow registry key does not match renderer definition: "
                    f"{content_type!r}/{design_key!r}"
                )
            if renderer.canvas_size[0] <= 0 or renderer.canvas_size[1] <= 0:
                raise DesignRegistryError(
                    f"Pillow renderer {content_type!r}/{design_key!r} has an "
                    "invalid canvas"
                )


_validate_registry()


def _key(value: str, *, field: str) -> str:
    key = (value or "").strip().lower()
    if not key:
        raise DesignRegistryError(f"{field} is required")
    return key


def get_design_renderer(content_type: str, design: str) -> DesignRenderer:
    """Resolve one exact registered implementation or fail closed."""

    content_key = _key(content_type, field="content_type")
    design_key = _key(design, field="design")
    designs = DESIGN_RENDERERS.get(content_key)
    renderer = designs.get(design_key) if designs is not None else None
    if renderer is None:
        registered = sorted(designs) if designs is not None else []
        raise DesignRegistryError(
            f"No Pillow renderer registered for content_type={content_key!r}, "
            f"design={design_key!r}; registered designs: {registered}"
        )
    return renderer


def registered_designs_by_content() -> dict[str, frozenset[str]]:
    """Return an immutable-value snapshot for catalog completeness checks."""

    return {
        content_type: frozenset(designs)
        for content_type, designs in DESIGN_RENDERERS.items()
    }
