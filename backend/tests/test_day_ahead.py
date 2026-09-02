"""Tests for the portrait and E1002 landscape Day Ahead displays.

Covers the pure pieces (no DB / no Home Assistant):
- the TRMNL pixel-font loader stays on native bitmap sizes,
- the DayShape helpers (hour bucketing, condition mapping, event
  classification, label formatting),
- the renderer's hero pick (now -> next -> calm),
- and end-to-end render + Spectra-6 encode conformance: a 1200x1600 frame
  that encodes to exactly 960,118 bytes with <= 6 unique colours, and is
  byte-deterministic for the same DayShape (so the ETag is stable within
  the hour).
"""
from __future__ import annotations

import io
from datetime import datetime, timezone

import pytest
from PIL import Image

from backend.models.terminal import TerminalSettings
from backend.services.eink import day_client as dc
from backend.services.eink.pillow import dayahead_editorial as de
from backend.services.eink.pillow import fonts
from backend.services.eink.pillow.day_ahead import render_day_ahead_image
from backend.services.eink.pillow.palette import E_PALETTE_SIX
from backend.services.terminal.bmp import encode_spectra6
from backend.services.terminal.renderer import _DAY_CACHE, render_day_ahead_bmp
from backend.services.terminal.variants import SPECTRA6_800


def M(h, m=0):
    return h * 60 + m


# ── Fonts ──────────────────────────────────────────────────────────────


def test_pix_trmnl_native_sizes():
    for sz in (12, 16, 21):
        for bold in (False, True):
            f = fonts.pix_trmnl(sz, bold=bold)
            assert f.size == sz


def test_pix_trmnl_clamps_non_native():
    assert fonts.pix_trmnl(14).size == 12
    assert fonts.pix_trmnl(19).size == 21
    assert fonts.pix_trmnl(9).size == 12
    assert fonts.pix_trmnl(40).size == 21


# ── day_client helpers ─────────────────────────────────────────────────


def test_bucketed_now_floors_to_hour():
    t = datetime(2026, 6, 5, 8, 47, 33, tzinfo=timezone.utc)
    b = dc._bucketed_now(t)
    assert b == datetime(2026, 6, 5, 8, 0, 0, tzinfo=timezone.utc)
    # Two instants in the same hour bucket identically.
    t2 = datetime(2026, 6, 5, 8, 12, 1, tzinfo=timezone.utc)
    assert dc._bucketed_now(t2) == b


def test_condition_to_code():
    assert dc._condition_to_code("partlycloudy") == "partly"
    assert dc._condition_to_code("sunny") == "sunny"
    assert dc._condition_to_code("clear-night") == "clear"
    assert dc._condition_to_code("rainy") == "rain"
    assert dc._condition_to_code("pouring") == "rain"
    assert dc._condition_to_code("snowy") == "rain"
    assert dc._condition_to_code(None) == "cloudy"
    assert dc._condition_to_code("totally-made-up") == "cloudy"


def test_classify_event():
    # >1 attendee -> meeting
    assert dc._classify_event("Sync", "Zoom", 5, False, False, False) == "meeting"
    # conferencing link with no attendees still reads as a meeting
    assert dc._classify_event("Chat", "", 0, True, True, False) == "meeting"
    # travel keyword wins
    assert dc._classify_event("Flight to SFO", "Airport", 0, False, True, False) == "travel"
    # focus keyword, solo
    assert dc._classify_event("Deep work block", "Desk", 0, False, True, False) == "focus"
    # solo self-organized timed event -> personal
    assert dc._classify_event("Lunch", "Cafe", 0, False, True, False) == "personal"


def test_compact_age():
    now = datetime(2026, 6, 5, 12, 0, 0, tzinfo=timezone.utc)
    assert dc._compact_age(None, now) == ""
    assert dc._compact_age(datetime(2026, 6, 5, 11, 59, 40, tzinfo=timezone.utc), now) == "now"
    assert dc._compact_age(datetime(2026, 6, 5, 7, 0, 0, tzinfo=timezone.utc), now) == "5h"
    assert dc._compact_age(datetime(2026, 6, 3, 12, 0, 0, tzinfo=timezone.utc), now) == "2d"


# ── renderer label + hero helpers ──────────────────────────────────────


