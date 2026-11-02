"""Editorial's single-activity card: its copy rotation, meters, and their data."""
import copy
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
from PIL import Image, ImageChops, ImageDraw

from backend.services.eink import ha_client as hc
from backend.services.eink import sauna_forecast as sf
from backend.services.eink.pillow import editorial, flavor, fonts, icons, meters
from backend.services.eink.pillow.appliances import APPLIANCES, pick_active
from backend.services.eink.pillow.draw import Run, _wrap_runs_into_lines, text_width
from backend.services.eink.pillow.ha_view import build_appliance_view
from backend.services.eink.pillow.layout import EDITORIAL
from backend.services.eink.pillow.palette import get_palette
from backend.services.eink.pillow.render_ctx import build_render_context

NOW = datetime(2026, 11, 1, 19, 12, tzinfo=timezone.utc)
T = NOW.timestamp()
P = get_palette("editorial", "bw")
COLUMN = EDITORIAL.body_lead.inset(left=18, right=18).w
BESIDE_ICON = COLUMN - icons.ICON_SIZE - editorial._ICON_GAP


def iso(minutes):
    return (NOW + timedelta(minutes=minutes)).isoformat()


def ctx_at(when=NOW, palette=P):
    return build_render_context({"fetchedAt": when.isoformat()}, palette,
                                tz_name="America/New_York")


def cycle(*pairs):
    return [{"s": status, "t": T + minutes * 60} for status, minutes in pairs]


WASHER = dict(operation="c", lastNotification=None, powerOn=True, cycles=154, energyMonth=12300)
DRYER = dict(operation="c", lastNotification=None, powerOn=True)


# Samples of Home Assistant's sensor.sauna_heat_forecast, computed at NOW.
SAUNA_SAMPLES = json.loads((Path(__file__).parent / "fixtures" / "sauna_heat_forecast.json").read_text())


def _sauna(sample="heating"):
    room = [{"t": T - 2400, "v": 64}, {"t": T - 120, "v": 90}]
    forecast = sf.from_sensor(copy.deepcopy(SAUNA_SAMPLES[sample]), room, T)
    attrs = SAUNA_SAMPLES[sample]["attributes"]
    current, room_now = (186, 168) if attrs["ready_reached"] else (123, 91)
    return dict(mode="heat", current=current, target=185, duration=180, heaters=3, door=False,
                roomTemp=room_now, roomHumidity=19, forecast=forecast)


SHAPES = {
    "washer": dict(washer=dict(status="rinsing", remaining=iso(14),
                               cycle=cycle(("running", -26), ("rinsing", -6)), **WASHER)),
    "washer without history": dict(washer=dict(status="running", remaining=iso(38), **WASHER)),
    "washer paused": dict(washer=dict(status="pause", remaining=iso(30),
                                      cycle=cycle(("running", -26), ("pause", -6)), **WASHER)),
    "washer-done": dict(washer=dict(status="power_off", remaining=None, operation="c", powerOn=False,
                                    cycles=154, energyMonth=0,
                                    lastNotification=dict(type="washing_is_complete", at=iso(-23)))),
    "dryer": dict(dryer=dict(status="wrinkle_care", remaining=iso(20),
                             cycle=cycle(("running", -58), ("cooling", -12), ("wrinkle_care", -3)),
                             **DRYER)),
    "dryer-done": dict(dryer=dict(status="end", remaining=None, operation="c", powerOn=True,
                                  lastNotification=dict(type="drying_is_complete", at=iso(-95)))),
    "dishwasher": dict(dishwasher=dict(state="run", program="Intensive 70", progress=62,
                                       finishTime=iso(47), door="closed")),
    "dishwasher without progress": dict(dishwasher=dict(state="run", program="", progress=None,
                                                        finishTime=None, door="")),
    "sauna": dict(sauna=_sauna()),
    "sauna ready": dict(sauna=_sauna("ready")),
    "sauna without forecast": dict(sauna=dict(mode="heat", current=127, target=185, duration=60,
                                              heaters=2, door=True, roomTemp=84, roomHumidity=19,
                                              forecast=None)),
    "pool": dict(pool=dict(operation="heating", current=78, target=88, air=61, heating=True,
                           pumpRunning=True, schedule=True, freezeProtect=True)),
    "pool in a freeze": dict(pool=dict(operation="heating", current=61, target=104, air=-12,
                                       heating=True, pumpRunning=True, schedule=True,
                                       freezeProtect=True)),
}


