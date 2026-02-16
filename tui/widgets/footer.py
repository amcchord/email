"""Footer widget showing context-sensitive keyboard shortcut hints."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import Static


class FooterWidget(Widget):
    """Bottom footer bar showing keyboard shortcut hints.

    Displays context-sensitive shortcuts in the format:
    [key] action  [key] action  ...
    """

    DEFAULT_CSS = """
    FooterWidget {
        dock: bottom;
        height: 1;
        background: $surface;
        color: $text-muted;
    }
    FooterWidget .footer-content {
        width: 1fr;
        padding: 0 1;
    }
    """

    def __init__(
        self,
        shortcuts: list[tuple[str, str]] | None = None,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._shortcuts = shortcuts or []

    def compose(self) -> ComposeResult:
        yield Static(self._render_shortcuts(), classes="footer-content", id="footer-content")

    def _render_shortcuts(self) -> str:
        """Render the shortcuts list as a formatted string."""
        parts = []
        for key, action in self._shortcuts:
            parts.append(f"[bold]{key}[/bold] {action}")
        return "  ".join(parts)

    def set_shortcuts(self, shortcuts: list[tuple[str, str]]) -> None:
        """Update the displayed shortcuts."""
        self._shortcuts = shortcuts
        try:
            widget = self.query_one("#footer-content", Static)
            widget.update(self._render_shortcuts())
        except Exception:
            pass
