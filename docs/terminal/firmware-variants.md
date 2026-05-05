# reTerminal Home Dashboard — Variant Catalog (server-side contract)

This server publishes the same home dashboard in several e-paper-friendly formats so the same scheduling logic can drive every reTerminal model:

- **BW** — 1 bpp, black + white, Floyd-Steinberg-dithered, 800×480 (E1001).
- **Gray** — 4 bpp, 16 grays, Floyd-Steinberg-dithered, 800×480.
- **Spectra-6 7.3"** — 4 bpp, native 6-color palette, 800×480 (E1002).
- **Spectra-6 13.3"** — 4 bpp, native 6-color palette, 1200×1600 (E1004).

All four follow the same HTTP protocol shape; the firmware only has to learn the variant's schedule query, `image.format` enum value, and BMP byte layout.

The 7.3" Spectra-6 path is the canonical contract documented in [`server-protocol.md`](server-protocol.md); this file is the catalog brief covering every other variant. Each variant section is self-contained for a firmware author who only needs to implement one.

## 1. Endpoints

| Variant         | Schedule URL                                                                                         | Image URL                                                                  |
| --------------- | ---------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------- |
| BW              | `https://www.mcchord.net/trmnl/reTerminal/device/schedule.json?variant=bw`                           | `https://www.mcchord.net/trmnl/reTerminal/device/imageBW.bmp`              |
| Gray            | `https://www.mcchord.net/trmnl/reTerminal/device/schedule.json?variant=gray`                         | `https://www.mcchord.net/trmnl/reTerminal/device/imageGray.bmp`            |
| Spectra-6 7.3"  | `https://www.mcchord.net/trmnl/reTerminal/device/schedule.json` (no query / default)                 | `https://www.mcchord.net/trmnl/reTerminal/device/image.bmp`                |
| Spectra-6 13.3" | `https://www.mcchord.net/trmnl/reTerminal/device/schedule.json?variant=spectra6_1200x1600`           | `https://www.mcchord.net/trmnl/reTerminal/device/image1200x1600.bmp`       |

The schedule URL is the only one the firmware needs in its runtime config. The image URL it actually fetches comes from `schedule.image.url`, exactly like the 7.3" Spectra-6 firmware. The `image.url` returned for a `variant=bw` schedule will always be the matching BW BMP; same for the other variants.

Both endpoints support `If-None-Match` and respond `304 Not Modified` when nothing has changed. HTTPS only, publicly trusted certs.

## 2. Device → server (request headers)

Identical to the Spectra-6 protocol. Recommended headers on every request to both endpoints:

```
User-Agent: <yourFirmwareName>/<semver>
Accept: application/json        (on schedule.json)
Accept: image/bmp               (on imageBW.bmp / imageGray.bmp)
X-Device-MAC: aa:bb:cc:dd:ee:ff
X-FW-Version: 0.1.0
X-Wake-Reason: timer | button | reset | first_boot | unknown
X-Boot-Count: <uint32>
X-Uptime-Sec: <uint32>
X-Battery-MV: <uint16>
X-Battery-Pct: <uint8 0-100>
X-RSSI-Dbm: <int>
X-Free-PSRAM: <uint32>
X-Last-Image-ETag: "<previous etag>"   (or empty string if none)
If-None-Match: "<previous etag>"
```

Server treats any missing `X-*` header as "unknown" — never 4xx the device for missing headers.

## 3. `schedule.json` response

JSON shape:

```json
{
  "schema_version": 1,
  "server_time_utc": "2026-04-29T20:35:00Z",
  "next_checkin_sec": 300,
  "next_checkin_utc": "2026-04-29T20:40:00Z",
  "variant": "bw",
  "image": {
    "url":    "https://www.mcchord.net/trmnl/reTerminal/device/imageBW.bmp",
    "etag":   "\"img-bw-9f3a2c1e4b00\"",
    "format": "bmp1-bw-800x480",
    "bytes":  48062
  },
  "message": "Live home dashboard (rendered on check-in)."
}
```

Field semantics that matter:

- `schema_version` — currently `1`. If you bump it server-side, firmware should refuse and use defaults.
- `next_checkin_sec` — authoritative for sleep duration. The server is the single source of truth for refresh cadence; firmware honors whatever value is returned, subject only to a 30 s absolute sanity floor (runaway-loop guard, not panel protection). Panel-life budgeting per variant is the server's responsibility. A `?dev=1` query is supported by the server for fast iteration during development.
- `image.url` — exact URL the firmware will GET. May be on a CDN.
- `image.etag` — must byte-match the `ETag` header returned by `image.url`. Compare against your stored last ETag; skip the image fetch when they match.
- `image.format` — enum:
  - `"bmp1-bw-800x480"` for the BW variant
  - `"bmp4-gray16-800x480"` for the Gray variant
  - `"bmp4-spectra6-800x480"` for the 7.3" Spectra-6 path (a BW or Gray firmware should ignore / not fetch this)
  - `"bmp4-spectra6-1200x1600"` for the 13.3" Spectra-6 path (E1004)
  - Reject any other value, sleep, retry next cycle.
- `image.bytes` — expected `Content-Length` of the BMP body. If your fetch returns wildly different, abort and retry.
- `variant` — optional echo of the variant the schedule was issued for. Useful for cross-checking that your `?variant=` param survived a CDN.

## 4. BMP byte layouts

All variants are uncompressed Microsoft Windows BMPs (`BI_RGB`), bottom-up rows (positive `biHeight`; the server may also accept top-down `-biHeight` for replay tools, but it always emits bottom-up).

### 4.1 BW variant — `bmp1-bw-800x480`, 48,062 bytes

| Offset | Size   | Field           | Required value                |
| ------ | ------ | --------------- | ----------------------------- |
| 0      | 2      | Magic           | `0x42 0x4D` (`"BM"`)          |
| 2      | 4      | bfSize          | `48062` little-endian         |
| 6      | 4      | bfReserved      | `0`                           |
| 10     | 4      | bfOffBits       | `62`                          |
| 14     | 4      | biSize          | `40` (BITMAPINFOHEADER)       |
| 18     | 4      | biWidth         | `800`                         |
| 22     | 4      | biHeight        | `480`                         |
| 26     | 2      | biPlanes        | `1`                           |
| 28     | 2      | biBitCount      | `1`                           |
| 30     | 4      | biCompression   | `0` (BI_RGB)                  |
| 34     | 4      | biSizeImage     | `48000`                       |
| 38     | 4      | biXPelsPerMeter | `2835`                        |
| 42     | 4      | biYPelsPerMeter | `2835`                        |
| 46     | 4      | biClrUsed       | `2`                           |
| 50     | 4      | biClrImportant  | `2`                           |
| 54     | 8      | RGBQUAD palette | 2 entries, see below          |
| 62     | 48000  | Pixel data      | 480 rows × 100 bytes (1 bpp)  |

**Palette (mandatory ordering):**

| Index | Color | RGB               | Bytes (B G R 0)  |
| ----- | ----- | ----------------- | ---------------- |
| 0     | Black | `(0, 0, 0)`       | `00 00 00 00`    |
| 1     | White | `(255, 255, 255)` | `FF FF FF 00`    |

**Pixel packing:**
- 1 bit per pixel, **MSB = leftmost pixel**, 8 pixels per byte.
- Row stride is `((800*1 + 31)/32)*4 = 100` bytes (already 4-byte aligned, no row padding).
- Bottom-up rows: row 0 of the pixel buffer is the **bottom** of the panel; the first row in the file is `y=479`, the last is `y=0`.
- Pixel value `0` paints palette index 0 (black), pixel value `1` paints index 1 (white). No further mapping needed if you treat black/white as "ink/no-ink" with `1 = white = no ink`.

### 4.2 Gray variant — `bmp4-gray16-800x480`, 192,118 bytes

Same envelope as the existing Spectra-6 BMP (so a Spectra-6 decoder can be reused with only the palette interpretation changed):