def test_ampm_and_duration_labels():
    assert de._ampm(M(8, 0)) == "8"
    assert de._ampm(M(8, 30)) == "8:30"
    assert de._ampm(M(13, 0)) == "1"
    assert de._mer(M(8, 0)) == "AM"
    assert de._mer(M(13, 0)) == "PM"
    assert de._dur_label(M(8, 0), M(9, 0)) == "1h"
    assert de._dur_label(M(8, 0), M(8, 30)) == "30m"
    assert de._dur_label(M(8, 0), M(9, 30)) == "1h30m"


def _ev(start, end, **kw):
    base = {
        "start": "", "end": "", "startMin": start, "endMin": end,
        "allDay": False, "title": "X", "loc": "Y", "kind": "meeting", "people": 0,
    }
    base.update(kw)
    return base


def test_allday_layout_packs_two_lines_with_overflow():
    f = de._serif(22, "semibold")
    # Many long titles can't all fit -> packer caps at 2 lines, reports the rest.
    titles = [f"All-day commitment number {i}" for i in range(12)]
    lines, remaining = de._layout_allday(titles, f, [400, 600])
    assert len(lines) == 2
    assert remaining > 0
    # A short list fits on one line with nothing left over.
    lines2, remaining2 = de._layout_allday(["PTO", "Offsite"], f, [600, 600])
    assert remaining2 == 0
    assert lines2[0] and not lines2[1]


def test_priorities_height_scales_with_items():
    empty = de._priorities_height({"priorities": {"items": []}})
    one = de._priorities_height({"priorities": {"items": [{"title": "x", "kind": "prep"}]}})
    five = de._priorities_height({"priorities": {"items": [
        {"title": str(i), "kind": "prep"} for i in range(5)
    ]}})
    assert empty > 0
    assert five > one > 0


def test_hero_pick_now_next_calm():
    # Happening now wins.
    day = {"nowMin": M(8, 15), "events": [_ev(M(8, 0), M(9, 0)), _ev(M(11, 0), M(11, 30))]}
    prep = de._prep(day)
    assert prep["hero_kind"] == "now"
    assert prep["hero"]["startMin"] == M(8, 0)

    # Nothing now -> next upcoming.
    day = {"nowMin": M(9, 30), "events": [_ev(M(8, 0), M(9, 0)), _ev(M(11, 0), M(11, 30))]}
    prep = de._prep(day)
    assert prep["hero_kind"] == "next"
    assert prep["hero"]["startMin"] == M(11, 0)
    assert prep["hero"]["rel"] is not None

    # Everything past -> calm.
    day = {"nowMin": M(23, 0), "events": [_ev(M(8, 0), M(9, 0))]}
    prep = de._prep(day)
    assert prep["hero_kind"] == "calm"
    assert prep["calm"] is True


# ── End-to-end render + encode conformance ─────────────────────────────


def _busy_day():
    return {
        "tz": "America/New_York", "now_utc": "2026-06-05T12:00:00+00:00",
        "nowMin": M(8, 0), "asOf": "8:00 AM",
        "date": {"weekday": "THURSDAY", "monthDay": "JUNE 5", "year": "2026", "dow3": "THU"},
        "weather": {
            "now": {"temp": 61, "code": "partly", "label": "Partly cloudy"},
            "hi": 74, "lo": 58, "sunrise": "5:18 AM", "sunset": "8:24 PM",
            "forecast": [
                {"dow": "FRI", "code": "sunny", "hi": 78, "lo": 60},
                {"dow": "SAT", "code": "rain", "hi": 66, "lo": 55},
                {"dow": "SUN", "code": "cloudy", "hi": 71, "lo": 57},
            ],
        },
        "events": [
            _ev(M(8, 30), M(9, 0), title="Morning review", loc="Desk", kind="focus"),
            _ev(M(11, 0), M(11, 30), title="Design standup", loc="Conf Room B", kind="meeting", people=5),
            _ev(M(18, 0), M(19, 0), title="Groceries", loc="Market", kind="personal"),
        ],
        "mail": {"needsReply": {"count": 3, "top": [
            {"from": "Marisa Chen", "subj": "Re: contract", "age": "2d"},
            {"from": "Dad", "subj": "Flight options", "age": "1d"},
            {"from": "Stripe", "subj": "Invoice #4471", "age": "5h"},
        ]}, "awaiting": 4, "unread": 28},
        "priorities": {"items": [
            {"title": "Prep for design standup", "detail": "11 AM \u00b7 5 on invite", "kind": "prep"},
            {"title": "Reply to Marisa on contract", "detail": "from Marisa Chen \u00b7 2d", "kind": "reply"},
            {"title": "Decide on Dad's flight options", "detail": "from Dad \u00b7 1d", "kind": "decision"},
            {"title": "Pay Stripe invoice #4471", "detail": "from Stripe \u00b7 5h", "kind": "review"},
            {"title": "Groceries after work", "detail": "6 PM \u00b7 Market", "kind": "personal"},
        ]},
        "house": {"temps": {"outdoor": 61, "first": 70, "second": 71, "third": 72, "basement": 68},
                  "people": [{"name": "Andrew", "home": True}, {"name": "Sam", "home": False}],
                  "advisory": "Garage open"},
        "tomorrow": {"first": {"start": "9:00", "title": "Dentist", "loc": "Dr. Okafor"}},
    }


