"""Terminal image protocol detection.

Detects whether the current terminal supports inline image display
via protocols like Kitty graphics, Sixel, or iTerm2 inline images.

This module is intended for future use when rendering inline email
images and attachments in the TUI.
"""

from __future__ import annotations

import os


def get_image_protocol() -> str | None:
    """Detect the best available terminal image protocol.

    Checks environment variables and terminal capabilities to determine
    which image protocol (if any) the current terminal supports.

    Returns
    -------
    str | None
        One of ``"kitty"``, ``"sixel"``, ``"iterm2"``, or ``None``
        if no image protocol is detected.
    """
    # Kitty terminal -- check for KITTY_WINDOW_ID env var
    if os.environ.get("KITTY_WINDOW_ID"):
        return "kitty"

    term_program = os.environ.get("TERM_PROGRAM", "").lower()

    # iTerm2 supports its own inline image protocol
    if term_program == "iterm2":
        return "iterm2"

    # WezTerm supports multiple protocols; prefer Kitty
    if term_program == "wezterm":
        return "kitty"

    # Mintty supports Sixel
    if term_program == "mintty":
        return "sixel"

    # Check for Sixel support via TERM variable
    term = os.environ.get("TERM", "")
    # Some terminals advertise sixel via TERM containing "sixel"
    if "sixel" in term.lower():
        return "sixel"

    # Foot terminal supports Sixel
    if term_program == "foot":
        return "sixel"

    # Contour terminal supports Sixel and Kitty
    if term_program == "contour":
        return "kitty"

    return None


def supports_images() -> bool:
    """Check whether the current terminal supports any image protocol.

    Returns
    -------
    bool
        ``True`` if an image protocol was detected, ``False`` otherwise.
    """
    return get_image_protocol() is not None


def get_protocol_info() -> dict[str, str | bool | None]:
    """Return a summary dict of image support information.

    Useful for debugging or displaying in the settings/about screen.

    Returns
    -------
    dict
        Keys: ``protocol``, ``supports_images``, ``term``,
        ``term_program``, ``kitty_window_id``.
    """
    return {
        "protocol": get_image_protocol(),
        "supports_images": supports_images(),
        "term": os.environ.get("TERM", ""),
        "term_program": os.environ.get("TERM_PROGRAM", ""),
        "kitty_window_id": os.environ.get("KITTY_WINDOW_ID", ""),
    }
