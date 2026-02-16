"""Inbox screen with email list, mailbox sidebar, and search."""

from __future__ import annotations

import logging
from typing import Any

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Static, Input, Tree, DataTable
from textual import work

from tui.client.emails import EmailClient
from tui.screens.base import BaseScreen
from tui.widgets.email_list import EmailListWidget

logger = logging.getLogger(__name__)

# Standard mailboxes shown in the sidebar tree
MAILBOXES = [
    ("INBOX", "Inbox"),
    ("STARRED", "Starred"),
    ("SENT", "Sent"),
    ("DRAFTS", "Drafts"),
    ("SPAM", "Spam"),
    ("TRASH", "Trash"),
    ("ALL", "All Mail"),
]


class InboxScreen(BaseScreen):
    """Inbox screen with mailbox tree, search, email list, and status bar."""

    SCREEN_TITLE = "Inbox"
    SCREEN_NAV_ID = "inbox"
    DEFAULT_SHORTCUTS = [
        ("j/k", "Nav"),
        ("Enter", "Open"),
        ("e", "Archive"),
        ("s", "Star"),
        ("#", "Trash"),
        ("/", "Search"),
        ("?", "Help"),
    ]

    BINDINGS = [
        *BaseScreen.BINDINGS,
        Binding("j", "cursor_down", "Down", show=False),
        Binding("k", "cursor_up", "Up", show=False),
        Binding("o", "open_email", "Open", show=False),
        Binding("enter", "open_email", "Open", show=False),
        Binding("e", "archive", "Archive", show=False),
        Binding("number_sign", "trash", "Trash", show=False),
        Binding("s", "toggle_star", "Star", show=False),
        Binding("I", "mark_read", "Mark read", show=False),
        Binding("U", "mark_unread", "Mark unread", show=False),
        Binding("exclamation_mark", "spam", "Spam", show=False),
        Binding("r", "reply", "Reply", show=False),
        Binding("f", "forward", "Forward", show=False),
        Binding("slash", "focus_search", "Search", show=False),
        Binding("F", "toggle_focused", "Focus filter", show=False),
        Binding("n", "next_page", "Next page", show=False),
        Binding("p", "prev_page", "Prev page", show=False),
    ]

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._email_client: EmailClient | None = None
        self._current_mailbox: str = "INBOX"
        self._current_page: int = 1
        self._total_pages: int = 1
        self._total_emails: int = 0
        self._page_size: int = 50
        self._search_query: str | None = None
        self._focused_mode: bool = False
        self._emails: list[dict[str, Any]] = []
        self._labels: list[dict[str, Any]] = []
        self._selected_ids: set[int] = set()

    def compose_content(self) -> ComposeResult:
        with Horizontal(id="inbox-layout"):
            # Mailbox sidebar tree
            with Vertical(id="mailbox-sidebar"):
                yield Static("[bold]Mailboxes[/bold]", id="mailbox-header")
                tree: Tree[str] = Tree("Mail", id="mailbox-tree")
                tree.show_root = False
                yield tree
            # Main content area
            with Vertical(id="inbox-main"):
                yield Input(
                    placeholder="Search emails... (press / to focus)",
                    id="search-input",
                )
                yield EmailListWidget(id="email-table")
                yield Static("Loading...", id="inbox-status")

    def on_mount(self) -> None:
        """Initialize email client and load data."""
        super().on_mount()
        self._email_client = EmailClient(self.app.api_client)
        self._build_mailbox_tree()
        self._load_emails()

    def _build_mailbox_tree(self) -> None:
        """Populate the mailbox tree with standard mailboxes."""
        try:
            tree = self.query_one("#mailbox-tree", Tree)
            tree.clear()
            for mailbox_id, mailbox_label in MAILBOXES:
                tree.root.add_leaf(mailbox_label, data=mailbox_id)
            tree.root.expand()
        except Exception:
            logger.debug("Failed to build mailbox tree", exc_info=True)

    @work(exclusive=True)
    async def _load_emails(self) -> None:
        """Fetch emails from the API and populate the list."""
        if self._email_client is None:
            return
        try:
            params: dict[str, Any] = {}
            if self._focused_mode:
                params["exclude_ai_category"] = "can_ignore"

            result = await self._email_client.list_emails(
                mailbox=self._current_mailbox,
                page=self._current_page,
                page_size=self._page_size,
                search=self._search_query,
                **params,
            )

            self._emails = result.get("emails", [])
            self._total_emails = result.get("total", 0)
            self._total_pages = result.get("total_pages", 1)
            self._current_page = result.get("page", 1)

            # Update the email list widget
            email_table = self.query_one("#email-table", EmailListWidget)
            email_table.load_emails(self._emails)

            # Update status bar
            self._update_status()

            # Also load labels for the sidebar
            self._load_labels()

        except Exception as e:
            logger.debug("Failed to load emails", exc_info=True)
            self._update_status(error=str(e))

    @work(exclusive=True, group="labels")
    async def _load_labels(self) -> None:
        """Fetch labels and update the mailbox tree with user labels."""
        if self._email_client is None:
            return
        try:
            self._labels = await self._email_client.get_labels()
            # Add user labels to the tree below standard mailboxes
            tree = self.query_one("#mailbox-tree", Tree)
            # Remove any previously added label nodes beyond the standard ones
            # We rebuild by checking existing leaves
            user_labels = [
                lbl for lbl in self._labels
                if lbl.get("label_type") == "user"
            ]
            if user_labels:
                # Check if we already have a "Labels" section
                has_labels_section = False
                for child in tree.root.children:
                    if hasattr(child, "data") and child.data == "__labels_header__":
                        has_labels_section = True
                        break

                if not has_labels_section:
                    labels_node = tree.root.add("Labels", data="__labels_header__")
                    for lbl in user_labels:
                        name = lbl.get("name", "")
                        count = lbl.get("messages_total", 0)
                        display = f"{name} ({count})" if count else name
                        labels_node.add_leaf(display, data=lbl.get("name", ""))
                    labels_node.expand()
        except Exception:
            logger.debug("Failed to load labels", exc_info=True)

    def _update_status(self, error: str | None = None) -> None:
        """Update the status bar at the bottom of the inbox."""
        try:
            status = self.query_one("#inbox-status", Static)
            if error:
                status.update(f"[red]Error: {error}[/red]")
                return

            unread_count = sum(
                1 for e in self._emails if not e.get("is_read", True)
            )
            focused_indicator = " [yellow][FOCUSED][/yellow]" if self._focused_mode else ""
            mailbox_name = self._current_mailbox
            for mid, mname in MAILBOXES:
                if mid == self._current_mailbox:
                    mailbox_name = mname
                    break

            text = (
                f"{mailbox_name} | "
                f"Page {self._current_page}/{self._total_pages} | "
                f"{self._total_emails} emails | "
                f"{unread_count} unread"
                f"{focused_indicator}"
            )
            if self._search_query:
                text += f" | Search: {self._search_query}"
            status.update(text)
        except Exception:
            pass

    # ── Tree selection ─────────────────────────────────────────

    def on_tree_node_selected(self, event: Tree.NodeSelected) -> None:
        """Handle mailbox selection in the sidebar tree."""
        node = event.node
        if node.data and node.data != "__labels_header__":
            mailbox = node.data
            # Check if this is a standard mailbox
            is_standard = any(m[0] == mailbox for m in MAILBOXES)
            if is_standard:
                self._current_mailbox = mailbox
            else:
                # User label: search within INBOX with that label
                self._current_mailbox = mailbox
            self._current_page = 1
            self._search_query = None
            self._load_emails()

    # ── Search ─────────────────────────────────────────────────

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle search submission."""
        if event.input.id == "search-input":
            query = event.input.value.strip()
            self._search_query = query if query else None
            self._current_page = 1
            self._load_emails()
            # Move focus back to the email list
            try:
                self.query_one("#email-table", EmailListWidget).focus()
            except Exception:
                pass

    # ── Keyboard actions ───────────────────────────────────────

    def action_cursor_down(self) -> None:
        """Move cursor down in the email list."""
        try:
            table = self.query_one("#email-table", EmailListWidget)
            table.action_cursor_down()
        except Exception:
            pass

    def action_cursor_up(self) -> None:
        """Move cursor up in the email list."""
        try:
            table = self.query_one("#email-table", EmailListWidget)
            table.action_cursor_up()
        except Exception:
            pass

    def action_open_email(self) -> None:
        """Open the selected email in detail view."""
        try:
            table = self.query_one("#email-table", EmailListWidget)
            email_id = table.get_selected_email_id()
            if email_id is not None:
                from tui.screens.email_view import EmailViewScreen
                self.app.push_screen(EmailViewScreen(email_id=email_id))
        except Exception:
            logger.debug("Failed to open email", exc_info=True)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Handle double-click / Enter on a row."""
        self.action_open_email()

    def action_archive(self) -> None:
        """Archive the selected email(s)."""
        self._perform_action("archive")

    def action_trash(self) -> None:
        """Trash the selected email(s)."""
        self._perform_action("trash")

    def action_toggle_star(self) -> None:
        """Toggle star on the selected email."""
        email_id = self._get_selected_email_id()
        if email_id is None:
            return
        # Find the email to check current star state
        email = self._find_email(email_id)
        if email and email.get("is_starred"):
            self._perform_action("unstar")
        else:
            self._perform_action("star")

    def action_mark_read(self) -> None:
        """Mark selected email(s) as read."""
        self._perform_action("mark_read")

    def action_mark_unread(self) -> None:
        """Mark selected email(s) as unread."""
        self._perform_action("mark_unread")

    def action_spam(self) -> None:
        """Mark selected email(s) as spam."""
        self._perform_action("spam")

    def action_reply(self) -> None:
        """Reply to the selected email."""
        email_id = self._get_selected_email_id()
        if email_id is None:
            return
        email = self._find_email(email_id)
        if email:
            from tui.screens.compose import ComposeScreen
            self.app.push_screen(ComposeScreen(reply_data=email))

    def action_forward(self) -> None:
        """Forward the selected email."""
        email_id = self._get_selected_email_id()
        if email_id is None:
            return
        email = self._find_email(email_id)
        if email:
            from tui.screens.compose import ComposeScreen
            self.app.push_screen(ComposeScreen(forward_data=email))

    def action_focus_search(self) -> None:
        """Focus the search input."""
        try:
            self.query_one("#search-input", Input).focus()
        except Exception:
            pass

    def action_toggle_focused(self) -> None:
        """Toggle focused filter (exclude can_ignore category)."""
        self._focused_mode = not self._focused_mode
        self._current_page = 1
        self._load_emails()

    def action_next_page(self) -> None:
        """Go to the next page of emails."""
        if self._current_page < self._total_pages:
            self._current_page += 1
            self._load_emails()

    def action_prev_page(self) -> None:
        """Go to the previous page of emails."""
        if self._current_page > 1:
            self._current_page -= 1
            self._load_emails()

    # ── Helpers ─────────────────────────────────────────────────

    def _get_selected_email_id(self) -> int | None:
        """Get the email_id of the currently selected row."""
        try:
            table = self.query_one("#email-table", EmailListWidget)
            return table.get_selected_email_id()
        except Exception:
            return None

    def _find_email(self, email_id: int) -> dict[str, Any] | None:
        """Find an email dict in the current list by id."""
        for email in self._emails:
            if email.get("id") == email_id:
                return email
        return None

    @work(exclusive=True, group="action")
    async def _perform_action(self, action: str) -> None:
        """Perform an email action and reload the list."""
        if self._email_client is None:
            return
        email_id = self._get_selected_email_id()
        if email_id is None:
            return
        try:
            await self._email_client.perform_actions([email_id], action)
            self.notify(f"{action.replace('_', ' ').title()}", severity="information")
            # Reload emails to reflect the change
            self._load_emails()
        except Exception as e:
            self.notify(f"Action failed: {e}", severity="error")
