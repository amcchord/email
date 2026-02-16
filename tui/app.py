"""Main MailApp class - the Textual application entry point."""

from __future__ import annotations

from textual.app import App
from textual.events import Key

from tui.client.base import APIClient
from tui.config import TUIConfig
from tui.utils.keybindings import KeySequenceHandler
from tui.widgets.sidebar import SidebarItem


class MailApp(App):
    """Mail TUI application.

    A terminal email client built with Textual that communicates
    with the backend API over HTTP.
    """

    CSS_PATH = "styles/app.tcss"
    TITLE = "Mail"

    # Disable default Textual bindings that conflict with our keys
    BINDINGS = [
        ("q", "quit", "Quit"),
    ]

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.config = TUIConfig.from_env()
        self.api_client = APIClient(self.config.api_base_url)
        self.auth_client = None
        self.user: dict | None = None
        self._key_handler = KeySequenceHandler()

    def on_mount(self) -> None:
        """Show the login screen on startup."""
        from tui.screens.login import LoginScreen
        self.push_screen(LoginScreen())

    async def on_key(self, event: Key) -> None:
        """Route key events through the KeySequenceHandler.

        This intercepts key presses for vim-style multi-key sequences
        before they reach the normal Textual key dispatch.
        """
        # Don't intercept keys when an Input or TextArea is focused,
        # or when on the login screen.
        from textual.widgets import Input, TextArea

        focused = self.focused
        if isinstance(focused, (Input, TextArea)):
            return

        from tui.screens.login import LoginScreen
        if isinstance(self.screen, LoginScreen):
            return

        key = event.key

        action = self._key_handler.process_key(key)
        if action is None:
            # Key is pending (part of a sequence), consume the event
            event.prevent_default()
            event.stop()
            return

        # Check if this action maps to a navigation command
        handled = self._handle_action(action)
        if handled:
            event.prevent_default()
            event.stop()

    def _handle_action(self, action: str) -> bool:
        """Handle a resolved key action. Returns True if handled."""
        from tui.screens.inbox import InboxScreen
        from tui.screens.placeholders import (
            FlowScreen,
            CalendarScreen,
            TodoScreen,
            StatsScreen,
            AIInsightsScreen,
            ChatScreen,
            SettingsScreen,
            ComposeScreen,
            HelpScreen,
        )

        action_map = {
            "g_f": FlowScreen,
            "g_i": InboxScreen,
            "g_l": CalendarScreen,
            "g_t": TodoScreen,
            "g_s": StatsScreen,
            "g_a": AIInsightsScreen,
            "g_h": ChatScreen,
            "g_comma": SettingsScreen,
            "c": ComposeScreen,
            "question_mark": HelpScreen,
        }

        screen_class = action_map.get(action)
        if screen_class is not None:
            self.switch_screen(screen_class())
            return True

        if action == "full_stop":
            self.action_toggle_dark()
            return True

        if action == "slash":
            # Placeholder for search focus
            return True

        return False

    def on_sidebar_item_selected(self, message: SidebarItem.Selected) -> None:
        """Handle sidebar navigation clicks."""
        nav_to_action = {
            "flow": "g_f",
            "inbox": "g_i",
            "calendar": "g_l",
            "todos": "g_t",
            "stats": "g_s",
            "ai_insights": "g_a",
            "chat": "g_h",
            "settings": "g_comma",
        }
        action = nav_to_action.get(message.item_id)
        if action:
            self._handle_action(action)

    async def action_quit(self) -> None:
        """Clean up and quit."""
        if self.api_client:
            await self.api_client.close()
        self.exit()