| Offset | Size   | Field           | Required value                          |
| ------ | ------ | --------------- | --------------------------------------- |
| 0      | 2      | Magic           | `"BM"`                                  |
| 2      | 4      | bfSize          | `192118`                                |
| 6      | 4      | bfReserved      | `0`                                     |
| 10     | 4      | bfOffBits       | `118`                                   |
| 14     | 4      | biSize          | `40`                                    |
| 18     | 4      | biWidth         | `800`                                   |
| 22     | 4      | biHeight        | `480`                                   |
| 26     | 2      | biPlanes        | `1`                                     |
| 28     | 2      | biBitCount      | `4`                                     |
| 30     | 4      | biCompression   | `0` (BI_RGB)                            |
| 34     | 4      | biSizeImage     | `192000`                                |
| 38     | 4      | biXPelsPerMeter | `2835`                                  |
| 42     | 4      | biYPelsPerMeter | `2835`                                  |
| 46     | 4      | biClrUsed       | `16`                                    |
| 50     | 4      | biClrImportant  | `16`                                    |
| 54     | 64     | RGBQUAD palette | 16 entries, see below                   |
| 118    | 192000 | Pixel data      | 480 rows × 400 bytes (4 bpp packed)     |

**Palette (mandatory ordering, 16 grays evenly spaced):**

| Index | Gray value (each channel) | RGB                         |
| ----- | ------------------------- | --------------------------- |
| 0     | `0`                       | `(0, 0, 0)`                 |
| 1     | `17`                      | `(17, 17, 17)`              |
| 2     | `34`                      | `(34, 34, 34)`              |
| ...   | `i * 17`                  | `(i*17, i*17, i*17)`        |
| 15    | `255`                     | `(255, 255, 255)`           |

In other words: index `i` maps to the 8-bit gray value `i * 17`, hitting pure black at `i=0` and pure white at `i=15` exactly. If your panel takes a pre-quantized 4-bit gray buffer, you can pass the pixel index straight through.

**Pixel packing:**
- 4 bits per pixel, **high nibble = left pixel**, 2 pixels per byte.
- Row stride is `((800*4 + 31)/32)*4 = 400` bytes (already 4-byte aligned).
- Bottom-up rows (same orientation rule as the BW BMP).

### 4.3 Spectra-6 13.3" variant — `bmp4-spectra6-1200x1600`, 960,118 bytes

Same envelope as the 7.3" Spectra-6 BMP documented in [`server-protocol.md`](server-protocol.md#5-server--device-imagebmp), with bigger geometry. The 16-entry palette is identical (indices 0..5 = Black, White, Green, Blue, Red, Yellow; 6..15 unused / treated as white). Pixel packing is identical (4 bpp, high nibble = left, two pixels per byte).

| Offset | Size    | Field           | Required value                            |
| ------ | ------- | --------------- | ----------------------------------------- |
| 0      | 2       | Magic           | `"BM"`                                    |
| 2      | 4       | bfSize          | `960118`                                  |
| 6      | 4       | bfReserved      | `0`                                       |
| 10     | 4       | bfOffBits       | `118`                                     |
| 14     | 4       | biSize          | `40`                                      |
| 18     | 4       | biWidth         | `1200`                                    |
| 22     | 4       | biHeight        | `1600`                                    |
| 26     | 2       | biPlanes        | `1`                                       |
| 28     | 2       | biBitCount      | `4`                                       |
| 30     | 4       | biCompression   | `0` (BI_RGB)                              |
| 34     | 4       | biSizeImage     | `960000`                                  |
| 38     | 4       | biXPelsPerMeter | `2835`                                    |
| 42     | 4       | biYPelsPerMeter | `2835`                                    |
| 46     | 4       | biClrUsed       | `6` or `16`                               |
| 50     | 4       | biClrImportant  | `6` or `0`                                |
| 54     | 64      | RGBQUAD palette | 16 entries; first 6 = Spectra-6 ordering  |
| 118    | 960000  | Pixel data      | 1600 rows × 600 bytes (4 bpp packed)      |

Row stride is `((1200*4 + 31)/32)*4 = 600` bytes (already 4-byte aligned). The portrait-oriented panel reports its native resolution as 1200 (width) × 1600 (height); rotation is handled on the server side.