def _shape(extra, when=NOW):
    return {"fetchedAt": when.isoformat(), **copy.deepcopy(extra)}


@pytest.mark.parametrize("name", SHAPES)
@pytest.mark.parametrize("palette", ["bw", "six"])
def test_every_single_activity_card_fits_the_column(name, palette):
    pal = get_palette("editorial", palette)
    ha = _shape(SHAPES[name])
    ctx = ctx_at(palette=pal)
    active = pick_active(ha, ctx)
    assert len(active) == 1
    box = EDITORIAL.body_lead.inset(left=18, right=18)
    scratch = Image.new("RGB", (box.w, box.h * 2), pal.bg)
    # Every copy slot, since a longer line can push the card down.
    for slot in range(24):
        when = NOW + timedelta(minutes=slot * flavor.ROTATION_MINUTES)
        y = editorial._draw_feature(scratch, ImageDraw.Draw(scratch), ctx_at(when, pal), active[0], box.w)
        assert y <= box.h, (name, slot, y)


def test_only_a_lone_activity_gets_the_feature_card(monkeypatch):
    calls = []
    monkeypatch.setattr(editorial, "_draw_feature", lambda *a, **k: calls.append(1) or 10)
    box = EDITORIAL.body_lead.inset(left=18, right=18)
    img = Image.new("RGB", (800, 480), P.bg)
    draw = ImageDraw.Draw(img)
    ctx = ctx_at()
    one = _shape(SHAPES["washer"])
    editorial._draw_lead_column(img, draw, ctx, one, pick_active(one, ctx), box)
    assert calls == [1]
    three = {**_shape(SHAPES["washer"]), **_shape(SHAPES["dishwasher"]), **_shape(SHAPES["sauna"])}
    editorial._draw_lead_column(img, draw, ctx, three, pick_active(three, ctx), box)
    assert calls == [1]


# ── Shared cards ──────────────────────────────────────────────────────

BOX = EDITORIAL.body_lead.inset(left=18, right=18)
PAIR_H = (BOX.h - editorial._PAIR_RULE_H) // 2
ROW_H = (BOX.h + editorial._ROW_GAP) // 3 - editorial._ROW_GAP


def test_every_registered_appliance_has_a_card_and_a_brief():
    assert {spec.kind for spec in APPLIANCES} == set(editorial._FEATURE_BUILDERS)
    assert set(editorial.EDITORIAL_BRIEFS) == set(editorial._FEATURE_BUILDERS)


@pytest.mark.parametrize("name", SHAPES)
@pytest.mark.parametrize("pair", [True, False], ids=["pair", "row"])
@pytest.mark.parametrize("palette", ["bw", "six"])
def test_every_shared_card_fits_its_share_of_the_column(name, pair, palette):
    pal = get_palette("editorial", palette)
    item = pick_active(_shape(SHAPES[name]), ctx_at(palette=pal))[0]
    h = PAIR_H if pair else ROW_H
    for slot in range(24):
        ctx = ctx_at(NOW + timedelta(minutes=slot * flavor.ROTATION_MINUTES), pal)
        img = Image.new("RGB", (BOX.w, h * 2), pal.bg)
        y = editorial._draw_tile(img, ImageDraw.Draw(img), ctx, item, 0, 0, BOX.w, h, pair=pair)
        ink = ImageChops.difference(img, Image.new("RGB", img.size, pal.bg)).getbbox()
        assert y <= h and ink[3] <= h, (name, slot, y, ink)


@pytest.mark.parametrize("name", SHAPES)
def test_shared_card_headlines_are_never_cut(name):
    item = pick_active(_shape(SHAPES[name]), ctx_at())[0]
    for slot in range(24):
        ctx = ctx_at(NOW + timedelta(minutes=slot * flavor.ROTATION_MINUTES))
        feature = editorial._FEATURE_BUILDERS[item.kind](item.view, ctx, P.ink)
        for sizes in (editorial._PAIR_HEAD_SIZES, editorial._ROW_HEAD_SIZES):
            runs, _, lines = editorial._tile_headline(feature, P.ink, P.ink, BESIDE_ICON, sizes)
            assert len(_wrap_runs_into_lines(runs, BESIDE_ICON)) <= lines, (name, slot)


