# reTerminal Server Protocol — 7.3" Spectra-6 Reference (E1002)

**Audience:** anyone (human or LLM) building the server side of this project at
`https://www.mcchord.net/trmnl/reTerminal/device`.

**Scope:** this document is the byte-level reference for the canonical
7.3" Spectra-6 path (E1002): the JSON envelope, the request headers, the
4 bpp Spectra-6 BMP layout, and the conformance bar. It is *one of three*
docs that together define the server contract:

- **[`server-implementation-guide.md`](server-implementation-guide.md)** —
  start here if you're new. Behavioral overview: variants, MAC routing,
  cadence decisions, dev mode, error semantics, logging, sample
  interactions. Links back into this doc and `firmware-variants.md` for
  byte-level details.
- **This file (`server-protocol.md`)** — wire-level spec for the
  default 7.3" Spectra-6 path. Authoritative for the JSON schema and
  the 4 bpp 800×480 BMP byte layout.
- **[`firmware-variants.md`](firmware-variants.md)** — wire-level spec
  for the BW (E1001), Gray, and 13.3" Spectra-6 (E1004) BMP layouts.

**Authoritative scope:** this document is the contract between the
firmware and the server for the canonical Spectra-6 path. If something
here disagrees with code in the firmware, the firmware is the truth and
this document needs to be updated; if the firmware disagrees with this
document *in spirit*, the document is the truth and the firmware needs
to be updated.

---

## 1. Overview

A reTerminal device is a battery-powered ESP32-S3 with an e-paper
panel; the canonical example is the E1002 (7.3", 800×480, 6-color
Spectra 6). To preserve battery and panel life, the device is asleep
almost all of the time. On a schedule (and on a manual button press) it
wakes, joins Wi-Fi, asks the server what to do, optionally downloads a
new image, paints it, and goes back to sleep.

