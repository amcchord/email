"""Variant catalog for e-ink terminal devices.

Each Variant captures everything the rest of the code needs to know:
- the panel resolution
- the wire-format `image.format` enum from schedule.json
- the recommended `next_checkin_sec` (panel-life budgeting per docs/terminal/server-implementation-guide.md)
- the ETag-stable rendering bucket (so back-to-back check-ins don't churn ETags
  faster than the panel can refresh)

The query-string spelling for each variant comes from docs/terminal/firmware-variants.md.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Variant:
    key: str  # internal/storage key
    query: str  # value of ?variant= (empty string for the default Spectra-6 7.3")
    image_format: str  # enum echoed in schedule.json's image.format
    width: int
    height: int
    bytes_total: int  # exact BMP size on the wire
    next_checkin_sec: int  # baseline cadence
    render_bucket_sec: int  # round time-of-render to this so ETags don't churn faster than the cadence


# Constants are picked to match the firmware-variants.md byte tables exactly.
SPECTRA6_800 = Variant(
    key="spectra6_800x480",
    query="",
    image_format="bmp4-spectra6-800x480",
    width=800,
    height=480,
    bytes_total=192118,
    next_checkin_sec=300,
    render_bucket_sec=300,
)

SPECTRA6_1200 = Variant(
    key="spectra6_1200x1600",
    query="spectra6_1200x1600",
    image_format="bmp4-spectra6-1200x1600",
    width=1200,
    height=1600,
    bytes_total=960118,
    next_checkin_sec=900,
    render_bucket_sec=900,
)

BW_800 = Variant(
    key="bw",
    query="bw",
    image_format="bmp1-bw-800x480",
    width=800,
    height=480,
    bytes_total=48062,
    next_checkin_sec=60,
    render_bucket_sec=60,
)

GRAY_800 = Variant(
    key="gray",
    query="gray",
    image_format="bmp4-gray16-800x480",
    width=800,
    height=480,
    bytes_total=192118,
    next_checkin_sec=60,
    render_bucket_sec=60,
)


VARIANTS: dict[str, Variant] = {
    SPECTRA6_800.key: SPECTRA6_800,
    SPECTRA6_1200.key: SPECTRA6_1200,
    BW_800.key: BW_800,
    GRAY_800.key: GRAY_800,
}


# Map ?variant= query value -> Variant. Empty/missing = Spectra-6 7.3" default.
_QUERY_MAP: dict[str, Variant] = {
    "": SPECTRA6_800,
    "spectra6_1200x1600": SPECTRA6_1200,
    "bw": BW_800,
    "gray": GRAY_800,
}


def parse_variant(query: Optional[str]) -> Variant:
    """Resolve a `?variant=` query value to its Variant. Unknown -> default."""
    return _QUERY_MAP.get((query or "").strip().lower(), SPECTRA6_800)
