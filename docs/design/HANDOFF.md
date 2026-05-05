# Cambridge · E‑Ink Home Dashboard — Implementation Handoff

> A complete brief for an implementing LLM or engineer. Read top‑to‑bottom.
> The mockup lives in `Cambridge Dashboard.html`; this document explains what
> was designed, why, and how to translate it onto the real device.

---

## 0. TL;DR

You are implementing a **single-screen e‑ink home dashboard** for a 7.3"
800×480 panel mounted somewhere visible (kitchen, foyer). It pulls data from
a Home Assistant instance and renders a static **calm** layout most of the
time, switching to a **prominent “lead story”** when something physical needs
attention (sauna heating, washer running, washer-done‑please‑unload, dishwasher,
pool heating).

Two finished design directions are provided; pick **one** to ship. Both have
been authored against two color modes:

- **6‑color** — for a Spectra/E‑Ink Gallery panel (Black + White + Red + Blue + Green + Yellow). Use brand-neutral tooling that drives a 6‑color Spectra panel.
- **B&W** — pure black and white, no greys. Use for a 2‑color e‑ink panel.

There is no greyscale and there are no smooth gradients in either mode.
That is the single most important constraint and it shapes every other decision.

---

## 1. Hardware target

| Attribute | Value |
|---|---|
| Resolution | 800 × 480 px (landscape) |
| Diagonal | 7.3" |
| Panel A (color) | 6‑color e‑ink (Spectra/Gallery): K, W, R, B, G, Y |
| Panel B (mono) | B&W e‑ink |
| Refresh model | Slow full refresh; ghosting on partial refresh; ~60–180 s update cadence is fine |
| DPI | ~133 PPI — readable but coarse |
| Viewing distance | ~0.5–2 m (glanceable) |
| Backlight | None (assume ambient light) |

Whatever microcontroller / Pi / ESP32 hardware you choose, the renderer must
push an **8‑bit indexed PNG (or BMP)** with a palette restricted to the panel’s
native colors. Any other path (JPEG, anti‑aliased rasters, browser blend modes)
will produce mush.

---

## 2. The visual problem space (theory)

E‑ink isn’t just “a screen with no backlight.” It rewards a fundamentally
different design language than an LCD. Specifically:

### 2.1 No greys
- **6‑color Spectra/Gallery** can render only K/W/R/G/B/Y. Anything else is
  dithered into noise. Photographs look bad. Soft gradients become grain.
- **2‑color B&W** literally has 1 bit of luminance. Greys must be simulated
  with **dot patterns** or hairline rules — and even then, fine dithers
  vibrate at this PPI.

**Implication:** Build the design **using value contrast and weight, not
tint.** Where you’d normally reach for `#888` (a soft grey label), you must
substitute one of these:
- A smaller pixel font in pure ink (size = hierarchy).
- An italic in pure ink (style = hierarchy).
- A hairline rule under or beside the text (geometry = hierarchy).
- Wider letterspacing (texture = hierarchy).

Both `editorial.jsx` and `swiss.jsx` deliberately set `muted: '#000000'` in
the BW palette and `muted: '#111111'` (effectively ink) in the 6-color
palette. **Never introduce a literal `#888` to “tone something down.”**

### 2.2 Aliasing and font choice at 133 PPI
Anti-aliasing is the enemy. Sub‑pixel hinting that would smooth a 14 px
serif on an LCD becomes a fuzzy halo on e‑ink because the panel can only
print pure ink dots — there’s no in-between.

The mockup uses three families on purpose:
1. **Source Serif 4** (Editorial) — a true serif at large display sizes
   (28–50 px) where AA artifacts become invisible. Never use a serif under
   ~14 px on e‑ink; switch to a pixel font.
2. **Helvetica Neue / Inter / Arial** (Swiss) — a sans display face for
   24–84 px numerics. Helvetica was chosen specifically because its
   straight verticals and bowls render cleanly when rasterized to a 1‑bit
   target.
3. **Cherry / Cherry Small / Tamzen / Spleen** (both directions) — bitmap
   pixel fonts for **all small data labels** (under ~12 px). These are
   shipped in `fonts/` and registered in `fonts.css`. They look correct
   because **the glyphs were authored at exactly the pixel grid**, so AA
   doesn’t need to do anything.

> Rule of thumb: if it’s under ~13 px, it must be a pixel font. If it’s a
> headline, a serif or display sans is fine.

The pixel-font CSS class set (`.pix-cherry`, etc.) disables font smoothing.
Apply it to every pixel-font run on the actual device — some browsers
ignore `-webkit-font-smoothing` and re-introduce AA.

