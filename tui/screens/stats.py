"""Statistics screen with summary cards, volume chart, and AI category breakdown."""

from __future__ import annotations

import logging
from typing import Any

from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Static

from tui.client.ai import AIClient
from tui.screens.base import BaseScreen

logger = logging.getLogger(__name__)

# Block characters for horizontal bar charts (increasing fill)
BAR_CHARS = " \u258f\u258e\u258d\u258c\u258b\u258a\u2589\u2588"

# Colors for category badges
CATEGORY_COLORS = {
    "can_ignore": "#6b7280",
    "fyi": "#3b82f6",
    "needs_response": "#f59e0b",
    "urgent": "#ef4444",
    "awaiting_reply": "#8b5cf6",
    "notification": "#6366f1",
    "newsletter": "#10b981",
    "transactional": "#64748b",
    "marketing": "#ec4899",
    "social": "#06b6d4",
}


def _bar(value: int, max_value: int, width: int = 30) -> str:
    """Build a horizontal bar string using block characters.

    Returns a string of `width` characters representing the proportion
    value/max_value using Unicode block characters.
    """
    if max_value <= 0 or value <= 0:
        return " " * width

    ratio = min(value / max_value, 1.0)
    filled_float = ratio * width
    full_blocks = int(filled_float)
    remainder = filled_float - full_blocks

    # Map remainder to one of 8 partial block characters
    partial_idx = int(remainder * 8)
    partial_idx = min(partial_idx, 8)

    bar = BAR_CHARS[8] * full_blocks
    if partial_idx > 0 and full_blocks < width:
        bar += BAR_CHARS[partial_idx]
    bar = bar.ljust(width)
    return bar[:width]


class SummaryCard(Static):
    """A small summary card showing a label and value."""

    DEFAULT_CSS = """
    SummaryCard {
        width: 1fr;
        min-width: 12;
        height: 5;
        padding: 1 2;
        margin: 0 1;
        background: $surface;
        border: round $primary-background-darken-2;
        content-align: center middle;
        text-align: center;
    }
    """

    def __init__(self, label: str, value: str = "...", **kwargs) -> None:
        super().__init__(f"[bold]{value}[/bold]\n[dim]{label}[/dim]", **kwargs)
        self._label = label
        self._value = value

    def set_value(self, value: str) -> None:
        """Update the displayed value."""
        self._value = value
        self.update(f"[bold]{self._value}[/bold]\n[dim]{self._label}[/dim]")


