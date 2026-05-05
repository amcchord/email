"""Byte-exact uncompressed Windows BMP encoders for the e-ink panel variants.

All encoders emit BI_RGB (no compression), bottom-up rows, and a fixed
14-byte BITMAPFILEHEADER + 40-byte BITMAPINFOHEADER + palette layout that
matches the tables in:
- docs/terminal/server-protocol.md       (Spectra-6 7.3" canonical)
- docs/terminal/firmware-variants.md     (BW, Gray16, Spectra-6 13.3")

All inputs are Pillow images sized exactly to the panel resolution (no
resizing happens here -- the renderer is responsible for handing in a
correctly sized image).

For 4 bpp (Gray16, Spectra-6): the high nibble holds the LEFT pixel.
For 1 bpp (BW): MSB = leftmost pixel.
"""
from __future__ import annotations

import struct
from io import BytesIO

from PIL import Image

from backend.services.terminal.palette import (
    BW_PALETTE,
    GRAY16_PALETTE,
    SPECTRA6_COLORS,
    SPECTRA6_PALETTE,
)


# ── Header helpers ──────────────────────────────────────────────────

_BITMAPFILEHEADER_SIZE = 14
_BITMAPINFOHEADER_SIZE = 40


def _file_header(bf_size: int, bf_off_bits: int) -> bytes:
    # 'BM', size, reserved1, reserved2, offBits
    return struct.pack("<2sIHHI", b"BM", bf_size, 0, 0, bf_off_bits)


def _info_header(
    width: int,
    height: int,
    bit_count: int,
    image_size: int,
    clr_used: int,
    clr_important: int,
) -> bytes:
    # biSize, biWidth, biHeight, biPlanes, biBitCount, biCompression,
    # biSizeImage, biXPelsPerMeter, biYPelsPerMeter, biClrUsed, biClrImportant
    return struct.pack(
        "<IiiHHIIiiII",
        _BITMAPINFOHEADER_SIZE,
        width,
        height,  # positive = bottom-up rows
        1,
        bit_count,
        0,  # BI_RGB
        image_size,
        2835,
        2835,
        clr_used,
        clr_important,
    )


# ── Bit-packing helpers ─────────────────────────────────────────────


def _pack_4bpp_row(indices: list[int], stride: int) -> bytes:
    """Pack a row of palette indices to 4 bpp, high nibble = left pixel.

    `stride` is the on-disk byte width; any unused trailing bytes are zero.
    """
    out = bytearray(stride)
    n = len(indices)
    # Two pixels per byte; high nibble is the left pixel.
    pairs = n // 2
    for i in range(pairs):
        left = indices[2 * i] & 0x0F
        right = indices[2 * i + 1] & 0x0F
        out[i] = (left << 4) | right
    if n % 2:
        out[pairs] = (indices[-1] & 0x0F) << 4
    return bytes(out)


def _pack_1bpp_row(bits: list[int], stride: int) -> bytes:
    """Pack a row of 0/1 values to 1 bpp, MSB = leftmost pixel.

    `stride` is the on-disk byte width; any unused trailing bits are zero.
    """
    out = bytearray(stride)
    for x, v in enumerate(bits):
        if v:
            out[x >> 3] |= 0x80 >> (x & 7)
    return bytes(out)


# ── Quantization helpers ────────────────────────────────────────────


def _spectra6_palette_image() -> Image.Image:
    """A Pillow palette image whose first 6 entries are the Spectra-6 colors.

    Used with `Image.quantize(palette=...)` so Pillow performs the nearest-color
    mapping itself. Indices in the resulting image are 0..5.
    """
    pal = Image.new("P", (1, 1))
    flat = []
    for r, g, b in SPECTRA6_COLORS:
        flat.extend([r, g, b])
    # Pad up to 256 colors (Pillow requires it) with a sentinel that we'll
    # never reach because we restrict colors=len(SPECTRA6_COLORS).
    flat.extend([0] * (768 - len(flat)))
    pal.putpalette(flat)
    return pal


_SPECTRA6_PAL_IMG = _spectra6_palette_image()


# ── Public encoders ─────────────────────────────────────────────────


