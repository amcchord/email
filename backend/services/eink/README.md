# E-Ink Dashboard

Renders the 800x480 BMP/PNG that drives the e-ink dashboard. Two
designs share one data layer: **Editorial** (newspaper-style) and
**Swiss** (modular grid). Both are pure Pillow.

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

4. **Draw it in each design.** Add a row to `SWISS_DRAWERS` in
   `swiss.py` (`_describe_<kind>_swiss(view, ctx) -> dict`) and a row
   to `EDITORIAL_LEAD_DRAWERS` plus `EDITORIAL_BRIEFS` in
   `editorial.py`. Read structured fields off the view (
   `view.finish_label`, `view.status_label`, `view.extras["..."]`) --
   never touch the HA dict here.

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
   per-kind drawers, just like `SWISS_HERO_DESCRIBERS` /
   `EDITORIAL_LEAD_DRAWERS`. Each drawer takes `(ctx, view)` and reads
   only structured fields.

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