Other variants (E1001 BW 800×480, E1004 13.3" Spectra-6 1200×1600)
follow the same protocol shape; their schedule queries and BMP layouts
are documented in [`firmware-variants.md`](firmware-variants.md). The
[`server-implementation-guide.md`](server-implementation-guide.md)
covers all variants together from the server-implementer's
perspective.

Two endpoints satisfy the entire interaction:

```text
GET <base>/schedule.json     # cheap metadata check-in, ~1 KB JSON
GET <base>/image.bmp         # ~192 KB pre-dithered 4-bit BMP, only when changed
```

Where `<base>` is `https://www.mcchord.net/trmnl/reTerminal/device`. The
`schedule.json` response can advertise a different URL for the image (e.g.
to point at a CDN); the firmware will follow whatever URL the schedule
returns.

### Why two endpoints?

Most check-ins should not refresh the screen. A schedule check-in is cheap
(JSON, no compute, no panel cycle). A panel refresh costs ~15 seconds of
wall time, ~100 mA-s of battery, and one of the panel's finite refresh
cycles. We only want to pay that cost when the content actually changes,
so we let the firmware diff the schedule's image ETag against what it
already drew before deciding to fetch.

---

## 2. Endpoint reference


| Method | Path             | Purpose                                                                            |
| ------ | ---------------- | ---------------------------------------------------------------------------------- |
| GET    | `/schedule.json` | Device check-in. Returns next-checkin metadata + image pointer.                    |
| GET    | `/image.bmp`     | Returns the 4-bit Spectra-6 BMP. Path is whatever `schedule.image.url` advertises. |


Both endpoints **MUST** support `If-None-Match` and respond `304 Not Modified`
when the resource hasn't changed.

Both endpoints **MUST** be served over HTTPS with a publicly trusted
certificate. The firmware uses ESP32 Arduino's `WiFiClientSecure` and the
built-in `setCACertBundle()`, so any cert chain that browsers accept will
work.

---

## 3. Device -> server (request headers)

The device emits these headers on **every** request to **both** endpoints.
Servers should treat any missing or unparseable header as "unknown" and
still respond — a brand-new device must always be able to check in.


| Header              | Type / format                  | Example                 | Notes                                                                                                                             |
| ------------------- | ------------------------------ | ----------------------- | --------------------------------------------------------------------------------------------------------------------------------- |
| `User-Agent`        | string                         | `reTerminalE1002/0.1.0` | Always starts with `reTerminalE1002/`.                                                                                            |
| `X-Device-MAC`      | lowercase MAC, colon-separated | `aa:bb:cc:dd:ee:ff`     | Stable per device; drawn from `esp_read_mac(MAC_WIFI_STA)`.                                                                       |
| `X-FW-Version`      | semver-ish string              | `0.1.0`                 | Same value as the suffix in `User-Agent`.                                                                                         |
| `X-Wake-Reason`     | enum                           | `timer`                 | One of `timer`, `button`, `reset`, `first_boot`, `unknown`.                                                                       |
| `X-Boot-Count`      | uint32                         | `142`                   | Monotonically increasing. Persists across deep sleep via NVS.                                                                     |
| `X-Uptime-Sec`      | uint32                         | `3`                     | Seconds since this wake. Useful for diagnosing slow boots.                                                                        |
| `X-Battery-MV`      | uint16                         | `4180`                  | Raw battery voltage in millivolts (already accounts for the /2 divider).                                                          |
| `X-Battery-Pct`     | uint8 (0-100)                  | `95`                    | Firmware-side LiPo SoC estimate. Treat as fuzzy.                                                                                  |
| `X-RSSI-Dbm`        | int (negative)                 | `-52`                   | RSSI in dBm at the moment of check-in.                                                                                            |
| `X-Free-PSRAM`      | uint32                         | `8123456`               | Bytes of free PSRAM.                                                                                                              |
| `X-Last-Image-ETag` | quoted ETag (RFC 7232)         | `"abc123def"`           | The ETag of the image currently painted on the panel; `""` if none.                                                               |
| `If-None-Match`     | quoted ETag                    | `"abc123def"`           | On `/image.bmp`, mirrors `X-Last-Image-ETag`. On `/schedule.json`, mirrors the schedule's previous ETag if the firmware kept one. |
| `Accept`            | MIME type                      | `application/json`      | `application/json` on `/schedule.json`, `image/bmp` on `/image.bmp`.                                                              |


Header names are case-insensitive but the firmware emits them as shown.

### Example request to `/schedule.json`

```http
GET /trmnl/reTerminal/device/schedule.json HTTP/1.1
Host: www.mcchord.net
User-Agent: reTerminalE1002/0.1.0
Accept: application/json
X-Device-MAC: aa:bb:cc:dd:ee:ff
X-FW-Version: 0.1.0
X-Wake-Reason: timer
X-Boot-Count: 142
X-Uptime-Sec: 3
X-Battery-MV: 4180
X-Battery-Pct: 95
X-RSSI-Dbm: -52
X-Free-PSRAM: 8123456
X-Last-Image-ETag: "abc123def"
```

---

## 4. Server -> device: `schedule.json`

### 4.1 Schema (JSON Schema, draft 2020-12)

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "required": ["schema_version", "server_time_utc", "next_checkin_sec", "image"],
  "properties": {
    "schema_version":   { "type": "integer", "minimum": 1 },
    "server_time_utc":  { "type": "string", "format": "date-time" },
    "next_checkin_sec": { "type": "integer", "minimum": 30 },
    "next_checkin_utc": { "type": "string", "format": "date-time" },
    "image": {
      "type": "object",
      "required": ["url", "etag", "format"],
      "properties": {
        "url":    { "type": "string", "format": "uri" },
        "etag":   { "type": "string", "minLength": 1 },
        "format": { "type": "string", "enum": ["bmp4-spectra6-800x480"] },
        "bytes":  { "type": "integer", "minimum": 0 }
      }
    },
    "device_actions": {
      "type": "object",
      "properties": {
        "reboot":          { "type": "boolean", "default": false },
        "clear_screen":    { "type": "boolean", "default": false },
        "sleep_until_utc": { "type": ["string", "null"], "format": "date-time" },
        "log_level":       { "type": "string", "enum": ["debug", "info", "warn", "error"] }
      },
      "additionalProperties": false
    },
    "message": { "type": "string" }
  }
}
```

### 4.2 Field semantics

- `schema_version` (required, int):
  - Currently `1`. Firmware compares against `cfg::SCHEDULE_SCHEMA_VERSION` and
  refuses to act on responses with a higher major version, falling back to the
  default sleep interval. **Bump this only on breaking changes.** Adding
  optional fields is non-breaking.
- `server_time_utc` (required, RFC 3339 UTC):
  - Used by the device to set its software RTC. Always include the `Z`.
- `next_checkin_sec` (required, integer):
  - **Authoritative for sleep duration.** The server is the single source of
    truth for refresh cadence; the firmware honors whatever value is
    returned, subject only to a 30 s absolute sanity floor (runaway-loop
    guard in `schedule.cpp`, not panel protection).
  - Panel-life budgeting (E1001 ~1 min minimum, E1002 ~5 min, E1004
    ~15 min, etc.) is the server's responsibility. Return a value that's
    appropriate for the device's variant — every Spectra-6 panel refresh
    consumes one of the panel's finite cycles, and 13.3" Spectra-6 panels
    in particular take ~20 s of wall-clock per refresh.
  - For dev/test, the server may return small values (e.g. 60 s) for a
    specific device or behind a `?dev=1` query. The firmware will follow.
- `next_checkin_utc` (optional, RFC 3339 UTC):
  - Informational. Should equal `server_time_utc + next_checkin_sec`. Useful for
  debugging and for human-readable logs.
- `image.url` (required, https URL):
  - The exact URL the firmware will GET when it decides to refresh. Typically
  `https://www.mcchord.net/trmnl/reTerminal/device/image.bmp`. May point
  elsewhere (CDN, signed URL).
