"""Compose editor widget with account selector, address fields, and body."""

from __future__ import annotations

import logging
from typing import Any

from textual.app import ComposeResult
from textual.containers import Vertical, Horizontal
from textual.widget import Widget
from textual.widgets import Input, Select, Static, TextArea

logger = logging.getLogger(__name__)


class ComposeEditorWidget(Widget):
    """Email compose form with account selector, address fields, subject, and body.

    Provides methods to pre-fill fields for reply/forward mode and to
    extract all compose data as a dict for the API.
    """

    DEFAULT_CSS = """
    ComposeEditorWidget {
        width: 100%;
        height: 100%;
    }
    .compose-form {
        width: 100%;
        height: 100%;
    }
    .compose-field-row {
        width: 100%;
        height: 3;
        padding: 0 1;
    }
    .compose-field-label {
        width: 8;
        height: 1;
        padding: 1 0 0 0;
        color: $text-muted;
    }
    .compose-field-input {
        width: 1fr;
        height: 3;
    }
    .compose-account-row {
        width: 100%;
        height: 3;
        padding: 0 1;
    }
    .compose-account-label {
        width: 8;
        height: 1;
        padding: 1 0 0 0;
        color: $text-muted;
    }
    .compose-account-select {
        width: 1fr;
        height: 3;
    }
    .compose-body-area {
        width: 100%;
        height: 1fr;
        padding: 0 1;
    }
    .compose-hidden {
        display: none;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._in_reply_to: str | None = None
        self._references: str | None = None
        self._thread_id: str | None = None
        self._account_id: int | None = None

    def compose(self) -> ComposeResult:
        with Vertical(classes="compose-form"):
            # Account selector row
            with Horizontal(classes="compose-account-row"):
                yield Static("From:", classes="compose-account-label")
                yield Select(
                    [],
                    prompt="Select account...",
                    id="compose-account",
                    classes="compose-account-select",
                )
            # To field
            with Horizontal(classes="compose-field-row"):
                yield Static("To:", classes="compose-field-label")
                yield Input(
                    placeholder="recipient@example.com",
                    id="compose-to",
                    classes="compose-field-input",
                )
            # Cc field (hidden by default)
            with Horizontal(classes="compose-field-row compose-hidden", id="compose-cc-row"):
                yield Static("Cc:", classes="compose-field-label")
                yield Input(
                    placeholder="cc@example.com",
                    id="compose-cc",
                    classes="compose-field-input",
                )
            # Bcc field (hidden by default)
            with Horizontal(classes="compose-field-row compose-hidden", id="compose-bcc-row"):
                yield Static("Bcc:", classes="compose-field-label")
                yield Input(
                    placeholder="bcc@example.com",
                    id="compose-bcc",
                    classes="compose-field-input",
                )
            # Subject field
            with Horizontal(classes="compose-field-row"):
                yield Static("Subj:", classes="compose-field-label")
                yield Input(
                    placeholder="Subject",
                    id="compose-subject",
                    classes="compose-field-input",
                )
            # Body text area
            yield TextArea(
                "",
                id="compose-body",
                classes="compose-body-area",
            )

    def set_accounts(self, accounts: list[dict[str, Any]]) -> None:
        """Populate the account selector with a list of accounts.

        Each account dict should have id, email, and optionally short_label.
        """
        try:
            select_widget = self.query_one("#compose-account", Select)
            options: list[tuple[str, int]] = []
            for acct in accounts:
                label = acct.get("email", "")
                short = acct.get("short_label")
                if short:
                    label = f"{label} ({short})"
                options.append((label, acct["id"]))

            select_widget.set_options(options)

            # Auto-select the first account if only one
            if len(options) == 1:
                select_widget.value = options[0][1]
                self._account_id = options[0][1]
        except Exception:
            logger.debug("Failed to set accounts", exc_info=True)

    def set_reply_data(self, email: dict[str, Any]) -> None:
        """Pre-fill fields for reply mode.

        Sets to=from_address, subject="Re: {subject}", and
        stores in_reply_to, references, thread_id for the API call.
        """
        try:
            # Set To field
            from_addr = email.get("from_address", "")
            to_input = self.query_one("#compose-to", Input)
            to_input.value = from_addr

            # Set Subject
            subject = email.get("subject", "")
            if not subject.startswith("Re: "):
                subject = f"Re: {subject}"
            subj_input = self.query_one("#compose-subject", Input)
            subj_input.value = subject

            # Store threading info
            self._in_reply_to = email.get("message_id_header")
            self._references = email.get("message_id_header")
            self._thread_id = email.get("gmail_thread_id")

            # Set account if account_email is available
            account_email = email.get("account_email")
            if account_email:
                try:
                    select_widget = self.query_one("#compose-account", Select)
                    # Try to find and select the matching account
                    for option_label, option_value in select_widget._options:
                        if account_email in str(option_label):
                            select_widget.value = option_value
                            self._account_id = option_value
                            break
                except Exception:
                    pass
        except Exception:
            logger.debug("Failed to set reply data", exc_info=True)

    def set_forward_data(self, email: dict[str, Any]) -> None:
        """Pre-fill fields for forward mode.

        Sets subject="Fwd: {subject}" and includes quoted original in body.
        """
        try:
            # Set Subject
            subject = email.get("subject", "")
            if not subject.startswith("Fwd: "):
                subject = f"Fwd: {subject}"
            subj_input = self.query_one("#compose-subject", Input)
            subj_input.value = subject

            # Build forwarded body
            from_name = email.get("from_name", "")
            from_addr = email.get("from_address", "")
            date_str = email.get("date", "")
            body_text = email.get("body_text") or email.get("snippet") or ""

            quoted = (
                f"\n\n---------- Forwarded message ----------\n"
                f"From: {from_name} <{from_addr}>\n"
                f"Date: {date_str}\n"
                f"Subject: {email.get('subject', '')}\n\n"
                f"{body_text}"
            )

            body_area = self.query_one("#compose-body", TextArea)
            body_area.load_text(quoted)

            # Store thread_id for context
            self._thread_id = email.get("gmail_thread_id")
        except Exception:
            logger.debug("Failed to set forward data", exc_info=True)

    def set_body_text(self, text: str) -> None:
        """Set the body text area content."""
        try:
            body_area = self.query_one("#compose-body", TextArea)
            body_area.load_text(text)
        except Exception:
            logger.debug("Failed to set body text", exc_info=True)

    def get_compose_data(self) -> dict[str, Any]:
        """Extract all compose fields as a dict ready for the API.

        Returns dict with account_id, to, cc, bcc, subject,
        body_html, body_text, in_reply_to, references, thread_id.
        """
        try:
            select_widget = self.query_one("#compose-account", Select)
            account_id = select_widget.value
            if account_id == Select.BLANK:
                account_id = self._account_id
        except Exception:
            account_id = self._account_id

        to_str = self._get_input_value("compose-to")
        cc_str = self._get_input_value("compose-cc")
        bcc_str = self._get_input_value("compose-bcc")
        subject = self._get_input_value("compose-subject")

        body_text = ""
        try:
            body_area = self.query_one("#compose-body", TextArea)
            body_text = body_area.text
        except Exception:
            pass

        # Convert body_text to simple HTML
        body_html = f"<p>{body_text.replace(chr(10), '<br>')}</p>" if body_text else ""

        # Parse comma-separated addresses
        to_list = self._parse_addresses(to_str)
        cc_list = self._parse_addresses(cc_str)
        bcc_list = self._parse_addresses(bcc_str)

        return {
            "account_id": account_id,
            "to": to_list,
            "cc": cc_list if cc_list else None,
            "bcc": bcc_list if bcc_list else None,
            "subject": subject,
            "body_html": body_html,
            "body_text": body_text,
            "in_reply_to": self._in_reply_to,
            "references": self._references,
            "thread_id": self._thread_id,
        }

    def toggle_cc(self) -> None:
        """Toggle visibility of the Cc field."""
        try:
            cc_row = self.query_one("#compose-cc-row")
            cc_row.toggle_class("compose-hidden")
        except Exception:
            pass

    def toggle_bcc(self) -> None:
        """Toggle visibility of the Bcc field."""
        try:
            bcc_row = self.query_one("#compose-bcc-row")
            bcc_row.toggle_class("compose-hidden")
        except Exception:
            pass

    def focus_body(self) -> None:
        """Focus the body text area."""
        try:
            body_area = self.query_one("#compose-body", TextArea)
            body_area.focus()
        except Exception:
            pass

    def _get_input_value(self, input_id: str) -> str:
        """Get the value of an Input widget by ID."""
        try:
            return self.query_one(f"#{input_id}", Input).value.strip()
        except Exception:
            return ""

    @staticmethod
    def _parse_addresses(text: str) -> list[str]:
        """Parse a comma-separated string of email addresses."""
        if not text:
            return []
        return [
            addr.strip()
            for addr in text.split(",")
            if addr.strip()
        ]