### 2.3 No animation, no transitions, no live anything
Refreshes flash. Don’t plan for animation, don’t plan for motion. The
device should:
- Render a **static frame**.
- Update on a **timer** (every minute or two), or an **HA push** (e.g. when
  the washer finishes).
- Schedule **deeper full refreshes** (the whole-panel flash that clears
  ghosting) at quiet times — once an hour, on a schedule, or after every
  N partial updates.

The mockup looks live in the browser; on device, treat each render as a
**still poster** that is occasionally reprinted.

### 2.4 Information rhythm: a “lead story”
Most of the time, nothing in the house demands attention — climate is
normal, nobody’s home, no appliances running. We don’t want a wall of
status indicators in that case; we want the dashboard to look **calm**
(Editorial: “THE CALM EDITION — All quiet on the home front”;
Swiss: a giant outlined `00`).

When something *is* happening — sauna heating, laundry done — that single
fact gets dramatic typographic prominence. This is borrowed directly from
newspaper above-the-fold logic, and it is the design’s organizing
principle. **Implement the active-item pickers (`pickActive` /
`pickActiveSimple` in `editorial.jsx`/exposed on `window`) faithfully**;
they’re the heart of the layout.

### 2.5 Color is information, not decoration
With only six colors available, every red pixel on the panel must mean
something. The mockup uses color this way:

| Color | Meaning |
|---|---|
| **Red (`#c8261b`)** | Heating / hot / requires attention (sauna heating, washer-done, pool heating, garage open) |
| **Blue (`#1d4d8a`)** | Water / running cycles (washer running, dishwasher) |
| **Green (`#1f6b3a`)** | Presence (`● home`) |
| **Yellow (`#e7b800`)** | Sun / non-urgent advisory (windows open, sun glyph) |
| **Black** | All structural ink — text, rules, frames |

In B&W, all five collapse to black; differentiation is carried entirely by
position, weight, and rules. The two palettes are co-designed: every
component must look correct in both with no logic changes (only palette
swap).

---

## 3. Repository layout

```
Cambridge Dashboard.html        Entry point. Loads React + Babel + the two designs in a design canvas.
fonts.css                       @font-face declarations for Cherry / Tamzen / Spleen.
fonts/
  cherry/                       Cherry pixel font, multiple sizes/weights.
  tamzen/                       Tamzen pixel font.
  spleen/                       Spleen pixel font.
ha-data.js                      Loads lastState.json, exposes window.HA_READY (Promise<HAShape>).
lastState.json                  Sample HA snapshot for offline rendering.
editorial.jsx                   Direction A — magazine/newspaper. Exposes window.EditorialDashboard, window.E_PALETTE.
swiss.jsx                       Direction B — Swiss/modular. Exposes window.SwissDashboard, window.SW_PALETTE.
design-canvas.jsx               Dev scaffolding — pan/zoom canvas to compare the four artboards.
debug/                          Reference screenshots from prior iterations.
HANDOFF.md                      This document.
```

---

## 4. Data layer (`ha-data.js`)

`ha-data.js` reads `lastState.json` (a snapshot of the HA `/api/states`
response) and reshapes it into a clean object. **In production, replace the
file fetch with a live HA REST or WebSocket call**, but keep the output
shape identical so the renderer doesn’t need changes.

### 4.1 Output shape

