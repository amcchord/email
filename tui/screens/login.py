"""Login screen for the mail TUI."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical, Center
from textual.screen import Screen
from textual.widgets import Static, Input, Button


BANNER = r"""
 __  __    _    ___ _
|  \/  |  / \  |_ _| |
| |\/| | / _ \  | || |
| |  | |/ ___ \ | || |___
|_|  |_/_/   \_\___|_____|
"""


class LoginScreen(Screen):
    """Login screen with centered card, username/password fields, and login button."""

    DEFAULT_CSS = """
    LoginScreen {
        align: center middle;
    }
    """

    def compose(self) -> ComposeResult:
        with Center():
            with Vertical(classes="login-card"):
                yield Static(BANNER, classes="login-banner")
                with Vertical(classes="login-form"):
                    yield Input(
                        placeholder="Username",
                        id="login-username",
                    )
                    yield Input(
                        placeholder="Password",
                        password=True,
                        id="login-password",
                    )
                    yield Static("", id="login-error", classes="login-error")
                    yield Button("Login", id="login-button", variant="primary")

    def on_mount(self) -> None:
        """Focus the username field on mount."""
        self.query_one("#login-username", Input).focus()

    def _show_error(self, message: str) -> None:
        """Display an error message."""
        error_widget = self.query_one("#login-error", Static)
        error_widget.update(message)
        error_widget.add_class("visible")

    def _hide_error(self) -> None:
        """Hide the error message."""
        error_widget = self.query_one("#login-error", Static)
        error_widget.update("")
        error_widget.remove_class("visible")

    async def _do_login(self) -> None:
        """Attempt to log in with the current credentials."""
        username = self.query_one("#login-username", Input).value.strip()
        password = self.query_one("#login-password", Input).value

        if not username or not password:
            self._show_error("Please enter username and password")
            return

        self._hide_error()
        button = self.query_one("#login-button", Button)
        button.disabled = True
        button.label = "Logging in..."

        try:
            from tui.client.auth import AuthClient

            app = self.app
            auth_client = AuthClient(app.api_client)
            user = await auth_client.login(username, password)
            app.user = user
            app.auth_client = auth_client

            # Switch to the main app screen
            from tui.screens.main import MainScreen
            app.switch_screen(MainScreen())

        except Exception as e:
            detail = str(e)
            if hasattr(e, "detail") and e.detail:
                detail = e.detail
            self._show_error(detail)
            button.disabled = False
            button.label = "Login"

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle login button press."""
        if event.button.id == "login-button":
            await self._do_login()

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle Enter key in input fields."""
        if event.input.id == "login-username":
            self.query_one("#login-password", Input).focus()
        elif event.input.id == "login-password":
            await self._do_login()
