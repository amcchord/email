"""Tests for the playful appliance copy + idle-snippet fallback.

These guard:

1. Determinism of ``pick_appliance_copy`` across calls (a flicker bug
   would churn the panel ETag every render bucket).
2. Variety: a small variant pool produces more than one variant across
   different cycle numbers.
3. Friendlier washer/dryer status labels (the original "Rinse, then
   spin." complaint).
4. Hourly rotation of ``fallback_idle_snippet``.
"""
from __future__ import annotations

from datetime import datetime, timezone

from zoneinfo import ZoneInfo

from backend.services.eink.pillow import flavor
from backend.services.eink.pillow.ha_view import build_appliance_view
from backend.services.eink.pillow.palette import get_palette
from backend.services.eink.pillow.render_ctx import RenderContext, build_render_context


def _ctx(tz: str = "America/New_York") -> RenderContext:
    return build_render_context(
        {"fetchedAt": "2026-05-23T18:00:00+00:00"},
        get_palette("editorial", "six"),
        tz_name=tz,
    )


# ── Friendlier status labels ──────────────────────────────────────────


def test_friendly_washer_status_rinse():
    assert flavor.friendly_washer_status("rinse") == "Rinsing"


def test_friendly_washer_status_spin():
    assert flavor.friendly_washer_status("spin") == "Spinning"


def test_friendly_washer_status_end():
    assert flavor.friendly_washer_status("end") == "Wrapping up"


def test_friendly_washer_status_unknown_falls_back():
    """Any status we haven't catalogued just gets title-cased -- never
    crashes, never returns None."""
    assert flavor.friendly_washer_status("hyperspin") == "Hyperspin"


def test_friendly_dryer_status_wrinkle_care():
    assert flavor.friendly_dryer_status("wrinkle_care") == "Wrinkle care"


def test_washer_view_uses_friendly_label():
    """End-to-end: the ApplianceView produced by ha_view.py exposes the
    friendly status label, not the raw HA code."""
    ctx = _ctx()
    ha = {
        "washer": {
            "status": "rinse",
            "operation": "wash",
            "remaining": "2026-05-23T19:00:00+00:00",
            "powerOn": True,
            "cycles": 17,
            "energyMonth": 32000.0,
        }
    }
    v = build_appliance_view(ha, "washer", ctx=ctx)
    assert v.status_label == "Rinsing"
    assert v.extras["phase"] == "rinse"


# ── Determinism + variety ─────────────────────────────────────────────


def _make_washer_view(cycle_no: int, phase: str = "wash"):
    ctx = _ctx()
    ha = {
        "washer": {
            "status": phase,
            "operation": "wash",
            "remaining": "2026-05-23T19:00:00+00:00",
            "powerOn": True,
            "cycles": cycle_no,
            "energyMonth": 32000.0,
        }
    }
    return build_appliance_view(ha, "washer", ctx=ctx), ctx


def test_pick_appliance_copy_is_deterministic():
    """Same (cycle_no, phase) -> same variant on every call. If this
    flapped, the panel would churn an ETag mid-cycle and the device
    would re-download the BMP every bucket for no reason."""
    view, ctx = _make_washer_view(cycle_no=42, phase="rinse")
    a = flavor.pick_appliance_copy(view, ctx)
    b = flavor.pick_appliance_copy(view, ctx)
    assert a == b


def test_pick_appliance_copy_varies_with_cycle():
    """Across a handful of cycle numbers we should see at least two
    distinct variants -- otherwise the rotation pool is effectively
    dead and the user complaint reappears."""
    seen: set[tuple[str, str]] = set()
    for cycle in range(1, 12):
        view, ctx = _make_washer_view(cycle_no=cycle, phase="wash")
        copy = flavor.pick_appliance_copy(view, ctx)
        seen.add((copy["head_pre"], copy["head_italic"]))
    assert len(seen) >= 2


def test_pick_appliance_copy_returns_strings():
    """The picker must never return None for any field -- the renderer
    feeds these straight into Run constructors."""
    view, ctx = _make_washer_view(cycle_no=1, phase="spin")
    copy = flavor.pick_appliance_copy(view, ctx)
    assert isinstance(copy["head_pre"], str) and copy["head_pre"]
    assert isinstance(copy["head_italic"], str)
    assert isinstance(copy["deck"], str)