```ts
type HAShape = {
  fetchedAt: Date;

  weather: {
    state: string;          // 'sunny' | 'partlycloudy' | 'cloudy' | 'rainy' | ...
    temperature: number;    // °F
    humidity: number;
    windSpeed: number;
    windBearing: number;
    pressure: number;       // inHg
    visibility: number;
  };

  // Per-floor instantaneous temps from real sensors (not thermostats).
  temps: { basement, first, second, third, outdoor: number };

  // The “primary” climate entities for the dashboard. radiantMain/Apt are
  // the Nest learning thermostats driving radiant zones; first/second/third/basement
  // are the floor-level set points.
  climates: {
    basement, first, second, third,
    radiantMain, radiantApt: ClimateEntity
  };

  // ALL climate entities (excluding sauna) — used for accurate “zones heating” counts.
  allClimates: ClimateEntity[];
  floorActivity: { first, second, third, basement, other: ClimateEntity[] };
  floorHeatCount(floorKey): number;
  floorAnyHeating(floorKey): boolean;

  people: { name: string, state: 'home' | 'not_home' | string }[];
  garage: { state: 'open' | 'closed' | string };
  openWindows: { id: string, name: string }[];

  sun: {
    state: 'above_horizon' | 'below_horizon';
    nextDawn, nextDusk, nextRising, nextSetting: ISOString;
  };

  pool: {
    operation: string; current: number; target: number; air: number;
    heating: boolean; pumpRunning: boolean;
    schedule: boolean; freezeProtect: boolean;
  } | null;

  sauna: {
    mode: 'off' | 'heat' | string;
    current: number; target: number; duration: number;
    heaters: number;        // 0–3 elements lit
    door: boolean;          // true == open
    light: boolean;
    roomTemp: number; roomHumidity: number;
  } | null;

  washer: {
    status: string;                      // 'power_off' | 'run' | 'spin' | ...
    operation: string; remaining: ISOString;
    lastNotification: { type: 'washing_is_complete' | string, at: ISOString } | null;
    powerOn: boolean; cycles: number; energyMonth: number;  // Wh
  };

  dishwasher: {
    state: string;        // 'run' | 'delayedstart' | 'pause' | 'actionrequired' | 'finished' | null
    program: string;      // 'dishcare_dishwasher_program_eco50' etc
    progress: number;     // 0–100
    finishTime: ISOString;
    door: 'closed' | 'open' | string;
    powerOn: boolean; connected: boolean;
  };
};

type ClimateEntity = {
  id?: string; name: string;
  mode: string;             // 'heat' | 'cool' | 'off' | 'auto' | ...
  current: number;
  target: number;
  action: 'heating' | 'idle' | 'cooling' | 'off' | string;  // hvac_action
};
```

### 4.2 Specific entity IDs hard‑wired today

Replace these with whatever you have in your install — keep the field
names the same, swap the entity IDs:

| Field | HA entity |
|---|---|
| `weather` | `data.weather_entity_id` (top-level pointer in lastState.json) |
| `pool.*` | `water_heater.53_55_raymond_pool` + sibling `binary_sensor.53_55_raymond_*` |
| `sauna.*` | `climate.saunum_leil` + sibling `sensor.saunum_leil_*` and `sensor.usl_environmental_*` |
| `washer.status` | `sensor.washer_current_status` |
| `washer.remaining` | `sensor.washer_remaining_time` |
| `washer.lastNotification` | `event.washer_notification` |
| `washer.cycles` | `sensor.washer_cycles` |
| `washer.energyMonth` | `sensor.washer_energy_this_month` |
| `dishwasher.state` | `sensor.dishwasher_operation_state` |
| `dishwasher.program` | `select.dishwasher_selected_program` |
| `dishwasher.progress` | `sensor.dishwasher_program_progress` |
| `dishwasher.finishTime` | `sensor.dishwasher_program_finish_time` |
| `temps.*` | `sensor.{floor}_temperature`, `sensor.weather_station_outdoor_temperature` |
| `climates.*` | `climate.first_floor` … `climate.basement`, `climate.nest_learning_thermostat_4th_gen[_3]` |
| `garage` | `cover.smart_garage_door_…` |
| `openWindows` | filter all `cover.*` excluding shade/blind/curtain/skylight/garage, state == open |
| `people` | all `person.*` |
| `sun.*` | `sun.sun` + `sensor.sun_next_*` |

### 4.3 Refresh strategy on device

```
Loop:
  Wait until next tick (60s).
  Pull /api/states (HTTP REST) OR last cached websocket state.
  Render to PNG with the renderer.
  If frame is bit-identical to the previous one → skip the panel update.
  If different → push to panel via partial refresh.
  Every 30 minutes (or after 30 partial refreshes) → full refresh to clear ghosting.
```

The renderer must be **deterministic** — same input ⇒ same PNG bytes —
because that’s how you cheaply skip redundant pushes.

---

## 5. Picking the active “lead story”

Both designs share a priority function. Reproduce it 1:1 — this is the
state machine that decides what gets the headline:

