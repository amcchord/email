# Cambridge E-Ink Dashboard — Handoff Bundle

Start here: **`HANDOFF.md`** — a complete implementation brief.

## What's in this bundle

| File / Folder | Purpose |
|---|---|
| `HANDOFF.md` | The full brief. Theory, data layer, both designs, e-ink rendering recipe. **Read this first.** |
| `Cambridge Dashboard.html` | Entry point. Loads React + Babel + both designs in a side-by-side design canvas. |
| `editorial.jsx` | Direction A — newspaper/magazine. ~850 lines. Exports `window.EditorialDashboard`, `window.E_PALETTE`. |
| `swiss.jsx` | Direction B — Swiss/modular grid. ~600 lines. Exports `window.SwissDashboard`, `window.SW_PALETTE`. |
| `design-canvas.jsx` | Dev scaffolding for comparing artboards. Not needed on device. |
| `ha-data.js` | Loads `lastState.json` and reshapes it into the `HAShape` consumed by both designs. **Replace the file fetch with a live HA call on device.** |
| `lastState.json` | Sample Home Assistant snapshot used as offline fixture. |
| `fonts.css` | `@font-face` declarations for the pixel fonts. |
| `fonts/` | TTFs for Cherry, Tamzen, Spleen pixel fonts (required — the design dies without them). |

## To run the mockup locally

The HTML uses `fetch('lastState.json')` so you need a real HTTP server (not `file://`):

```bash
cd handoff-bundle
python3 -m http.server 8000
# then open http://localhost:8000/Cambridge%20Dashboard.html
```

You'll see four artboards: Editorial 6-color, Editorial B&W, Swiss 6-color, Swiss B&W.

## To implement on device

See `HANDOFF.md` §9 (Rendering theory) and §13 (Build / run instructions).
The short version: render the React tree to PNG via headless Chromium,
quantize to the panel's native palette with `-dither None`, push to the panel.

## Targets

- 800×480 px, 7.3" e-ink
- Two color modes shipped from the same components: 6-color (K/W/R/G/B/Y) and pure B&W
- Pick **one** design direction to ship — both are finished
