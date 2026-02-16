"""Email body renderer widget."""

from __future__ import annotations

from textual.widgets import Static

from tui.utils.html_to_rich import html_to_text


class EmailBodyWidget(Static):
    """Displays the body of an email, converting HTML to text.

    Takes body_html and body_text strings and renders the converted
    content as plain text in the terminal.
    """

    DEFAULT_CSS = """
    EmailBodyWidget {
        width: 100%;
        height: auto;
        padding: 1 2;
    }
    """

    def __init__(
        self,
        body_html: str | None = None,
        body_text: str | None = None,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._body_html = body_html
        self._body_text = body_text

    def on_mount(self) -> None:
        self._render_body()

    def set_body(
        self, body_html: str | None = None, body_text: str | None = None
    ) -> None:
        """Update the displayed email body."""
        self._body_html = body_html
        self._body_text = body_text
        self._render_body()

    def _render_body(self) -> None:
        """Convert and display the email body."""
        text = html_to_text(self._body_html, self._body_text)
        if text:
            # Escape Rich markup in the plain text to prevent rendering issues
            escaped = text.replace("[", "\\[")
            self.update(escaped)
        else:
            self.update("[dim]No content[/dim]")