```js
function pickActive(ha, P /* palette */) {
  const out = [];

  // 1. Sauna heating — highest priority (physical safety, very hot)
  if (ha.sauna && (ha.sauna.mode === 'heat' || (ha.sauna.heaters||0) > 0))
    out.push({ kind: 'sauna', severity: 1, accent: P.red });

  // 2. Washer state
  const w = ha.washer;
  if (w?.status && !['power_off','end','initial','unavailable','unknown',null,''].includes(w.status)) {
    out.push({ kind: 'washer', severity: 2, accent: P.blue });           // running
  } else if (w?.lastNotification?.type === 'washing_is_complete') {
    const ageHrs = (Date.now() - new Date(w.lastNotification.at).getTime()) / 3600000;
    if (ageHrs < 6) out.push({ kind: 'washer-done', severity: 1, accent: P.red });  // unload-me window
  }

  // 3. Dishwasher running / needs attention
  const dw = ha.dishwasher;
  if (dw && ['run','delayedstart','pause','actionrequired','finished'].includes(dw.state)) {
    out.push({ kind: 'dishwasher', severity: dw.state === 'actionrequired' ? 1 : 3, accent: P.blue });
  }

  // 4. Pool heating
  if (ha.pool?.heating)
    out.push({ kind: 'pool', severity: 3, accent: P.red });

  return out.sort((a,b) => a.severity - b.severity);
}
```

The **top item** becomes the lead/hero. Everything else becomes a
secondary brief in Editorial, or is implicit in Swiss’s instrument grid.

When `pickActive(ha)` is empty, render the **calm/quiet state**: in
Editorial it’s “THE CALM EDITION”; in Swiss it’s the giant outlined `00`.

---

## 6. Direction A — Editorial (newspaper / magazine)

`editorial.jsx` exports `window.EditorialDashboard` and `window.E_PALETTE`.

### 6.1 Mental model
A small-circulation broadsheet, printed every minute. The flag (masthead)
contains the wall clock, the masthead `CAMBRIDGE`, the date, and the
outdoor edition badge. Below, three columns of editorial copy describe
the current state of the house.

### 6.2 Anatomy

```
┌───────────────────────────────────────────────────────────────┐
│  ── HAIRLINE ──                                                │
│   8:42      C  A  M  B  R  I  D  G  E       ☼  72°            │  ← MASTHEAD
│  am          MONDAY · MAY 4               PARTLY CLOUDY        │
│  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ │  ← thick + hairline (newspaper convention)
│                                                                 │
│  ◇ OUTSIDE ─── │   ★ THE CALM EDITION ★    │ ◇ THE HOUSE ──    │
│  Wind  6 mph N │                            │   Third      72°  │  ← LEFT RAIL · LEAD COL · RIGHT RAIL
│  Hum    44 %   │  All quiet on the          │   Second     71°  │
│  Press 30.12   │  home front.               │   First      70°  │
│  ────          │                            │   Basement   68°  │
│  ◇ SUN ──      │  ════════════════════════  │  ────             │
│   ↑ 5:42  ↓ 8:01│ Aall appliances idle…     │  ◇ HEARTH         │
│  ────          │                            │   ● MAIN  68°→70° │
│  ◇ AT HOME ──  │                            │  ────             │
│   Ed   ● home  │                            │  ◇ POOL · IDLE    │
│   …            │                            │   [thermometer]   │
│ ──────────────────────────────────────────────────────────────  │
│  ● ED HOME       “All the news that fits the house.”   ↻ 8:42  │  ← COLOPHON
└───────────────────────────────────────────────────────────────┘
```

### 6.3 Components (file map)

| Component | Role |
|---|---|
| `EditorialDashboard({ ha, palette })` | Top-level frame, 800×480, sets up the absolute-positioned masthead/body/colophon. |
| `Masthead` | The flag: time-left / wordmark-center / weather-right + thick + hairline rule pair under it. |
| `LeftRail` | Outside stats (wind/humidity/pressure/visibility), sun arc, people. |
| `RightRail` | Floor temps with heat counts, radiant rows, pool mini. |
| `LeadColumn` | Routes to one of `CalmLead` / `SaunaLead` / `WasherLead` / `WasherDoneLead` / `DishwasherLead` / `PoolLead`, each wrapping `StoryShell`. |
| `StoryShell` | Kicker (with diamond + accent), big serif headline, italic deck, drop-cap body, factstrip. **The reusable lead format.** |
| `FactStrip` | Horizontal grid of 3–4 cells: KICKER / value / sub. Top thick rule + bottom hairline. |
| `Brief` | Compact secondary-active row used under “Also Active.” |
| `SunArc` | SVG: dotted half-circle horizon line, sun position computed from `nextRising`/`nextSetting`. |
| `WeatherGlyph` | SVG icons for clear / partly cloudy / cloudy / rain / fallback. **Hand-built, 1.5px stroke** — never use icon fonts (they alias). |
| `Thermometer` / `VerticalThermometer` | 32-segment bar (or 12-segment vertical column). The “fill” segments are solid accent; “empty” segments are mostly white with a 1‑in‑4 dotted reference. Target is a 2px ink tick. |
| `Kicker`, `Hr`, `DoubleHr`, `DropCap`, `Diamond`, `RailStat`, `PeopleList`, `FloorList`, `RadiantRow`, `PoolMini`, `Colophon` | Atoms — names match their newspaper analogues. |