- `image.etag` (required, opaque string):
  - Identity of the current image. Firmware compares this against its stored
  last ETag; if they match, no fetch happens. The exact value is opaque —
  SHA-1 of the BMP body works, so does any monotonic version string.
  - **MUST** match the `ETag` HTTP header that `/image.bmp` returns.
- `image.format` (required):
  - The only value v1 firmware accepts is `"bmp4-spectra6-800x480"`. Any other
  value causes the firmware to skip the image fetch and try again next cycle.
- `image.bytes` (optional, int):
  - Expected `Content-Length` of the image body. If present and the actual
  response is wildly different, firmware logs and aborts the render.
- `device_actions` (optional, object):
  - All fields optional; missing field == default behavior.
  - `reboot` (bool): firmware does `ESP.restart()` after queuing sleep. Useful
  for forcing a clean boot remotely.
  - `clear_screen` (bool): firmware paints the panel pure white **instead of**
  fetching the image, then sleeps. Useful before long idle periods to
  prevent ghosting.
  - `sleep_until_utc` (string|null): if set, firmware sleeps until that UTC
    instant **instead of** using `next_checkin_sec`. Subject to the same
    30 s absolute sanity floor against `server_time_utc`.
  - `log_level` (enum): persisted in NVS; controls Serial1 verbosity.
- `message` (optional, string): human-readable note. Firmware logs it; never
shown on the panel.

### 4.3 Example response

```http
HTTP/1.1 200 OK
Content-Type: application/json; charset=utf-8
ETag: "sched-20260428-140200"
Cache-Control: no-cache
```

