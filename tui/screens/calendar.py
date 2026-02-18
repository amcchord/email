"""Calendar screen with month, week, and day views."""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.widgets import Static
from textual import work

from tui.client.calendar import CalendarClient
from tui.screens.base import BaseScreen
from tui.widgets.calendar_grid import CalendarGridWidget

logger = logging.getLogger(__name__)


class CalendarScreen(BaseScreen):
    """Calendar screen with month, week, and day views.

    Displays events in a grid layout with navigation controls.
    """

    SCREEN_TITLE = "Calendar"
    SCREEN_NAV_ID = "calendar"
    DEFAULT_SHORTCUTS = [
        ("m/w/d", "View"),
        ("p/n", "Prev/Next"),
        ("t", "Today"),
        ("s", "Sync"),
        ("?", "Help"),
    ]

    BINDINGS = [
        *BaseScreen.BINDINGS,
        Binding("t", "go_today", "Today", show=False),
        Binding("p", "prev_period", "Previous", show=False),
        Binding("n", "next_period", "Next", show=False),
        Binding("m", "month_view", "Month view", show=False),
        Binding("w", "week_view", "Week view", show=False),
        Binding("d", "day_view", "Day view", show=False),
        Binding("s", "sync_calendar", "Sync", show=False),
        Binding("enter", "show_day_detail", "Day detail", show=False),
        Binding("escape", "go_back", "Back", show=False),
    ]

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._calendar_client: CalendarClient | None = None
        self._events: list[dict[str, Any]] = []

    def compose_content(self) -> ComposeResult:
        with Vertical(id="calendar-container"):
            yield Static("", id="calendar-header")
            with VerticalScroll(id="calendar-scroll"):
                yield CalendarGridWidget(id="calendar-grid")
            yield Static("Loading...", id="calendar-status")

    def on_mount(self) -> None:
        """Initialize calendar client and load events."""
        super().on_mount()
        self._calendar_client = CalendarClient(self.app.api_client)
        self._update_header()
        self._load_events()

    def _get_grid(self) -> CalendarGridWidget | None:
        """Get the calendar grid widget."""
        try:
            return self.query_one("#calendar-grid", CalendarGridWidget)
        except Exception:
            return None

    def _update_header(self) -> None:
        """Update the header bar with current view info."""
        grid = self._get_grid()
        if grid is None:
            return

        ref = grid.ref_date
        mode = grid.view_mode

        if mode == "month":
            period_label = ref.strftime("%B %Y")
        elif mode == "week":
            monday = ref - timedelta(days=ref.weekday())
            sunday = monday + timedelta(days=6)
            if monday.month == sunday.month:
                period_label = f"{monday.strftime('%b %d')} - {sunday.strftime('%d, %Y')}"
            else:
                period_label = f"{monday.strftime('%b %d')} - {sunday.strftime('%b %d, %Y')}"
        else:
            period_label = ref.strftime("%A, %B %d, %Y")

        # View mode indicators
        modes = {"month": "M", "week": "W", "day": "D"}
        mode_parts = []
        for m, label in modes.items():
            if m == mode:
                mode_parts.append(f"[bold reverse] {label} [/bold reverse]")
            else:
                mode_parts.append(f"[dim] {label} [/dim]")
        mode_indicator = " ".join(mode_parts)

        header_text = (
            f"  [bold]{period_label}[/bold]"
            f"  {mode_indicator}"
            f"  [dim]p/n: nav | t: today | m/w/d: view | s: sync[/dim]"
        )

        try:
            self.query_one("#calendar-header", Static).update(header_text)
        except Exception:
            pass

    def _update_status(self, text: str | None = None) -> None:
        """Update the status bar."""
        if text is None:
            count = len(self._events)
            text = f"{count} event{'s' if count != 1 else ''}"
        try:
            self.query_one("#calendar-status", Static).update(text)
        except Exception:
            pass

    def _read_date_range(self) -> tuple[str, str] | None:
        """Read the date range from the grid widget (main thread only)."""
        grid = self._get_grid()
        if grid is None:
            return None
        return grid.get_date_range()

    def _apply_events(self) -> None:
        """Apply loaded events to the grid widget (main thread only)."""
        grid = self._get_grid()
        if grid is not None:
            grid.set_events(self._events)

    @work(exclusive=True)
    async def _load_events(self) -> None:
        """Fetch events from the API for the current view range."""
        if self._calendar_client is None:
            return

        date_range = self._read_date_range()
        if date_range is None:
            return

        start_str, end_str = date_range

        try:
            self._update_status("Loading events...")
            result = await self._calendar_client.get_events(
                start=start_str,
                end=end_str,
            )
            self._events = result.get("events", [])
            self._apply_events()
            self._update_status()
        except Exception as e:
            logger.debug("Failed to load calendar events", exc_info=True)
            self._update_status(f"[red]Error: {e}[/red]")

    def _navigate(self, delta: int) -> None:
        """Navigate forward or backward by the current view's period."""
        grid = self._get_grid()
        if grid is None:
            return

        ref = grid.ref_date
        mode = grid.view_mode

        if mode == "month":
            # Move by one month
            if delta > 0:
                if ref.month == 12:
                    new_date = ref.replace(year=ref.year + 1, month=1, day=1)
                else:
                    new_date = ref.replace(month=ref.month + 1, day=1)
            else:
                if ref.month == 1:
                    new_date = ref.replace(year=ref.year - 1, month=12, day=1)
                else:
                    new_date = ref.replace(month=ref.month - 1, day=1)
        elif mode == "week":
            new_date = ref + timedelta(weeks=delta)
        else:
            new_date = ref + timedelta(days=delta)

        grid.set_date(new_date)
        self._update_header()
        self._load_events()

    # ── Keyboard actions ───────────────────────────────────────

    def action_go_today(self) -> None:
        """Jump to today's date."""
        grid = self._get_grid()
        if grid is None:
            return
        grid.set_date(date.today())
        self._update_header()
        self._load_events()

    def action_prev_period(self) -> None:
        """Navigate to the previous period."""
        self._navigate(-1)

    def action_next_period(self) -> None:
        """Navigate to the next period."""
        self._navigate(1)

    def action_month_view(self) -> None:
        """Switch to month view."""
        grid = self._get_grid()
        if grid is not None:
            grid.set_view("month")
            self._update_header()
            self._load_events()

    def action_week_view(self) -> None:
        """Switch to week view."""
        grid = self._get_grid()
        if grid is not None:
            grid.set_view("week")
            self._update_header()
            self._load_events()

    def action_day_view(self) -> None:
        """Switch to day view."""
        grid = self._get_grid()
        if grid is not None:
            grid.set_view("day")
            self._update_header()
            self._load_events()

    def action_show_day_detail(self) -> None:
        """Switch to day view for the current reference date (detail mode)."""
        grid = self._get_grid()
        if grid is not None and grid.view_mode != "day":
            grid.set_view("day")
            self._update_header()
            self._load_events()
        elif grid is not None and self._events:
            # If already in day view, show event info via notification
            events_today = grid._events_for_date(grid.ref_date)
            if events_today:
                event = events_today[0]
                summary = event.get("summary", "(no title)")
                location = event.get("location", "")
                loc_str = f" @ {location}" if location else ""
                self.notify(f"{summary}{loc_str}", severity="information")

    @work(exclusive=True, group="sync")
    async def action_sync_calendar(self) -> None:
        """Trigger a calendar sync."""
        if self._calendar_client is None:
            return
        try:
            self._update_status("Syncing...")
            result = await self._calendar_client.sync()
            msg = result.get("message", "Sync triggered")
            self.notify(msg, severity="information")
            self._load_events()
        except Exception as e:
            self.notify(f"Sync failed: {e}", severity="error")
            self._update_status()

    def action_go_back(self) -> None:
        """Handle escape - go back if possible."""
        grid = self._get_grid()
        if grid is not None and grid.view_mode == "day":
            grid.set_view("week")
            self._update_header()
            self._load_events()
        elif grid is not None and grid.view_mode == "week":
            grid.set_view("month")
            self._update_header()
            self._load_events()