### 6.4 Type system (`TY` constant)

```js
serifHero    Source Serif 4, 700, -0.025em   // 22–50 px display
serifMed     Source Serif 4, 600, -0.005em   // 13–16 px subheads
serifLight   Source Serif 4, 400              // 13 px body
serifItalic  Source Serif 4, 400 italic       // decks, captions
serifItalicB Source Serif 4, 700 italic       // emphatic phrases inside heads
black        UnifrakturCook 700               // reserved (unused unless you want the Old English flag)
cherry/B     Cherry 13px pixel font           // medium pixel data
cherrySm/B   Cherry Small 10–11px pixel font  // small ALL-CAPS section labels
```

### 6.5 Editorial-specific rules
- **Drop cap on the lead body.** `<DropCap>A</DropCap>ll appliances idle…` —
  serif hero at ~36 px floated left, padding-right 6 px. This is the single
  biggest visual cue that this is editorial copy, not a UI panel.
- **Italic decks.** Every lead has a one-line italic deck under the
  headline (`serifItalic`, 14 px). Decks are descriptive, not declarative —
  they sound like a copy editor wrote them (“Cabin presently 138°, with
  37° left to climb.”).
- **Thick + hairline doubled rules** under the masthead and as
  `<DoubleHr>` separators. Two ink weights side-by-side reads as
  “authoritative print.”
- **Diamond ornaments** before kickers and as bullet markers on `Brief`
  rows. Use a real `transform: rotate(45deg)` square — not the `◆`
  character (which renders inconsistently).
- **No greys.** Where you’d normally fade a label, drop to italic + smaller
  size or keep it ink and let position do the work.
- **Colophon (footer)** is a one-line strip: presence on the left, a
  pull-quote in italic in the middle, status counters on the right. The
  pull-quote (“All the news that fits the house.”) is decorative —
  consider rotating from a small pool if you want personality, but never
  let it grow past one line.

---

## 7. Direction B — Swiss / Modular

`swiss.jsx` exports `window.SwissDashboard` and `window.SW_PALETTE`.

### 7.1 Mental model
Müller-Brockmann meets Crouwel: a 12-column grid, thick top/bottom rules,
ISO-style numbered section labels (`01 / TIME · LOCAL`), giant Helvetica
numerics for the live values, pixel fonts for ISO data readouts, and the
boldest cells inverted to solid color when they’re “hot.”

### 7.2 Anatomy

```
┌────────────────────────────────────────────────────────────────┐
│ ▓▓ CAMBRIDGE ▓▓│ HOME STATUS    MON, MAY 04, 2026 │● 1 ACTIVE│ ↻ 08:42 │  ← header strip (ink-on-ink wordmark cell)
├──────────────────────────────────────────────────┬─────────────┤
│ 00 / NOW · SAUNA HEATING                          │ 01/TIME·LOCAL│
│                                                   │             │
│ Climbing to 175°,                          138°  │   08:42     │
│ 37° to go.                              CABIN·NOW │ MON MAY 04  │
│ 2/3 elements · 60m cycle · room 73° 41%RH         ├─────────────┤
│ ▓▓▓▓▓▓▓▓▓▓░░░░░░░░░░░░░░░░░░░░░ TGT  → 175°       │ 02/OUTSIDE  │
│ 60°                  NOW 138°               175°  │   72°F      │
├───────────┬───────────────────────┬───────────────┴─────────────┤
│ 03/CLIMATE│ 04/POOL · IDLE        │ 06/OCCUPANCY                 │
│ 3F  ▆▆ 72°│  82°F → 84°            │  Ed     ● HOME              │
│ 2F  ▆▆ 71°│  AIR 64° · NO FREEZE   │  Sarah  ○ NOT_HOME           │
│ 1F  ▆▆ 70°├───────────────────────┤  GARAGE CLOSED  WINDOWS 0 OPEN│
│ BS  ▆▆ 68°│ 05/SAUNA · HEATING ▓▓ │  SUN · BELOW                 │
│ ── RADIANT│ 138°F → 175°  ELEM 2/3│  ↑ 5:42  ──  ↓ 8:01           │
│ ● MAIN 68→70                                                     │
├──────────┴───────────────────────┴────────────────────────────────┤
│ SRC·HA·KBOS │ ▲ 1 ITEM REQUIRES ATTENTION │ ZONES HEATING 4/12 │ ↻ 08:42 │
└─────────────────────────────────────────────────────────────────┘
```

