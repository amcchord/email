# reTerminal Server — Implementation Guide

**Audience:** anyone (human or LLM) building the server side of this
project at `https://www.mcchord.net/trmnl/reTerminal/device`.

**Scope:** this document is the *behavioral* overview. It explains what
a reTerminal device does on each wake, what the server is responsible
for, and how to make sensible decisions about cadence, error handling,
per-device routing, and dev-vs-prod modes. It deliberately does **not**
restate the byte-level wire spec — that lives in two sibling documents:

- **This file (`server-implementation-guide.md`)** — start here.
  Behavioral overview: variants, MAC routing, cadence, dev mode,
  error semantics, logging, worked examples. Links into the wire-level
  docs for the bytes.
- [`server-protocol.md`](server-protocol.md) — wire-level spec for the
  canonical 7.3" Spectra-6 path (E1002): JSON schema, request headers,
  4 bpp 800×480 BMP byte layout.
- [`firmware-variants.md`](firmware-variants.md) — wire-level spec for
  the BW (E1001), Gray, and 13.3" Spectra-6 (E1004) BMP layouts, plus
  the `?variant=` schedule-URL conventions.

If you only have time for one document and you're reading bytes off the
wire, jump straight to `server-protocol.md`. If you're trying to decide
"what should my server *do*?", read this one first.

---

## 1. The 30-second mental model

A reTerminal is a battery-powered ESP32-S3 with an e-paper panel. It is
asleep almost all of the time. On a schedule (and on a manual button
press) it wakes, joins Wi-Fi, asks the server what to do, optionally
downloads a new image, paints the panel, and goes back to sleep.

Every wake fits this shape:

```
sleep ──► wake ──► Wi-Fi up ──► GET /schedule.json
                                   │
                                   ├─ etag matches stored?  ──► sleep
                                   │
                                   └─ etag changed
                                         │
                                         ▼
                                   GET <image.url>
                                         │
                                         ▼
                                   render panel ──► sleep
```

Two things follow from that:

1. **The server decides cadence.** The firmware sleeps for whatever
   `next_checkin_sec` you return, with only a 30 s absolute sanity floor
   (so a buggy `next_checkin_sec: 0` doesn't drain the battery in
   minutes). Panel-life budgeting per variant is *your* responsibility.
2. **The server decides what counts as "new".** The firmware compares the
   `image.etag` you advertise in `schedule.json` against the ETag of the
   image currently painted on the panel. If they match, the firmware
   doesn't even fetch `image.bmp`. The cheapest possible check-in is one
   ~1 KB JSON request and zero panel work.

Everything else in this document is consequences of those two facts.

---

## 2. Variants and which URL the device hits

The same server publishes the same dashboard in four e-paper-friendly
formats so the same scheduling logic can drive every reTerminal model.
The firmware build picks which `?variant=` query it appends to the
configured `schedule_url`. From the server's perspective:

| Variant         | Panel                | `?variant=` query           | `image.format` enum         | BMP size   |
| --------------- | -------------------- | --------------------------- | --------------------------- | ---------- |
| Spectra-6 7.3"  | E1002 (default build)| *(none)*                    | `bmp4-spectra6-800x480`     | 192,118 B  |
| Spectra-6 13.3" | E1004                | `variant=spectra6_1200x1600`| `bmp4-spectra6-1200x1600`   | 960,118 B  |
| BW              | E1001                | `variant=bw`                | `bmp1-bw-800x480`           | 48,062 B   |
| Gray            | (no shipping device) | `variant=gray`              | `bmp4-gray16-800x480`       | 192,118 B  |

