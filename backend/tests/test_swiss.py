"""The Swiss design: the big-number story, its dither, and what it won't claim."""
from datetime import datetime, timedelta, timezone

import pytest
from PIL import Image

from backend.services.eink import ha_client as hc
from backend.services.eink.pillow import render_eink_image, swiss
from backend.services.eink.pillow.appliances import pick_active
from backend.services.eink.pillow.draw import pixel_dither
from backend.services.eink.pillow.palette import get_palette
from backend.services.eink.pillow.render_ctx import build_render_context

NOW = datetime(2026, 7, 1, 16, 33, tzinfo=timezone.utc)
ZONE = "America/New_York"


def shape(**extra):
    base = hc.empty_ha_shape(fetched_at=NOW)
    base["weather"].update({
        "state": "partlycloudy", "temperature": 72, "humidity": 44, "windSpeed": 6,
        "windBearing": 10,
        "forecast": {"daily": [
            {"datetime": NOW.isoformat(), "condition": "sunny", "temperature": 80, "templow": 60},
            {"datetime": (NOW + timedelta(days=1)).isoformat(), "condition": "rainy",
             "temperature": 70, "templow": 55},
        ]},
    })
    base["sun"] = {"state": "above_horizon", "nextRising": "2026-07-02T09:10:00+00:00",
                   "nextSetting": "2026-07-02T00:20:00+00:00"}
    base["temps"].update({"primaryBedroom": 68, "nursery": 67})
    base["people"] = [{"name": "Fixture Person", "state": "home"}]
    base["coffee"] = {"cupsToday": 3}
    base["solar"] = {"todayKwh": 12.5, "currentKw": 3.2, "panelCount": 20}
    base.update(extra)
    return base


def washer(minutes=42):
    return {"status": "rinse", "operation": "cycle",
            "remaining": (NOW + timedelta(minutes=minutes)).isoformat(),
            "lastNotification": None, "powerOn": True, "cycles": 54, "energyMonth": 12000}


def dryer(minutes=58):
    return {"status": "running", "operation": "cycle",
            "remaining": (NOW + timedelta(minutes=minutes)).isoformat(),
            "lastNotification": None, "powerOn": True}


def heating_sauna(**forecast):
    return {
        "mode": "heat", "current": 123, "target": 185, "duration": 120, "heaters": 3,
        "door": False, "roomTemp": 91, "roomHumidity": 19,
        "forecast": {
            "readyReached": False, "readyAt": (NOW + timedelta(minutes=61)).isoformat(),
            "readyInMinutes": 61, "targetReached": False,
            "targetAt": (NOW + timedelta(minutes=40)).isoformat(), "targetInMinutes": 40,
            "fan": {"state": "planned", "at": (NOW + timedelta(minutes=40)).isoformat()},
            "sessionEndsBeforeReadyAt": None, **forecast,
        },
    }


def story(data):
    ctx = build_render_context(data, get_palette("swiss", "bw"), tz_name=ZONE)
    return swiss._story_for(pick_active(data, ctx), ctx)


class Spy:
    def __init__(self, monkeypatch):
        self.drawn = []
        for name in ("draw_text_bl", "draw_text_bl_right", "draw_tracked_text_bl"):
            monkeypatch.setattr(swiss, name, self._wrap(getattr(swiss, name)))

    def _wrap(self, fn):
        def spy(draw, xy, text, *args, **kwargs):
            self.drawn.append(text)
            return fn(draw, xy, text, *args, **kwargs)
        return spy


def render(data, palette="bw"):
    return render_eink_image("swiss", palette, data, tz_name=ZONE, use_cache=False)


@pytest.mark.parametrize("palette", ["bw", "six"])
@pytest.mark.parametrize("data", [
    shape(),
    shape(washer=washer(), dryer=dryer(), sauna=heating_sauna()),
    shape(washer={"status": "power_off", "remaining": None, "powerOn": False, "cycles": 54,
                  "energyMonth": 0, "operation": None,
                  "lastNotification": {"type": "washing_is_complete",
                                       "at": (NOW - timedelta(minutes=5)).isoformat()}}),
    hc.unavailable_ha_shape(fetched_at=NOW),
], ids=["calm", "busy", "attention", "unavailable"])
def test_every_pixel_is_a_palette_ink(palette, data):
    """No antialiasing or blended dots for the panel encoders to mangle."""
    P = get_palette("swiss", palette)
    allowed = {P.bg, P.ink, P.paper, P.red, P.blue, P.green, P.yellow, P.rule}
    colours = {colour for _, colour in render(data, palette).getcolors(maxcolors=4096)}
    assert colours <= allowed, colours - allowed