### 7.3 Grid

- 12 columns × 2 body rows (170 px hero / remainder).
- Top header: 36 px, `gridTemplateColumns: '180px 1fr 200px 110px'`.
- Body left-7 / right-5 split for the hero row.
- Body bottom: cols 1‑4 (climate), 5‑8 (pool/sauna stack), 9‑12 (occupancy).
- Footer: 22 px, `120px 1fr 1fr 120px`.

### 7.4 Components

| Component | Role |
|---|---|
| `SwissDashboard` | Top-level frame, header / 12-col body / footer. |
| `HeroQuiet` | Calm state: tiny `00 / NOW · ALL CLEAR`, “Nothing running.” headline, giant outlined `00` numeral on the right. Outline via `WebkitTextStroke: 1.5px ink` + `color: transparent` — DO NOT use `text-shadow`, which doesn’t render cleanly to a 1‑bit raster. |
| `HeroActive({ item })` | Active state. Calls `describeActive()` to pick `eyebrow / headline / sub / big / bigLabel / bigSub / bar`. |
| `describeActive` | Switch by kind: sauna / washer / washer-done / dishwasher / pool-heating. Returns the props the hero renders. |
| `SegBar` | 36‑segment horizontal bar; same fill/empty rule as Editorial’s `Thermometer`. |
| `FloorRow` | Per-floor row: `[3F] ▆▆▆▆▆▆░░░░░ 72° H2` — label + bar relative to floor temp range + temp + heat-zone count. |
| `RadiantBlock`, `PersonRow`, `StatusChip`, `SunStrip`, `KvR`, `SectionLabel`, `SubLabel` | Atoms. |

### 7.5 Type system (`SW_TY`)

```js
display     Helvetica Neue / Inter / Arial, 700, -0.045em   // 18–84 px display digits
sans        same family, 500                                  // 13 px body
cherry/B    Cherry 13px                                       // numeric data labels
cherrySm/B  Cherry Small 10–11px                              // ALL the section labels and meta lines
tamzen/B    Tamzen 8x16                                       // available — currently unused, swap in if Cherry feels too narrow
```

### 7.6 Swiss-specific rules
- **Inverted cells when hot.** Pool and Sauna cells flip to solid red
  background with white type when `heating: true` (`pool.heating` or
  `sauna.mode === 'heat'`). In B&W they flip to solid black. This is the
  single biggest hierarchy lever in Swiss; it must read across the room.
- **Numbered sections.** Every cell is labeled with `NN / NAME · STATE`
  (`03 / CLIMATE`, `04 / POOL · IDLE`). Numbers are stable per-cell, not
  per-render. Treat them as part of the navigation grammar.
- **Letterspacing on small caps.** Pixel fonts get `letterSpacing: 0.18em`
  to `0.22em`. Tighten only when in the inverted strips where bg/fg
  contrast already does the work.
- **Outlined display digits** are reserved exclusively for the calm `00`.
  Don’t use them elsewhere — the moment you do, they stop reading as “the
  one big thing.”
- **Header wordmark** is a single ink-on-ink cell (`background: ink, color:
  bg`). It functions as a register mark for the whole layout — your eye
  finds it first, anchors, and scans right.

---

## 8. Color/palette swap mechanism

Each dashboard takes a `palette` prop with this shape:

```js
{ bg, ink, paper, red, blue, green, yellow, rule, soft, muted }
```

In **6-color**, these have their literal values. In **B&W**, every accent
is forced to `#000000` so the same JSX paints correctly without branching.
**Do not introduce `if (palette.red === '#000000')` checks in component
internals.** The only acceptable site for that check is at the boundary of
a “fill” (like the inverted Pool/Sauna cells in Swiss), where the color
*has* to differ from black to be a fill. The pattern there:

```js
background: pool.heating ? (P.red === '#000000' ? '#000' : P.red) : 'transparent'
```

That is the *only* branch of its kind. Keep it that way.

---

## 9. Rendering theory: getting from React to e‑ink

The mockup uses React because it’s the fastest way to author and iterate.
On device, you have several options. In rough order of practicality:

### 9.1 Server-side render to PNG, push to panel
1. Run a tiny Node service on a Pi (or in HA itself) that:
   - Pulls HA state.
   - Renders the React tree to HTML via `react-dom/server`.
   - Loads it in headless Chromium (Puppeteer/Playwright) at 800×480, 1×.
   - Snapshots a PNG.
   - **Quantizes to the panel’s 6-color palette** (or 1‑bit) using a
     fixed palette in `sharp` / ImageMagick (`-remap` against a 6-color
     palette PNG).
   - Pushes to panel.
