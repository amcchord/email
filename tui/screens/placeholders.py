"""Placeholder screens for navigation targets not yet implemented."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.widgets import Static

from tui.screens.base import BaseScreen


class HelpScreen(BaseScreen):
    SCREEN_TITLE = "Help"
    SCREEN_NAV_ID = ""

    def compose_content(self) -> ComposeResult:
        yield Static(
            "Keyboard Shortcuts\n\n"
            "[bold]g f[/bold]  Flow\n"
            "[bold]g i[/bold]  Inbox\n"
            "[bold]g l[/bold]  Calendar\n"
            "[bold]g t[/bold]  Todos\n"
            "[bold]g s[/bold]  Stats\n"
            "[bold]g a[/bold]  AI Insights\n"
            "[bold]g h[/bold]  Chat\n"
            "[bold]g ,[/bold]  Settings\n"
            "[bold]c[/bold]    Compose\n"
            "[bold]/[/bold]    Search\n"
            "[bold].[/bold]    Toggle theme\n"
            "[bold][[/bold]    Toggle sidebar\n"
            "[bold]?[/bold]    This help\n"
            "[bold]q[/bold]    Quit\n",
            classes="placeholder-label",
        )