def _uniform(tone_value, size=(64, 64), origin=(0, 0)):
    image = Image.new("1", (origin[0] + size[0], origin[1] + size[1]), 1)
    pixel_dither(image, origin, Image.new("L", size, tone_value), 0)
    return image


def _ink_fraction(image):
    return image.convert("L").histogram()[0] / (image.width * image.height)


@pytest.mark.parametrize(("tone_value", "fraction"), [
    (0, 0), (32, 2 / 16), (64, 4 / 16), (128, 8 / 16), (191, 12 / 16), (223, 14 / 16),
    (255, 1),
])
def test_dither_snaps_to_exact_clean_levels(tone_value, fraction):
    assert _ink_fraction(_uniform(tone_value, (96, 96))) == fraction


def test_dither_works_at_one_panel_pixel():
    """The midpoint is a checkerboard of single pixels, the finest the panel can show."""
    image = _uniform(128, (32, 32))
    for y in range(32):
        for x in range(32):
            assert (image.getpixel((x, y)) == 0) == ((x + y) % 2 == 0), (x, y)


def test_dither_lightest_pattern_is_isolated_single_pixels():
    image = _uniform(32, (32, 32))
    for y in range(1, 31):
        for x in range(1, 31):
            if image.getpixel((x, y)) == 0:
                neighbours = [image.getpixel((x + dx, y + dy))
                              for dx in (-1, 0, 1) for dy in (-1, 0, 1) if dx or dy]
                assert all(neighbours), (x, y)


def test_dither_light_and_dark_levels_mirror_in_coverage():
    assert _ink_fraction(_uniform(32, (32, 32))) == 1 - _ink_fraction(_uniform(223, (32, 32)))


@pytest.mark.parametrize("tone_value", [32, 64, 128, 191, 223])
def test_dither_is_a_perfect_repeat(tone_value):
    image = _uniform(tone_value, (64, 64))
    block = image.crop((0, 0, 4, 4)).tobytes()
    for y in range(0, 64, 4):
        for x in range(0, 64, 4):
            assert image.crop((x, y, x + 4, y + 4)).tobytes() == block, (x, y)


def test_dither_grid_is_fixed_to_panel_coordinates():
    whole = _uniform(100, (64, 32))
    split = Image.new("1", (64, 32), 1)
    pixel_dither(split, (0, 0), Image.new("L", (23, 32), 100), 0)
    pixel_dither(split, (23, 0), Image.new("L", (41, 32), 100), 0)
    assert whole.tobytes() == split.tobytes()


def test_dither_paints_only_the_fill_colour():
    image = Image.new("RGB", (32, 32), (255, 255, 255))
    pixel_dither(image, (0, 0), Image.linear_gradient("L").resize((32, 32)), (200, 40, 30))
    assert {colour for _, colour in image.getcolors()} == {(255, 255, 255), (200, 40, 30)}


def test_calm_hero_is_the_clock_and_time_appears_once(monkeypatch):
    spy = Spy(monkeypatch)
    render(shape())
    assert story(shape()).number == "12:33"
    # The digits are also drawn into the shadow mask; only the solid copy is on
    # the page as type, and no other element repeats the time.
    assert not any("12:33 PM" in text for text in spy.drawn)
    assert sum("12:33" in text for text in spy.drawn) == 2


def test_countdown_hero_moves_the_time_to_the_header(monkeypatch):
    data = shape(washer=washer(42))
    assert story(data).number == "42"
    spy = Spy(monkeypatch)
    render(data)
    assert sum("12:33" in text for text in spy.drawn) == 1
    assert "12:33 PM" in spy.drawn


def test_attention_hero_says_what_to_do():
    data = shape(washer={"status": "power_off", "remaining": None, "powerOn": False,
                         "cycles": 54, "energyMonth": 0, "operation": None,
                         "lastNotification": {"type": "washing_is_complete",
                                              "at": (NOW - timedelta(minutes=5)).isoformat()}})
    s = story(data)
    assert s.attention is True
    assert s.headline == ("Move the wash", "to the dryer.")


