"""Footer widget with Textual-style inverse key hints."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import Static


class FooterWidget(Widget):
    """Bottom footer bar with inverse-background keyboard shortcut hints.

    Renders keys in reverse video for a polished, professional look that
    matches modern TUI conventions.
    """

    DEFAULT_CSS = """
    FooterWidget {
        dock: bottom;
        height: 1;
        background: #1a1b2e;
        color: #94a3b8;
    }
    FooterWidget .footer-shortcuts {
        width: 1fr;
        padding: 0 1;
    }
    FooterWidget .footer-palette-hint {
        width: auto;
        padding: 0 1;
        color: #64748b;
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
        yield Static(
            self._render_shortcuts(),
            classes="footer-shortcuts",
            id="footer-shortcuts",
        )
        yield Static(
            "[dim]q[/dim] Quit",
            classes="footer-palette-hint",
            id="footer-palette-hint",
        )

    def _render_shortcuts(self) -> str:
        """Render shortcuts with inverse-video key labels."""
        parts = []
        for key, action in self._shortcuts:
            parts.append(f"[reverse] {key} [/reverse] {action}")
        return "  ".join(parts)

    def set_shortcuts(self, shortcuts: list[tuple[str, str]]) -> None:
        """Update the displayed shortcuts."""
        self._shortcuts = shortcuts
        try:
            widget = self.query_one("#footer-shortcuts", Static)
            widget.update(self._render_shortcuts())
        except Exception:
            pass