def _lay_out(monkeypatch, *names):
    """Where the shared column puts each card, and what it lists as briefs."""
    tiles, briefs, kickers = [], [], []
    monkeypatch.setattr(editorial, "_draw_tile", lambda img, draw, ctx, item, x0, y0, w, h, *,
                        pair: tiles.append((item.kind, y0 - BOX.y0, h, pair)))
    monkeypatch.setattr(editorial, "_draw_brief", lambda draw, ctx, ha, x0, y, w, item, *,
                        last: briefs.append(item.kind) or y + editorial._BRIEF_ROW_H)
    monkeypatch.setattr(editorial, "_draw_kicker", lambda draw, box, *, text, P: kickers.append(text))
    ha = {k: v for name in names for k, v in _shape(SHAPES[name]).items()}
    img = Image.new("RGB", (800, 480), P.bg)
    ctx = ctx_at()
    editorial._draw_lead_column(img, ImageDraw.Draw(img), ctx, ha, pick_active(ha, ctx), BOX)
    return tiles, briefs, kickers


def test_two_activities_split_the_column(monkeypatch):
    tiles, briefs, _ = _lay_out(monkeypatch, "washer", "dishwasher")
    assert tiles == [("washer", 0, PAIR_H, True), ("dishwasher", BOX.h - PAIR_H, PAIR_H, True)]
    assert briefs == []


def test_three_activities_take_a_row_each_most_urgent_first(monkeypatch):
    tiles, briefs, _ = _lay_out(monkeypatch, "washer", "dishwasher", "sauna")
    pitch = ROW_H + editorial._ROW_GAP
    assert tiles == [("sauna", 0, ROW_H, False), ("washer", pitch, ROW_H, False),
                     ("dishwasher", 2 * pitch, ROW_H, False)]
    assert briefs == []


def test_past_three_the_last_row_lists_the_rest_and_counts_any_left_off(monkeypatch):
    tiles, briefs, kickers = _lay_out(monkeypatch, "sauna", "washer", "dryer", "dishwasher", "pool")
    assert [kind for kind, *_ in tiles] == ["sauna", "washer"]
    assert briefs == ["dryer", "dishwasher"]
    assert kickers == ["Also Active  ·  +1 more"]


def _sauna_card(**attributes):
    sample = copy.deepcopy(SAUNA_SAMPLES["heating"])
    sample["attributes"].update(attributes)
    ha = _shape({"sauna": dict(_sauna(), forecast=sf.from_sensor(sample, [], T))})
    view = pick_active(ha, ctx_at())[0].view
    return editorial._FEATURE_BUILDERS["sauna"](view, ctx_at(), P.ink).gauge, view.extras["forecast"]


def test_sauna_gauge_measures_the_room_and_names_the_fan():
    gauge, forecast = _sauna_card()
    assert (gauge.value, gauge.label) == ("91°", "ROOM")
    assert (gauge.right_label, gauge.right_value) == ("FAN", forecast["fan_label"])
    assert gauge.pct == pytest.approx(100 * (91 - 60) / (sf.READY_F - 60))


def test_sauna_gauge_says_when_the_fan_ran_or_the_session_ends_first():
    gauge, forecast = _sauna_card(fan_state="done", fan_at=iso(-10), fan_in_minutes=None)
    assert (gauge.right_label, gauge.right_value) == ("FAN RAN", forecast["fan_label"])
    gauge, forecast = _sauna_card(session_ends_before_ready_at=iso(30))
    assert (gauge.right_label, gauge.right_value) == ("ENDS", forecast["ends_before_ready"])


@pytest.mark.parametrize(("target", "shown"), [(32, "Preset"), (None, "—")])
def test_a_preset_or_unknown_sauna_target_gets_no_bar(target, shown):
    ha = _shape({"sauna": dict(SHAPES["sauna without forecast"]["sauna"], target=target)})
    view = pick_active(ha, ctx_at())[0].view
    gauge = editorial._FEATURE_BUILDERS["sauna"](view, ctx_at(), P.ink).gauge
    assert gauge.right_value == shown and gauge.pct is None and gauge.ticks == ()


@pytest.mark.parametrize(("target", "goal"), [(185, "GOAL 185°"), (32, "GOAL PRESET"),
                                               (None, "GOAL —")])