## 5. ETag / cache behavior

Identical to the Spectra-6 contract:

- `schedule.json` returns its own `ETag` (e.g. `"sched-bw-XXXXXXXXXXXX"`); use it for `If-None-Match` on the **schedule** to short-circuit a no-change check-in to a `304`.
- `image.bmp`'s `ETag` (e.g. `"img-bw-XXXXXXXXXXXX"`) is what `schedule.image.etag` advertises and what `If-None-Match` should send when fetching the image. The server returns `304 Not Modified` (no body) when the device's stored ETag still matches the on-disk BMP.
- `image.etag` may change between a `schedule.json` fetch and the matching `image.bmp` fetch (the dashboard re-rendered in the meantime). Two correct server behaviors when that happens:
  1. Return `200` with the newer body and a fresher `ETag` — your firmware should accept the body as canonical, store the new ETag.
  2. Return `304` because the device's `If-None-Match` matches what the server now considers current — your firmware should treat that as "no change", and the next schedule check-in will advertise the new ETag.

Both of those are normal; firmware shouldn't treat either as an error.

## 6. Render cadence (informational)

The server re-renders the BMP for whichever variant was just requested, on each check-in, with a 30-second debounce per variant. From the firmware's perspective this is invisible — the server is just sometimes a few hundred ms slower to respond on the first hit after a long idle. Stable response times are <5 s; firmware HTTP timeouts of ~15 s are plenty.

A render failure does **not** cause a 5xx — the server falls back to serving the previous BMP, so the device always gets a well-formed file.

## 7. Quick conformance checklist

For a firmware-side decoder targeting these endpoints:

- [ ] Send `?variant=bw`, `?variant=gray`, `?variant=spectra6_1200x1600`, or no variant query (default = 7.3" Spectra-6) on every `schedule.json` GET, depending on the firmware build.
- [ ] Validate `image.format` against your single accepted enum (`"bmp1-bw-800x480"`, `"bmp4-gray16-800x480"`, `"bmp4-spectra6-800x480"`, or `"bmp4-spectra6-1200x1600"`); skip + retry on any other value.
- [ ] Refuse `schema_version > 1` (or whatever your firmware was built against).
- [ ] Honor `next_checkin_sec` as returned by the server; only apply a small absolute sanity floor (firmware uses 30 s) to avoid wake-loops on a buggy server response. Panel-life budgeting is the server's responsibility.
- [ ] Use `If-None-Match` on both endpoints with the most-recently-stored ETag.
- [ ] BMP decoder verifies: magic `"BM"`, `biWidth=800`, `biHeight=±480`, `biCompression=0`, `biBitCount=1` (or `4`), palette[0..N-1] matches the table above byte-for-byte.
- [ ] BMP decoder respects bottom-up rows: row 0 in the pixel buffer = bottom row of the panel.
- [ ] BMP decoder respects MSB-first bit packing (1 bpp) / high-nibble-first (4 bpp).
- [ ] On 4xx/5xx/timeouts: log, sleep `ERROR_RETRY_SEC` (suggested 5 min), retry next cycle. Never panic-stop.

## 8. Reference data for testing

You can pull a known-good BMP at any time:

```sh
curl -fsSL https://www.mcchord.net/trmnl/reTerminal/device/imageBW.bmp     -o imageBW.bmp
curl -fsSL https://www.mcchord.net/trmnl/reTerminal/device/imageGray.bmp   -o imageGray.bmp

# Force a specific layout fixture for repeatable testing - hit the live HTML
# preview directly to see what the BMP will contain before you fetch it:
#   https://www.mcchord.net/trmnl/reTerminal/home.php?bit=bw&fake=sauna
#   https://www.mcchord.net/trmnl/reTerminal/home.php?bit=gray&fake=laundry
```

The reference encoder (Python, used server-side) lives at [`tools/bw_bmp.py`](../tools/bw_bmp.py) and [`tools/gray16_bmp.py`](../tools/gray16_bmp.py) in the same repo if you want to round-trip-verify your decoder against an authoritative sample.
