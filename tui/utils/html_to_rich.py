"""Convert HTML email bodies to readable plain text for the terminal."""

from __future__ import annotations

import html2text


def html_to_text(body_html: str | None, body_text: str | None = None) -> str:
    """Convert HTML email body to readable plain text.

    Uses the html2text library to produce a markdown-ish representation
    suitable for terminal display.

    If body_html is empty or None, falls back to body_text.
    Returns a plain string (not Rich markup).
    """
    if body_html:
        converter = html2text.HTML2Text()
        converter.body_width = 0  # No wrapping
        converter.ignore_images = False
        converter.protect_links = True
        converter.unicode_snob = True
        return converter.handle(body_html).strip()

    if body_text:
        return body_text.strip()

    return ""