def test_the_thermostat_cell_never_calls_an_unknown_target_a_preset(target, goal):
    ha = _shape({"sauna": dict(_sauna(), target=target)})
    view = pick_active(ha, ctx_at())[0].view
    cells = editorial._FEATURE_BUILDERS["sauna"](view, ctx_at(), P.ink).cells
    assert next(c["sub"] for c in cells if c["k"] == "Thermostat") == goal


# ── Copy rotation ─────────────────────────────────────────────────────


def _washer_view(status, cycles=154, ctx=None):
    ha = {"washer": dict(WASHER, status=status, remaining=iso(38), cycles=cycles)}
    return build_appliance_view(ha, "washer", ctx=ctx or ctx_at())


def test_the_status_this_washer_really_reports_gets_real_copy():
    """It reports `running`, and missing that left every wash on the default line."""
    assert flavor.WASHER_VARIANTS["running"] is flavor.WASHER_VARIANTS["wash"]
    copy_ = flavor.pick_appliance_copy(_washer_view("running"), ctx_at())
    assert copy_["head_pre"] != flavor._WASHER_DEFAULT.head_pre
    assert flavor.friendly_washer_status("running") == "Washing"


def test_rotation_visits_the_whole_pool_before_repeating():
    pool = list(range(11))
    seen = [flavor._rotate(pool, "seed", slot) for slot in range(len(pool))]
    assert sorted(seen) == pool
    assert [flavor._rotate(pool, "seed", s) for s in range(11, 22)] == seen


def test_copy_moves_on_during_a_long_phase_but_holds_within_a_slot():
    heads = []
    start = datetime(2026, 11, 1, 19, 0, tzinfo=timezone.utc)
    for i in range(6):
        when = start + timedelta(minutes=i * flavor.ROTATION_MINUTES)
        ctx = ctx_at(when)
        got = flavor.pick_appliance_copy(_washer_view("running", ctx=ctx), ctx)
        heads.append(got["head_pre"] + got["head_italic"])
        later = ctx_at(when + timedelta(minutes=flavor.ROTATION_MINUTES - 1))
        same = flavor.pick_appliance_copy(_washer_view("running", ctx=later), later)
        assert same["head_pre"] + same["head_italic"] == heads[-1]
    assert all(a != b for a, b in zip(heads, heads[1:]))
    assert len(set(heads)) >= 5


def test_daypart_variants_only_run_in_their_part_of_the_day():
    night = [v for v in flavor.WASHER_VARIANTS["wash"] if v.when == ("late-night",)]
    assert night
    noon = datetime(2026, 11, 1, 17, 0, tzinfo=timezone.utc)
    for i in range(30):
        when = noon + timedelta(minutes=i)
        ctx = ctx_at(when)
        got = flavor.pick_appliance_copy(_washer_view("running", cycles=i, ctx=ctx), ctx)
        assert got["head_pre"] not in {v.head_pre for v in night}


FIELDS = {"remaining": "1h 42m", "finish": "12:45 PM", "relative": "12m ago", "cycle_no": 154,
          "program": "Intensive 70", "progress": 88, "kwh": "12.3", "weekday": "Wednesday",
          "daypart": "late-night"}


def _all_variants():
    for table in (flavor.WASHER_VARIANTS, flavor.DRYER_VARIANTS, flavor.DISHWASHER_VARIANTS):
        for variants in table.values():
            yield from variants


def _fits_feature_headline(head_pre, head_italic):
    upright = fonts.serif(editorial._FEATURE_HEAD_SIZES[-1], weight="bold")
    italic = fonts.serif(editorial._FEATURE_HEAD_SIZES[-1], italic=True, weight="bold")
    return len(_wrap_runs_into_lines(
        [Run(head_pre, upright, P.ink), Run(head_italic, italic, P.ink)], BESIDE_ICON,
    )) <= 2


def test_every_appliance_line_fits_beside_the_icon():
    deck_font = fonts.serif(15, italic=True, weight="semibold")
    for variant in _all_variants():
        pre = flavor._safe_format(variant.head_pre, FIELDS)
        tail = flavor._safe_format(variant.head_italic, FIELDS)
        assert _fits_feature_headline(pre, tail), variant
        deck = flavor._safe_format(variant.deck, FIELDS)
        assert text_width(deck_font, deck) <= COLUMN * 2 - 40, variant


