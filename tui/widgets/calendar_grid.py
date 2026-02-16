"""Calendar grid widget with month, week, and day views."""

from __future__ import annotations

import calendar
from datetime import date, datetime, timedelta
from typing import Any

from rich.style import Style
from rich.table import Table
from rich.text import Text
from textual.widgets import Static


# Color palette for events (cycles if more than available)
EVENT_COLORS = [
    "#4f46e5",  # indigo
    "#0891b2",  # cyan
    "#059669",  # emerald
    "#d97706",  # amber
    "#dc2626",  # red
    "#7c3aed",  # violet
    "#db2777",  # pink
    "#65a30d",  # lime
]


def _parse_event_date(event: dict[str, Any]) -> tuple[date | None, date | None]:
    """Parse start and end dates from an event dict.

    Returns (start_date, end_date) as date objects.
    """
    is_all_day = event.get("is_all_day", False)

    if is_all_day:
        start_str = event.get("start_date", "")
        end_str = event.get("end_date", "")
        try:
            start_d = datetime.strptime(start_str, "%Y-%m-%d").date() if start_str else None
        except (ValueError, TypeError):
            start_d = None
        try:
            end_d = datetime.strptime(end_str, "%Y-%m-%d").date() if end_str else None
        except (ValueError, TypeError):
            end_d = None
        return start_d, end_d
    else:
        start_str = event.get("start_time", "")
        end_str = event.get("end_time", "")
        try:
            start_dt = datetime.fromisoformat(str(start_str).replace("Z", "+00:00")) if start_str else None
            start_d = start_dt.date() if start_dt else None
        except (ValueError, TypeError):
            start_d = None
        try:
            end_dt = datetime.fromisoformat(str(end_str).replace("Z", "+00:00")) if end_str else None
            end_d = end_dt.date() if end_dt else None
        except (ValueError, TypeError):
            end_d = None
        return start_d, end_d


def _parse_event_time(event: dict[str, Any]) -> tuple[int | None, int | None]:
    """Parse start and end hours from a timed event.

    Returns (start_hour, end_hour) or (None, None) for all-day events.
    """
    if event.get("is_all_day", False):
        return None, None

    start_str = event.get("start_time", "")
    end_str = event.get("end_time", "")
    start_hour = None
    end_hour = None

    try:
        start_dt = datetime.fromisoformat(str(start_str).replace("Z", "+00:00"))
        start_hour = start_dt.hour
    except (ValueError, TypeError):
        pass
    try:
        end_dt = datetime.fromisoformat(str(end_str).replace("Z", "+00:00"))
        end_hour = end_dt.hour
    except (ValueError, TypeError):
        pass

    return start_hour, end_hour


def _format_time(event: dict[str, Any]) -> str:
    """Format the time portion of an event for display."""
    if event.get("is_all_day", False):
        return "All day"
    start_str = event.get("start_time", "")
    end_str = event.get("end_time", "")
    try:
        start_dt = datetime.fromisoformat(str(start_str).replace("Z", "+00:00"))
        end_dt = datetime.fromisoformat(str(end_str).replace("Z", "+00:00"))
        return f"{start_dt.strftime('%I:%M%p').lstrip('0').lower()}-{end_dt.strftime('%I:%M%p').lstrip('0').lower()}"
    except (ValueError, TypeError):
        return ""