def _calm_day():
    return {
        "tz": "America/New_York", "now_utc": "2026-06-07T22:30:00+00:00",
        "nowMin": M(18, 30), "asOf": "6:30 PM",
        "date": {"weekday": "SATURDAY", "monthDay": "JUNE 7", "year": "2026", "dow3": "SAT"},
        "weather": {"now": {"temp": 72, "code": "clear", "label": "Clear"},
                    "hi": 79, "lo": 61, "sunrise": None, "sunset": None,
                    "forecast": [{"dow": "SUN", "code": "sunny", "hi": 81, "lo": 63}]},
        "events": [],
        "mail": {"needsReply": {"count": 0, "top": []}, "awaiting": 1, "unread": 4},
        "priorities": {"items": []},
        "house": {"temps": {"outdoor": 67, "first": 71, "second": 72, "third": 73, "basement": 69},
                  "people": [{"name": "Andrew", "home": True}], "advisory": ""},
        "tomorrow": {"first": {"start": "9:30", "title": "Brunch", "loc": "Tatte"}},
    }


def _empty_day():
    return {
        "tz": "UTC", "now_utc": "2026-06-01T10:00:00+00:00", "nowMin": M(10, 0), "asOf": "10:00 AM",
        "date": {"weekday": "MONDAY", "monthDay": "JUNE 1", "year": "2026", "dow3": "MON"},
        "weather": {"now": {"temp": None, "code": "cloudy", "label": ""}, "hi": None, "lo": None,
                    "sunrise": None, "sunset": None, "forecast": []},
        "events": [], "mail": {"needsReply": {"count": 0, "top": []}, "awaiting": 0, "unread": 0},
        "priorities": {"items": []},
        "house": {"temps": {}, "people": [], "advisory": ""},
        "tomorrow": {"first": None},
    }


def _allday_heavy_day():
    """Many all-day events (so the band overflows to '+N MORE') plus a few
    timed rows -- exercises the calendar compaction path."""
    day = _busy_day()
    allday_titles = [
        "Sarah PTO", "Quarterly release freeze", "Company offsite",
        "Marketing campaign launch", "Hiring committee review",
        "Dad's birthday", "Conference travel day", "Budget planning week",
    ]
    allday = [
        {"start": "00:00", "end": "23:59", "startMin": 0, "endMin": 24 * 60,
         "allDay": True, "title": t, "loc": "", "kind": "personal", "people": 0}
        for t in allday_titles
    ]
    day["events"] = allday + [
        _ev(M(11, 0), M(11, 30), title="Design standup", loc="Conf Room B", kind="meeting", people=5),
        _ev(M(15, 0), M(16, 0), title="Budget sync", loc="Zoom", kind="meeting", people=3),
    ]
    return day


def _landscape_stress_day():
    """Worst-case labels and counts for the bounded 800x480 composition."""

    day = _busy_day()
    day["date"] = {
        "weekday": "WEDNESDAY",
        "monthDay": "SEPTEMBER 30",
        "year": "2026",
        "dow3": "WED",
    }
    day["events"][0]["title"] = (
        "Quarterly operating review and long-range planning session"
    )
    day["events"][0]["loc"] = "Executive conference room with a long name"
    day["events"][1]["title"] = "International design systems working session"
    day["priorities"]["items"][0]["title"] = (
        "Prepare the exceptionally detailed operating review packet"
    )
    day["priorities"]["items"][0]["detail"] = (
        "11 AM · conference room · twelve attendees"
    )
    day["weather"]["now"] = {
        "temp": -12,
        "code": "rain",
        "label": "Thunderstorms likely through the afternoon",
    }
    day["weather"]["hi"] = 105
    day["weather"]["lo"] = -18
    day["mail"] = {
        "needsReply": {"count": 999, "top": []},
        "awaiting": 888,
        "unread": 9999,
    }
    day["house"]["advisory"] = (
        "Several windows and the detached garage door are still open"
    )
    day["tomorrow"]["first"] = {
        "start": "10:30",
        "title": "A very long first appointment title for tomorrow",
        "loc": "",
    }
    return day


