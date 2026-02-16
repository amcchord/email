"""Main screen shown after login - the app shell."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.widgets import Static

from tui.screens.base import BaseScreen


class MainScreen(BaseScreen):
    """Main screen displayed after successful login.

    Shows the app shell with sidebar navigation. Defaults to the Flow view.
    """

    SCREEN_TITLE = "Flow"
    SCREEN_NAV_ID = "flow"
    DEFAULT_SHORTCUTS = [
        ("g f", "Flow"),
        ("g i", "Inbox"),
        ("g l", "Calendar"),
        ("g t", "Todos"),
        ("c", "Compose"),
        ("[", "Sidebar"),
        (".", "Theme"),
        ("?", "Help"),
    ]

    def compose_content(self) -> ComposeResult:
        yield Static(
            "Welcome to Mail TUI\n\n"
            "Use [bold]g f[/bold] for Flow, [bold]g i[/bold] for Inbox, "
            "and other shortcuts to navigate.\n\n"
            "Press [bold]?[/bold] for help.",
            classes="placeholder-label",
        )