2. This is what to ship. It preserves authoring fidelity and is robust.
3. Quantization is non‑negotiable: do **nearest-neighbor** to the panel
   palette. **Disable dithering for text.** You may optionally enable
   ordered (Bayer 8×8) dithering for any “grey” regions — but the design
   should have none. If you find yourself reaching for dither, remove the
   thing causing it instead.

### 9.2 Native draw on device (advanced)
Re-implement both directions in your panel SDK’s primitives (rects, lines,
text). Faster refresh, no Chromium dependency. More work, and you lose
serif fidelity unless you ship the TTFs. Recommend only if 9.1 proves too
slow for your hardware.

### 9.3 Direct iframe (proof-of-concept only)
Some panels ship with a thin web view. You *can* point it at the HTML
file and let it run. Don’t — refresh management, font loading races, and
quantization are all your problem and you’ll regret it.

### 9.4 Things to verify in your renderer
- **Fonts are embedded.** Headless Chromium without the TTFs will silently
  fall back to Times/Arial and the design dies. `fonts.css` must be
  available at the path the HTML expects.
- **Subpixel positioning is off.** Add `text-rendering: geometricPrecision`
  globally, and confirm by zooming a snapshot — if you see fractional-pixel
  glyphs, the PNG quantization will fuzz the strokes.
- **Image rendering uses `pixelated`** for any pixel-font runs.
- **No `box-shadow`, `filter`, `backdrop-filter`, `linear-gradient`,
  `opacity` < 1.** All of these introduce intermediate values that won’t
  survive the 6-color palette. Audit the source — the mockup uses
  `box-shadow` only on the device-frame chrome (which is *not* part of
  the rendered area) and uses `opacity: 0.18 / 0.5` only inside the
  segment bars to mark dotted reference ticks. If you can’t round those
  to 0/1 in your quantizer, replace them with explicit dotted strokes
  (`backgroundImage: repeating-linear-gradient(...)` is also a trap —
  use a real SVG dotted line).
- **Border widths.** `0.5px` and `0.75px` borders look great on a
  retina-display browser preview but disappear on an 800×480 raster.
  Audit every value < 1 px and round to 1 px on device. The mockup
  freely uses sub-pixel rules for browser fidelity; **before shipping,
  globally rewrite `0.5px → 1px` and `0.75px → 1px`** unless you’ve
  proved your renderer keeps them.

### 9.5 Color quantization recipe (for the 6-color panel)

Build a 6‑color palette PNG (single column of 6 pixels, one per native
color), then in `sharp`:

```js
await sharp(rendered)
  .resize(800, 480, { fit: 'cover', kernel: 'nearest' })
  .png({ palette: true, dither: 0 })
  .toColourspace('srgb')
  // remap to fixed palette
  .ensureAlpha()
  .pipe(/* … */)
```

Or shell out to ImageMagick:

```
convert in.png -dither None -remap palette6.png out.png
```

**Always `-dither None`.** The whole point of designing without greys is
that no dither is needed.

### 9.6 1‑bit (B&W) recipe

```
convert in.png -dither None -remap palette2.png out.png
# OR for a true threshold:
convert in.png -threshold 50% -monochrome out.png
```

Avoid Floyd–Steinberg here; the design is engineered to be naturally
1‑bit, and any error diffusion will buzz on type strokes.

---

## 10. Layout notes — pixel-perfect details

These are easy to miss and matter on the panel:

- **Edge gutters: 22 px** in Editorial; the Swiss layout butts content
  to the panel edge except inside cells (14–16 px inset). That difference
  is intentional — Editorial reads as a printed page (margins); Swiss
  reads as a dashboard (full bleed grid).
- **Masthead height: 70 px** in Editorial; **header: 36 px** in Swiss.
- **Body bottom inset: 28 px** in Editorial (room for colophon);
  **footer: 22 px** in Swiss.
- **Column widths in Editorial:** `160px 1fr 168px`. The center column is
  the only one that flexes; the rails are fixed. This is intentional
  rhythm.
- **In Swiss,** the `170px 1fr` row split for the body is a hard limit —
  the hero must not push down into the bottom row. If you change anything
  in the lead, verify it doesn’t scroll. Use `overflow: hidden`,
  `minHeight: 0`, and `textWrap: balance` to keep heads compact.
