"""Chat screen with SSE streaming, conversation list, and message display."""

from __future__ import annotations

import json
import logging
from typing import Any

from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Static, Input, ListView, ListItem

from tui.client.chat import ChatClient
from tui.screens.base import BaseScreen
from tui.widgets.chat_message import ChatMessageWidget

logger = logging.getLogger(__name__)


class ConversationItem(ListItem):
    """A conversation in the sidebar list."""

    DEFAULT_CSS = """
    ConversationItem {
        width: 100%;
        height: auto;
        padding: 0 1;
    }
    ConversationItem > Static {
        width: 100%;
        height: auto;
    }
    """

    def __init__(self, conv_data: dict[str, Any], **kwargs) -> None:
        super().__init__(**kwargs)
        self.conv_data = conv_data

    def compose(self) -> ComposeResult:
        title = self.conv_data.get("title") or "Untitled"
        if len(title) > 30:
            title = title[:27] + "..."
        yield Static(title)


class ChatScreen(BaseScreen):
    """Chat screen with conversation list and streaming message display."""

    SCREEN_TITLE = "Chat"
    SCREEN_NAV_ID = "chat"
    DEFAULT_SHORTCUTS = [
        ("n", "New"),
        ("j/k", "Nav"),
        ("i", "Input"),
        ("Enter", "Send"),
        ("Esc", "Back"),
        ("?", "Help"),
    ]

    BINDINGS = [
        *BaseScreen.BINDINGS,
        Binding("n", "new_conversation", "New conversation", show=False),
        Binding("j", "cursor_down", "Down", show=False),
        Binding("k", "cursor_up", "Up", show=False),
        Binding("i", "focus_input", "Focus input", show=False),
        Binding("escape", "unfocus", "Unfocus", show=False),
        Binding("d", "delete_conversation", "Delete", show=False),
    ]

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._chat_client: ChatClient | None = None
        self._conversation_id: int | None = None
        self._conversations: list[dict[str, Any]] = []
        self._streaming = False
        self._accumulated_text = ""

    def compose_content(self) -> ComposeResult:
        with Horizontal(id="chat-layout"):
            # Left panel: conversation list
            with Vertical(id="chat-sidebar"):
                yield Static(
                    "[bold]Conversations[/bold]", id="chat-sidebar-header"
                )
                yield ListView(id="chat-conv-list")

            # Right panel: messages + input
            with Vertical(id="chat-main"):
                yield VerticalScroll(id="chat-messages")
                yield Input(
                    placeholder="Type a message... (Enter to send)",
                    id="chat-input",
                )
                yield Static("", id="chat-status")

    def on_mount(self) -> None:
        """Initialize chat client and load conversations."""
        super().on_mount()
        self._chat_client = ChatClient(self.app.api_client)
        self._load_conversations()

    @work(exclusive=True, group="load-convs")
    async def _load_conversations(self) -> None:
        """Fetch conversation list from the API."""
        if self._chat_client is None:
            return
        try:
            self._conversations = await self._chat_client.list_conversations()
            self._populate_conversation_list()
        except Exception as e:
            logger.debug("Failed to load conversations", exc_info=True)
            self._update_status(f"Failed to load conversations: {e}")

    def _populate_conversation_list(self) -> None:
        """Populate the sidebar with conversation items."""
        try:
            listview = self.query_one("#chat-conv-list", ListView)
            listview.clear()

            if not self._conversations:
                listview.append(
                    ListItem(Static("  [dim]No conversations yet[/dim]"))
                )
                return

            for conv in self._conversations:
                listview.append(ConversationItem(conv))
        except Exception:
            logger.debug("Failed to populate conversation list", exc_info=True)

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Handle conversation selection."""
        item = event.item
        if isinstance(item, ConversationItem):
            conv_id = item.conv_data.get("id")
            if conv_id:
                self._conversation_id = conv_id
                self._load_conversation(conv_id)

    @work(exclusive=True, group="load-conv")
    async def _load_conversation(self, conv_id: int) -> None:
        """Load a conversation's messages."""
        if self._chat_client is None:
            return
        try:
            data = await self._chat_client.get_conversation(conv_id)
            messages = data.get("messages", [])
            self._display_messages(messages)
        except Exception as e:
            logger.debug("Failed to load conversation", exc_info=True)
            self._update_status(f"Failed to load conversation: {e}")

    def _display_messages(self, messages: list[dict[str, Any]]) -> None:
        """Display loaded messages in the message area."""
        try:
            scroll = self.query_one("#chat-messages", VerticalScroll)
            scroll.remove_children()

            for msg in messages:
                role = msg.get("role", "assistant")
                content = msg.get("content", "")
                if content:
                    widget = ChatMessageWidget(role=role, content=content)
                    scroll.mount(widget)

            # Scroll to bottom
            scroll.scroll_end(animate=False)
        except Exception:
            logger.debug("Failed to display messages", exc_info=True)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle Enter key in the chat input."""
        if event.input.id != "chat-input":
            return
        message = event.value.strip()
        if not message:
            return
        if self._streaming:
            self.notify("Still streaming a response...", severity="warning")
            return

        # Clear input
        event.input.value = ""

        # Add user message to display
        self._add_user_message(message)

        # Start streaming
        self._stream_response(message, self._conversation_id)

    def _add_user_message(self, message: str) -> None:
        """Add a user message widget to the display."""
        try:
            scroll = self.query_one("#chat-messages", VerticalScroll)
            widget = ChatMessageWidget(role="user", content=message)
            scroll.mount(widget)
            scroll.scroll_end(animate=False)
        except Exception:
            logger.debug("Failed to add user message", exc_info=True)

    def _add_assistant_placeholder(self) -> ChatMessageWidget:
        """Add an empty assistant message widget and return it."""
        try:
            scroll = self.query_one("#chat-messages", VerticalScroll)
            widget = ChatMessageWidget(
                role="assistant", content="", id="streaming-msg"
            )
            scroll.mount(widget)
            scroll.scroll_end(animate=False)
            return widget
        except Exception:
            logger.debug("Failed to add assistant placeholder", exc_info=True)
            return None

    @work(exclusive=True, group="stream")
    async def _stream_response(
        self, message: str, conv_id: int | None = None
    ) -> None:
        """Stream a chat response from the API."""
        if self._chat_client is None:
            return

        self._streaming = True
        self._accumulated_text = ""
        self._update_status("AI is thinking...")

        # Create the assistant placeholder
        self._add_assistant_placeholder()

        try:
            async for event_type, data_str in self._chat_client.stream_chat(
                message, conv_id
            ):
                try:
                    data = json.loads(data_str) if data_str else {}
                except (json.JSONDecodeError, TypeError):
                    data = {}

                if event_type == "content":
                    text = data.get("text", "")
                    if text:
                        self._accumulated_text = text
                        self._update_streaming_message(text)

                elif event_type == "conversation_id":
                    new_id = data.get("conversation_id")
                    if new_id:
                        self._conversation_id = new_id

                elif event_type == "clarification":
                    question = data.get("question", "")
                    if question:
                        self._accumulated_text = question
                        self._update_streaming_message(question)

                elif event_type == "plan_ready":
                    tasks = data.get("tasks", [])
                    if tasks:
                        plan_text = "Planning...\n"
                        for i, task in enumerate(tasks, 1):
                            if isinstance(task, dict):
                                plan_text += (
                                    f"  {i}. {task.get('description', task.get('tool', 'task'))}\n"
                                )
                            else:
                                plan_text += f"  {i}. {task}\n"
                        self._update_streaming_message(plan_text)

                elif event_type == "task_complete":
                    summary = data.get("summary", "")
                    task_id = data.get("task_id", "")
                    if summary:
                        self._update_status(f"Completed: {summary[:60]}")

                elif event_type == "task_failed":
                    error = data.get("error", "Unknown error")
                    self._update_status(f"Task failed: {error[:60]}")

                elif event_type == "phase":
                    phase = data.get("phase", "")
                    if phase:
                        self._update_status(f"Phase: {phase}")

                elif event_type == "done":
                    # Don't break here -- the backend sends conversation_id
                    # after the done event. The stream will end naturally.
                    self._update_status("")

                elif event_type == "error":
                    error_msg = data.get("message", data.get("error", "Unknown error"))
                    self._update_streaming_message(f"Error: {error_msg}")
                    self.notify(f"Error: {error_msg}", severity="error")
                    break

        except Exception as e:
            logger.error("Chat stream error", exc_info=True)
            self.notify(f"Stream error: {e}", severity="error")
        finally:
            self._streaming = False
            self._update_status("")
            # Refresh conversation list to show new/updated conversation
            self._refresh_conversations_after_stream()

    def _refresh_conversations_after_stream(self) -> None:
        """Refresh conversation list after streaming completes."""
        self._load_conversations()

    def _update_streaming_message(self, text: str) -> None:
        """Update the streaming assistant message widget."""
        try:
            widget = self.query_one("#streaming-msg", ChatMessageWidget)
            widget.append_content(text)
            scroll = self.query_one("#chat-messages", VerticalScroll)
            scroll.scroll_end(animate=False)
        except Exception:
            logger.debug("Failed to update streaming message", exc_info=True)

    def _update_status(self, text: str) -> None:
        """Update the status bar text."""
        try:
            self.query_one("#chat-status", Static).update(text)
        except Exception:
            pass

    # ── Key actions ──────────────────────────────────────────

    def action_new_conversation(self) -> None:
        """Start a new conversation."""
        self._conversation_id = None
        self._accumulated_text = ""
        try:
            scroll = self.query_one("#chat-messages", VerticalScroll)
            scroll.remove_children()
            self._update_status("New conversation")
            # Focus input
            chat_input = self.query_one("#chat-input", Input)
            chat_input.focus()
        except Exception:
            pass

    def action_focus_input(self) -> None:
        """Focus the chat input."""
        try:
            chat_input = self.query_one("#chat-input", Input)
            chat_input.focus()
        except Exception:
            pass

    def action_unfocus(self) -> None:
        """Unfocus the input / deselect."""
        focused = self.app.focused
        if isinstance(focused, Input):
            self.query_one("#chat-conv-list", ListView).focus()
        # Otherwise do nothing (don't navigate away)

    def action_cursor_down(self) -> None:
        """Move cursor down in the conversation list."""
        try:
            lv = self.query_one("#chat-conv-list", ListView)
            lv.action_cursor_down()
        except Exception:
            pass

    def action_cursor_up(self) -> None:
        """Move cursor up in the conversation list."""
        try:
            lv = self.query_one("#chat-conv-list", ListView)
            lv.action_cursor_up()
        except Exception:
            pass

    @work(exclusive=True, group="delete-conv")
    async def action_delete_conversation(self) -> None:
        """Delete the selected conversation."""
        if self._conversation_id is None:
            return
        if self._chat_client is None:
            return
        try:
            await self._chat_client.delete_conversation(self._conversation_id)
            self._conversation_id = None
            self.notify("Conversation deleted")
            # Clear messages and refresh list
            self._clear_and_refresh()
        except Exception as e:
            self.notify(f"Delete failed: {e}", severity="error")

    def _clear_and_refresh(self) -> None:
        """Clear messages and refresh conversation list."""
        try:
            scroll = self.query_one("#chat-messages", VerticalScroll)
            scroll.remove_children()
        except Exception:
            pass
        self._load_conversations()
