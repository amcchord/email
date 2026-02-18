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

# Standard mailboxes with Unicode icons
MAILBOXES = [
    ("INBOX", "\u2709 Inbox"),
    ("STARRED", "\u2605 Starred"),
    ("SENT", "\u27a4 Sent"),
    ("DRAFTS", "\u270e Drafts"),
    ("SPAM", "\u26a0 Spam"),
    ("TRASH", "\u2717 Trash"),
    ("ALL", "\u2261 All Mail"),
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
        ("F", "Focus"),
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
            with Vertical(id="mailbox-sidebar"):
                yield Static("[bold #6366f1]\u2709 Mailboxes[/bold #6366f1]", id="mailbox-header")
                tree: Tree[str] = Tree("Mail", id="mailbox-tree")
                tree.show_root = False
                yield tree
            with Vertical(id="inbox-main"):
                yield Input(
                    placeholder="\u2315  Search emails...",
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

            self._render_email_list(self._emails)
            self._load_labels()

        except Exception as e:
            err_msg = str(e)
            if hasattr(e, "detail") and e.detail:
                err_msg = e.detail
            self._update_status(error=err_msg)

    def _render_email_list(self, emails: list[dict[str, Any]]) -> None:
        """Render the email list and status on the main thread."""
        try:
            table = self.query_one("#email-table", EmailListWidget)
            table.load_emails(emails)
            self._update_status()
        except Exception:
            logger.debug("Failed to render email list", exc_info=True)

    @work(exclusive=True, group="labels")
    async def _load_labels(self) -> None:
        """Fetch labels and update the mailbox tree with user labels."""
        if self._email_client is None:
            return
        try:
            self._labels = await self._email_client.get_labels()
            labels = self._labels
            self._render_labels(labels)
        except Exception:
            logger.debug("Failed to load labels", exc_info=True)

    def _render_labels(self, labels: list[dict[str, Any]]) -> None:
        """Render user labels into the mailbox tree on the main thread."""
        try:
            tree = self.query_one("#mailbox-tree", Tree)
            user_labels = [
                lbl for lbl in labels
                if lbl.get("label_type") == "user"
            ]
            if user_labels:
                has_labels_section = False
                for child in tree.root.children:
                    if hasattr(child, "data") and child.data == "__labels_header__":
                        has_labels_section = True
                        break

                if not has_labels_section:
                    labels_node = tree.root.add("\u2630 Labels", data="__labels_header__")
                    for lbl in user_labels:
                        name = lbl.get("name", "")
                        count = lbl.get("messages_total", 0)
                        display = f"  {name}" if not count else f"  {name} [#2dd4bf]({count})[/#2dd4bf]"
                        labels_node.add_leaf(display, data=lbl.get("name", ""))
                    labels_node.expand()
        except Exception:
            logger.debug("Failed to render labels", exc_info=True)

    def _update_status(self, error: str | None = None) -> None:
        """Update the status bar at the bottom of the inbox."""
        try:
            status = self.query_one("#inbox-status", Static)
            if error:
                status.update(f"[#ef4444]\u26a0 Error: {error}[/#ef4444]")
                return

            unread_count = sum(
                1 for e in self._emails if not e.get("is_read", True)
            )

            focused_indicator = ""
            if self._focused_mode:
                focused_indicator = " [on #2dd4bf][#0f0f1a] FOCUSED [/#0f0f1a][/on #2dd4bf]"

            mailbox_name = self._current_mailbox
            for mid, mname in MAILBOXES:
                if mid == self._current_mailbox:
                    mailbox_name = mname
                    break

            text = (
                f"{mailbox_name} \u2502 "
                f"Page {self._current_page}/{self._total_pages} \u2502 "
                f"[#2dd4bf]{self._total_emails}[/#2dd4bf] emails \u2502 "
                f"[#f59e0b]{unread_count}[/#f59e0b] unread"
                f"{focused_indicator}"
            )
            if self._search_query:
                text += f" \u2502 \u2315 {self._search_query}"
            status.update(text)
        except Exception:
            pass

    # ── Tree selection ----

    def on_tree_node_selected(self, event: Tree.NodeSelected) -> None:
        node = event.node
        if node.data and node.data != "__labels_header__":
            mailbox = node.data
            is_standard = any(m[0] == mailbox for m in MAILBOXES)
            if is_standard:
                self._current_mailbox = mailbox
            else:
                self._current_mailbox = mailbox
            self._current_page = 1
            self._search_query = None
            self._load_emails()

    # ── Search ----

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "search-input":
            query = event.input.value.strip()
            self._search_query = query if query else None
            self._current_page = 1
            self._load_emails()
            try:
                self.query_one("#email-table", EmailListWidget).focus()
            except Exception:
                pass

    # ── Keyboard actions ----

    def action_cursor_down(self) -> None:
        try:
            table = self.query_one("#email-table", EmailListWidget)
            table.action_cursor_down()
        except Exception:
            pass

    def action_cursor_up(self) -> None:
        try:
            table = self.query_one("#email-table", EmailListWidget)
            table.action_cursor_up()
        except Exception:
            pass

    def action_open_email(self) -> None:
        try:
            table = self.query_one("#email-table", EmailListWidget)
            email_id = table.get_selected_email_id()
            if email_id is not None:
                from tui.screens.email_view import EmailViewScreen
                self.app.push_screen(EmailViewScreen(email_id=email_id))
        except Exception:
            logger.debug("Failed to open email", exc_info=True)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        self.action_open_email()

    def action_archive(self) -> None:
        self._perform_action("archive")

    def action_trash(self) -> None:
        self._perform_action("trash")

    def action_toggle_star(self) -> None:
        email_id = self._get_selected_email_id()
        if email_id is None:
            return
        email = self._find_email(email_id)
        if email and email.get("is_starred"):
            self._perform_action("unstar")
        else:
            self._perform_action("star")

    def action_mark_read(self) -> None:
        self._perform_action("mark_read")

    def action_mark_unread(self) -> None:
        self._perform_action("mark_unread")

    def action_spam(self) -> None:
        self._perform_action("spam")

    def action_reply(self) -> None:
        email_id = self._get_selected_email_id()
        if email_id is None:
            return
        email = self._find_email(email_id)
        if email:
            from tui.screens.compose import ComposeScreen
            self.app.push_screen(ComposeScreen(reply_data=email))

    def action_forward(self) -> None:
        email_id = self._get_selected_email_id()
        if email_id is None:
            return
        email = self._find_email(email_id)
        if email:
            from tui.screens.compose import ComposeScreen
            self.app.push_screen(ComposeScreen(forward_data=email))

    def action_focus_search(self) -> None:
        try:
            self.query_one("#search-input", Input).focus()
        except Exception:
            pass

    def action_toggle_focused(self) -> None:
        self._focused_mode = not self._focused_mode
        self._current_page = 1
        self._load_emails()

    def action_next_page(self) -> None:
        if self._current_page < self._total_pages:
            self._current_page += 1
            self._load_emails()

    def action_prev_page(self) -> None:
        if self._current_page > 1:
            self._current_page -= 1
            self._load_emails()

    # ── Helpers ----

    def _get_selected_email_id(self) -> int | None:
        try:
            table = self.query_one("#email-table", EmailListWidget)
            return table.get_selected_email_id()
        except Exception:
            return None

    def _find_email(self, email_id: int) -> dict[str, Any] | None:
        for email in self._emails:
            if email.get("id") == email_id:
                return email
        return None

    @work(exclusive=True, group="action")
    async def _perform_action(self, action: str) -> None:
        if self._email_client is None:
            return
        email_id = self._get_selected_email_id()
        if email_id is None:
            return
        try:
            await self._email_client.perform_actions([email_id], action)
            msg = action.replace('_', ' ').title()
            self.notify(f"\u2713 {msg}", severity="information")
            self._load_emails()
        except Exception as e:
            self.notify(f"Action failed: {e}", severity="error")
