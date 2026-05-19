"""Tests for the HA view layer in ``eink/pillow/ha_view.py``.

These guard the two production bugs the view layer was introduced to
prevent:

1. **Cooling labelled as heating** -- ``ZoneView`` / ``FloorView`` /
   ``HvacSummary`` reconcile ``mode`` + ``hvac_action`` instead of
   trusting ``hvac_action`` alone.
2. **Appliance clocks in UTC** -- ``ApplianceView`` pre-formats every
   timestamp with the user's IANA zone, so renderers can't print UTC
   even by accident.
"""
from __future__ import annotations

from zoneinfo import ZoneInfo

from backend.services.eink.pillow.ha_view import (
    ApplianceView,
    FloorView,
    HvacSummary,
    ZoneView,
    build_appliance_view,
    build_floor_view,
    build_floor_views,
    build_hvac_summary,
    build_zone_view,
    supported_appliance_kinds,
)
from backend.services.eink.pillow.palette import get_palette
from backend.services.eink.pillow.render_ctx import RenderContext, build_render_context


# ── ZoneView / FloorView / HvacSummary ────────────────────────────────


def test_zone_view_heating():
    z = build_zone_view({"name": "Main", "mode": "heat", "action": "heating",
                         "current": 70, "target": 72})
    assert z.state == "heating"
    assert z.accent_kind == "heat"
    assert z.chip_label == "H"
    assert z.is_active


def test_zone_view_cooling():
    z = build_zone_view({"name": "Apt", "mode": "cool", "action": "cooling",
                         "current": 76, "target": 72})
    assert z.state == "cooling"
    assert z.accent_kind == "cool"
    assert z.chip_label == "C"
    assert z.is_active


def test_zone_view_clamps_stale_action():
    """The bug we are guarding against: HA reports ``hvac_action='heating'``
    on a thermostat the user has switched to ``cool``. Without the view
    layer the floor cell would proudly show "heating"."""
    z = build_zone_view({"name": "?", "mode": "cool", "action": "heating",
                         "current": 76, "target": 72})
    # The action can't be reconciled with the mode, so we don't pick a
    # direction at all -- much safer than asserting "heating".
    assert z.state == "unknown"
    assert z.accent_kind == "idle"
    assert z.chip_label == ""
    assert not z.is_active


def test_zone_view_idle():
    z = build_zone_view({"name": "x", "mode": "heat", "action": "idle",
                         "current": 70, "target": 70})
    assert z.state == "idle"
    assert z.accent_kind == "idle"
    assert z.chip_label == ""


def test_zone_view_off():
    z = build_zone_view({"name": "x", "mode": "off"})
    assert z.state == "off"


def test_zone_view_none():
    z = build_zone_view(None, name="empty")
    assert z.state == "unknown"
    assert z.accent_kind == "idle"


def _ha_with_floors(first=(), second=()):
    return {
        "temps": {"first": 72, "second": 70},
        "floorActivity": {"first": list(first), "second": list(second)},
        "allClimates": list(first) + list(second),
    }


def test_floor_view_heating():
    ha = _ha_with_floors(first=[
        {"mode": "heat", "action": "heating"},
        {"mode": "heat", "action": "heating"},
    ])
    f = build_floor_view(ha, "first", "First", 72)
    assert f.state == "heating"
    assert f.heat_count == 2
    assert f.cool_count == 0
    assert f.chip_label == "H2"
    assert f.accent_kind == "heat"


def test_floor_view_cooling():
    ha = _ha_with_floors(first=[
        {"mode": "cool", "action": "cooling"},
        {"mode": "cool", "action": "cooling"},
    ])
    f = build_floor_view(ha, "first", "First", 76)
    assert f.state == "cooling"
    assert f.cool_count == 2
    assert f.chip_label == "C2"
    assert f.accent_kind == "cool"


def test_floor_view_idle_when_action_stale():
    """A floor with one stale "heating" action on a "cool"-mode unit
    has zero reconciled-heating zones and zero cooling zones, so the
    floor reads as idle (not heating, not cooling)."""
    ha = _ha_with_floors(first=[{"mode": "cool", "action": "heating"}])
    f = build_floor_view(ha, "first", "First", 75)
    assert f.heat_count == 0
    assert f.cool_count == 0
    assert f.state == "idle"
    assert f.chip_label == ""


def test_floor_views_helper():
    ha = _ha_with_floors(
        first=[{"mode": "heat", "action": "heating"}],
        second=[{"mode": "cool", "action": "cooling"}],
    )
    views = build_floor_views(ha, [("first", "First"), ("second", "Second")])
    assert [v.state for v in views] == ["heating", "cooling"]


