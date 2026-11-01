"""Home Editorial must not state unknowns as facts, or cut off what it says."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from PIL import Image, ImageDraw

from backend.services.eink import ha_client as hc
from backend.services.eink.pillow import editorial, flavor, fonts, layout, render_eink_image
from backend.services.eink.pillow.appliances import pick_active
from backend.services.eink.pillow.draw import (
    Run,
    _wrap_runs_into_lines,
    draw_paragraph,
    text_width,
)
from backend.services.eink.pillow.palette import get_palette
from backend.services.eink.pillow.render_ctx import build_render_context
from backend.services.terminal import renderer
from backend.services.terminal.variants import BW_800

NOW = datetime(2026, 7, 1, 16, 33, tzinfo=timezone.utc)
ZONE = "America/New_York"
P = get_palette("editorial", "bw")
COLUMN = layout.EDITORIAL.body_lead.inset(left=18, right=18).w


class Spy:
    """Records every string the renderer draws, whichever helper draws it."""

    def __init__(self, monkeypatch):
        self.drawn = []
        for name in (
            "draw_text_bl", "draw_text_bl_right", "draw_text_bl_center",
            "draw_tracked_text_bl", "draw_tracked_text_bl_center",
            "draw_tracked_text_bl_right", "draw_text_clipped_bl",
            "draw_text_clipped_bl_right",
        ):
            monkeypatch.setattr(editorial, name, self._wrap(getattr(editorial, name)))
        monkeypatch.setattr(editorial, "draw_paragraph", self._wrap(editorial.draw_paragraph))

    def _wrap(self, fn):
        def spy(draw, xy, text, *args, **kwargs):
            self.drawn.append(text)
            return fn(draw, xy, text, *args, **kwargs)
        return spy

    @property
    def text(self):
        return "\n".join(self.drawn)


def render(shape):
    return render_eink_image("editorial", "bw", shape, tz_name=ZONE, use_cache=False)


def full_shape(**extra):
    shape = hc.empty_ha_shape(fetched_at=NOW)
    shape["weather"].update({
        "state": "sunny", "temperature": 72, "humidity": 44, "windSpeed": 6,
        "windBearing": 10, "visibility": 10, "uvIndex": 2,
    })
    shape["sun"] = {"state": "above_horizon"}
    shape["temps"].update({"primaryBedroom": 68, "nursery": 67})
    shape["people"] = [{"name": "Fixture Person", "state": "home"}]
    shape["coffee"] = {"cupsToday": 3}
    shape.update(extra)
    return shape


def test_unknown_readings_are_dashes_but_zero_stays_zero():
    assert editorial._reading(None) == "—"
    assert editorial._reading("unavailable") == "—"
    assert editorial._reading(0) == "0"
    assert editorial._reading(6.4) == "6"


def test_missing_weather_never_prints_a_false_zero(monkeypatch):
    spy = Spy(monkeypatch)
    render(full_shape(weather={"state": "sunny"}))
    joined = spy.text
    assert "—" in joined
    assert "\n0\n" not in f"\n{joined}\n"


def test_home_assistant_outage_does_not_announce_a_calm_house(monkeypatch):
    spy = Spy(monkeypatch)
    render(hc.unavailable_ha_shape(fetched_at=NOW))
    joined = spy.text
    assert "No news from the house." in joined
    assert "NO DATA" in joined
    assert "LIVE" not in joined
    assert "All quiet" not in joined
    assert "NOBODY HOME" not in joined
    assert "HOME UNKNOWN" in joined
    assert "WINDOWS UNKNOWN" in joined
    assert "Sun · Set".upper() not in joined.upper()


def test_a_merely_empty_shape_is_not_reported_as_an_outage(monkeypatch):
    spy = Spy(monkeypatch)
    render(full_shape())
    assert "No news from the house." not in spy.text
    assert "LIVE" in spy.text


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [None, RuntimeError("ha exploded")])
async def test_renderer_marks_a_failed_fetch_unavailable(monkeypatch, failure):
    seen = {}

    async def fetch(settings):
        if failure:
            raise failure
        return None

    async def no_snippet(tz):
        return None

    def capture(design, palette, shape, **kwargs):
        seen.update(shape)
        return Image.new("RGB", (800, 480), (255, 255, 255))

    monkeypatch.setattr(renderer, "fetch_and_shape", fetch)
    monkeypatch.setattr(renderer, "get_current_snippet_dict", no_snippet)
    monkeypatch.setattr(renderer, "render_eink_image", capture)
    await renderer.render_dashboard_bmp(
        BW_800,
        device=None,
        settings=SimpleNamespace(timezone=ZONE),
        design_override="editorial",
    )
    assert seen["unavailable"] is True


def test_time_appears_once_and_house_rail_shows_the_two_rooms(monkeypatch):
    spy = Spy(monkeypatch)
    shape = full_shape()
    shape["allClimates"] = [{"name": "First", "mode": "heat", "current": 70,
                             "target": 72, "action": "heating"}]
    # The masthead paints the clock digits directly, so only it can show them.
    render(shape)
    assert not any("12:33" in text for text in spy.drawn)
    joined = spy.text
    assert "Primary Suite" in joined and "Nursery" in joined
    assert "Living Room" not in joined and "Bedroom" not in joined
    assert "ZONES" not in joined and "HVAC" not in joined


def test_masthead_names_the_real_timezone(monkeypatch):
    spy = Spy(monkeypatch)
    render_eink_image("editorial", "bw", full_shape(), tz_name="America/Los_Angeles",
                      use_cache=False)
    assert "PDT · LIVE" in spy.drawn
    assert not any("EASTERN" in text for text in spy.drawn)


@pytest.mark.parametrize(("count", "label"), [
    (0, "WINDOWS SHUT"), (1, "1 WINDOW OPEN"), (3, "3 WINDOWS OPEN"),
])
def test_window_chip_says_what_it_means(monkeypatch, count, label):
    spy = Spy(monkeypatch)
    render(full_shape(openWindows=[{"id": str(i), "name": "w"} for i in range(count)]))
    assert label in spy.drawn


@pytest.mark.parametrize("headline", [
    editorial._washer_done_headline, editorial._dryer_done_headline,
])
def test_fixed_hero_headlines_fit_their_two_lines(headline):
    assert len(_wrap_runs_into_lines(headline(P), COLUMN)) == 2


def test_every_appliance_headline_fits_its_two_lines():
    fields = {"remaining": "1h 42m", "finish": "12:45 PM", "relative": "12m ago",
              "cycle_no": 154}
    tables = (flavor.WASHER_VARIANTS, flavor.DRYER_VARIANTS, flavor.DISHWASHER_VARIANTS)
    checked = 0
    for table in tables:
        for variants in table.values():
            for variant in variants:
                for size in (32, 22):
                    upright = fonts.serif(size, weight="bold")
                    italic = fonts.serif(size, italic=True, weight="bold")
                    runs = [
                        Run(flavor._safe_format(variant.head_pre, fields) + " ", upright, P.ink),
                        Run(flavor._safe_format(variant.head_italic, fields), italic, P.ink),
                    ]
                    assert len(_wrap_runs_into_lines(runs, COLUMN)) <= 2, variant
                    checked += 1
    assert checked > 100


class RecordingDraw:
    def __init__(self):
        self.lines = []

    def text(self, xy, text, font=None, fill=None):
        self.lines.append((text, font))


@pytest.mark.parametrize("quote", flavor.FALLBACK_QUOTES, ids=lambda q: q["text"][:24])
def test_no_curated_quote_overflows_the_column(quote):
    body = "“" + quote["text"] + "”"
    factory = lambda s: fonts.serif(s, italic=True, weight="semibold")
    font = editorial._pick_snippet_size(factory, body, COLUMN, (22, 20, 18, 17, 16))
    draw = RecordingDraw()
    draw_paragraph(draw, (0, 0, COLUMN, 200), body, font=font, fill=P.ink,
                   line_height_px=30, max_lines=5)
    assert "".join(line for line, _ in draw.lines).replace(" ", "") == body.replace(" ", "")
    for line, used in draw.lines:
        assert used.getlength(line) <= COLUMN, line


def _ink_rows(image):
    gray = image.convert("L")
    return {y for y in range(gray.height)
            if any(gray.getpixel((x, y)) < 128 for x in range(gray.width))}


def test_fact_strip_sub_line_stays_inside_the_strip():
    image = Image.new("RGB", (400, 200), (255, 255, 255))
    bottom = editorial._draw_fact_strip(ImageDraw.Draw(image), P, 0, 10, 392, [
        {"k": "Room", "v": "84°", "sub": "19% RH"},
        {"k": "Target", "v": "185°"},
    ])
    assert max(_ink_rows(image)) < bottom


def test_fact_strip_without_sub_lines_keeps_its_height():
    image = Image.new("RGB", (400, 200), (255, 255, 255))
    bottom = editorial._draw_fact_strip(ImageDraw.Draw(image), P, 0, 10, 392, [
        {"k": "Target", "v": "185°"},
    ])
    assert bottom == 10 + 2 + 48 + 2


def test_brief_sub_line_clears_the_dotted_rule():
    ctx = build_render_context({"fetchedAt": NOW.isoformat()}, P, tz_name=ZONE)
    shape = full_shape(dryer={"status": "running", "operation": "cycle",
                              "remaining": (NOW + timedelta(minutes=30)).isoformat(),
                              "lastNotification": None, "powerOn": True})
    item = next(a for a in pick_active(shape, ctx) if a.kind == "dryer")
    with_rule = Image.new("RGB", (400, 60), (255, 255, 255))
    editorial._draw_brief(ImageDraw.Draw(with_rule), ctx, shape, 0, 0, 392, item, last=False)
    without_rule = Image.new("RGB", (400, 60), (255, 255, 255))
    editorial._draw_brief(ImageDraw.Draw(without_rule), ctx, shape, 0, 0, 392, item, last=True)
    rule_y = 40 - 2
    assert rule_y in _ink_rows(with_rule)
    assert max(_ink_rows(without_rule)) < rule_y, "text must end above the rule"


def test_weather_glyph_is_clear_of_the_temperature():
    image = render(full_shape())
    col = layout.EDITORIAL.masthead_col_weather
    gray = image.convert("L")
    font = fonts.serif(layout.EditorialType.TEMP_PX, weight="bold")
    digits_x0 = col.x1 - text_width(font, "72°")
    # Rows level with the digits: the 8 px before them must hold no sun ray.
    gap = range(digits_x0 - 8, digits_x0 - 1)
    for y in range(col.y0 + 6, col.y0 + 36):
        assert all(gray.getpixel((x, y)) > 127 for x in gap), y


def _sauna_shape(**forecast):
    base = {
        "readyReached": False, "readyAt": (NOW + timedelta(minutes=61)).isoformat(),
        "readyInMinutes": 61, "targetReached": False,
        "targetAt": (NOW + timedelta(minutes=40)).isoformat(), "targetInMinutes": 40,
        "fan": {"state": "planned", "at": (NOW + timedelta(minutes=40)).isoformat()},
        "sessionEndsBeforeReadyAt": None,
    }
    return full_shape(sauna={
        "mode": "heat", "current": 123, "target": 185, "duration": 120, "heaters": 3,
        "door": False, "roomTemp": 91, "roomHumidity": 19, "forecast": {**base, **forecast},
    })


@pytest.mark.parametrize(("forecast", "expected"), [
    ({}, ["Sauna · Heating", "1:34 PM.", "In 1 h 1 min. 3 of 3 elements on; door closed.",
          "19% RH", "GOAL 185°", "IN 40 min", "10 min Med"]),
    ({"fan": {"state": "due"}}, ["Run now", "Run the fan now, 10 min on Medium."]),
    ({"fan": {"state": "running", "minutesLeft": 4}},
     ["Running", "4 min left", "fan has 4 min left."]),
    ({"readyReached": True, "readyAt": (NOW - timedelta(minutes=3)).isoformat(),
      "readyInMinutes": None, "targetReached": True, "targetAt": NOW.isoformat(),
      "targetInMinutes": None},
     ["Sauna · Ready", "ready.", "Room reached 165° at 12:30 PM.", "REACHED", "READY"]),
    ({"readyAt": None, "readyInMinutes": None, "targetAt": None, "targetInMinutes": None},
     ["165°.", "The room levels off below it at this target.", "ABOVE TARGET"]),
    ({"sessionEndsBeforeReadyAt": (NOW + timedelta(minutes=5)).isoformat()},
     ["Session ends 12:38 PM, before it's ready."]),
])
def test_sauna_card_shows_the_forecast(monkeypatch, forecast, expected):
    drawn = []
    real_para = editorial.draw_paragraph
    monkeypatch.setattr(editorial, "draw_paragraph", lambda draw, box, text, **kw: (
        drawn.append(text), real_para(draw, box, text, **kw))[1])
    real_tracked = editorial.draw_tracked_text_bl
    monkeypatch.setattr(editorial, "draw_tracked_text_bl", lambda draw, xy, text, *a, **k: (
        drawn.append(text), real_tracked(draw, xy, text, *a, **k))[1])
    real_center = editorial.draw_tracked_text_bl_center
    monkeypatch.setattr(editorial, "draw_tracked_text_bl_center", lambda draw, xy, text, *a, **k: (
        drawn.append(text), real_center(draw, xy, text, *a, **k))[1])
    real_value = editorial.draw_text_bl_center
    monkeypatch.setattr(editorial, "draw_text_bl_center", lambda draw, xy, text, *a, **k: (
        drawn.append(text), real_value(draw, xy, text, *a, **k))[1])
    real_headline = editorial.draw_headline

    def headline(draw, box, runs, **kw):
        drawn.extend(run.text for run in runs)
        return real_headline(draw, box, runs, **kw)

    monkeypatch.setattr(editorial, "draw_headline", headline)
    render(_sauna_shape(**forecast))
    for want in expected:
        assert any(want.upper() in text.upper() for text in drawn), (want, drawn)


def test_preset_target_is_not_shown_as_a_32_degree_goal(monkeypatch):
    shape = _sauna_shape()
    shape["sauna"]["target"] = 32
    drawn = []
    real = editorial.draw_tracked_text_bl_center
    monkeypatch.setattr(editorial, "draw_tracked_text_bl_center", lambda draw, xy, text, *a, **k: (
        drawn.append(text), real(draw, xy, text, *a, **k))[1])
    render(shape)
    assert "GOAL PRESET" in drawn
    assert not any("32\u00b0" in text for text in drawn)


def test_sauna_card_without_forecast_keeps_the_plain_story(monkeypatch):
    shape = _sauna_shape()
    shape["sauna"]["forecast"] = None
    drawn = []
    real_para = editorial.draw_paragraph
    monkeypatch.setattr(editorial, "draw_paragraph", lambda draw, box, text, **kw: (
        drawn.append(text), real_para(draw, box, text, **kw))[1])
    render(shape)
    assert any("Cabin presently 123°" in text for text in drawn)
