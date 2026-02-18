"""AI category colored badge widget with modern pill styling."""

from __future__ import annotations

from textual.widgets import Static


# Category display: (label_text, rich_markup)
CATEGORY_STYLES: dict[str, tuple[str, str]] = {
    "urgent": ("URGENT", "[on #ef4444][#ffffff] URGENT [/#ffffff][/on #ef4444]"),
    "fyi": ("FYI", "[on #0891b2][#ffffff] FYI [/#ffffff][/on #0891b2]"),
    "can_ignore": ("IGNORE", "[#64748b]ignore[/#64748b]"),
    "awaiting_reply": ("AWAIT", "[on #f59e0b][#0f0f1a] AWAIT [/#0f0f1a][/on #f59e0b]"),
    "needs_action": ("ACTION", "[on #6366f1][#ffffff] ACTION [/#ffffff][/on #6366f1]"),
}


class CategoryBadge(Static):
    """Displays an AI category as a short colored pill badge.

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
        """Render the badge with colored pill styling."""
        if not self._category:
            self.update("")
            return

        style_entry = CATEGORY_STYLES.get(self._category)
        if style_entry:
            _, markup = style_entry
            self.update(markup)
        else:
            self.update(f"[#94a3b8]{self._category.upper()}[/#94a3b8]")
