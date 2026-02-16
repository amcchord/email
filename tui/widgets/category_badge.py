"""AI category colored badge widget."""

from __future__ import annotations

from textual.widgets import Static


# Category display configuration: (label, rich style)
CATEGORY_STYLES: dict[str, tuple[str, str]] = {
    "urgent": ("[URGENT]", "bold red"),
    "fyi": ("[FYI]", "cyan"),
    "can_ignore": ("[IGNORE]", "dim"),
    "awaiting_reply": ("[AWAIT]", "yellow"),
}


class CategoryBadge(Static):
    """Displays an AI category as a short colored badge.

    Accepts a category string such as "urgent", "fyi", "can_ignore",
    or "awaiting_reply" and renders it with appropriate styling.
    """

    DEFAULT_CSS = """
    CategoryBadge {
        width: auto;
        height: 1;
    }
    """

    def __init__(self, category: str | None = None, **kwargs) -> None:
        super().__init__(**kwargs)
        self._category = category

    def on_mount(self) -> None:
        self._render_badge()

    def set_category(self, category: str | None) -> None:
        """Update the displayed category."""
        self._category = category
        self._render_badge()

    def _render_badge(self) -> None:
        """Render the badge with appropriate color styling."""
        if not self._category:
            self.update("")
            return

        label, style = CATEGORY_STYLES.get(
            self._category, (f"[{self._category.upper()}]", "")
        )
        if style:
            self.update(f"[{style}]{label}[/{style}]")
        else:
            self.update(label)
