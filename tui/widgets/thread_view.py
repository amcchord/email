"""Thread view widget for displaying a conversation of email messages."""

from __future__ import annotations

from typing import Any

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Static, Collapsible

from tui.utils.date_format import relative_date
from tui.utils.html_to_rich import html_to_text


class ThreadMessageWidget(Static):
    """A single message within a thread, showing from, date, and body."""

    DEFAULT_CSS = """
    ThreadMessageWidget {
        width: 100%;
        height: auto;
        padding: 0 1;
        margin: 0 0 1 0;
    }
    """

    def __init__(self, message: dict[str, Any], **kwargs) -> None:
        super().__init__(**kwargs)
        self._message = message

    def on_mount(self) -> None:
        msg = self._message
        from_name = msg.get("from_name") or msg.get("from_address") or "Unknown"
        date_str = relative_date(msg.get("date"))

        body = html_to_text(msg.get("body_html"), msg.get("body_text"))
        if body:
            body_escaped = body.replace("[", "\\[")
        else:
            body_escaped = "[dim]No content[/dim]"

        content = (
            f"[bold]{from_name}[/bold]  [dim]{date_str}[/dim]\n"
            f"{body_escaped}"
        )
        self.update(content)


class ThreadViewWidget(VerticalScroll):
    """Scrollable container showing all messages in a thread.

    Each message is shown in a collapsible section. The most recent
    message is expanded by default; earlier messages are collapsed
    and show only the header line (from + date).
    """

    DEFAULT_CSS = """
    ThreadViewWidget {
        width: 100%;
        height: 1fr;
        padding: 1 0;
    }
    """

    def load_thread(self, messages: list[dict[str, Any]]) -> None:
        """Populate the thread view with messages.

        Messages should be in chronological order (oldest first).
        The last message is expanded; others are collapsed.
        """
        self.remove_children()

        if not messages:
            self.mount(Static("[dim]No messages in thread[/dim]"))
            return

        for i, msg in enumerate(messages):
            is_last = i == len(messages) - 1
            from_name = msg.get("from_name") or msg.get("from_address") or "Unknown"
            date_str = relative_date(msg.get("date"))
            title = f"{from_name} - {date_str}"

            collapsible = Collapsible(
                ThreadMessageWidget(msg),
                title=title,
                collapsed=not is_last,
            )
            self.mount(collapsible)
