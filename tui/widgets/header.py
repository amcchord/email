"""Header bar widget for the mail TUI -- modern design with breadcrumbs and status."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widget import Widget
from textual.widgets import Static


class HeaderWidget(Widget):
    """Top header bar with app name, breadcrumb title, and status indicators.

    Displays a single row with accent background, information-dense layout.
    """

    DEFAULT_CSS = """
    HeaderWidget {
        dock: top;
        height: 1;
        background: #6366f1;
        color: #ffffff;
    }
    HeaderWidget .header-app-name {
        width: auto;
        padding: 0 1;
        text-style: bold;
        color: #ffffff;
    }
    HeaderWidget .header-separator {
        width: auto;
        color: #a5b4fc;
    }
    HeaderWidget .header-title {
        width: 1fr;
        padding: 0 1;
        color: #e0e7ff;
    }
    HeaderWidget .header-status {
        width: auto;
        padding: 0 1;
        color: #c7d2fe;
    }
    HeaderWidget .header-user {
        width: auto;
        padding: 0 1;
        color: #e0e7ff;
    }
    """

    def __init__(
        self,
        app_name: str = "\u2501 Mail",
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
            yield Static(" \u203a ", classes="header-separator")
            yield Static(self._screen_title, classes="header-title", id="header-title")
            yield Static("", classes="header-status", id="header-status")
            yield Static(
                f"\u25cf {self._user_name}" if self._user_name else "",
                classes="header-user",
                id="header-user",
            )

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
            widget.update(f"\u25cf {name}" if name else "")
        except Exception:
            pass

    def set_status(self, text: str) -> None:
        """Update the status area in the header."""
        try:
            widget = self.query_one("#header-status", Static)
            widget.update(text)
        except Exception:
            pass