The firmware doesn't know about `image.bmp` paths directly — it always
fetches whatever `schedule.image.url` points at. So the server is free to
use any URL convention it likes for the actual BMPs (per-variant paths,
per-device CDN URLs, signed URLs). The convention this repo's mock
server uses is documented in
[`firmware-variants.md` § 1](firmware-variants.md#1-endpoints).

For the byte-level layout of each BMP variant, see:

- 7.3" Spectra-6 (canonical): [`server-protocol.md` § 5](server-protocol.md#5-server--device-imagebmp).
- BW, Gray, 13.3" Spectra-6: [`firmware-variants.md` § 4](firmware-variants.md#4-bmp-byte-layouts).

If a firmware build asks for one variant and gets back a `schedule.json`
whose `image.format` doesn't match its `cfg::EXPECTED_IMAGE_FORMAT`, the
firmware logs the rejection and sleeps until the next cycle. So
`schedule.image.format` is the contract; the URL the BMP comes from is
not.

---

## 3. The check-in headers (a.k.a. free telemetry)

On **every** request to **both** endpoints the firmware emits a fixed
set of `X-*` headers populated with whatever it knows about itself at
the moment of the wake. The full table with byte-level types is in
[`server-protocol.md` § 3](server-protocol.md#3-device---server-request-headers);
the short version, in priority order for "what's worth keying server
behavior off":

- `X-Device-MAC` — stable per device, drawn from eFuse, lowercase
  colon-separated. Use this to identify which device is checking in.
- `X-Wake-Reason` — `timer | button | reset | first_boot | unknown`.
  `button` means a human pressed the green key on the device; `timer` is
  the routine schedule wake.
- `X-Last-Image-ETag` — the ETag the firmware *thinks* is currently on
  the panel. Useful as a sanity check against your own state.
- `X-Battery-MV` / `X-Battery-Pct` — millivolts of battery, plus a
  fuzzy LiPo SoC estimate (linear 3.30 V → 0 %, 4.20 V → 100 %).
- `X-RSSI-Dbm` — RSSI at the moment of check-in.
- `X-Boot-Count` / `X-Uptime-Sec` / `X-Free-PSRAM` — diagnostic.
- `User-Agent` / `X-FW-Version` — firmware build.

**Hard rule:** a brand-new device must always be able to check in.
Treat any missing or unparseable `X-*` header as "unknown" and serve a
schedule anyway; **do not** 4xx or 401 the device for missing
metadata. Aggressive header validation is a footgun: it locks out
exactly the devices you most want to recover (the ones with bad
clocks, low batteries, or reset NVS).

The mock server in [`tools/serve_test_image.py`](../tools/serve_test_image.py)
prints every `X-*` header it sees on every request, which is the
easiest way to confirm the firmware is actually sending the metadata
you expect.

---

## 4. Per-device images (MAC-based routing)

Most deployments will want different content on different devices
(e.g. one in the kitchen showing the family calendar, one in the
office showing on-call rotations). The firmware sends `X-Device-MAC`
on every request, so the server has two equivalent strategies for
returning per-device content. **Both work without any firmware
changes.**

### 4.1 Strategy A — per-device URL (recommended for CDN-backed setups)

`schedule.json` returns a different `image.url` per MAC, e.g.:

```json
{
  "image": {
    "url":    "https://www.mcchord.net/trmnl/reTerminal/images/aa-bb-cc-dd-ee-ff.bmp",
    "etag":   "img-aa-bb-cc-dd-ee-ff-9f3a2c1e",
    "format": "bmp4-spectra6-800x480"
  }
}
```

The firmware fetches whatever URL the schedule advertises, so this is
fully transparent — it doesn't even need to know it's getting a
per-device image. Works great with signed CDN URLs or pre-rendered
files on disk.

### 4.2 Strategy B — shared URL, per-device ETag + body

`schedule.json` always returns the same `image.url` (e.g.
`/image.bmp`), and the server inspects `X-Device-MAC` on the
`/image.bmp` request to decide what bytes (and what `ETag`) to return.
The firmware compares ETags, not URLs, so a different ETag for the
same URL still triggers a fetch.

### 4.3 Either way, honor `If-None-Match`

The firmware echoes its last-seen `ETag` back via `If-None-Match` on
the image fetch. If the value still matches what the server considers
current for this device, return `304 Not Modified` (no body) and save
the device a ~192 KB / ~960 KB transfer. This is by far the most
expensive thing a check-in can do over Wi-Fi, so the savings are
real (and battery-positive).

The same applies to `schedule.json` — return `304` if the schedule
itself hasn't changed since the firmware's last fetch — but the
schedule is so cheap (~1 KB) that this is a nice-to-have rather than
a must.

### 4.4 Tolerate missing MAC

Same rule as every `X-*` header: if `X-Device-MAC` isn't there or
doesn't parse, fall back to a sensible default schedule + image. A
brand-new device's first request must succeed.

---

## 5. Cadence — the most important number you return

`next_checkin_sec` is the single most important thing your server does.
It directly trades off:

- **Freshness** — how long until the device sees a new image after you
  publish it.
- **Battery life** — every wake is ~3 s of full-power radio + maybe
  ~15 s of panel refresh. Five-minute wakes drain a 1500 mAh LiPo in
  weeks; one-hour wakes last months.
- **Panel life** — Spectra-6 panels have a finite number of refresh
  cycles. Refreshing every minute will visibly degrade a Spectra-6
  panel within a year. The BW UC8179 panel is much more tolerant.

The firmware honors whatever value you return as-is, subject only to a
30 s absolute sanity floor (a runaway-loop guard in
[`src/schedule.cpp`](../src/schedule.cpp), **not** panel
protection). So **the server is the single source of truth for refresh
cadence**, including the panel-life budget.

### 5.1 Recommended baselines

| Variant         | Suggested `next_checkin_sec` | Rationale                               |
| --------------- | ---------------------------- | --------------------------------------- |
| E1001 (BW)      | `60`                         | UC8179 fast partial is ~450 ms, gentle. |
| E1002 (Spectra-6 7.3") | `300` (5 min)         | Spectra-6 full refresh ~15 s, finite cycles. |
| E1004 (Spectra-6 13.3")| `900` (15 min)        | Same panel chemistry, ~20 s per refresh. |

These are *defaults*; the server is encouraged to vary them
contextually:

- **Quiet hours** — return a longer `next_checkin_sec` (or use
  `device_actions.sleep_until_utc`) overnight so the panel doesn't
  refresh while everyone's asleep.
- **Live event** — return a shorter `next_checkin_sec` for the next few
  hours when content is genuinely changing fast (a sports game, a
  release window).
- **Idle content** — if the same image is going to be on the panel for
  a week, you can advertise `next_checkin_sec: 86400` (one day) and the
  device will simply sleep through.

### 5.2 Don't 429

Aggressive rate limiting will starve the device into never updating.
The firmware respects `next_checkin_sec`, so the right way to slow
devices down is to return a longer interval — not to refuse the
request. See [`server-protocol.md` § 6.2](server-protocol.md#62-server-side-validation-hints).

### 5.3 Sleep-until vs. sleep-for

`device_actions.sleep_until_utc` is an alternative to
`next_checkin_sec`. When set, the firmware computes
`(sleep_until_utc - server_time_utc)` (both in UTC) and sleeps that
long instead of using `next_checkin_sec`. It's still subject to the
30 s sanity floor.

Use `sleep_until_utc` for absolute schedules ("wake at 06:00 UTC every
day") where computing the delta on the server is clumsy. Use
`next_checkin_sec` for everything else; it's simpler and doesn't depend
on the device's clock having any particular skew.

---

## 6. Dev mode

There's no formal "dev mode" header. The conventions this repo
documents are entirely server-side; pick whichever fits your
deployment:

- **`?dev=1` query on the schedule URL.** If your server sees it,
  short-circuit cadence policy and return e.g. `next_checkin_sec: 60`
  regardless of the variant's normal panel budget. The firmware just
  follows the shorter interval.
- **Per-MAC overrides.** If a particular MAC is "the dev unit on my
  desk", return the dev cadence + a freshly-rendered image for it
  unconditionally, and leave everyone else on the production
  schedule.
- **Per-variant overrides.** A request with `?variant=bw` is almost
  certainly the BW dev unit (E1001s are uncommon in the field); a
  request with `?variant=spectra6_1200x1600` is almost certainly an
  E1004 bring-up unit. Both are reasonable triggers for a dev-mode
  cadence.

The firmware needs no changes to support any of these; just point a
firmware build's `schedule_url` (in `data/config.json`, see the
[README](../README.md#configure-the-device-wifi--server-url)) at the
dev URL with whatever query param you've wired up server-side.

The local mock server in
[`tools/serve_test_image.py`](../tools/serve_test_image.py) takes the
analogous knobs as CLI flags rather than query parameters
(`--refresh-sec`, `--reboot`, `--clear-screen`, `--sleep-until-utc`,
`--log-level`, `--message`), since you're typically the only client
hitting it.

---

## 7. Error semantics — what the device does when things go wrong

The full table is in
[`server-protocol.md` § 6.1](server-protocol.md#61-http-status-codes-the-firmware-understands).
Behaviorally:

- **200** — happy path; act on the response.
- **304** — no change since `If-None-Match`; firmware skips the panel
  refresh (or trusts cached schedule fields).
- **4xx / 5xx / TLS / DNS / TCP failure** — firmware logs, sleeps for
  `cfg::ERROR_RETRY_SEC` (currently 5 minutes), and tries again on the
  next wake. There is no "panic mode"; the device just keeps checking
  in indefinitely.

That last bullet is important for server design: **you cannot
permanently break a device by returning errors**. Even an extended
outage will produce a flood of "5 minutes later, retrying" check-ins
once the server comes back. So:

- It's safe to redeploy aggressively.
- It's safe to return 5xx from a half-broken renderer; the firmware
  will recover when the renderer recovers.
- It is **not** safe to assume a low-volume API will stay low-volume
  during an outage. If you have N devices and they all hit
  `ERROR_RETRY_SEC = 300 s`, you're looking at `N / 300` requests per
  second sustained until you fix it.

### 7.1 Don't depend on auth in v1

The protocol is unauthenticated. If you need to add a shared-secret
header or mutual TLS, that's a coordinated firmware-side change — see
[`server-protocol.md` § 9](server-protocol.md#9-out-of-scope-for-v1).
Don't preemptively 401 / 403 the device.

### 7.2 Render failures should fall back, not 5xx

A common server-side bug is to 5xx the image fetch when your
dashboard renderer crashes. Better: serve the *previous* successful
render with its previous ETag. The device sees "ETag unchanged" and
skips the refresh, exactly as if the dashboard genuinely hadn't
changed. The mock server in [`tools/serve_test_image.py`](../tools/serve_test_image.py)
demonstrates this by caching the BMP bytes + ETag in process memory
and only re-reading from disk when the file's mtime changes.

---

## 8. Logging — what to capture, what to ignore

Every request brings ~10 headers' worth of free telemetry. A useful
server-side log line per check-in includes at minimum:

- Timestamp (server-side; the device's clock isn't trustworthy until
  after `server_time_utc` lands).
- `X-Device-MAC` (or "unknown").
- `X-Wake-Reason`.
- `X-Battery-MV` / `X-Battery-Pct`.
- `X-RSSI-Dbm`.
- `X-Last-Image-ETag` and the ETag your server is serving (so you can
  spot stuck devices).
- HTTP status code returned.

A good first dashboard graph: **time since last check-in, per MAC**.
A device that hasn't checked in for >2× its `next_checkin_sec` is
probably either offline (Wi-Fi down) or out of battery. The mock
server's per-request log line in
[`tools/serve_test_image.py`](../tools/serve_test_image.py)
(`log_request()`) is a good template.

Things you **don't** need to alert on:

- Individual 304s on the image endpoint (that's the desired path).
- Individual `If-None-Match` hits on the schedule endpoint.
- Brief 4xx / 5xx bursts (the firmware will retry; see § 7).

---

## 9. Worked examples

### 9.1 First-ever check-in from a brand-new device

```http
> GET /trmnl/reTerminal/device/schedule.json HTTP/1.1
> User-Agent: reTerminalE1002/0.1.0
> X-Device-MAC: aa:bb:cc:dd:ee:ff
> X-Wake-Reason: first_boot
> X-Boot-Count: 1
> X-Last-Image-ETag: ""
```

The server has never seen this MAC. Sensible response: register it,
return the default-variant schedule with the current image. The
firmware will fetch the image (it has no stored ETag to match
against) and paint it.

```http
< HTTP/1.1 200 OK
< Content-Type: application/json
< {
<   "schema_version": 1,
<   "server_time_utc": "2026-04-28T14:02:00Z",
<   "next_checkin_sec": 300,
<   "image": {
<     "url":    "https://.../image.bmp",
<     "etag":   "img-9f3a2c1e",
<     "format": "bmp4-spectra6-800x480"
<   },
<   "message": "Welcome, new device aa:bb:cc:dd:ee:ff"
> }
```

### 9.2 Routine no-op check-in (the common case)

```http
> GET /schedule.json
> X-Wake-Reason: timer
> X-Last-Image-ETag: "img-9f3a2c1e"
```

```http
< HTTP/1.1 200 OK
< {
<   "schema_version": 1,
<   "server_time_utc": "2026-04-28T14:07:00Z",
<   "next_checkin_sec": 300,
<   "image": { "url": "...", "etag": "img-9f3a2c1e", "format": "..." }
> }
```

ETag matches what the firmware already painted; firmware sleeps for
300 s without ever requesting `image.bmp`. This is a few hundred ms of
device wall time and ~1 KB of network traffic. Optimize for this path.

### 9.3 Image changed

```http
> GET /schedule.json
> X-Last-Image-ETag: "img-9f3a2c1e"
```

```http
< { "image": { "etag": "img-aa7b00f1", ... } }
```

```http
> GET /image.bmp
> If-None-Match: "img-9f3a2c1e"
```

```http
< HTTP/1.1 200 OK
< Content-Type: image/bmp
< ETag: "img-aa7b00f1"
< Content-Length: 192118
< (192,118 bytes)
```

### 9.4 Force-refresh from the green button

```http
> GET /schedule.json
> X-Wake-Reason: button
> X-Last-Image-ETag: "img-aa7b00f1"
```

The server can usually treat this exactly like a `timer` wake — the
firmware itself bypasses both the ETag check and the in-device
content-CRC dedup when `X-Wake-Reason == button`, so it will fetch
the image regardless of what you return. If you want to return a
different image specifically when a human pressed the button (e.g.
a "force-refresh acknowledged" banner), the header gives you the
hook, but it's purely optional.

### 9.5 "Going dark for the night"

```json
{
  "schema_version": 1,
  "server_time_utc":   "2026-04-28T22:00:00Z",
  "next_checkin_sec":  28800,
  "image": { "url": "...", "etag": "...", "format": "bmp4-spectra6-800x480" },
  "device_actions": { "clear_screen": true },
  "message": "Going dark for the night."
}
```

Firmware skips the image fetch entirely, paints the panel pure white
(also dropping its in-flash pixel cache so the next non-clear refresh
is forced through a full cycle), and sleeps 8 hours. Useful for long
quiet periods — leaving a partial image on a Spectra-6 panel for hours
on end can ghost.

### 9.6 Forced clean reboot

```json
{
  "schema_version": 1,
  "server_time_utc":   "2026-04-28T14:02:00Z",
  "next_checkin_sec":  300,
  "image": { "url": "...", "etag": "...", "format": "..." },
  "device_actions": { "reboot": true }
}
```

Firmware does the rest of the wake normally (fetches the image if the
ETag changed, paints the panel) and *then* `ESP.restart()`s instead
of sleeping. Useful for clearing a flaky session or recovering from
a stuck driver state without touching the device physically.

The `reboot` flag is consumed by the firmware on the same wake — the
server should clear it on its side after the next check-in confirms
the device came back. The reference mock server in
[`tools/serve_test_image.py`](../tools/serve_test_image.py)
demonstrates this with `--reboot` (one-shot: cleared after one
successful schedule fetch).

### 9.7 Race: image changed between schedule and image fetch

If `schedule.json` advertised `etag = X`, but by the time the device
GETs `image.bmp` your renderer has produced `Y`, two correct
behaviors:

1. Return `200` + body of `Y` + `ETag: "Y"`. Firmware stores `Y`
   and renders it. Done.
2. Return `304` (you've decided the device's `If-None-Match: "X"`
   matches what you now consider current). Firmware skips render. The
   *next* schedule check-in will advertise `Y` and the device will
   catch up then.

Both are fine. The firmware doesn't treat either as an error.

---

## 10. Reference implementations in this repo

If you want a working example to crib from:

- **Mock server (Python / Flask):**
  [`tools/serve_test_image.py`](../tools/serve_test_image.py).
  Implements both endpoints, supports `If-None-Match` on the image,
  reloads the BMP from disk when its mtime changes, and demonstrates
  one-shot vs. persistent `device_actions`. Hard-coded to the 7.3"
  Spectra-6 `image.format` enum; the Python source has an
  `image_format` field on `State` that you can swap in code if you
  need it to serve a different variant's BMP. CLI flags map directly
  to schedule fields, so it doubles as a protocol explorer.
- **Reference image encoder (Python / Pillow):**
  [`tools/png_to_e6_bmp.py`](../tools/png_to_e6_bmp.py). Converts
  any image to a byte-level-conformant 7.3" Spectra-6 BMP via
  Floyd-Steinberg dither against the 6-color palette. The server's
  image generator should match this script's output byte-for-byte
  for the same input image (validate via `cmp`).
- **Firmware-side HTTP client:** [`src/net.cpp`](../src/net.cpp).
  The actual code that makes the calls described here, including
  PSRAM-buffered chunked-encoding handling and HTTPS via
  `WiFiClientSecure`.
- **Firmware-side schedule parser:** [`src/schedule.cpp`](../src/schedule.cpp).
  The exact JSON parsing + validation logic the device runs,
  including the 30 s sanity floor.
- **Firmware-side check-in headers:** [`src/metadata.cpp`](../src/metadata.cpp).
  Where every `X-*` header is gathered and stamped onto the request.

If something in this guide ever disagrees with what those files
actually do, the firmware is the truth and this guide needs updating.
If the firmware disagrees with this guide *in spirit*, this guide is
the truth and the firmware needs updating.

---

## 11. Conformance — am I done?

You're done implementing the server side when:

1. A brand-new device with empty NVS hits your `schedule.json`, gets a
   200, fetches the advertised image, and paints it. (See the
   conformance checklist at
   [`server-protocol.md` § 8](server-protocol.md#8-conformance-checklist).)
2. A second wake from the same device with the same image returns 200
   on `schedule.json` (with the same `image.etag`) and the firmware
   *doesn't* fetch `image.bmp` at all.
3. After you change the image server-side, the next wake fetches
   `image.bmp` and gets `200` + the new bytes + a new `ETag` header
   that matches `schedule.image.etag`.
4. `If-None-Match` with a current ETag returns `304` on `image.bmp`.
5. `device_actions.reboot` and `device_actions.clear_screen` are
   honored once and then cleared by your server (so they don't fire
   every check-in).
6. Missing `X-*` headers don't cause 4xx; the device still gets a
   parseable schedule.
7. Aggressive deploys / 5xx bursts don't brick devices — they recover
   on the next `ERROR_RETRY_SEC` retry.

If all seven of those hold, the firmware is happy. Anything fancier
(per-device images, variant routing, dev-mode short cadences,
overnight wind-downs) is layered on top of that core contract.
