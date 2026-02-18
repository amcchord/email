"""Email list DataTable widget with modern styling and colored category pills."""

from __future__ import annotations

from typing import Any

from textual.widgets import DataTable

from tui.utils.date_format import relative_date


# AI category display with colored Rich markup pills
CATEGORY_MARKUP: dict[str, str] = {
    "urgent": "[on #ef4444][#ffffff] URGENT [/#ffffff][/on #ef4444]",
    "fyi": "[on #0891b2][#ffffff] FYI [/#ffffff][/on #0891b2]",
    "can_ignore": "[#64748b]ignore[/#64748b]",
    "awaiting_reply": "[on #f59e0b][#0f0f1a] AWAIT [/#0f0f1a][/on #f59e0b]",
    "needs_action": "[on #6366f1][#ffffff] ACTION [/#ffffff][/on #6366f1]",
}


class EmailListWidget(DataTable):
    """DataTable displaying a list of emails with rich formatting.

    Columns: status indicator, from, subject, date, AI category.
    Unread emails are bold, starred emails show a yellow star.
    Categories are displayed as colored pills.
    """

    DEFAULT_CSS = """
    EmailListWidget {
        height: 1fr;
        background: #0f0f1a;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.cursor_type = "row"
        self.zebra_stripes = True
        self._email_id_map: dict[Any, int] = {}
        self._row_key_map: dict[int, Any] = {}
        self._columns_added = False

    def on_mount(self) -> None:
        """Add columns on mount."""
        if not self._columns_added:
            self.add_columns(" ", "From", "Subject", "Date", "Category")
            self._columns_added = True

    def load_emails(self, emails: list[dict[str, Any]]) -> None:
        """Clear and repopulate the table with a list of email dicts."""
        self.clear()
        self._email_id_map.clear()
        self._row_key_map.clear()

        if not self._columns_added:
            self.add_columns(" ", "From", "Subject", "Date", "Category")
            self._columns_added = True

        for email in emails:
            email_id = email.get("id", 0)
            is_read = email.get("is_read", False)
            is_starred = email.get("is_starred", False)

            # Status indicator
            if is_starred:
                indicator = "[#f59e0b]\u2605[/#f59e0b]"
            elif is_read:
                indicator = "[#3d3f5c]\u00b7[/#3d3f5c]"
            else:
                indicator = "[#6366f1]\u25cf[/#6366f1]"

            # From field (wider)
            from_name = email.get("from_name") or email.get("from_address") or ""
            if len(from_name) > 24:
                from_name = from_name[:22] + ".."
            if not is_read:
                from_name = f"[bold]{from_name}[/bold]"

            # Subject
            subject = email.get("subject") or "(no subject)"
            if not is_read:
                subject = f"[bold]{subject}[/bold]"

            # Date
            date_str = f"[#94a3b8]{relative_date(email.get('date'))}[/#94a3b8]"

            # AI category as colored pill
            cat = email.get("ai_category") or ""
            cat_display = CATEGORY_MARKUP.get(cat, f"[#64748b]{cat}[/#64748b]" if cat else "")

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