```json
{
  "schema_version": 1,
  "server_time_utc": "2026-04-28T14:02:00Z",
  "next_checkin_sec": 900,
  "next_checkin_utc": "2026-04-28T14:17:00Z",
  "image": {
    "url": "https://www.mcchord.net/trmnl/reTerminal/device/image.bmp",
    "etag": "img-9f3a2c1e",
    "format": "bmp4-spectra6-800x480",
    "bytes": 192118
  },
  "device_actions": {
    "reboot": false,
    "clear_screen": false,
    "sleep_until_utc": null,
    "log_level": "info"
  },
  "message": "All systems normal"
}
```

### 4.4 Action ordering (firmware-side)

The firmware applies the schedule in this order:

1. Validate `schema_version`. If unsupported, log + use defaults + sleep.
2. Update software RTC from `server_time_utc`.
3. Persist `log_level`, `next_checkin_sec`.
4. If `device_actions.clear_screen` is true: paint white, **skip image fetch**,
  go to step 7.
5. If `image.etag != stored_last_etag`: GET `image.url`, parse, render, store
  the new ETag.
6. Otherwise: no panel refresh.
7. If `device_actions.sleep_until_utc` is set: schedule deep-sleep wake for
   that instant (subject to a 30 s absolute sanity floor from now).
   Else: schedule deep-sleep wake for `next_checkin_sec` (subject to the
   same 30 s sanity floor).
8. If `device_actions.reboot` is true: `ESP.restart()`. Else: deep sleep.

`reboot` is processed last so the device still gets through the rest of the
flow (and into a known sleep config) before resetting.

### 4.5 Per-device images (MAC-based routing)

The firmware sends `X-Device-MAC: aa:bb:cc:dd:ee:ff` (lowercase, colon-separated)
on every `schedule.json` and `image.bmp` request. The MAC is read directly
from eFuse via `esp_read_mac(MAC_WIFI_STA)` and is stable for the life of the
device.

The server may key its render off this header to return per-device images.
Two equivalent server-side strategies, both supported on the firmware side
without any code changes:

1. **Per-device URL.** Return a unique `image.url` in `schedule.json`
   keyed on the MAC (e.g. `https://.../images/aa-bb-cc-dd-ee-ff.bmp`,
   or a signed CDN URL). The firmware fetches whatever URL the schedule
   advertises, so this just works.
2. **Shared URL, per-device ETag.** Keep a single `image.url` (e.g.
   `https://.../image.bmp`) and vary the ETag and body per device by
   inspecting `X-Device-MAC` server-side. Firmware compares the schedule's
   `image.etag` against its own stored ETag, so a different ETag for the
   same URL will cause the device to fetch the new bytes.

Either strategy benefits from honoring the firmware's `If-None-Match`
header (the firmware echoes its last ETag back on every fetch) so an
unchanged image returns `304 Not Modified` and saves the device the
~192 KB / ~960 KB image fetch.

The server should also tolerate `X-Device-MAC` being missing (treat as
"unknown"), the same as every other `X-*` header.

### 4.6 Other variants (BW, Gray, 13.3" Spectra-6)

This document is the canonical contract for the 7.3" Spectra-6 path
(default schedule URL, `bmp4-spectra6-800x480`). Other firmware builds
hit the same `schedule.json` endpoint with a `?variant=...` query and
expect a different `image.format` enum + BMP layout. See
[`firmware-variants.md`](firmware-variants.md) for the BW, Gray, and
13.3" Spectra-6 (E1004) byte-level specs.

---

## 5. Server -> device: `image.bmp`

The device expects an uncompressed Microsoft Windows-style **4-bit indexed
BMP** matching the layout below exactly.

### 5.1 File layout (byte-level)