def test_templates_use_only_known_fields_and_spacing_is_clean():
    for variant in _all_variants():
        for text in (variant.head_pre, variant.head_italic, variant.deck):
            rendered = flavor._safe_format(text, FIELDS)
            assert "—" not in rendered or "—" in text, variant
            assert "{" not in rendered and "  " not in rendered, variant
        assert not variant.head_pre.endswith(" "), variant
        tail = variant.head_italic
        assert not tail or tail[0] in " ,.", variant


@pytest.mark.parametrize("tiers", [flavor._WASHER_DONE, flavor._DRYER_DONE])
def test_finished_cycle_copy_always_says_what_to_do(tiers):
    for _, pool in tiers:
        for pre, tail in pool:
            lowered = tail.lower()
            assert any(word in lowered for word in ("dryer", "fold", "unload", "wet load")), tail
            assert _fits_feature_headline(pre, tail)


def test_finished_cycle_copy_gets_firmer_as_the_load_waits():
    def heads(minutes):
        ha = {"washer": dict(status="power_off", cycles=1, lastNotification=dict(
            type="washing_is_complete", at=iso(-minutes)))}
        ctx = ctx_at()
        return flavor.done_copy(build_appliance_view(ha, "washer-done", ctx=ctx), ctx)["head_pre"]

    tiers = flavor._WASHER_DONE
    assert heads(5) in {p for p, _ in tiers[0][1]}
    assert heads(30) in {p for p, _ in tiers[1][1]}
    assert heads(55) in {p for p, _ in tiers[2][1]}


def _sauna_view(ctx, **sauna):
    return build_appliance_view({"sauna": sauna}, "sauna", ctx=ctx)


@pytest.mark.parametrize("slot", range(16))
def test_sauna_lines_always_carry_the_ready_time(slot):
    ctx = ctx_at(NOW + timedelta(minutes=slot * flavor.ROTATION_MINUTES))
    view = _sauna_view(ctx, **SHAPES["sauna"]["sauna"])
    forecast = view.extras["forecast"]
    head, tail, deck = flavor.sauna_forecast_copy(view, forecast, ctx, sf.READY_F)
    assert forecast["ready_label"] in tail
    assert _fits_feature_headline(head, tail)
    assert "{" not in deck
    ready = _sauna_view(ctx, **SHAPES["sauna ready"]["sauna"])
    head, tail, deck = flavor.sauna_forecast_copy(ready, ready.extras["forecast"], ctx, sf.READY_F)
    assert "ready" in tail.lower()
    assert ready.extras["forecast"]["ready_label"] in deck


@pytest.mark.parametrize("slot", range(8))
def test_pool_lines_state_the_goal_and_the_freeze_guard(slot):
    ctx = ctx_at(NOW + timedelta(minutes=slot * flavor.ROTATION_MINUTES))
    view = build_appliance_view(SHAPES["pool"], "pool", ctx=ctx)
    head, tail, deck = flavor.pool_copy(view, ctx)
    assert "88°" in tail and "Freeze guard armed." in deck


def test_calm_copy_rotates_hourly_and_names_the_edition():
    seen = set()
    for hour in range(24):
        when = datetime(2026, 11, 1, hour, 30, tzinfo=timezone.utc)
        calm = flavor.calm_copy(ctx_at(when), {})
        seen.add(calm["head_pre"] + calm["head_italic"])
        assert calm["kicker"].endswith("EDITION")
        assert "{" not in calm["deck"]
    assert len(seen) >= 8
    assert flavor.calm_copy(ctx_at(datetime(2026, 11, 1, 3, tzinfo=timezone.utc)), {})["kicker"] == \
        "THE LATE EDITION"


def test_calm_headlines_and_decks_fit():
    head = fonts.serif(26, weight="bold")
    italic = fonts.serif(26, italic=True, weight="bold")
    deck = fonts.serif(12, italic=True, weight="semibold")
    pools = (flavor._CALM_HEADS, flavor._CALM_MORNING_HEADS, flavor._CALM_EVENING_HEADS,
             flavor._CALM_NIGHT_HEADS)
    for pool in pools:
        for pre, tail in pool:
            assert text_width(head, pre.rstrip()) <= COLUMN and text_width(italic, tail) <= COLUMN
    ha = {"coffee": {"cupsToday": 123}, "solar": {"currentKw": 18.4}, "pool": {"current": 104}}
    for slot in range(48):
        when = NOW + timedelta(hours=slot)
        assert text_width(deck, flavor.calm_copy(ctx_at(when), ha)["deck"]) <= COLUMN