class CalendarGridWidget(Static):
    """A calendar grid widget that renders month, week, or day views.

    Uses Rich Tables with box-drawing characters for rendering.
    Extends Static and updates its renderable.
    """

    DEFAULT_CSS = """
    CalendarGridWidget {
        width: 100%;
        height: 1fr;
        overflow-y: auto;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__("", **kwargs)
        self._view_mode: str = "month"  # month, week, day
        self._ref_date: date = date.today()
        self._events: list[dict[str, Any]] = []
        self._selected_date: date | None = None

    def set_view(self, mode: str) -> None:
        """Set the view mode: 'month', 'week', or 'day'."""
        if mode in ("month", "week", "day"):
            self._view_mode = mode
            self.render_grid()

    def set_date(self, ref_date: date) -> None:
        """Set the reference date for the view."""
        self._ref_date = ref_date
        self.render_grid()

    def set_events(self, events: list[dict[str, Any]]) -> None:
        """Set the list of event dicts from the API."""
        self._events = events
        self.render_grid()

    @property
    def view_mode(self) -> str:
        """Current view mode."""
        return self._view_mode

    @property
    def ref_date(self) -> date:
        """Current reference date."""
        return self._ref_date

    def render_grid(self) -> None:
        """Rebuild the display based on current mode, date, and events."""
        if self._view_mode == "month":
            renderable = self._render_month()
        elif self._view_mode == "week":
            renderable = self._render_week()
        else:
            renderable = self._render_day()
        self.update(renderable)

    def get_date_range(self) -> tuple[str, str]:
        """Get the start and end dates for the current view as YYYY-MM-DD strings.

        Useful for the parent screen to know what date range to fetch.
        """
        if self._view_mode == "month":
            # Full month range (including days from adjacent months visible in grid)
            first_day = self._ref_date.replace(day=1)
            _, num_days = calendar.monthrange(self._ref_date.year, self._ref_date.month)
            last_day = self._ref_date.replace(day=num_days)
            # Extend to cover the full weeks shown
            start = first_day - timedelta(days=first_day.weekday())  # Monday
            end = last_day + timedelta(days=(6 - last_day.weekday()))  # Sunday
            return start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")
        elif self._view_mode == "week":
            monday = self._ref_date - timedelta(days=self._ref_date.weekday())
            sunday = monday + timedelta(days=6)
            return monday.strftime("%Y-%m-%d"), sunday.strftime("%Y-%m-%d")
        else:
            return self._ref_date.strftime("%Y-%m-%d"), self._ref_date.strftime("%Y-%m-%d")

    def _events_for_date(self, target: date) -> list[dict[str, Any]]:
        """Get events that fall on a given date."""
        result = []
        for event in self._events:
            start_d, end_d = _parse_event_date(event)
            if start_d is None:
                continue
            if end_d is None:
                end_d = start_d
            if start_d <= target <= end_d:
                result.append(event)
        return result

    def _event_color(self, event: dict[str, Any]) -> str:
        """Get a consistent color for an event based on its ID."""
        event_id = event.get("id", 0)
        return EVENT_COLORS[event_id % len(EVENT_COLORS)]

    # ── Month view ─────────────────────────────────────────────

    def _render_month(self) -> Table:
        """Render a month grid with 7 columns (Mon-Sun)."""
        today = date.today()
        year = self._ref_date.year
        month = self._ref_date.month
        _, num_days = calendar.monthrange(year, month)
        first_day = date(year, month, 1)

        table = Table(
            show_header=True,
            header_style="bold cyan",
            border_style="dim",
            expand=True,
            show_lines=True,
            pad_edge=False,
            padding=(0, 1),
        )

        # Add day-of-week columns
        for day_name in ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]:
            table.add_column(day_name, justify="left", ratio=1, no_wrap=False)

        # Calculate the grid - start from the Monday of the week containing the 1st
        start_offset = first_day.weekday()  # 0=Monday
        grid_start = first_day - timedelta(days=start_offset)

        # Build 6 weeks of rows (standard calendar grid)
        for week in range(6):
            row_cells = []
            week_start = grid_start + timedelta(days=week * 7)

            # Stop if we've passed the month entirely
            if week > 0 and week_start.month != month and week_start > date(year, month, num_days):
                break

            for dow in range(7):
                cell_date = week_start + timedelta(days=dow)
                events_today = self._events_for_date(cell_date)

                cell = Text()

                # Date number
                if cell_date == today:
                    cell.append(f"{cell_date.day:>2}", style=Style(bold=True, bgcolor="rgb(79,70,229)", color="white"))
                elif cell_date.month != month:
                    cell.append(f"{cell_date.day:>2}", style="dim")
                else:
                    cell.append(f"{cell_date.day:>2}", style="bold")

                # Show up to 2 event titles
                for i, event in enumerate(events_today[:2]):
                    summary = event.get("summary", "")[:12]
                    color = self._event_color(event)
                    cell.append("\n")
                    cell.append(f" {summary}", style=Style(color=color))

                if len(events_today) > 2:
                    cell.append(f"\n +{len(events_today) - 2} more", style="dim italic")

                row_cells.append(cell)

            table.add_row(*row_cells)

        return table

    # ── Week view ──────────────────────────────────────────────

    def _render_week(self) -> Table:
        """Render a week view with 7 columns and hourly rows (8am-8pm)."""
        today = date.today()
        monday = self._ref_date - timedelta(days=self._ref_date.weekday())

        table = Table(
            show_header=True,
            header_style="bold cyan",
            border_style="dim",
            expand=True,
            show_lines=True,
            pad_edge=False,
            padding=(0, 0),
        )

        # Time column
        table.add_column("Time", width=6, style="dim")

        # Day columns with date headers
        for dow in range(7):
            col_date = monday + timedelta(days=dow)
            day_label = col_date.strftime("%a %d")
            style = "bold reverse" if col_date == today else "bold"
            table.add_column(day_label, ratio=1, no_wrap=False, header_style=style)

        # Build rows for each hour from 8am to 8pm
        for hour in range(8, 21):
            time_label = f"{hour:>2}:00"
            row_cells = [Text(time_label, style="dim")]

            for dow in range(7):
                col_date = monday + timedelta(days=dow)
                events_today = self._events_for_date(col_date)

                cell = Text()
                slot_events = []

                for event in events_today:
                    if event.get("is_all_day", False):
                        # All-day events shown only in the 8am row
                        if hour == 8:
                            slot_events.append(event)
                    else:
                        start_h, end_h = _parse_event_time(event)
                        if start_h is not None and end_h is not None:
                            if start_h <= hour < end_h:
                                slot_events.append(event)
                        elif start_h is not None and start_h == hour:
                            slot_events.append(event)

                for event in slot_events[:2]:
                    summary = event.get("summary", "")[:10]
                    color = self._event_color(event)
                    if cell.plain:
                        cell.append("\n")
                    cell.append(summary, style=Style(color=color, bold=True))

                if not cell.plain:
                    row_cells.append(cell)
                else:
                    row_cells.append(Text(""))

            table.add_row(*row_cells)

        return table

    # ── Day view ───────────────────────────────────────────────

    def _render_day(self) -> Table:
        """Render a single-day timeline view with full event details."""
        today = date.today()
        target = self._ref_date

        table = Table(
            show_header=True,
            header_style="bold cyan",
            border_style="dim",
            expand=True,
            show_lines=True,
            pad_edge=False,
            padding=(0, 1),
        )

        day_label = target.strftime("%A, %B %d, %Y")
        if target == today:
            day_label += "  (today)"

        table.add_column("Time", width=12, style="dim")
        table.add_column(day_label, ratio=1, no_wrap=False)

        events_today = self._events_for_date(target)

        # All-day events at the top
        all_day = [e for e in events_today if e.get("is_all_day", False)]
        if all_day:
            cell = Text()
            for event in all_day:
                summary = event.get("summary", "(no title)")
                color = self._event_color(event)
                if cell.plain:
                    pass
                else:
                    cell.append("\n")
                cell.append(f"  {summary}", style=Style(color=color, bold=True))
                location = event.get("location", "")
                if location:
                    cell.append(f"  @ {location}", style="dim")
            table.add_row(Text("All day", style="bold"), cell)

        # Hourly slots from 7am to 9pm
        for hour in range(7, 22):
            time_label = f"{hour:>2}:00"
            slot_events = []

            for event in events_today:
                if event.get("is_all_day", False):
                    continue
                start_h, end_h = _parse_event_time(event)
                if start_h is not None:
                    effective_end = end_h if end_h is not None else start_h + 1
                    if start_h <= hour < effective_end:
                        slot_events.append(event)

            cell = Text()
            for event in slot_events:
                summary = event.get("summary", "(no title)")
                color = self._event_color(event)
                time_str = _format_time(event)
                location = event.get("location", "")
                attendees = event.get("attendees") or []

                if cell.plain:
                    pass
                else:
                    cell.append("\n")

                cell.append(f"  {summary}", style=Style(color=color, bold=True))
                cell.append(f"  {time_str}", style="dim")
                if location:
                    cell.append(f"\n    @ {location}", style="dim italic")
                if attendees:
                    names = ", ".join(
                        a.get("displayName", a.get("email", ""))
                        for a in attendees[:4]
                    )
                    if len(attendees) > 4:
                        names += f" +{len(attendees) - 4}"
                    cell.append(f"\n    {names}", style="dim")

            table.add_row(Text(time_label), cell if cell.plain else cell)

        return table
