"""Chat message widget for displaying user and assistant messages."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.widgets import Static


class ChatMessageWidget(Static):
    """Displays a single chat message with role-based styling.

    User messages are right-aligned with cyan styling.
    Assistant messages are left-aligned and rendered as Markdown.
    """

    DEFAULT_CSS = """
    ChatMessageWidget {
        width: 100%;
        height: auto;
        padding: 0 1;
        margin: 0 0 1 0;
    }

    ChatMessageWidget.user-message {
        text-align: right;
        color: #22d3ee;
    }

    ChatMessageWidget.user-message .chat-role-label {
        color: #22d3ee;
        text-style: bold;
    }

    ChatMessageWidget.user-message .chat-content {
        color: #e2e8f0;
    }

    ChatMessageWidget.assistant-message {
        text-align: left;
    }

    ChatMessageWidget.assistant-message .chat-role-label {
        color: #a78bfa;
        text-style: bold;
    }

    ChatMessageWidget.assistant-message .chat-content {
        color: #e2e8f0;
    }

    .chat-role-label {
        width: 100%;
        height: auto;
    }

    .chat-content {
        width: 100%;
        height: auto;
        padding: 0 0 0 2;
    }
    """

    def __init__(
        self,
        role: str,
        content: str = "",
        **kwargs,
    ) -> None:
        self._role = role
        self._content = content

        classes = kwargs.pop("classes", "")
        role_class = "user-message" if role == "user" else "assistant-message"
        if classes:
            classes = f"{classes} {role_class}"
        else:
            classes = role_class

        super().__init__(classes=classes, **kwargs)

    def compose(self) -> ComposeResult:
        label = "You:" if self._role == "user" else "AI:"
        yield Static(label, classes="chat-role-label")
        yield Static(self._content, classes="chat-content", markup=False)

    def append_content(self, text: str) -> None:
        """Append text to the message content."""
        self._content = text
        try:
            content_widget = self.query_one(".chat-content", Static)
            content_widget.update(text)
        except Exception:
            pass

    @property
    def content(self) -> str:
        """Get the current message content."""
        return self._content