def test_calm_copy_uses_only_readings_it_has():
    for slot in range(48):
        when = NOW + timedelta(hours=slot)
        deck = flavor.calm_copy(ctx_at(when), {})["deck"]
        assert "coffee" not in deck and "kW" not in deck and "pool" not in deck


def test_calm_copy_claims_nothing_about_a_pool_still_heating():
    ha = {"pool": {"current": 87.5, "target": 88, "heating": True}}
    for slot in range(48):
        calm = flavor.calm_copy(ctx_at(NOW + timedelta(hours=slot)), ha)
        assert "pool" not in calm["deck"] and "Nothing running" not in calm["deck"]
        assert calm["head_italic"] not in {tail for _, tail in flavor._CALM_IDLE_HEADS}


def test_no_copy_says_the_laundry_is_done_with_while_it_may_not_be():
    lines = [text for pool in (flavor._CALM_DECKS, flavor._CALM_IDLE_DECKS) for text in pool]
    assert not any("no laundry" in line.lower() for line in lines)


def test_wrinkle_care_copy_never_says_to_open_the_dryer():
    for variant in flavor.DRYER_VARIANTS["wrinkle_care"]:
        text = (variant.head_pre + variant.head_italic + variant.deck).lower()
        assert "unload" not in text and "ready when" not in text


def test_a_paused_washer_shows_the_pause_icon_with_or_without_history():
    ctx = ctx_at()
    for raw in (None, cycle(("running", -26), ("pause", -6))):
        ha = {"washer": dict(WASHER, status="pause", remaining=iso(30), cycle=raw)}
        view = build_appliance_view(ha, "washer", ctx=ctx)
        assert editorial._feature_washer(view, ctx, P.ink).icon_phase == "pause"


# ── Cycle progress data ───────────────────────────────────────────────


def rows(*pairs):
    return [{"s": status, "t": t} for status, t in pairs]


def test_cycle_starts_after_the_last_idle_state_and_survives_an_outage():
    got = hc._cycle_segments(rows(
        ("running", 1), ("end", 2), ("power_off", 3), ("initial", 4), ("running", 5),
        ("unavailable", 6), ("running", 7), ("rinsing", 8),
    ), "rinsing")
    assert got == [{"s": "running", "t": 5}, {"s": "rinsing", "t": 8}]


@pytest.mark.parametrize(("history", "live"), [
    (None, "running"), ([], "running"),
    # The look-back doesn't reach the start, so its length would be a guess.
    (rows(("running", 1), ("rinsing", 2)), "rinsing"),
    (rows(("power_off", 1), ("running", 2)), "power_off"),
    (rows(("power_off", 1), ("running", 2)), "unavailable"),
])
def test_cycle_is_unknown_without_a_visible_start(history, live):
    assert hc._cycle_segments(history, live) is None


def test_cycle_view_reports_true_time_progress():
    ha = {"washer": dict(WASHER, status="rinsing", remaining=iso(30),
                         cycle=cycle(("running", -20), ("rinsing", -10)))}
    view = build_appliance_view(ha, "washer", ctx=ctx_at())
    got = view.extras["cycle"]
    assert got["pct"] == 40, "20 of 50 minutes"
    assert got["started_label"] == "1:52 PM"
    assert got["elapsed_label"] == "20 min"
    assert got["segments"] == [("running", pytest.approx(10)), ("rinsing", pytest.approx(10))]


@pytest.mark.parametrize(("remaining", "raw"), [
    (None, cycle(("running", -20))), (iso(-1), cycle(("running", -20))), (iso(30), None),
])
def test_cycle_view_needs_both_ends(remaining, raw):
    ha = {"washer": dict(WASHER, status="running", remaining=remaining, cycle=raw)}
    assert build_appliance_view(ha, "washer", ctx=ctx_at()).extras["cycle"] is None


def test_station_follows_the_cycle_and_a_pause_keeps_its_place():
    assert flavor.laundry_station("washer", "running") == 0
    assert flavor.laundry_station("washer", "rinsing") == 1
    assert flavor.laundry_station("washer", "spinning") == 2
    assert flavor.laundry_station("dryer", "wrinkle_care") == 2
    assert flavor.laundry_station("washer", "pause") is None
    assert flavor.laundry_station("washer", "pause", ["running", "rinsing", "pause"]) == 1