| Offset | Size   | Field           | Required value                                                                        |
| ------ | ------ | --------------- | ------------------------------------------------------------------------------------- |
| 0      | 2      | Magic           | `0x42 0x4D` (`"BM"`)                                                                  |
| 2      | 4      | bfSize          | total file size, little-endian                                                        |
| 6      | 4      | bfReserved      | `0x00000000`                                                                          |
| 10     | 4      | bfOffBits       | offset to pixel data, typically `118`                                                 |
| 14     | 4      | biSize          | `40` (BITMAPINFOHEADER)                                                               |
| 18     | 4      | biWidth         | `800`                                                                                 |
| 22     | 4      | biHeight        | `480` (positive: bottom-up rows). `-480` (top-down) is also accepted by the firmware. |
| 26     | 2      | biPlanes        | `1`                                                                                   |
| 28     | 2      | biBitCount      | `4`                                                                                   |
| 30     | 4      | biCompression   | `0` (BI_RGB; **no compression**)                                                      |
| 34     | 4      | biSizeImage     | `192000` or `0`                                                                       |
| 38     | 4      | biXPelsPerMeter | any (recommended `2835`)                                                              |
| 42     | 4      | biYPelsPerMeter | any (recommended `2835`)                                                              |
| 46     | 4      | biClrUsed       | `6` or `16`                                                                           |
| 50     | 4      | biClrImportant  | `6` or `0`                                                                            |
| 54     | 64     | RGBQUAD palette | 16 entries, see 5.2                                                                   |
| 118    | 192000 | pixel data      | 480 rows of 400 bytes (4 bpp packed)                                                  |


Total file size: **192,118 bytes**.

### 5.2 Palette (mandatory ordering)

The palette is 16 `RGBQUAD` entries (B, G, R, reserved=0). The first 6
entries **MUST** be exactly:


| Index | Color  | RGB               | Bytes (B G R 0) |
| ----- | ------ | ----------------- | --------------- |
| 0     | Black  | `( 0, 0, 0)`      | `00 00 00 00`   |
| 1     | White  | `(255, 255, 255)` | `FF FF FF 00`   |
| 2     | Green  | `( 0, 255, 0)`    | `00 FF 00 00`   |
| 3     | Blue   | `( 0, 0, 255)`    | `FF 00 00 00`   |
| 4     | Red    | `(255, 0, 0)`     | `00 00 FF 00`   |
| 5     | Yellow | `(255, 255, 0)`   | `00 FF FF 00`   |


Indices 6-15 are unused; recommended to fill them with the white entry to
keep image viewers happy. Pixels with palette index >= 6 are treated as
white by the firmware.

### 5.3 Pixel packing

- 4 bits per pixel, two pixels per byte, **high nibble = left pixel**.
- Row stride: `(800 * 4 + 31) / 32 * 4 = 400` bytes (already 4-byte aligned;
no row padding needed).
- Default row order is bottom-up (positive `biHeight`). Top-down rows
(negative `biHeight`) are also accepted by the firmware.

### 5.4 Required response headers

```http
HTTP/1.1 200 OK
Content-Type: image/bmp
Content-Length: 192118
ETag: "img-9f3a2c1e"
Cache-Control: no-cache
```

`ETag` **MUST** match `schedule.image.etag`.

### 5.5 Dithering

The panel only displays 6 colors. The server is responsible for converting
arbitrary input art to the 6-color palette. The reference implementation is
`[tools/png_to_e6_bmp.py](../tools/png_to_e6_bmp.py)` — it uses Pillow's
Floyd-Steinberg dither against this exact palette and emits a byte-level
identical BMP. The server should match that implementation's output for the
same input image.

If you build your own dithering path, validate it by:

1. Running the reference tool on a sample PNG.
2. Running your tool on the same PNG.
3. `cmp` the resulting BMPs. They should be byte-for-byte identical.

---

## 6. Error semantics

### 6.1 HTTP status codes the firmware understands