- **Sun arc width: 138 px**, height: 36 px in Editorial. Tick marks at
  the rise/set ends are 6 px tall, sit straddling the horizon line.
- **Segment counts:** 32 (Editorial Thermometer), 36 (Swiss SegBar), 12
  (Editorial VerticalThermometer). These are fixed and read as the
  design’s native “tick count.” Don’t parameterize them away.

---

## 11. Empty states, edge cases, and missing data

The renderer must never crash on missing entities. Sample data is
synthetic; production data will fight you.

| Situation | Behavior |
|---|---|
| `ha.weather` null | Header shows `0°` and an empty state label. **Show a small `?` glyph instead** in production, and log. |
| `ha.pool` null | Right rail in Editorial: omit the Pool block (don’t leave the kicker). Swiss: render the `04 / POOL · OFFLINE` cell as a hairline-only frame with `OFFLINE` in pixel font. |
| `ha.sauna` null | Same pattern. |
| `washer.remaining` is `'unknown'` | `fmtRelTime` and `fmtDuration` already return `null`. The `Brief` row shows `—`. Hero (Swiss) shows `—` for `big`. Acceptable. |
| Person’s state is something exotic (`zone.work`, etc.) | Currently rendered as that literal string lowercased. Decide: pass through, or map to `away`. |
| `dishwasher.progress` is null | Hide the bar; show `—%`. |
| Sun: it’s the polar night | Sun arc fraction clamps. Don’t worry about it. |
| HA unreachable | Renderer should keep last good frame and overlay a small `↯ STALE NN m` chip in the colophon/footer. **Implement this — silent staleness is worse than a wrong number.** |

---

## 12. Additions you’ll likely want, but should ask first

The current mockup deliberately omits these to stay calm. Don’t add them
without confirming with the owner:

- Calendar / next event.
- Energy/solar production widgets.
- Per-device fault states (filter dirty, freezer alarm).
- Doorbell/intercom screenshots.
- Weather forecast strip (today’s high/low + 3-day).

If you do add a forecast strip, the natural place is *under* the
masthead in Editorial (replacing the third hairline) or as a 13th
labeled cell in Swiss’s header bar.

---

## 13. Build / run instructions

For the mockup (this repo):
1. Serve the directory over any static server (the `fetch('lastState.json')`
   needs HTTP, not `file://`).
2. Open `Cambridge Dashboard.html`. The design canvas shows four
   artboards: Editorial 6-color, Editorial B&W, Swiss 6-color, Swiss B&W.

For implementing on device:
1. Stand up the Node renderer in §9.1.
2. Replace `ha-data.js`’s file fetch with a live HA REST call (or a
   websocket subscriber that maintains an in-memory state map) and
   re-emit the same `HAShape` object.
3. Wire `pickActive` and pass into either `EditorialDashboard` or
   `SwissDashboard` (you only need to ship one).
4. Snapshot, quantize (§9.5/§9.6), push.
5. Add the staleness chip from §11.

---

## 14. Decision register (for the implementer)

Things you will be tempted to change. Don’t, without good reason:

| Decision | Why |
|---|---|
| Pixel fonts for everything < 13 px | AA murders 11 px text on e‑ink |
| `muted: ink` (no greys) in both palettes | Panel can’t print greys cleanly |
| Active-item priority order: sauna → washer-done → washer → dishwasher → pool | Reflects physical urgency: sauna is hot+door+heaters, unloading is a mom-tax, pool is slow |
| Inverted Pool/Sauna cells in Swiss when heating | The single across-the-room visual; everything else is too quiet to see at 2 m |
| Drop cap on the calm-state body in Editorial | This is the move that separates editorial from “status panel” |
| 800×480 fixed canvas | The panel resolution. The browser scales it via `<DCArtboard>`; the device renders 1:1 |
| One direction shipped, not both | Two designs on one device just dilutes the language |

---

## 15. Open questions to resolve before shipping

1. **Which direction.** Editorial reads warmer, Swiss reads more
   instrumental. Both are finished — pick.
2. **Clock format.** Editorial uses 12-hour with am/pm. Swiss uses
   24-hour. If you mix directions for some reason, settle one.
3. **Quotes/aphorisms in Editorial’s colophon.** Static, rotating, or
   removed?
4. **Time-of-day variants.** A “night mode” isn’t a thing on e‑ink (no
   backlight), but you could change the calm-state copy by hour. Worth
   doing? Probably not for v1.
5. **Refresh cadence.** 60 s default; 30 s when an active item is
   present? Verify the panel can keep up without ghosting before
   committing.

---

End of handoff.