def _unique_colours(body: bytes) -> int:
    dec = Image.open(io.BytesIO(body)).convert("RGB")
    return len(dec.getcolors(maxcolors=100000))


def test_render_size_and_palette_conformance():
    for day in (_busy_day(), _calm_day(), _empty_day(), _allday_heavy_day()):
        img = render_day_ahead_image("editorial", "six", day, tz_name=day["tz"])
        assert img.size == (1200, 1600)
        body = encode_spectra6(img, width=1200, height=1600, dither=False)
        assert len(body) == 960118
        assert _unique_colours(body) <= 6


def test_e1002_landscape_render_size_and_palette_conformance():
    for day in (
        _busy_day(),
        _calm_day(),
        _empty_day(),
        _allday_heavy_day(),
        _landscape_stress_day(),
    ):
        img = render_day_ahead_image(
            "editorial",
            "six",
            day,
            tz_name=day["tz"],
            profile_key="landscape_16_9",
        )
        assert img.size == (800, 480)
        body = encode_spectra6(img, width=800, height=480, dither=False)
        assert len(body) == 192118
        assert Image.open(io.BytesIO(body)).size == (800, 480)
        assert _unique_colours(body) <= 6


def test_e1002_landscape_sky_reaches_top_status_rail():
    img = render_day_ahead_image(
        "editorial",
        "six",
        _busy_day(),
        tz_name="America/New_York",
        profile_key="landscape_16_9",
    )

    assert E_PALETTE_SIX.blue in {
        img.getpixel((x, 0)) for x in range(img.width)
    }


def test_render_is_deterministic_for_stable_etag():
    # Same DayShape -> byte-identical BMP -> identical ETag within the hour.
    day = _busy_day()
    a = encode_spectra6(render_day_ahead_image("editorial", "six", day, tz_name=day["tz"]),
                        width=1200, height=1600, dither=False)
    b = encode_spectra6(render_day_ahead_image("editorial", "six", day, tz_name=day["tz"]),
                        width=1200, height=1600, dither=False)
    assert a == b

    landscape_a = encode_spectra6(
        render_day_ahead_image(
            "editorial",
            "six",
            day,
            tz_name=day["tz"],
            profile_key="landscape_16_9",
        ),
        width=800,
        height=480,
        dither=False,
    )
    landscape_b = encode_spectra6(
        render_day_ahead_image(
            "editorial",
            "six",
            day,
            tz_name=day["tz"],
            profile_key="landscape_16_9",
        ),
        width=800,
        height=480,
        dither=False,
    )
    assert landscape_a == landscape_b


def test_bw_palette_renders_clean():
    day = _busy_day()
    img = render_day_ahead_image("editorial", "bw", day, tz_name=day["tz"])
    body = encode_spectra6(img, width=1200, height=1600, dither=False)
    assert len(body) == 960118
    # B&W collapses every accent to ink -> at most 2 colours on the panel.
    assert _unique_colours(body) <= 2

    landscape = render_day_ahead_image(
        "editorial",
        "bw",
        day,
        tz_name=day["tz"],
        profile_key="landscape_16_9",
    )
    landscape_body = encode_spectra6(
        landscape,
        width=800,
        height=480,
        dither=False,
    )
    assert len(landscape_body) == 192118
    assert _unique_colours(landscape_body) <= 2


@pytest.mark.asyncio
async def test_e1002_device_path_uses_native_landscape_renderer(monkeypatch):
    day = _busy_day()

    async def assemble(_settings):
        return day

    monkeypatch.setattr(dc, "assemble_day_shape", assemble)
    _DAY_CACHE.clear()
    settings = TerminalSettings(
        user_id=7,
        code="unit-day-ahead-e1002",
        timezone=day["tz"],
    )

    body, etag = await render_day_ahead_bmp(
        SPECTRA6_800,
        device=None,
        settings=settings,
    )

    assert len(body) == SPECTRA6_800.bytes_total == 192118
    assert Image.open(io.BytesIO(body)).size == (800, 480)
    assert _unique_colours(body) <= 6
    assert etag.startswith('"img-') and etag.endswith('"')
