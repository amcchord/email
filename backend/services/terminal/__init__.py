"""E-ink terminal protocol helpers.

Implements the byte-level BMP layouts described in:
- docs/terminal/server-protocol.md  (Spectra-6 7.3" canonical)
- docs/terminal/firmware-variants.md  (BW, Gray16, Spectra-6 13.3")

Public surface:
- variants.VARIANTS, parse_variant
- bmp.encode_bw, encode_gray16, encode_spectra6
- renderer.render_bmp(variant, device, settings)
"""

from backend.services.terminal.variants import (
    VARIANTS,
    Variant,
    parse_variant,
)

__all__ = ["VARIANTS", "Variant", "parse_variant"]
