# E-Ink Dashboard

Renders the 800x480 BMP/PNG that drives the e-ink dashboard. Two
designs share one data layer: **Editorial** (newspaper-style) and
**Swiss** (one big number, with 1x pixel dithers). Both are pure Pillow.

```
backend/services/eink/
  ha_client.py            # Talks to Home Assistant; produces HAShape dict
  pillow/
    helpers.py            # Low-level parse/format + HVAC reconciliation
    ha_view.py            # ── Typed views over HAShape (the contract)
    render_ctx.py         # ── Ambient state: now_utc, zone, palette, accents
    appliances.py         # ── Registry: kind -> predicate + view + drawer
    palette.py            # Colours per design + per palette mode (six / bw)
    layout.py             # Box geometry (no drawing)
    draw.py               # Drawing primitives (Pillow wrappers)
    fonts.py              # Font loaders
    swiss.py              # Swiss design renderer
    editorial.py          # Editorial design renderer
    render.py             # Top-level dispatcher (cache + design pick)
```

## Architecture

```
   HA REST  -->  ha_client.shape_ha_state  -->   ha_view (ZoneView / FloorView / HvacSummary / ApplianceView)
                                                    |
   TerminalSettings  -->  build_render_context  -->  RenderContext (zone, now, palette, accent())
                                                    |
                                                    v
                                       appliances.APPLIANCES (registry)
                                                    |
                                                    v
                                  swiss.py drawers      editorial.py drawers
```

The view layer was introduced after two production bugs:

1. **Cooling zones rendered as "heating"** because every renderer
   asked `c.get("action") == "heating"` directly and trusted whatever
   HA returned, even when the user-set `mode` was `cool`. Now they
   read `ZoneView.state`, which `derive_hvac_state` reconciles.
2. **Appliance clocks displayed UTC** because each renderer called
   `fmt_clock(...)` without `tz=zone`. Now they read
   `ApplianceView.finish_label`, built once in the user's IANA zone.

## Layer rules

The view layer collapses both bug surfaces into one place. To keep it
that way:

- `helpers.py` is the **only** module that holds raw parse/format
  functions. Don't import `fmt_clock` from anywhere else for HA times
  -- read the pre-formatted view fields instead.
- `ha_view.py` is the **only** module that touches raw HA dict fields
  for state-reconciled or time-localized values (`c.get("action")`,
  `wsh.get("remaining")`, `dw.get("finishTime")`, etc.). Pure
  presentation reads (`ha.get("temps")`, `ha.get("people")`) are
  fine in renderers.
- `render_ctx.py` carries ambient state. **Never** add a new
  positional `zone` / `now_utc` / `palette` parameter to a `_draw_*`
  helper -- extend `RenderContext` instead so it doesn't ripple
  through five signatures.
- `appliances.py` is the **only** module that knows what counts as
  "active" and which drawer handles each kind.
- `swiss.py` and `editorial.py` are pure presentation. They take
  `(ctx, view)` and paint pixels.

A repo-wide grep should find:

- Zero `c.get("action")` outside `helpers.py` and `ha_view.py`.
- Zero `fmt_clock(` calls without `tz=` outside `helpers.py` and
  `ha_view.py`.
- Zero hard-coded `P.red` / `P.blue` for state accents -- use
  `ctx.accent("heat")` / `ctx.accent("cool")` etc. so a future palette
  can re-skin without grepping every renderer.

## How to add a new appliance

1. **Shape the HA payload.** Add the appliance fields to
   `ha_client.shape_ha_state` so it lands in the `HAShape` dict in a
   stable form.

2. **Build a view.** Write `_build_<kind>_view(ha, ctx) -> ApplianceView`
   in `ha_view.py`. Pre-format every time string with `_clock(...)` /
   `_duration(...)` / `_relative(...)`. Per-kind data lives in
   `extras` (document the keys in the function docstring). Register
   the builder in `_APPLIANCE_BUILDERS`.