def test_hvac_summary_heat_only():
    ha = {"allClimates": [{"mode": "heat", "action": "heating"},
                          {"mode": "heat", "action": "heating"},
                          {"mode": "heat", "action": "idle"}]}
    s = build_hvac_summary(ha)
    assert s.heating == 2 and s.cooling == 0 and s.total == 3
    assert s.dominant == "heat"
    assert s.label == "ZONES HEATING 2/3"


def test_hvac_summary_cool_only():
    ha = {"allClimates": [{"mode": "cool", "action": "cooling"},
                          {"mode": "cool", "action": "idle"}]}
    s = build_hvac_summary(ha)
    assert s.cooling == 1
    assert s.dominant == "cool"
    assert s.label == "ZONES COOLING 1/2"


def test_hvac_summary_mixed_shows_both():
    """When both directions are active (mixed thermostats), the
    colophon/footer should show both counts so the user sees the whole
    picture instead of one side being silently dropped."""
    ha = {"allClimates": [{"mode": "heat", "action": "heating"},
                          {"mode": "heat", "action": "heating"},
                          {"mode": "cool", "action": "cooling"}]}
    s = build_hvac_summary(ha)
    assert s.heating == 2 and s.cooling == 1
    assert s.dominant == "heat"  # heat outnumbers cool
    assert s.label == "HEAT 2 \u00b7 COOL 1"


def test_hvac_summary_idle():
    ha = {"allClimates": [{"mode": "heat", "action": "idle"}]}
    s = build_hvac_summary(ha)
    assert not s.is_active
    assert s.dominant == "idle"
    assert s.label == "HVAC IDLE"


def test_hvac_summary_no_zones():
    s = build_hvac_summary({})
    assert s.total == 0
    assert s.label == "HVAC IDLE"


# ── ApplianceView (timezone / time-format correctness) ────────────────


def _ctx(tz: str = "America/New_York") -> RenderContext:
    return build_render_context(
        {"fetchedAt": "2026-05-05T18:00:00+00:00"},
        get_palette("editorial", "six"),
        tz_name=tz,
    )


def test_washer_finish_label_in_user_zone():
    """The bug we are guarding against: the washer hero used to print
    HA's UTC ISO string verbatim, so an 18:34 UTC finish displayed as
    "6:34 PM" even for a user in Eastern Time (where it's 2:34 PM)."""
    ctx = _ctx("America/New_York")
    ha = {"washer": {"status": "wash", "cycles": 12, "energyMonth": 1234,
                     "remaining": "2026-05-05T18:34:00+00:00"}}
    v = build_appliance_view(ha, "washer", ctx=ctx)
    # 18:34 UTC on 2026-05-05 is 14:34 EDT.
    assert v.finish_label == "2:34 PM"
    assert v.finish_at_local is not None
    assert v.finish_at_local.tzinfo is not None
    assert v.finish_at_local.utcoffset() == ZoneInfo("America/New_York").utcoffset(v.finish_at_local)
    # Remaining: from 18:00 UTC to 18:34 UTC == 34m.
    assert v.remaining_label == "34m"
    assert v.relative_label.startswith("in ") or v.relative_label == "in 34m"


def test_dishwasher_finish_label_in_user_zone():
    ctx = _ctx("America/New_York")
    ha = {"dishwasher": {"state": "run", "program": "dishcare_dishwasher_program_eco_50",
                         "progress": 60, "finishTime": "2026-05-05T19:34:00+00:00",
                         "door": "closed"}}
    v = build_appliance_view(ha, "dishwasher", ctx=ctx)
    # 19:34 UTC -> 15:34 EDT.
    assert v.finish_label == "3:34 PM"
    assert v.progress_pct == 60
    assert v.program_label  # "Eco 50" or similar
    assert v.extras["door_state"] == "closed"


def test_washer_done_uses_localized_completion_time():
    ctx = _ctx("America/New_York")
    ha = {"washer": {"status": "end", "cycles": 12,
                     "lastNotification": {"type": "washing_is_complete",
                                          "at": "2026-05-05T17:30:00+00:00"}}}
    v = build_appliance_view(ha, "washer-done", ctx=ctx)
    # 17:30 UTC on 2026-05-05 is 13:30 EDT.
    assert v.finish_label == "1:30 PM"
    assert v.relative_label and v.relative_label != ""


