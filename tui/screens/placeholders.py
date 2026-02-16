"""Placeholder screens for navigation targets not yet implemented."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.widgets import Static

from tui.screens.base import BaseScreen


class FlowScreen(BaseScreen):
    SCREEN_TITLE = "Flow"
    SCREEN_NAV_ID = "flow"

    def compose_content(self) -> ComposeResult:
        yield Static("Flow - Coming Soon", classes="placeholder-label")


class CalendarScreen(BaseScreen):
    SCREEN_TITLE = "Calendar"
    SCREEN_NAV_ID = "calendar"

    def compose_content(self) -> ComposeResult:
        yield Static("Calendar - Coming Soon", classes="placeholder-label")


class TodoScreen(BaseScreen):
    SCREEN_TITLE = "Todos"
    SCREEN_NAV_ID = "todos"

    def compose_content(self) -> ComposeResult:
        yield Static("Todos - Coming Soon", classes="placeholder-label")


class StatsScreen(BaseScreen):
    SCREEN_TITLE = "Stats"
    SCREEN_NAV_ID = "stats"

    def compose_content(self) -> ComposeResult:
        yield Static("Stats - Coming Soon", classes="placeholder-label")


class AIInsightsScreen(BaseScreen):
    SCREEN_TITLE = "AI Insights"
    SCREEN_NAV_ID = "ai_insights"

    def compose_content(self) -> ComposeResult:
        yield Static("AI Insights - Coming Soon", classes="placeholder-label")


class ChatScreen(BaseScreen):
    SCREEN_TITLE = "Chat"
    SCREEN_NAV_ID = "chat"

    def compose_content(self) -> ComposeResult:
        yield Static("Chat - Coming Soon", classes="placeholder-label")


class SettingsScreen(BaseScreen):
    SCREEN_TITLE = "Settings"
    SCREEN_NAV_ID = "settings"

    def compose_content(self) -> ComposeResult:
        yield Static("Settings - Coming Soon", classes="placeholder-label")


class ComposeScreen(BaseScreen):
    SCREEN_TITLE = "Compose"
    SCREEN_NAV_ID = ""

    def compose_content(self) -> ComposeResult:
        yield Static("Compose - Coming Soon", classes="placeholder-label")


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