@pytest.mark.parametrize(("forecast", "number", "detail"), [
    ({}, "61", "Ready around 1:34 PM. Run the fan at 1:13 PM"),
    ({"fan": {"state": "due"}}, "61", "Ready around 1:34 PM. Run the fan now"),
    ({"fan": {"state": "running", "minutesLeft": 4}}, "61",
     "Ready around 1:34 PM. Fan has 4 min left"),
    ({"readyReached": True, "readyAt": (NOW - timedelta(minutes=3)).isoformat(),
      "readyInMinutes": None}, "Ready", "Room reached 165° at 12:30 PM"),
    ({"readyAt": None, "readyInMinutes": None}, "91°",
     "Won't reach 165° at this target"),
    ({"sessionEndsBeforeReadyAt": (NOW + timedelta(minutes=5)).isoformat()}, "61",
     "Session ends 12:38 PM, before it's ready"),
])
def test_sauna_hero_leads_with_the_forecast(forecast, number, detail):
    s = story(shape(sauna=heating_sauna(**forecast)))
    assert s.number == number
    assert s.detail == detail


def test_sauna_preset_target_is_not_called_32_degrees():
    sauna = heating_sauna()
    sauna.update(target=32, forecast=None)
    s = story(shape(sauna=sauna))
    assert s.detail == "Heating to its preset"


def test_unavailable_is_stated_and_invents_nothing(monkeypatch):
    spy = Spy(monkeypatch)
    render(hc.unavailable_ha_shape(fetched_at=NOW))
    joined = "\n".join(spy.drawn)
    assert "No data" in joined
    assert "Home unknown" in joined and "Garage unknown" in joined
    assert "Nobody home" not in joined and "Garage closed" not in joined
    assert "\n0\n" not in f"\n{joined}\n"
    assert "6:19" not in joined


def test_missing_readings_are_dashes_not_zeros(monkeypatch):
    spy = Spy(monkeypatch)
    render(shape(weather={"state": "sunny"}))
    joined = "\n".join(spy.drawn)
    assert "Wind —" in joined and "Humidity —%" in joined
    assert "—" in spy.drawn


def test_rail_shows_the_two_rooms_and_garage_only_inverts_when_open(monkeypatch):
    spy = Spy(monkeypatch)
    render(shape())
    joined = "\n".join(spy.drawn)
    assert "Primary Suite" in joined and "Nursery" in joined
    assert "Windows shut" in joined and "Garage closed" in joined
    spy.drawn.clear()
    render(shape(garage={"state": "open"}))
    assert "Garage open" in spy.drawn


@pytest.mark.parametrize(("state", "printed"), [
    ("opening", "Garage opening"),
    ("closing", "Garage closing"),
    ("unavailable", "Garage unavailable"),
    ("unknown", "Garage unknown"),
    ("", "Garage unknown"),
])
def test_only_a_reported_closed_garage_says_closed(monkeypatch, state, printed):
    spy = Spy(monkeypatch)
    render(shape(garage={"state": state}))
    joined = "\n".join(spy.drawn)
    assert printed in joined
    assert "Garage closed" not in joined


def test_missing_garage_entity_is_unknown_not_closed():
    assert hc.shape_ha_state([], fetched_at=NOW)["garage"]["state"] == "unknown"


@pytest.mark.parametrize("state", [
    "sunny", "clear", "clear-night", "partlycloudy", "mostlycloudy", "cloudy", "rainy",
    "pouring", "snowy", "lightning", "lightning-rainy", "snowy-rainy", "fog", "mist", "haze",
    "hail", "windy", "windy-variant", "exceptional", "made-up-state",
])
def test_every_weather_state_renders(state):
    data = shape()
    data["weather"]["state"] = state
    assert render(data).size == (800, 480)


def test_more_running_than_fits_says_how_many_more(monkeypatch):
    data = shape(
        sauna=heating_sauna(), washer=washer(), dryer=dryer(),
        dishwasher={"state": "run", "program": "eco", "progress": 50,
                    "finishTime": (NOW + timedelta(minutes=30)).isoformat(),
                    "door": "closed", "powerOn": True, "connected": True},
        pool={"operation": "heating", "current": 70, "target": 90, "air": 60,
              "heating": True, "pumpRunning": True, "schedule": True, "freezeProtect": False},
    )
    spy = Spy(monkeypatch)
    render(data)
    assert "+2 more" in spy.drawn
