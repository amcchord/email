"""Main MailApp class - the Textual application entry point."""

from __future__ import annotations

import os

from textual.app import App
from textual.events import Key

from tui.client.base import APIClient
from tui.config import TUIConfig
from tui.utils.keybindings import KeySequenceHandler
from tui.widgets.sidebar import SidebarItem


def _should_disable_mouse() -> bool:
    """Return True when mouse support should be turned off.

    Mouse is disabled for:
    - SSH sessions (TUI_SSH_SERVER=1) -- prevents mouse-tracking
      escape sequences from interfering with the terminal and
      allows normal text selection / hyperlink clicking.
    - Web terminal via textual-serve (TEXTUAL_WEB=1 or
      TEXTUAL_DRIVER contains 'web_driver') -- xterm.js mouse
      handling conflicts with Textual.
    """
    if os.environ.get("TUI_SSH_SERVER") == "1":
        return True
    driver = os.environ.get("TEXTUAL_DRIVER", "")
    if "web_driver" in driver.lower():
        return True
    if os.environ.get("TEXTUAL_WEB") == "1":
        return True
    return False


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

    async def on_mount(self) -> None:
        """Check for env-var tokens (SSH auth passthrough), otherwise show login."""
        access_token = os.environ.get("TUI_ACCESS_TOKEN", "").strip()
        refresh_token = os.environ.get("TUI_REFRESH_TOKEN", "").strip()

        if access_token and refresh_token:
            # SSH layer already authenticated -- skip the login screen
            self.api_client.set_tokens(access_token, refresh_token)
            try:
                from tui.client.auth import AuthClient
                auth_client = AuthClient(self.api_client)
                self.user = await auth_client.me()
                self.auth_client = auth_client
                from tui.screens.flow import FlowScreen
                self.install_screen(FlowScreen(), name="flow")
                self.push_screen("flow")
                return
            except Exception:
                # Token invalid / expired -- fall through to login
                self.api_client.clear_tokens()

        from tui.screens.login import LoginScreen
        self.install_screen(LoginScreen(), name="login")
        self.push_screen("login")

    # Keys that the sequence handler should process.  Everything else
    # (arrow keys, escape, function keys, modifiers, etc.) is left
    # alone so Textual widgets can handle them normally.
    _HANDLED_KEYS = frozenset(
        set("abcdefghijklmnopqrstuvwxyz0123456789")
        | {"comma", "full_stop", "slash", "question_mark",
           "left_square_bracket", "number_sign", "exclamation_mark",
           "space"}
    )

    async def on_key(self, event: Key) -> None:
        """Route key events through the KeySequenceHandler.

        Only intercepts simple character keys used for vim-style navigation
        and single-key shortcuts.  Arrow keys, escape, tab, enter, and
        other structural keys are left untouched so Textual widgets can
        handle them normally.
        """
        from textual.widgets import Input, TextArea

        focused = self.focused
        if isinstance(focused, (Input, TextArea)):
            return

        from tui.screens.login import LoginScreen
        if isinstance(self.screen, LoginScreen):
            return

        key = event.key

        # Only intercept simple character keys -- leave arrows, escape,
        # enter, tab, function keys, and modifier combos for Textual.
        if key not in self._HANDLED_KEYS:
            return

        action = self._key_handler.process_key(key)
        if action is None:
            # Pending sequence (e.g. pressed "g", waiting for second key)
            event.prevent_default()
            event.stop()
            return

        handled = self._handle_action(action)
        if handled:
            event.prevent_default()
            event.stop()

    def _handle_action(self, action: str) -> bool:
        """Handle a resolved key action. Returns True if handled."""
        from tui.screens.inbox import InboxScreen
        from tui.screens.flow import FlowScreen
        from tui.screens.compose import ComposeScreen
        from tui.screens.calendar import CalendarScreen
        from tui.screens.todos import TodoScreen
        from tui.screens.stats import StatsScreen
        from tui.screens.ai_insights import AIInsightsScreen
        from tui.screens.chat import ChatScreen
        from tui.screens.settings import SettingsScreen
        from tui.screens.placeholders import HelpScreen

        switch_map = {
            "g_f": FlowScreen,
            "g_i": InboxScreen,
            "g_l": CalendarScreen,
            "g_t": TodoScreen,
            "g_s": StatsScreen,
            "g_a": AIInsightsScreen,
            "g_h": ChatScreen,
            "g_comma": SettingsScreen,
            "question_mark": HelpScreen,
        }

        screen_class = switch_map.get(action)
        if screen_class is not None:
            self.pop_screen()
            self.push_screen(screen_class())
            return True

        if action == "c":
            self.push_screen(ComposeScreen())
            return True

        if action == "full_stop":
            self.action_toggle_dark()
            return True

        if action == "slash":
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