| Code   | Endpoint         | Firmware behavior                                                      |
| ------ | ---------------- | ---------------------------------------------------------------------- |
| 200    | `/schedule.json` | Parse JSON, act on it.                                                 |
| 200    | `/image.bmp`     | Parse BMP, render.                                                     |
| 304    | `/schedule.json` | Use cached schedule fields if any; otherwise treat as transient error. |
| 304    | `/image.bmp`     | Skip render; keep currently displayed image. Sleep normally.           |
| 4xx    | either           | Log, sleep `ERROR_RETRY_SEC` (5 min), retry next cycle.                |
| 5xx    | either           | Log, sleep `ERROR_RETRY_SEC` (5 min), retry next cycle.                |
| (none) | either           | TLS / DNS / TCP failure: same as 5xx.                                  |


The firmware **never** treats a 4xx/5xx as a reason to stop trying. There is
no panic mode; the device just keeps checking in.

### 6.2 Server-side validation hints

- Don't 4xx on missing `X-`* headers; treat them as "unknown".
- Don't 401/403 the device unless you've decided to add a shared secret
(not in v1). If you do, return the response in the spec's shape so the
firmware can still parse `next_checkin_sec` from it.
- Aggressive rate limiting will starve the device. The firmware respects
`next_checkin_sec`, so just return a longer interval if you want it to
back off; don't 429.

---

## 7. Sample interactions

### 7.1 Normal happy path (image unchanged)

```http
> GET /trmnl/reTerminal/device/schedule.json HTTP/1.1
> X-Last-Image-ETag: "img-9f3a2c1e"
< HTTP/1.1 200 OK
< Content-Type: application/json
< {"schema_version":1,"server_time_utc":"...","next_checkin_sec":900,
<  "image":{"url":"https://www.mcchord.net/.../image.bmp",
<           "etag":"img-9f3a2c1e","format":"bmp4-spectra6-800x480"}, ... }
```

Firmware notices `etag` matches its stored last ETag and goes straight to
sleep without ever requesting `image.bmp`.

### 7.2 New image available

```http
> GET /trmnl/reTerminal/device/schedule.json HTTP/1.1
> X-Last-Image-ETag: "img-9f3a2c1e"
< HTTP/1.1 200 OK
< {"...","image":{"...","etag":"img-aa7b00f1","format":"bmp4-spectra6-800x480"}}

> GET /trmnl/reTerminal/device/image.bmp HTTP/1.1
> If-None-Match: "img-9f3a2c1e"
< HTTP/1.1 200 OK
< Content-Type: image/bmp
< Content-Length: 192118
< ETag: "img-aa7b00f1"
< (192,118 bytes of BMP)
```

### 7.3 Race: server changed image between schedule and image fetch

If the schedule said `etag = X` but by the time the device requests
`image.bmp` the server has a newer image `Y`, the server has two correct
options:

- Return `200` with `ETag: "Y"` and the body of `Y`. The firmware will
store `Y` and render it. Fine.
- Return `304` (the server has decided the device's `If-None-Match: "X"`
matches what it considers current). Firmware skips render. The next
schedule check-in will advertise `Y` and the device will catch up then.

### 7.4 Forced clear screen

```json
{
  "schema_version": 1,
  "server_time_utc": "2026-04-28T22:00:00Z",
  "next_checkin_sec": 28800,
  "image": { "url": "...", "etag": "...", "format": "bmp4-spectra6-800x480" },
  "device_actions": { "clear_screen": true },
  "message": "Going dark for the night."
}
```

Firmware ignores the image, paints white, sleeps 8 hours.

---

## 8. Conformance checklist

A correct server-side implementation of this protocol satisfies every item
below. Anything that fails should block release.

### Schedule endpoint

- `GET /schedule.json` returns 200 + valid JSON matching the schema in 4.1.
- `schema_version` is `1`.
- `server_time_utc` is in RFC 3339 UTC form (ends in `Z`).
- `next_checkin_sec` is set to a value appropriate for the device's panel
  variant (typically 60 s for E1001, 300 s for E1002, 900 s for E1004 in
  normal operation). Firmware honors any value >= 30 s as-is.