def _mock_ha(monkeypatch, handler):
    real = httpx.AsyncClient
    monkeypatch.setattr(hc.httpx, "AsyncClient",
                        lambda **kw: real(transport=httpx.MockTransport(handler), **kw))


@pytest.mark.asyncio
async def test_cycle_history_parses_minimal_rows(monkeypatch):
    def handler(request):
        assert request.url.params["filter_entity_id"] == hc._WASHER_STATUS
        return httpx.Response(200, json=[[
            {"entity_id": hc._WASHER_STATUS, "state": "power_off",
             "last_changed": "2026-11-01T18:00:00+00:00"},
            {"state": "Running", "last_changed": "2026-11-01T18:30:00+00:00"},
        ]])

    _mock_ha(monkeypatch, handler)
    got = await hc.fetch_ha_cycle_history("http://ha.example.test/", "t", [hc._WASHER_STATUS], now=NOW)
    assert [r["s"] for r in got[hc._WASHER_STATUS]] == ["power_off", "running"]


@pytest.mark.asyncio
@pytest.mark.parametrize("response", [
    httpx.Response(500, text="boom"),
    httpx.Response(200, text="not json"),
    httpx.Response(200, json={"unexpected": "shape"}),
])
async def test_cycle_history_failure_costs_only_the_progress(monkeypatch, response):
    _mock_ha(monkeypatch, lambda request: response)
    assert await hc.fetch_ha_cycle_history("http://ha.example.test", "t", ["a"], now=NOW) is None


def test_shape_passes_history_only_for_the_running_machine():
    states = [
        {"entity_id": hc._WASHER_STATUS, "state": "rinsing", "attributes": {}},
        {"entity_id": hc._DRYER_STATUS, "state": "power_off", "attributes": {}},
    ]
    history = {hc._WASHER_STATUS: rows(("power_off", 1), ("running", 2), ("rinsing", 3)),
               hc._DRYER_STATUS: rows(("running", 1))}
    shaped = hc.shape_ha_state(states, fetched_at=NOW, cycle_history=history)
    assert [row["s"] for row in shaped["washer"]["cycle"]] == ["running", "rinsing"]
    assert shaped["dryer"]["cycle"] is None


def test_sauna_forecast_carries_the_curve_and_history_for_the_chart():
    states = [
        {"entity_id": hc._SAUNA_ID, "state": "heat",
         "attributes": {"current_temperature": 123, "temperature": 185, "fan_mode": "off"}},
        {"entity_id": hc._SAUNA_ROOM_TEMP, "state": "91", "attributes": {}},
        copy.deepcopy(SAUNA_SAMPLES["heating"]),
    ]
    history = [{"t": T - 9000, "v": 60}, {"t": T - 600, "v": 80}]
    forecast = hc.shape_ha_state(states, fetched_at=NOW, sauna_history=history)["sauna"]["forecast"]
    assert forecast["roomCurve"][0] == 91
    assert len(forecast["roomCurve"]) == 181
    assert forecast["roomHistory"] == [{"minutes": -10.0, "value": 80}], "this session only"
    assert forecast["fanInMinutes"] == 33


# ── Meter drawing ─────────────────────────────────────────────────────


def _canvas():
    img = Image.new("RGB", (400, 140), P.bg)
    return img, ImageDraw.Draw(img)


def _is_ink(img, x, y):
    return img.getpixel((x, y)) == P.ink


def test_bar_is_solid_up_to_the_measured_share_and_dithered_after():
    img, draw = _canvas()
    meters.draw_progress_bar(img, draw, P, 0, 10, 204, pct=50, accent=P.ink, h=20)
    row = 20
    assert all(_is_ink(img, x, row) for x in range(2, 102))
    forecast = [_is_ink(img, x, row) for x in range(106, 200)]
    assert any(forecast) and not all(forecast)


@pytest.mark.parametrize("pct", [0, 100])
def test_bar_handles_its_ends(pct):
    img, draw = _canvas()
    meters.draw_progress_bar(img, draw, P, 0, 10, 204, pct=pct, accent=P.ink)