def test_dryer_running_view_phase():
    ctx = _ctx("America/New_York")
    ha = {"dryer": {"status": "running",
                    "remaining": "2026-05-05T19:00:00+00:00",
                    "powerOn": True}}
    v = build_appliance_view(ha, "dryer", ctx=ctx)
    assert v.eyebrow_label == "DRYER RUNNING"
    assert v.accent_kind == "info"
    assert v.extras["phase"] == "running"
    assert v.status_label  # title-cased non-empty
    # 19:00 UTC -> 15:00 EDT
    assert v.finish_label == "3:00 PM"


def test_dryer_view_wrinkle_care_phase():
    ctx = _ctx("America/New_York")
    ha = {"dryer": {"status": "wrinkle_care",
                    "remaining": "2026-05-05T19:30:00+00:00",
                    "powerOn": True}}
    v = build_appliance_view(ha, "dryer", ctx=ctx)
    assert v.extras["phase"] == "wrinkle_care"


def test_dryer_done_active_only_when_powered_off():
    """LG dryers stay powered ON through cooling/wrinkle_care, so the
    done-card waits for the user to press power-off before it appears.
    That doubles as the "I unloaded it" dismissal signal."""
    from datetime import datetime, timezone
    from backend.services.eink.pillow.appliances import _dryer_done_active
    now = datetime(2026, 5, 5, 18, 0, tzinfo=timezone.utc)
    notif = {"type": "drying_is_complete",
             "at": "2026-05-05T17:30:00+00:00"}
    ha_powered = {"dryer": {"status": "end", "powerOn": True,
                            "lastNotification": notif}}
    ha_off = {"dryer": {"status": "power_off", "powerOn": False,
                        "lastNotification": notif}}
    assert _dryer_done_active(ha_powered, now) is True
    assert _dryer_done_active(ha_off, now) is False


def test_washer_done_dismissed_when_dryer_running():
    """The strongest 'I moved the laundry' signal: the dryer is running.
    The washer-done card must drop the moment we see that, even if the
    washer notification is still well within its 1h cap."""
    from datetime import datetime, timezone
    from backend.services.eink.pillow.appliances import _washer_done_active
    now = datetime(2026, 5, 5, 17, 30, tzinfo=timezone.utc)
    notif = {"type": "washing_is_complete",
             "at": "2026-05-05T17:00:00+00:00"}
    # Washer stays powered ON between cycle end and unload -- that's the
    # window where the card belongs on screen.
    base_washer = {"status": "end", "powerOn": True,
                   "lastNotification": notif}
    # Without any dryer engagement: card is active.
    assert _washer_done_active(
        {"washer": base_washer, "dryer": {"status": "power_off",
                                          "powerOn": False}},
        now,
    ) is True
    # With a running dryer: card is dismissed.
    assert _washer_done_active(
        {"washer": base_washer, "dryer": {"status": "running"}},
        now,
    ) is False


def test_washer_done_dismissed_when_dryer_touched():
    """Broader 'user engaged the dryer' signals also dismiss the card.
    The narrow `_dryer_active` check used to miss these because LG's
    `initial` state and `switch.dryer_power=on` both fall outside the
    'running' status enum."""
    from datetime import datetime, timezone
    from backend.services.eink.pillow.appliances import _washer_done_active
    now = datetime(2026, 5, 5, 17, 30, tzinfo=timezone.utc)
    notif = {"type": "washing_is_complete",
             "at": "2026-05-05T17:00:00+00:00"}
    base_washer = {"status": "end", "powerOn": True,
                   "lastNotification": notif}
    # Dryer power flipped on (user pressed the power button).
    assert _washer_done_active(
        {"washer": base_washer,
         "dryer": {"status": "power_off", "powerOn": True}},
        now,
    ) is False
    # Dryer status went to `initial` (powered on, awaiting cycle pick).
    assert _washer_done_active(
        {"washer": base_washer,
         "dryer": {"status": "initial", "powerOn": False}},
        now,
    ) is False
    # Dryer has a programmed cycle (remaining time set).
    assert _washer_done_active(
        {"washer": base_washer,
         "dryer": {"status": "power_off", "powerOn": False,
                   "remaining": "2026-05-05T18:30:00+00:00"}},
        now,
    ) is False


def test_washer_done_dismissed_when_washer_powered_off():
    """We have no washer door sensor, so `switch.washer_power` going off
    is our proxy for 'user opened the door and unloaded'. As long as the
    washer is powered on, the card stays; the moment it's off, drop it."""
    from datetime import datetime, timezone
    from backend.services.eink.pillow.appliances import _washer_done_active
    now = datetime(2026, 5, 5, 17, 30, tzinfo=timezone.utc)
    notif = {"type": "washing_is_complete",
             "at": "2026-05-05T17:00:00+00:00"}
    dryer = {"status": "power_off", "powerOn": False}
    # Powered ON, status `end`: card belongs on screen.
    assert _washer_done_active(
        {"washer": {"status": "end", "powerOn": True,
                    "lastNotification": notif}, "dryer": dryer},
        now,
    ) is True
    # Powered OFF (user hit power after unloading): card dismissed.
    assert _washer_done_active(
        {"washer": {"status": "power_off", "powerOn": False,
                    "lastNotification": notif}, "dryer": dryer},
        now,
    ) is False