- `image.format` is exactly `"bmp4-spectra6-800x480"`.
- `image.etag` matches the `ETag` returned by `/image.bmp`.
- `image.url` resolves to an HTTPS URL serving the matching BMP.
- Response has `Content-Type: application/json`.
- Response has its own `ETag` header (not strictly required, but helpful).
- Server tolerates missing `X-*` request headers without 4xx.

### Image endpoint

- `GET /image.bmp` returns 200 + 192,118-byte body in normal operation.
- First two bytes are `'B' 'M'` (`0x42 0x4D`).
- `biWidth = 800`, `biHeight = 480` (or `-480`), `biBitCount = 4`,
`biCompression = 0`.
- Palette indices 0..5 match table 5.2 exactly (byte-level).
- Pixel data is 192,000 bytes; 400 bytes/row x 480 rows.
- Response `ETag` matches the `image.etag` field that the most recent
schedule advertised.
- `If-None-Match` with the current `ETag` returns `304`.
- Output of the image generator on a fixed sample PNG matches
`tools/png_to_e6_bmp.py` byte-for-byte.

### Operational

- HTTPS with a publicly trusted certificate.
- Stable response times under ~5s (firmware HTTP read timeout is 20s
but anything > 5s eats battery for no reason).
- No 401/403/429 in v1 (add auth in a coordinated firmware-side change).

---

## 8.1 Partial refresh (informational; no protocol impact)

Starting with firmware 0.1.x, the device opportunistically performs
partial-window refreshes against the GDEP073E01's `PTLW` (`0x83`)
command instead of always full-refreshing. The decision is made entirely
**client-side** by diffing the freshly-fetched BMP against a flash-cached
copy of the previous render. The wire protocol is unchanged: the server
still returns one full BMP body per ETag and does not need to send dirty
rectangles.

What this means for the server:

- No new fields, headers, or endpoints. Implementations that satisfy the
  conformance checklist in section 8 work without modification.
- A change to a tiny region of the image (e.g. a clock minute) will still
  result in a full-image fetch, but the device may visually flash only a
  small bbox. This is invisible to the server.
- Partial refreshes accumulate ghosting. The firmware forces a full
  refresh on its own schedule (currently every hour, plus whenever the
  dirty area exceeds 30% of the panel). The server has no role in
  triggering this.
- The existing `device_actions.clear_screen` action still works; the
  firmware drops its pixel cache when handling it so the next image fetch
  full-refreshes.

If a future revision needs server-side dirty rectangles (for example to
avoid downloading 192 KB to repaint a clock minute), that will be a
breaking schema change behind a higher `schema_version`.

## 9. Out of scope for v1

The following are explicitly *not* in this protocol yet. Don't preemptively
add support for them; they need a coordinated firmware-side change first.

- Authentication / shared-secret headers.
- OTA firmware updates.
- Server-initiated push (the device is asleep; it can't be pushed to).
- Multiple images / playlists in a single response (use one `image` object).
- Plug-in panel formats other than 4-bit Spectra 6 800x480.
- Two-way data (sensor uploads, etc.).

---

## 10. Quick reference (copy-paste)

```text
Endpoints:
  GET <base>/schedule.json    -> JSON, see 4.1
  GET <base>/image.bmp        -> 4-bit BMP, see 5.1

Required JSON fields:
  schema_version: 1
  server_time_utc: RFC 3339 UTC
  next_checkin_sec: server-chosen, >= 30 (firmware sanity floor)
  image: { url, etag, format="bmp4-spectra6-800x480" }

Image:
  800x480, 4 bpp indexed, BI_RGB, 192,118 bytes total
  Palette[0..5] = Black, White, Green, Blue, Red, Yellow
  ETag must match schedule.image.etag

Headers from device (informational, never required):
  User-Agent, X-Device-MAC, X-FW-Version, X-Wake-Reason,
  X-Boot-Count, X-Uptime-Sec, X-Battery-MV, X-Battery-Pct,
  X-RSSI-Dbm, X-Free-PSRAM, X-Last-Image-ETag, If-None-Match
```