3. **Register the appliance.** Add an `ApplianceSpec` row to
   `APPLIANCES` in `appliances.py` with:
   - `kind` -- the same string used as the view builder key.
   - `severity` -- 1 (urgent, leads the hero) .. 3 (advisory).
   - `accent_kind` -- `"heat"` / `"cool"` / `"alert"` / `"info"` / `"ok"`.
   - `is_active` -- `(ha, now_utc) -> bool`.
   - `severity_for` (optional) -- dynamic severity override.

   `appliances.py` asserts at import time that every spec has a
   matching view builder, so a half-registered appliance can't ship.

4. **Draw it in each design.** Add a branch to `_story_for` plus a row in
   `_also_row` in `swiss.py`, and a row to `_FEATURE_BUILDERS` (a `_Feature`
   with its `_Gauge`) plus `EDITORIAL_BRIEFS` in `editorial.py`. Read structured
   fields off the view (`view.finish_label`, `view.status_label`,
   `view.extras["..."]`) -- never touch the HA dict here. A test fails if a
   registered kind has no Editorial card or brief.

That's it. The registry handles "which appliances are currently
active" for both designs; you never have to touch
`pick_active`-style logic.

## How to add a new design

1. Create `mydesign.py` next to `swiss.py` / `editorial.py`. Its
   `render_dashboard(img, ha, palette, *, tz_name)` builds a
   `RenderContext` via `build_render_context(ha, palette, tz_name=...)`
   and passes `ctx` (not bare `zone` / `now_utc` / `palette`) to every
   helper.

2. Reuse the data layer untouched: `build_floor_views`,
   `build_hvac_summary`, `build_zone_view` for HVAC; `pick_active(ha,
   ctx)` for the active list; each `ActiveAppliance.view` for hero /
   brief / lead drawers.

3. Add a `MYDESIGN_DRAWERS` dispatch dict mapping appliance kinds to
   per-kind drawers, just like Editorial's `_FEATURE_BUILDERS`. Each drawer
   takes `(ctx, view)` and reads only structured fields.

4. Wire it into `render.py`'s dispatcher.

The view layer guarantees both bugs (cooling-as-heating, UTC clocks)
stay fixed in your new design without you having to remember.

## Testing

- `backend/tests/test_eink_helpers.py` covers `derive_hvac_state`,
  `parse_iso`, `fmt_clock`, and the floor / zone counters.
- `backend/tests/test_ha_view.py` covers `ZoneView` /
  `FloorView` / `HvacSummary` / `ApplianceView` end-to-end against the
  same HA shapes the renderers consume. Adding a new appliance should
  add a `test_<kind>_finish_label_in_user_zone`-style case so the TZ
  contract is exercised.

## Swiss design

The left column answers one question. Calm, the hero is the time; with something
running, it is the minutes left (sauna: minutes to ready); when something needs a
person, it is an inverted slab saying what to do. The time is on the page exactly
once: when a countdown takes the hero, it moves to the header. The right column is
always the weather and the same readings as Home Editorial.

**Dither rule:** solid ink is measured; dithered pixels are forecast or ambient. So
the daylight band and the forecast ranges are dithered with a solid tick for now;
progress bars are solid for how far they have come and dithered for the distance
left; and "No data" is printed in dither alone. Type never sits on the dither.

The dither follows the tone, and both work at 1x, one decision per panel pixel:

- **Gradients** use `draw.atkinson_dither`, error diffusion that renders them smoothly:
  the daylight band, the sun, and the attention slab's fade. It is deterministic, and a
  pixel with no tone never takes ink, so shapes keep sharp edges.
- **Flat levels** use `draw.bayer_dither`, an ordered 4x4 pattern fixed to panel
  coordinates: the digits' shadow, forecast ranges, and what's left of a progress bar.
  Tone snaps to five clean patterns (sparse diagonal, square grid, checkerboard, and the
  two inverses), so each area is perfectly regular.

Every pixel from either is exactly the fill colour, so both pass the `dither=False`
encoders untouched. Swiss sets `draw.fontmode = "1"` so its text adds no grey either.
`test_swiss.py` holds both palettes to that.