def encode_bw(image: Image.Image, *, dither: bool = True) -> bytes:
    """Encode a 800x480 image as the `bmp1-bw-800x480` variant (48,062 B).

    `dither=True` (default) uses Floyd-Steinberg, which softens photographs
    but buzzes on small text. The e-ink dashboard renderer passes
    `dither=False` to use a hard 50% threshold instead -- per
    docs/design/HANDOFF.md Sec 9.6 the design is engineered to be naturally
    1-bit, so any error diffusion would degrade type fidelity.
    """
    width, height = 800, 480
    if image.size != (width, height):
        raise ValueError(f"BW BMP requires 800x480, got {image.size}")

    if dither:
        # PIL "1" uses Floyd-Steinberg by default.
        img = image.convert("L").convert("1")
    else:
        # Hard threshold at 50% luminance, no error diffusion.
        img = image.convert("L").point(lambda p: 255 if p > 127 else 0, mode="1")

    stride = ((width * 1 + 31) // 32) * 4  # = 100
    image_size = stride * height
    off_bits = _BITMAPFILEHEADER_SIZE + _BITMAPINFOHEADER_SIZE + len(BW_PALETTE)
    bf_size = off_bits + image_size

    pixels = img.load()
    # Bottom-up: emit row y=height-1 first ... then y=0.
    rows: list[bytes] = []
    for y in range(height - 1, -1, -1):
        # In PIL "1", pixel 0 == black, 255 == white. Our palette index 0 is
        # black, index 1 is white -> bit value 0=black, 1=white.
        bits = [1 if pixels[x, y] else 0 for x in range(width)]
        rows.append(_pack_1bpp_row(bits, stride))

    body = b"".join(rows)
    fh = _file_header(bf_size, off_bits)
    ih = _info_header(width, height, 1, image_size, 2, 2)
    out = fh + ih + BW_PALETTE + body
    assert len(out) == 48062, f"BW BMP wrong size: {len(out)}"
    return out


def encode_gray16(image: Image.Image) -> bytes:
    """Encode a 800x480 image as the `bmp4-gray16-800x480` variant (192,118 B)."""
    width, height = 800, 480
    if image.size != (width, height):
        raise ValueError(f"Gray16 BMP requires 800x480, got {image.size}")

    # Quantize to 16 evenly-spaced grays (i*17). Floyd-Steinberg via "L".convert via Image.quantize.
    img_l = image.convert("L")
    # Build a 16-entry gray palette image and quantize against it.
    pal_img = Image.new("P", (1, 1))
    flat: list[int] = []
    for i in range(16):
        v = i * 17
        flat.extend([v, v, v])
    flat.extend([0] * (768 - len(flat)))
    pal_img.putpalette(flat)
    quantized = img_l.convert("RGB").quantize(
        colors=16, palette=pal_img, dither=Image.Dither.FLOYDSTEINBERG
    )
    pixels = quantized.load()

    stride = ((width * 4 + 31) // 32) * 4  # = 400
    image_size = stride * height
    off_bits = _BITMAPFILEHEADER_SIZE + _BITMAPINFOHEADER_SIZE + len(GRAY16_PALETTE)
    bf_size = off_bits + image_size

    rows: list[bytes] = []
    for y in range(height - 1, -1, -1):
        indices = [pixels[x, y] & 0x0F for x in range(width)]
        rows.append(_pack_4bpp_row(indices, stride))

    body = b"".join(rows)
    fh = _file_header(bf_size, off_bits)
    ih = _info_header(width, height, 4, image_size, 16, 16)
    out = fh + ih + GRAY16_PALETTE + body
    assert len(out) == 192118, f"Gray16 BMP wrong size: {len(out)}"
    return out


def encode_spectra6(
    image: Image.Image,
    *,
    width: int,
    height: int,
    dither: bool = True,
) -> bytes:
    """Encode an image as a 4 bpp Spectra-6 BMP at the given panel resolution.

    `width` x `height` must be either 800x480 (E1002) or 1200x1600 (E1004).

    `dither=True` (default) uses Floyd-Steinberg to nearest-color-map RGB
    inputs to the 6-color palette. The e-ink dashboard renderer passes
    `dither=False` so the design's flat color blocks stay crisp -- per
    docs/design/HANDOFF.md Sec 9.5 the design intentionally avoids greys
    so dithering would only add noise.
    """
    if image.size != (width, height):
        raise ValueError(
            f"Spectra-6 BMP requires {width}x{height}, got {image.size}"
        )
    if width == 800 and height == 480:
        expected_total = 192118
        expected_image = 192000
        expected_stride = 400
    elif width == 1200 and height == 1600:
        expected_total = 960118
        expected_image = 960000
        expected_stride = 600
    else:
        raise ValueError(f"unsupported Spectra-6 geometry {width}x{height}")

    quantized = image.convert("RGB").quantize(
        colors=len(SPECTRA6_COLORS),
        palette=_SPECTRA6_PAL_IMG,
        dither=Image.Dither.FLOYDSTEINBERG if dither else Image.Dither.NONE,
    )
    pixels = quantized.load()

    stride = ((width * 4 + 31) // 32) * 4
    assert stride == expected_stride
    image_size = stride * height
    assert image_size == expected_image
    off_bits = _BITMAPFILEHEADER_SIZE + _BITMAPINFOHEADER_SIZE + len(SPECTRA6_PALETTE)
    bf_size = off_bits + image_size

    rows: list[bytes] = []
    for y in range(height - 1, -1, -1):
        indices = [pixels[x, y] & 0x0F for x in range(width)]
        rows.append(_pack_4bpp_row(indices, stride))

    body = b"".join(rows)
    fh = _file_header(bf_size, off_bits)
    # Spectra-6 declares 16 colors used (full palette declared even though
    # only 6 are meaningful) to match the `biClrUsed = 6 or 16` allowance in
    # the doc and to keep the byte total consistent.
    ih = _info_header(width, height, 4, image_size, 16, 16)
    out = fh + ih + SPECTRA6_PALETTE + body
    assert len(out) == expected_total, (
        f"Spectra-6 {width}x{height} BMP wrong size: {len(out)}"
    )
    return out
