"""Email view screen showing full email detail and thread."""

from __future__ import annotations

import logging
from typing import Any

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Static
from textual import work

from tui.client.emails import EmailClient
from tui.widgets.category_badge import CategoryBadge
from tui.widgets.email_body import EmailBodyWidget
from tui.widgets.thread_view import ThreadViewWidget

logger = logging.getLogger(__name__)


class EmailViewScreen(Screen):
    """Full email detail view with thread support.

    Pushed on top of InboxScreen so Escape pops back.
    Does not use BaseScreen to avoid double sidebar/header;
    it is a focused view screen.
    """

    BINDINGS = [
        Binding("escape", "go_back", "Back", show=True),
        Binding("r", "reply", "Reply", show=False),
        Binding("f", "forward", "Forward", show=False),
        Binding("e", "archive", "Archive", show=False),
        Binding("number_sign", "trash", "Trash", show=False),
        Binding("s", "toggle_star", "Star", show=False),
    ]

    DEFAULT_CSS = """
    EmailViewScreen {
        background: $background;
    }
    #email-view-container {
        width: 100%;
        height: 100%;
    }
    #email-header-section {
        width: 100%;
        height: auto;
        padding: 1 2;
        background: $surface;
    }
    #email-subject {
        width: 100%;
        text-style: bold;
        padding: 0 0 1 0;
    }
    #email-meta {
        width: 100%;
        color: $text-muted;
    }
    #email-ai-section {
        width: 100%;
        height: auto;
        padding: 0 2;
        background: $surface;
    }
    #email-ai-summary {
        width: 100%;
        padding: 0 0 1 0;
    }
    #email-body-section {
        width: 100%;
        height: 1fr;
    }
    #email-action-hints {
        dock: bottom;
        width: 100%;
        height: 1;
        background: $surface;
        color: $text-muted;
        padding: 0 1;
    }
    """

    def __init__(self, email_id: int, **kwargs) -> None:
        super().__init__(**kwargs)
        self._email_id = email_id
        self._email_client: EmailClient | None = None
        self._email_data: dict[str, Any] | None = None
        self._thread_data: dict[str, Any] | None = None

    def compose(self) -> ComposeResult:
        with Vertical(id="email-view-container"):
            # Header section with subject, from, to, date
            with Vertical(id="email-header-section"):
                yield Static("Loading...", id="email-subject")
                yield Static("", id="email-meta")
            # AI analysis section
            with Vertical(id="email-ai-section"):
                yield CategoryBadge(id="email-category-badge")
                yield Static("", id="email-ai-summary")
            # Body section (scrollable)
            with VerticalScroll(id="email-body-section"):
                yield EmailBodyWidget(id="email-body")
                yield ThreadViewWidget(id="email-thread")
            # Action hints at the bottom
            yield Static(
                "[bold]r[/bold] Reply  "
                "[bold]f[/bold] Forward  "
                "[bold]e[/bold] Archive  "
                "[bold]#[/bold] Trash  "
                "[bold]s[/bold] Star  "
                "[bold]Esc[/bold] Back",
                id="email-action-hints",
            )

    def on_mount(self) -> None:
        """Fetch the email and thread data."""
        self._email_client = EmailClient(self.app.api_client)
        self._fetch_email()

    @work(exclusive=True)
    async def _fetch_email(self) -> None:
        """Load the full email detail from the API."""
        if self._email_client is None:
            return
        try:
            self._email_data = await self._email_client.get_email(self._email_id)
            self._render_email()

            # Mark as read if not already
            if self._email_data and not self._email_data.get("is_read", True):
                try:
                    await self._email_client.perform_actions(
                        [self._email_id], "mark_read"
                    )
                except Exception:
                    pass

            # Fetch thread if thread_id exists
            thread_id = self._email_data.get("gmail_thread_id")
            if thread_id:
                self._fetch_thread(thread_id)

        except Exception as e:
            logger.debug("Failed to fetch email", exc_info=True)
            try:
                self.query_one("#email-subject", Static).update(
                    f"[red]Error loading email: {e}[/red]"
                )
            except Exception:
                pass

    @work(exclusive=True, group="thread")
    async def _fetch_thread(self, thread_id: str) -> None:
        """Load the thread messages from the API."""
        if self._email_client is None:
            return
        try:
            self._thread_data = await self._email_client.get_thread(thread_id)
            messages = self._thread_data.get("emails", [])
            if len(messages) > 1:
                # Show thread view, hide single-email body
                try:
                    body_widget = self.query_one("#email-body", EmailBodyWidget)
                    body_widget.display = False
                except Exception:
                    pass
                try:
                    thread_widget = self.query_one("#email-thread", ThreadViewWidget)
                    thread_widget.load_thread(messages)
                except Exception:
                    pass
            else:
                # Single message thread, hide the thread view
                try:
                    thread_widget = self.query_one("#email-thread", ThreadViewWidget)
                    thread_widget.display = False
                except Exception:
                    pass
        except Exception:
            logger.debug("Failed to fetch thread", exc_info=True)

    def _render_email(self) -> None:
        """Render the email data into the widgets."""
        email = self._email_data
        if not email:
            return

        # Subject
        subject = email.get("subject") or "(no subject)"
        try:
            self.query_one("#email-subject", Static).update(subject)
        except Exception:
            pass

        # Meta: from, to, cc, date
        from_name = email.get("from_name") or email.get("from_address") or "Unknown"
        from_addr = email.get("from_address") or ""
        from_line = f"From: [bold]{from_name}[/bold]"
        if from_addr and from_addr != from_name:
            from_line += f" <{from_addr}>"

        to_addrs = email.get("to_addresses") or []
        to_line = "To: " + self._format_addresses(to_addrs)

        cc_addrs = email.get("cc_addresses") or []
        cc_line = ""
        if cc_addrs:
            cc_line = "\nCc: " + self._format_addresses(cc_addrs)

        from tui.utils.date_format import relative_date
        date_str = relative_date(email.get("date"))

        meta_text = f"{from_line}\n{to_line}{cc_line}\nDate: {date_str}"

        try:
            self.query_one("#email-meta", Static).update(meta_text)
        except Exception:
            pass

        # AI section
        ai_category = email.get("ai_category")
        try:
            badge = self.query_one("#email-category-badge", CategoryBadge)
            badge.set_category(ai_category)
        except Exception:
            pass

        ai_summary = email.get("ai_summary")
        ai_priority = email.get("ai_priority")
        ai_parts = []
        if ai_priority is not None:
            ai_parts.append(f"Priority: {ai_priority}")
        if ai_summary:
            ai_parts.append(f"Summary: {ai_summary}")
        ai_text = "  ".join(ai_parts) if ai_parts else ""
        try:
            self.query_one("#email-ai-summary", Static).update(ai_text)
            # Hide AI section if no data
            ai_section = self.query_one("#email-ai-section")
            if not ai_category and not ai_text:
                ai_section.display = False
        except Exception:
            pass

        # Body
        try:
            body_widget = self.query_one("#email-body", EmailBodyWidget)
            body_widget.set_body(
                email.get("body_html"),
                email.get("body_text"),
            )
        except Exception:
            pass

    def _format_addresses(self, addresses: list) -> str:
        """Format a list of address dicts or strings for display."""
        parts = []
        for addr in addresses:
            if isinstance(addr, dict):
                name = addr.get("name", "")
                address = addr.get("address", "")
                if name and name != address:
                    parts.append(f"{name} <{address}>")
                else:
                    parts.append(address)
            else:
                parts.append(str(addr))
        return ", ".join(parts) if parts else ""

    # ── Actions ────────────────────────────────────────────────

    def action_go_back(self) -> None:
        """Pop this screen and return to inbox."""
        self.app.pop_screen()

    def action_reply(self) -> None:
        """Reply to the current email."""
        if self._email_data:
            from tui.screens.compose import ComposeScreen
            self.app.push_screen(ComposeScreen(reply_data=self._email_data))

    def action_forward(self) -> None:
        """Forward the current email."""
        if self._email_data:
            from tui.screens.compose import ComposeScreen
            self.app.push_screen(ComposeScreen(forward_data=self._email_data))

    @work(exclusive=True, group="action")
    async def action_archive(self) -> None:
        """Archive the current email."""
        if self._email_client is None:
            return
        try:
            await self._email_client.perform_actions([self._email_id], "archive")
            self.notify("Archived", severity="information")
            self.app.pop_screen()
        except Exception as e:
            self.notify(f"Archive failed: {e}", severity="error")

    @work(exclusive=True, group="action")
    async def action_trash(self) -> None:
        """Trash the current email."""
        if self._email_client is None:
            return
        try:
            await self._email_client.perform_actions([self._email_id], "trash")
            self.notify("Trashed", severity="information")
            self.app.pop_screen()
        except Exception as e:
            self.notify(f"Trash failed: {e}", severity="error")

    @work(exclusive=True, group="action")
    async def action_toggle_star(self) -> None:
        """Toggle star on the current email."""
        if self._email_client is None or self._email_data is None:
            return
        try:
            action = "unstar" if self._email_data.get("is_starred") else "star"
            await self._email_client.perform_actions([self._email_id], action)
            self._email_data["is_starred"] = not self._email_data.get("is_starred", False)
            self.notify(
                "Starred" if self._email_data["is_starred"] else "Unstarred",
                severity="information",
            )
        except Exception as e:
            self.notify(f"Star toggle failed: {e}", severity="error")