def test_washer_done_drops_after_one_hour():
    """The window shrank from 6h to 1h -- stale 'wash complete' cards
    that have been ignored for an hour aren't useful anymore."""
    from datetime import datetime, timedelta, timezone
    from backend.services.eink.pillow.appliances import _washer_done_active
    finished_at = datetime(2026, 5, 5, 17, 0, tzinfo=timezone.utc)
    notif = {"type": "washing_is_complete",
             "at": finished_at.isoformat()}
    base = {
        "washer": {"status": "end", "powerOn": True,
                   "lastNotification": notif},
        "dryer": {"status": "power_off", "powerOn": False},
    }
    # 59 minutes after completion: still within the 1h window.
    assert _washer_done_active(base, finished_at + timedelta(minutes=59)) is True
    # 61 minutes after completion: dropped.
    assert _washer_done_active(base, finished_at + timedelta(minutes=61)) is False


def test_appliance_view_handles_missing_time():
    ctx = _ctx("America/New_York")
    v = build_appliance_view({"washer": {"status": "wash"}}, "washer", ctx=ctx)
    assert v.finish_label == "\u2014"
    assert v.remaining_label == "\u2014"


def test_appliance_view_unknown_kind_does_not_crash():
    ctx = _ctx("America/New_York")
    v = build_appliance_view({}, "future-appliance", ctx=ctx)
    # Falls back to a generic placeholder rather than raising.
    assert v.kind == "future-appliance"


def test_supported_appliance_kinds_matches_registry():
    """Every kind exposed by ha_view must have a matching registry row,
    or appliances.py would refuse to import."""
    from backend.services.eink.pillow.appliances import APPLIANCES
    registered = {s.kind for s in APPLIANCES}
    supported = set(supported_appliance_kinds())
    assert supported == registered, (
        f"ha_view supports {supported - registered} that aren't registered, "
        f"and appliances.py registers {registered - supported} without a view."
    )


# ── RenderContext ────────────────────────────────────────────────────


def test_render_context_localizes_now():
    P = get_palette("editorial", "six")
    ctx = build_render_context({"fetchedAt": "2026-05-05T18:00:00+00:00"}, P,
                                tz_name="America/New_York")
    assert ctx.now_utc.tzinfo is not None
    assert ctx.now_local.utcoffset() == ZoneInfo("America/New_York").utcoffset(ctx.now_local)
    # 18:00 UTC -> 14:00 EDT.
    assert ctx.now_local.hour == 14
    assert ctx.now_local.minute == 0


def test_render_context_accent_lookup():
    P = get_palette("editorial", "six")
    ctx = build_render_context({}, P, tz_name="UTC")
    assert ctx.accent("heat") == P.red
    assert ctx.accent("cool") == P.blue
    assert ctx.accent("ok") == P.green
    assert ctx.accent("idle") == P.muted
    assert ctx.accent("ink") == P.ink


def test_render_context_accent_unknown_kind_returns_ink():
    P = get_palette("editorial", "six")
    ctx = build_render_context({}, P, tz_name="UTC")
    # Unknown kinds fall back to ink so a future renderer can't crash.
    assert ctx.accent("not-a-real-kind") == P.ink  # type: ignore[arg-type]


# ── End-to-end registry sanity ────────────────────────────────────────


def test_pick_active_returns_localized_views():
    """Smoke test that the registry hands renderers tz-correct views."""
    from backend.services.eink.pillow.appliances import pick_active
    P = get_palette("editorial", "six")
    ha = {
        "fetchedAt": "2026-05-05T18:00:00+00:00",
        "washer": {"status": "wash", "cycles": 7, "energyMonth": 500,
                   "remaining": "2026-05-05T20:00:00+00:00"},
    }
    ctx = build_render_context(ha, P, tz_name="America/New_York")
    actives = pick_active(ha, ctx)
    kinds = [a.kind for a in actives]
    assert "washer" in kinds
    washer = next(a for a in actives if a.kind == "washer")
    # 20:00 UTC -> 16:00 EDT.
    assert washer.view.finish_label == "4:00 PM"