class StatsScreen(BaseScreen):
    """Statistics dashboard with summary cards, volume chart, and AI categories."""

    SCREEN_TITLE = "Stats"
    SCREEN_NAV_ID = "stats"
    DEFAULT_SHORTCUTS = [
        ("j/k", "Scroll"),
        ("r", "Refresh"),
        ("?", "Help"),
    ]

    BINDINGS = [
        *BaseScreen.BINDINGS,
        Binding("j", "scroll_down", "Scroll down", show=False),
        Binding("k", "scroll_up", "Scroll up", show=False),
        Binding("r", "refresh_data", "Refresh", show=False),
    ]

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._ai_client: AIClient | None = None

    def compose_content(self) -> ComposeResult:
        with VerticalScroll(id="stats-scroll"):
            # Summary cards row
            with Horizontal(id="stats-cards"):
                yield SummaryCard("Total Emails", id="card-total")
                yield SummaryCard("Unread", id="card-unread")
                yield SummaryCard("Starred", id="card-starred")
                yield SummaryCard("Attachments", id="card-attachments")

            # Volume chart section
            yield Static(
                "[bold]Email Volume (Last 30 Days)[/bold]",
                id="stats-volume-header",
            )
            yield Static(
                "[dim]Loading...[/dim]", id="stats-volume-chart"
            )

            # AI category breakdown
            yield Static(
                "[bold]AI Category Breakdown[/bold]",
                id="stats-category-header",
            )
            yield Static(
                "[dim]Loading...[/dim]", id="stats-category-chart"
            )

            # AI analysis coverage
            yield Static(
                "[bold]AI Analysis Coverage[/bold]",
                id="stats-coverage-header",
            )
            yield Static(
                "[dim]Loading...[/dim]", id="stats-coverage-info"
            )

            yield Static("", id="stats-status")

    def on_mount(self) -> None:
        """Initialize and fetch data."""
        super().on_mount()
        self._ai_client = AIClient(self.app.api_client)
        self._load_all_data()

    @work(exclusive=True, group="stats-load")
    async def _load_all_data(self) -> None:
        """Fetch all stats data in parallel."""
        import asyncio

        self._update_status("Loading statistics...")

        results = await asyncio.gather(
            self._fetch_admin_stats(),
            self._fetch_ai_stats(),
            self._fetch_ai_trends(),
            return_exceptions=True,
        )

        errors = [r for r in results if isinstance(r, Exception)]
        if errors:
            error_msgs = "; ".join(str(e)[:50] for e in errors)
            self._update_status(f"Some data failed: {error_msgs}")
        else:
            self._update_status("")

    async def _fetch_admin_stats(self) -> None:
        """Fetch admin/stats data for summary cards and volume chart."""
        try:
            data = await self.app.api_client.get("/admin/stats")
            self._render_summary_cards(data)
            self._render_volume_chart(data)
        except Exception as e:
            logger.debug("Failed to fetch admin stats, trying dashboard", exc_info=True)
            # Fall back to dashboard endpoint
            try:
                data = await self.app.api_client.get("/admin/dashboard")
                self._render_summary_cards_dashboard(data)
            except Exception as e2:
                logger.debug("Failed to fetch dashboard too", exc_info=True)
                raise e

    async def _fetch_ai_stats(self) -> None:
        """Fetch AI analysis statistics."""
        try:
            data = await self._ai_client.get_stats()
            self._render_coverage_info(data)
        except Exception as e:
            logger.debug("Failed to fetch AI stats", exc_info=True)
            raise

    async def _fetch_ai_trends(self) -> None:
        """Fetch AI trends for category breakdown."""
        try:
            data = await self._ai_client.get_trends()
            self._render_category_chart(data)
        except Exception as e:
            logger.debug("Failed to fetch AI trends", exc_info=True)
            raise

    # ── Rendering ────────────────────────────────────────────

    def _render_summary_cards(self, data: dict[str, Any]) -> None:
        """Render summary cards from admin/stats data."""
        try:
            total = data.get("total_emails", 0)
            unread = data.get("total_unread", 0)
            starred = data.get("total_starred", 0)
            attachments = data.get("total_with_attachments", 0)

            self.query_one("#card-total", SummaryCard).set_value(
                f"{total:,}"
            )
            self.query_one("#card-unread", SummaryCard).set_value(
                f"{unread:,}"
            )
            self.query_one("#card-starred", SummaryCard).set_value(
                f"{starred:,}"
            )
            self.query_one("#card-attachments", SummaryCard).set_value(
                f"{attachments:,}"
            )
        except Exception:
            logger.debug("Failed to render summary cards", exc_info=True)

    def _render_summary_cards_dashboard(self, data: dict[str, Any]) -> None:
        """Render summary cards from dashboard data (fallback)."""
        try:
            total = data.get("total_emails", 0)
            unread = data.get("total_unread", data.get("unread_emails", 0))
            starred = data.get("starred_emails", 0)
            ai_count = data.get("ai_analyses_count", 0)

            self.query_one("#card-total", SummaryCard).set_value(
                f"{total:,}"
            )
            self.query_one("#card-unread", SummaryCard).set_value(
                f"{unread:,}"
            )
            self.query_one("#card-starred", SummaryCard).set_value(
                f"{starred:,}"
            )
            self.query_one("#card-attachments", SummaryCard).set_value(
                f"{ai_count:,}"
            )
        except Exception:
            logger.debug("Failed to render dashboard cards", exc_info=True)

    def _render_volume_chart(self, data: dict[str, Any]) -> None:
        """Render horizontal bar chart of email volume by day."""
        try:
            volume = data.get("volume_by_day", [])
            if not volume:
                self.query_one("#stats-volume-chart", Static).update(
                    "[dim]No volume data available[/dim]"
                )
                return

            max_count = max((d.get("count", 0) for d in volume), default=1)
            if max_count == 0:
                max_count = 1

            lines = []
            for entry in volume[-14:]:  # Last 14 days
                date_str = entry.get("date", "????-??-??")
                # Show only month-day
                short_date = date_str[-5:] if len(date_str) >= 5 else date_str
                count = entry.get("count", 0)
                bar = _bar(count, max_count, width=30)
                lines.append(
                    f"  {short_date}  [cyan]{bar}[/cyan]  {count}"
                )

            avg = data.get("emails_per_day_avg", 0)
            if avg:
                lines.append(f"\n  [dim]Average: {avg} emails/day[/dim]")

            self.query_one("#stats-volume-chart", Static).update(
                "\n".join(lines)
            )
        except Exception:
            logger.debug("Failed to render volume chart", exc_info=True)

    def _render_category_chart(self, data: dict[str, Any]) -> None:
        """Render AI category breakdown as horizontal bars."""
        try:
            cat_data = data.get("category_over_time", [])
            if not cat_data:
                self.query_one("#stats-category-chart", Static).update(
                    "[dim]No category data available[/dim]"
                )
                return

            # Aggregate categories across all dates
            category_totals: dict[str, int] = {}
            for entry in cat_data:
                cat = entry.get("category", "unknown")
                count = entry.get("count", 0)
                category_totals[cat] = category_totals.get(cat, 0) + count

            if not category_totals:
                self.query_one("#stats-category-chart", Static).update(
                    "[dim]No categories found[/dim]"
                )
                return

            # Sort by count descending
            sorted_cats = sorted(
                category_totals.items(), key=lambda x: x[1], reverse=True
            )
            max_count = sorted_cats[0][1] if sorted_cats else 1

            lines = []
            for cat_name, count in sorted_cats:
                color = CATEGORY_COLORS.get(cat_name, "#9ca3af")
                bar = _bar(count, max_count, width=25)
                label = cat_name.replace("_", " ").title()
                lines.append(
                    f"  {label:<20s}  [{color}]{bar}[/{color}]  {count}"
                )

            self.query_one("#stats-category-chart", Static).update(
                "\n".join(lines)
            )
        except Exception:
            logger.debug("Failed to render category chart", exc_info=True)

    def _render_coverage_info(self, data: dict[str, Any]) -> None:
        """Render AI analysis coverage info."""
        try:
            total = data.get("total_emails", 0)
            analyzed = data.get("total_analyzed", 0)
            models = data.get("models", {})
            unanalyzed = data.get("unanalyzed", {})

            pct = (analyzed / total * 100) if total > 0 else 0
            coverage_bar = _bar(analyzed, total, width=30)

            lines = [
                f"  Analyzed: {analyzed:,} / {total:,}  ({pct:.1f}%)",
                f"  [green]{coverage_bar}[/green]",
                "",
            ]

            if unanalyzed:
                lines.append("  [bold]Unanalyzed:[/bold]")
                for period, count in unanalyzed.items():
                    lines.append(f"    {period}: {count:,}")

            if models:
                lines.append("")
                lines.append("  [bold]By Model:[/bold]")
                for model_name, count in models.items():
                    lines.append(f"    {model_name}: {count:,}")

            self.query_one("#stats-coverage-info", Static).update(
                "\n".join(lines)
            )
        except Exception:
            logger.debug("Failed to render coverage info", exc_info=True)

    def _update_status(self, text: str) -> None:
        """Update the status bar."""
        try:
            self.query_one("#stats-status", Static).update(text)
        except Exception:
            pass

    # ── Actions ──────────────────────────────────────────────

    def action_scroll_down(self) -> None:
        """Scroll down."""
        try:
            self.query_one("#stats-scroll", VerticalScroll).scroll_down()
        except Exception:
            pass

    def action_scroll_up(self) -> None:
        """Scroll up."""
        try:
            self.query_one("#stats-scroll", VerticalScroll).scroll_up()
        except Exception:
            pass

    def action_refresh_data(self) -> None:
        """Refresh all stats data."""
        self._load_all_data()
