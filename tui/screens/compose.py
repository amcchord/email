"""Compose screen for sending and drafting emails with modern styling."""

from __future__ import annotations

import logging
from typing import Any

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Static
from textual import work

from tui.client.accounts import AccountsClient
from tui.client.compose import ComposeClient
from tui.widgets.compose_editor import ComposeEditorWidget

logger = logging.getLogger(__name__)


class ComposeScreen(Screen):
    """Email compose screen pushed as an overlay.

    Can be initialized with reply_data or forward_data dicts to
    pre-fill fields for reply/forward mode.

    Escape pops back to the previous screen.
    """

    BINDINGS = [
        Binding("escape", "go_back", "Back", show=True),
        Binding("ctrl+s", "save_draft", "Save Draft", show=True),
    ]

    DEFAULT_CSS = """
    ComposeScreen {
        background: #0f0f1a;
    }
    #compose-container {
        width: 100%;
        height: 100%;
    }
    #compose-title-bar {
        width: 100%;
        height: 1;
        background: #6366f1;
        color: #ffffff;
        padding: 0 1;
        text-style: bold;
    }
    #compose-hints {
        dock: bottom;
        width: 100%;
        height: 1;
        background: #1a1b2e;
        color: #94a3b8;
        padding: 0 1;
    }
    """

    def __init__(
        self,
        reply_data: dict[str, Any] | None = None,
        forward_data: dict[str, Any] | None = None,
        initial_body: str | None = None,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._reply_data = reply_data
        self._forward_data = forward_data
        self._initial_body = initial_body
        self._accounts_client: AccountsClient | None = None
        self._compose_client: ComposeClient | None = None

    def compose(self) -> ComposeResult:
        # Title with mode badge
        if self._reply_data:
            title = "\u21a9  Reply"
            badge = "[on #2dd4bf][#0f0f1a] REPLY [/#0f0f1a][/on #2dd4bf] "
        elif self._forward_data:
            title = "\u27a4  Forward"
            badge = "[on #f59e0b][#0f0f1a] FWD [/#0f0f1a][/on #f59e0b] "
        else:
            title = "\u270e  Compose"
            badge = "[on #6366f1][#ffffff] NEW [/#ffffff][/on #6366f1] "

        with Vertical(id="compose-container"):
            yield Static(f" {badge}{title}", id="compose-title-bar")
            yield ComposeEditorWidget(id="compose-editor")
            yield Static(
                "[reverse] Ctrl+Enter [/reverse] Send  "
                "[reverse] Ctrl+s [/reverse] Draft  "
                "[reverse] Esc [/reverse] Back  "
                "[reverse] Ctrl+Shift+c [/reverse] Cc  "
                "[reverse] Ctrl+Shift+b [/reverse] Bcc",
                id="compose-hints",
            )

    def on_mount(self) -> None:
        """Initialize clients and load accounts."""
        self._accounts_client = AccountsClient(self.app.api_client)
        self._compose_client = ComposeClient(self.app.api_client)
        self._load_accounts()

    @work(exclusive=True)
    async def _load_accounts(self) -> None:
        """Fetch accounts list and populate the selector."""
        if self._accounts_client is None:
            return
        try:
            accounts = await self._accounts_client.list_accounts()
            self._apply_accounts(accounts)
        except Exception as e:
            logger.debug("Failed to load accounts", exc_info=True)
            self.notify(f"Failed to load accounts: {e}", severity="error")

    def _apply_accounts(self, accounts: list) -> None:
        """Apply account data to the compose editor (main thread only)."""
        editor = self.query_one("#compose-editor", ComposeEditorWidget)
        editor.set_accounts(accounts)

        if self._reply_data:
            editor.set_reply_data(self._reply_data)
        elif self._forward_data:
            editor.set_forward_data(self._forward_data)

        if self._initial_body:
            editor.set_body_text(self._initial_body)

        if self._reply_data or self._forward_data or self._initial_body:
            editor.focus_body()

    def on_key(self, event) -> None:
        """Handle key events that Textual bindings cannot capture directly."""
        key = event.key
        if key == "ctrl+j" or key == "ctrl+enter":
            event.prevent_default()
            event.stop()
            self._do_send()
            return
        if key == "ctrl+shift+c":
            event.prevent_default()
            event.stop()
            self._toggle_cc()
            return
        if key == "ctrl+shift+b":
            event.prevent_default()
            event.stop()
            self._toggle_bcc()
            return

    def action_go_back(self) -> None:
        self.app.pop_screen()

    def _toggle_cc(self) -> None:
        try:
            editor = self.query_one("#compose-editor", ComposeEditorWidget)
            editor.toggle_cc()
        except Exception:
            pass

    def _toggle_bcc(self) -> None:
        try:
            editor = self.query_one("#compose-editor", ComposeEditorWidget)
            editor.toggle_bcc()
        except Exception:
            pass

    def _read_compose_data(self) -> dict[str, Any]:
        """Read compose data from the editor widget (main thread only)."""
        editor = self.query_one("#compose-editor", ComposeEditorWidget)
        return editor.get_compose_data()

    @work(exclusive=True, group="send")
    async def _do_send(self) -> None:
        """Validate and send the email."""
        if self._compose_client is None:
            return
        try:
            data = self._read_compose_data()

            if not data.get("account_id"):
                self.notify("Please select an account", severity="warning")
                return
            if not data.get("to"):
                self.notify("Please enter a recipient", severity="warning")
                return
            if not data.get("subject"):
                self.notify("Please enter a subject", severity="warning")
                return

            result = await self._compose_client.send_email(
                account_id=data["account_id"],
                to=data["to"],
                subject=data["subject"],
                body_html=data["body_html"],
                body_text=data["body_text"],
                cc=data.get("cc"),
                bcc=data.get("bcc"),
                in_reply_to=data.get("in_reply_to"),
                references=data.get("references"),
                thread_id=data.get("thread_id"),
            )

            self.notify("\u2713 Email sent!", severity="information")
            self.app.pop_screen()

        except Exception as e:
            logger.debug("Failed to send email", exc_info=True)
            self.notify(f"Send failed: {e}", severity="error")

    @work(exclusive=True, group="draft")
    async def action_save_draft(self) -> None:
        """Save the current compose as a draft."""
        if self._compose_client is None:
            return
        try:
            data = self._read_compose_data()

            if not data.get("account_id"):
                self.notify("Please select an account", severity="warning")
                return

            result = await self._compose_client.save_draft(
                account_id=data["account_id"],
                to=data.get("to", []),
                subject=data.get("subject", ""),
                body_html=data.get("body_html", ""),
                body_text=data.get("body_text", ""),
                cc=data.get("cc"),
                bcc=data.get("bcc"),
                in_reply_to=data.get("in_reply_to"),
                references=data.get("references"),
                thread_id=data.get("thread_id"),
            )

            self.notify("\u2713 Draft saved!", severity="information")

        except Exception as e:
            logger.debug("Failed to save draft", exc_info=True)
            self.notify(f"Draft save failed: {e}", severity="error")