def test_pick_appliance_copy_no_filler_adverb_tails():
    """Regression: the original variant pool ended several headlines on
    hollow adverbial tails like ", with patience." / ", patiently." /
    ", briefly." -- the user called these out as unhelpful. The default
    fallback no longer carries one, and active phases lean on
    information-bearing tails (objects, next steps) instead. This test
    pins those down across every washer + dryer variant we know."""
    forbidden = {
        ", with patience.",
        ", patiently.",
        ", briefly.",
        ", really.",
        ", thoughtfully.",
        ", quietly.",
        ", gently.",
        ", with care.",
        ", soap and all.",
        ", as one does.",
        ", at last.",
    }
    bad: list[str] = []
    for table_name, table in (
        ("WASHER_VARIANTS", flavor.WASHER_VARIANTS),
        ("DRYER_VARIANTS", flavor.DRYER_VARIANTS),
    ):
        for phase, variants in table.items():
            for v in variants:
                if v.head_italic.strip().lower() in {f.strip().lower() for f in forbidden}:
                    bad.append(f"{table_name}[{phase!r}]: {v.head_italic!r}")
    # Also pin the defaults.
    for name, default in (
        ("_WASHER_DEFAULT", flavor._WASHER_DEFAULT),
        ("_DRYER_DEFAULT", flavor._DRYER_DEFAULT),
    ):
        if default.head_italic.strip().lower() in {f.strip().lower() for f in forbidden}:
            bad.append(f"{name}: {default.head_italic!r}")
    assert not bad, "forbidden filler tails: " + ", ".join(bad)


def test_pick_appliance_copy_gerund_washer_status_hits_variant():
    """Regression: the live LG ThinQ integration reports washer phases
    in gerund form (``"rinsing"`` / ``"washing"`` / ``"spinning"``) on
    some firmware. The variant table now aliases those to the noun
    spelling so we never silently fall through to ``_WASHER_DEFAULT``."""
    ctx = _ctx()
    for gerund in ("washing", "rinsing", "spinning", "draining", "soaking"):
        ha = {
            "washer": {
                "status": gerund,
                "operation": "wash",
                "remaining": "2026-05-23T19:00:00+00:00",
                "powerOn": True,
                "cycles": 7,
                "energyMonth": 32000.0,
            }
        }
        v = build_appliance_view(ha, "washer", ctx=ctx)
        copy = flavor.pick_appliance_copy(v, ctx)
        default = flavor._WASHER_DEFAULT
        assert (copy["head_pre"], copy["head_italic"]) != (
            default.head_pre, default.head_italic,
        ), f"gerund {gerund!r} fell through to _WASHER_DEFAULT"


def test_pick_appliance_copy_dryer_wrinkle_care():
    ctx = _ctx()
    ha = {
        "dryer": {
            "status": "wrinkle_care",
            "remaining": "2026-05-23T19:30:00+00:00",
            "powerOn": True,
        }
    }
    v = build_appliance_view(ha, "dryer", ctx=ctx)
    copy = flavor.pick_appliance_copy(v, ctx)
    # Headline + deck both populated for wrinkle_care phase.
    assert copy["head_pre"]
    assert copy["deck"]


def test_pick_appliance_copy_dishwasher_bucketed_by_progress():
    """Two different progress percentages should land in different
    progress buckets and therefore (in general) produce different copy."""
    ctx = _ctx()

    def _copy_for(progress: int):
        ha = {
            "dishwasher": {
                "state": "run",
                "program": "Auto",
                "progress": progress,
                "finishTime": "2026-05-23T20:30:00+00:00",
                "door": "closed",
                "powerOn": True,
                "connected": True,
            }
        }
        v = build_appliance_view(ha, "dishwasher", ctx=ctx)
        return flavor.pick_appliance_copy(v, ctx)

    starting = _copy_for(5)
    finishing = _copy_for(95)
    assert starting != finishing


# ── Idle-snippet rotation ─────────────────────────────────────────────


def _ctx_for_hour(hour: int) -> RenderContext:
    """A RenderContext anchored at a specific local hour for hash testing."""
    local = datetime(2026, 5, 23, hour, 0, 0, tzinfo=ZoneInfo("America/New_York"))
    utc = local.astimezone(timezone.utc)
    return RenderContext(
        now_utc=utc,
        now_local=local,
        zone=ZoneInfo("America/New_York"),
        palette=get_palette("editorial", "six"),
    )


def test_fallback_idle_snippet_shape():
    snippet = flavor.fallback_idle_snippet(_ctx_for_hour(10))
    assert set(snippet.keys()) == {"kind", "text", "byline"}
    assert snippet["text"]
    assert snippet["kind"] in {"quote", "observation"}


def test_fallback_idle_snippet_rotates_by_hour():
    """Two different hours of the same day should generally land on
    different snippets. The pool is large enough that at least 4 out
    of 24 hours produce a unique value -- a much stronger guarantee
    than 'any two pick differently'."""
    seen: set[str] = set()
    for hour in range(0, 24):
        snippet = flavor.fallback_idle_snippet(_ctx_for_hour(hour))
        seen.add(snippet["text"])
    assert len(seen) >= 6


def test_fallback_idle_snippet_stable_within_hour():
    """Same context -> same snippet (deterministic)."""
    ctx = _ctx_for_hour(13)
    a = flavor.fallback_idle_snippet(ctx)
    b = flavor.fallback_idle_snippet(ctx)
    assert a == b
