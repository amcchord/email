"""Header bar widget for the mail TUI."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widget import Widget
from textual.widgets import Static


class HeaderWidget(Widget):
    """Top header bar showing app name, screen title, and user info.

    Displays a single row spanning full width with accent background.
    """

    DEFAULT_CSS = """
    HeaderWidget {
        dock: top;
        height: 1;
        background: $accent;
        color: $text;
    }
    HeaderWidget .header-app-name {
        width: auto;
        padding: 0 1;
        text-style: bold;
        color: #ffffff;
    }
    HeaderWidget .header-title {
        width: 1fr;
        padding: 0 1;
        color: #e0e0e0;
    }
    HeaderWidget .header-user {
        width: auto;
        padding: 0 1;
        color: #e0e0e0;
    }
    """

    def __init__(
        self,
        app_name: str = "Mail",
        screen_title: str = "",
        user_name: str = "",
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._app_name = app_name
        self._screen_title = screen_title
        self._user_name = user_name

    def compose(self) -> ComposeResult:
        with Horizontal():
            yield Static(self._app_name, classes="header-app-name")
            yield Static(self._screen_title, classes="header-title", id="header-title")
            yield Static(self._user_name, classes="header-user", id="header-user")

    def set_title(self, title: str) -> None:
        """Update the screen title displayed in the header."""
        try:
            widget = self.query_one("#header-title", Static)
            widget.update(title)
        except Exception:
            pass

    def set_user(self, name: str) -> None:
        """Update the user display name in the header."""
        try:
            widget = self.query_one("#header-user", Static)
            widget.update(name)
        except Exception:
            pass