def test_phase_cut_falls_where_the_phase_changed():
    img, draw = _canvas()
    meters.draw_progress_bar(img, draw, P, 0, 10, 204, pct=100, accent=P.ink,
                             segments=[meters.BarSegment(30), meters.BarSegment(10)])
    assert not _is_ink(img, 2 + 150, 20) or not _is_ink(img, 2 + 149, 20)
    assert _is_ink(img, 100, 20)


def test_phase_track_claims_nothing_when_the_phase_is_unknown():
    def solid_circles(current):
        img, draw = _canvas()
        meters.draw_phase_track(img, draw, P, 0, 10, 400, stations=("A", "B", "C"),
                                current=current, accent=P.ink)
        return sum(_is_ink(img, x, 19) for x in (16, 200, 384))

    assert solid_circles(None) == 0
    assert solid_circles(1) == 2


def test_reading_line_drops_a_crowded_label_the_right_one_first(monkeypatch):
    drawn = []
    record = lambda draw, xy, text, *args: drawn.append(text)
    monkeypatch.setattr(meters, "draw_tracked_text_bl", record)
    monkeypatch.setattr(meters, "draw_tracked_text_bl_right", record)
    img, draw = _canvas()

    def labels(w):
        drawn.clear()
        meters.draw_reading_line(draw, P, 0, 0, w, value="1h59m", value_label="LEFT · 30%",
                                 accent=P.ink, right_value="7:59 PM", right_label="DONE BY")
        return list(drawn)

    seen = [labels(w) for w in range(296, 100, -2)]
    assert seen[0] == ["DONE BY", "LEFT · 30%"]
    assert ["LEFT · 30%"] in seen and ["DONE BY"] not in seen
    assert seen[-1] == []


def test_scale_labels_stay_inside_the_scale():
    img, draw = _canvas()
    meters.draw_scale_meter(img, draw, P, 20, 10, 360, low=50, high=90, now=78, target=88,
                            accent=P.ink, marker=61, marker_label="AIR")
    width, height = img.size
    for y in range(height):
        for x in list(range(20)) + list(range(380, width)):
            assert img.getpixel((x, y)) == P.bg, (x, y)


def test_heat_curve_copes_with_no_history_and_never_reaching_ready():
    img, draw = _canvas()
    curve = [(minute, 60 + minute * 0.5) for minute in range(181)]
    assert meters.draw_heat_curve(
        img, draw, P, 0, 0, 400, 120, curve=curve, history=[], ready_f=165, ready_minutes=None,
        ready_label=None, fan_minutes=None, accent=P.ink,
    ) == 120


@pytest.mark.parametrize("kind", ["washer", "dryer", "dishwasher", "sauna", "pool",
                                  "washer-done", "dryer-done"])
@pytest.mark.parametrize("phase", ["", "wash", "rinse", "spin", "pause", "running", "cooling",
                                   "wrinkle_care", "0", "1", "3"])
def test_icons_stay_in_their_square_and_use_pure_ink(kind, phase):
    size = icons.ICON_SIZE
    img = Image.new("RGB", (size + 40, size + 40), (255, 255, 255))
    icons.draw_icon(img, 20, 20, kind=kind, phase=phase, ink=(0, 0, 0), fill=(0, 0, 0))
    assert img.convert("L").getextrema() == (0, 255)
    for x in range(img.width):
        for y in range(img.height):
            pixel = img.getpixel((x, y))
            assert pixel in ((0, 0, 0), (255, 255, 255))
            if not (20 <= x < 20 + size and 20 <= y < 20 + size):
                assert pixel == (255, 255, 255), (x, y)


def test_sauna_icon_shows_a_wave_per_lit_element():
    def waves(phase):
        """White runs across a row through the waves, inside the door's glass."""
        img = Image.new("RGB", (icons.ICON_SIZE, icons.ICON_SIZE), (255, 255, 255))
        icons.draw_icon(img, 0, 0, kind="sauna", phase=phase, ink=(0, 0, 0), fill=(0, 0, 0))
        return img.crop((36, 25, 50, 34)).convert("L").histogram()[255]

    assert waves("0") < waves("1") < waves("2") < waves("3")
    assert waves("") == waves("3")


def test_view_builders_stay_compatible_with_the_shared_shape():
    """Every other design still builds from a shape with no cycle key."""
    ha = {"washer": dict(WASHER, status="running", remaining=iso(10))}
    assert build_appliance_view(ha, "washer", ctx=ctx_at()).extras["cycle"] is None
