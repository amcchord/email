"""Email list DataTable widget for displaying emails."""

from __future__ import annotations

from typing import Any

from textual.widgets import DataTable

from tui.utils.date_format import relative_date


# AI category short labels with Rich markup
CATEGORY_MARKUP: dict[str, str] = {
    "urgent": "[bold red]URGENT[/bold red]",
    "fyi": "[cyan]FYI[/cyan]",
    "can_ignore": "[dim]ignore[/dim]",
    "awaiting_reply": "[yellow]await[/yellow]",
}


class EmailListWidget(DataTable):
    """DataTable displaying a list of emails.

    Columns: status indicator, from, subject, date, AI category.
    Rows are formatted with bold for unread, star/read indicators.
    """

    DEFAULT_CSS = """
    EmailListWidget {
        height: 1fr;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.cursor_type = "row"
        self.zebra_stripes = True
        self._email_id_map: dict[Any, int] = {}  # row_key -> email_id
        self._row_key_map: dict[int, Any] = {}  # email_id -> row_key
        self._columns_added = False

    def on_mount(self) -> None:
        """Add columns on mount."""
        if not self._columns_added:
            self.add_columns("", "From", "Subject", "Date", "Cat")
            self._columns_added = True

    def load_emails(self, emails: list[dict[str, Any]]) -> None:
        """Clear and repopulate the table with a list of email dicts."""
        self.clear()
        self._email_id_map.clear()
        self._row_key_map.clear()

        if not self._columns_added:
            self.add_columns("", "From", "Subject", "Date", "Cat")
            self._columns_added = True

        for email in emails:
            email_id = email.get("id", 0)
            is_read = email.get("is_read", False)
            is_starred = email.get("is_starred", False)

            # Status indicator
            if is_starred:
                indicator = "[yellow]\u2605[/yellow]"
            elif is_read:
                indicator = "[dim]\u00b7[/dim]"
            else:
                indicator = "[bold blue]\u25cf[/bold blue]"

            # From field
            from_name = email.get("from_name") or email.get("from_address") or ""
            if len(from_name) > 20:
                from_name = from_name[:18] + ".."

            # Subject
            subject = email.get("subject") or "(no subject)"
            if not is_read:
                subject = f"[bold]{subject}[/bold]"

            # Date
            date_str = relative_date(email.get("date"))

            # AI category
            cat = email.get("ai_category") or ""
            cat_display = CATEGORY_MARKUP.get(cat, cat)

            row_key = self.add_row(
                indicator,
                from_name,
                subject,
                date_str,
                cat_display,
                key=str(email_id),
            )
            self._email_id_map[row_key] = email_id
            self._row_key_map[email_id] = row_key

    def get_selected_email_id(self) -> int | None:
        """Return the email_id of the currently highlighted row."""
        if self.row_count == 0:
            return None
        try:
            row_key, _ = self.coordinate_to_cell_key(self.cursor_coordinate)
            return self._email_id_map.get(row_key)
        except Exception:
            return None