## Editorial's activity cards

When exactly one appliance is active, `editorial._draw_feature` draws it with an
icon (`icons.py`), a meter (`meters.py`), and rotating copy (`flavor.py`).

When several are active, `editorial._draw_shared` gives each a smaller card built
from the same `_Feature`: the icon, kicker, and headline, plus its `_Gauge`, a
reading at each end over a bar. Two split the column; each half also has the deck
when all of it fits beside the icon, and labels the bar's ends or shows the phase
track below it. Three take a row each, with everything beside the icon. Past
three, the two most urgent keep rows and the rest are briefs. A gauge follows the
meter rules below. The sauna's reads the room against its ready line and names
the fan plan, or the session's end when that comes first.

- **Icons** show the current phase: the washer's drum changes with wash, rinse,
  and spin, and the sauna is the house's SaunaLife Cube, with one heat wave per lit
  element rising from its heater.
- **Meters** draw only reported values. Laundry progress is elapsed time over
  elapsed plus remaining, from a status history (`fetch_ha_cycle_history`) that is
  read only while a machine runs. If that history is missing or can't see the
  cycle's start, the bar drops out and the phase track and countdown stay. The
  sauna chart is the room sensor as a solid line and the pinned forecast (D-054)
  as a dithered one.
- **Dither** follows the Swiss rule (D-055): solid ink is measured, dither is
  forecast, flat tones are Bayer, gradients are Atkinson, and type never sits on
  dither.
- **Copy** walks a per-cycle shuffle of its pool every `ROTATION_MINUTES`, so
  nothing repeats until the pool has run. Every variant must be true whenever it
  can be picked, and instructions such as "move it to the dryer" stay in every
  variant. `test_editorial_feature.py` checks that all of it fits.

## Home Editorial readings and hourly copy

The House rail shows Primary Suite and Nursery temperatures, followed by coffee
cups today. `temps.primaryBedroom` uses the room sensor
`sensor.usl_environmental_temperature_3` (not `_4`, which is the suite's duct
supply air); `temps.nursery` uses `sensor.nursery_temperature`. Celsius readings
are normalized to Fahrenheit. Floor aggregates remain available to the other
designs. The time appears only in the masthead.

When Home Assistant can't be read, `render_dashboard_bmp` passes
`unavailable_ha_shape()`. Editorial then says so instead of drawing the calm
edition, and every missing reading is a dash, never a zero.

The sauna card's heat-up forecast comes from Home Assistant's
`sensor.sauna_heat_forecast`, which runs the same model as its Sauna panel
(`custom_components/sauna_forecast` in the HomeAssistant project; the attribute
contract is in its `SAUNA_CONTROLS_RUNBOOK.md`). The screens hold no model, so a
refit or fan-plan change there needs no change here (D-058). `sauna_forecast.py`
reads the sensor, drops it once `computed_at` is over 3 minutes old, and moves its
minutes and curve to render time. "Ready" is the room sensor at 165°F; "185°" is
the controller's thermostat. When the sensor is missing, stale or reports a
`reason`, the card shows its live readings without a forecast. The chart's
measured line is the room sensor's history since the sensor's `session_start`.
`backend/tests/fixtures/sauna_heat_forecast.json` holds samples from Home
Assistant's model; regenerate them with `scripts/sauna_forecast_samples.py` only
if the contract changes.

`coffee.cupsToday` comes only from `sensor.kitchen_coffee_cups_today`, the Home
Assistant daily utility meter. HA owns its local-midnight reset; the lifetime
counter is never substituted. Missing, nonfinite, negative, or fractional
counts display a dash; zero remains a real zero.

Hourly quotes and observations use the dedicated `DASHBOARD_SNIPPET_MODEL`
specification (`claude-opus-5-5`, extra-high effort) in `ai_models.py`, without
changing mail/chat model preferences. The generator uses JSON outputs rather
than forced tool choice, with a bounded request and the existing curated
fallback on provider failure, refusal, truncation, or malformed content.
