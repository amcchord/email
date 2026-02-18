"""Login screen for the mail TUI with device-code auth flow."""

from __future__ import annotations

import asyncio

from textual.app import ComposeResult
from textual.containers import Vertical, Center
from textual.screen import Screen
from textual.widgets import Static, Input, Button, LoadingIndicator
from textual import work


BANNER = (
    "[bold #6366f1]\u2501\u2501\u2501  [/bold #6366f1]"
    "[bold #818cf8]M A I L[/bold #818cf8]"
    "[bold #6366f1]  \u2501\u2501\u2501[/bold #6366f1]"
)

SUBTITLE = "[#94a3b8]Terminal Email Client[/#94a3b8]"


class LoginScreen(Screen):
    """Login screen with device-code auth (primary) and password login (fallback).

    The device-code flow shows a URL + code. The user opens the URL in their
    browser, enters the code, and the TUI polls until authorized.
    """

    DEFAULT_CSS = """
    LoginScreen {
        align: center middle;
        background: #0f0f1a;
    }

    LoginScreen .login-card {
        width: 80;
        max-width: 90%;
        height: auto;
        max-height: 40;
        padding: 2 3;
        background: #1a1b2e;
        border: round #3d3f5c;
    }

    LoginScreen .login-card:focus-within {
        border: round #6366f1;
    }

    LoginScreen .login-banner {
        width: 100%;
        content-align: center middle;
        text-align: center;
        padding: 1 0 0 0;
    }

    LoginScreen .login-subtitle {
        width: 100%;
        content-align: center middle;
        text-align: center;
        padding: 0 0 1 0;
    }

    LoginScreen .login-device-section {
        width: 100%;
        height: auto;
        padding: 1 1;
        text-align: center;
    }

    LoginScreen .login-device-url {
        width: 100%;
        text-align: center;
        color: #94a3b8;
        padding: 0 1;
    }

    LoginScreen .login-device-code {
        width: 100%;
        text-align: center;
        padding: 1 0;
    }

    LoginScreen .login-device-status {
        width: 100%;
        text-align: center;
        color: #64748b;
        padding: 0 1;
    }

    LoginScreen .login-or-divider {
        width: 100%;
        text-align: center;
        color: #3d3f5c;
        padding: 1 0 0 0;
    }

    LoginScreen .login-form {
        width: 100%;
        height: auto;
        padding: 0 1;
        display: none;
    }

    LoginScreen .login-form.visible {
        display: block;
    }

    LoginScreen .login-form Input {
        width: 100%;
        margin: 0 0 1 0;
    }

    LoginScreen .login-form Button {
        width: 100%;
        margin: 1 0 0 0;
        background: #6366f1;
        color: #ffffff;
    }

    LoginScreen .login-form Button:hover {
        background: #818cf8;
    }

    LoginScreen .login-error {
        width: 100%;
        color: #ef4444;
        text-align: center;
        padding: 0 1;
        display: none;
    }

    LoginScreen .login-error.visible {
        display: block;
    }

    LoginScreen .login-help {
        width: 100%;
        text-align: center;
        color: #64748b;
        padding: 1 1 0 1;
    }

    LoginScreen .login-server-url {
        width: 100%;
        text-align: center;
        color: #64748b;
        padding: 0 1;
    }

    LoginScreen .login-loading {
        width: 100%;
        height: 3;
        display: none;
    }

    LoginScreen .login-loading.visible {
        display: block;
    }

    LoginScreen .login-toggle-btn {
        width: 100%;
        margin: 1 0 0 0;
        background: transparent;
        color: #6366f1;
        border: none;
    }

    LoginScreen .login-device-hint {
        width: 100%;
        text-align: center;
        color: #64748b;
        padding: 0 1;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._device_code: str | None = None
        self._polling: bool = False
        self._password_mode: bool = False

    def compose(self) -> ComposeResult:
        with Center():
            with Vertical(classes="login-card"):
                yield Static(BANNER, classes="login-banner")
                yield Static(SUBTITLE, classes="login-subtitle")

                # Device-code auth section (primary)
                with Vertical(classes="login-device-section", id="device-section"):
                    yield Static(
                        "[#94a3b8]Open this URL in your browser:[/#94a3b8]",
                        classes="login-device-url",
                    )
                    yield Static(
                        "[#64748b]Loading...[/#64748b]",
                        id="device-url-display",
                        classes="login-device-url",
                    )
                    yield Static(
                        "",
                        id="device-code-display",
                        classes="login-device-code",
                    )
                    yield Static(
                        "[#64748b]\u231b Waiting for authorization...[/#64748b]",
                        id="device-status",
                        classes="login-device-status",
                    )
                    yield Static(
                        "[#64748b]Copy the URL above and paste it in your browser[/#64748b]",
                        id="device-hint",
                        classes="login-device-hint",
                    )

                # Divider
                yield Static(
                    "[#3d3f5c]\u2500\u2500\u2500 or sign in with password \u2500\u2500\u2500[/#3d3f5c]",
                    classes="login-or-divider",
                )
                yield Button(
                    "\u2328  Use password instead",
                    id="toggle-password-btn",
                    classes="login-toggle-btn",
                )

                # Password login form (hidden by default)
                with Vertical(classes="login-form", id="password-form"):
                    yield Input(
                        placeholder="\u2709  Email or username",
                        id="login-username",
                    )
                    yield Input(
                        placeholder="\U0001f512  Password",
                        password=True,
                        id="login-password",
                    )
                    yield Static("", id="login-error", classes="login-error")
                    yield LoadingIndicator(id="login-loading", classes="login-loading")
                    yield Button("\u2192  Sign In", id="login-button", variant="primary")

                yield Static("", id="login-server-url", classes="login-server-url")

    def on_mount(self) -> None:
        """Show server URL and start device-code flow."""
        server_url = getattr(self.app, "config", None)
        if server_url and hasattr(server_url, "api_base_url"):
            url = server_url.api_base_url.replace("/api", "")
            self.query_one("#login-server-url", Static).update(
                f"[#64748b]\u2022 {url}[/#64748b]"
            )
        self._start_device_flow()

    @work(exclusive=True, group="device-flow")
    async def _start_device_flow(self) -> None:
        """Request a device code and start polling for authorization."""
        try:
            client = self.app.api_client
            result = await client.post("/auth/device/start")

            self._device_code = result.get("device_code", "")
            user_code = result.get("user_code", "")
            verification_url = result.get("verification_url", "")
            interval = result.get("interval", 5)

            # Display the URL in a bright, easy-to-read color.
            # Keep markup minimal so terminal text selection works
            # for copy-paste.
            self.query_one("#device-url-display", Static).update(
                f"[bold #2dd4bf]{verification_url}[/bold #2dd4bf]"
            )
            self.query_one("#device-code-display", Static).update(
                f"[bold #e2e8f0 on #232440]  {user_code}  [/bold #e2e8f0 on #232440]"
            )
            self.query_one("#device-status", Static).update(
                "[#64748b]\u231b Waiting for browser authorization...[/#64748b]"
            )

            # Start polling
            self._polling = True
            while self._polling:
                await asyncio.sleep(interval)
                if not self._polling:
                    break

                try:
                    status_result = await client.get(
                        "/auth/device/status",
                        params={"device_code": self._device_code},
                    )
                    device_status = status_result.get("status", "")

                    if device_status == "authorized":
                        access_token = status_result.get("access_token", "")
                        refresh_token = status_result.get("refresh_token", "")
                        user = status_result.get("user", {})

                        self.app.api_client.set_tokens(access_token, refresh_token)
                        self.app.user = user

                        from tui.client.auth import AuthClient
                        self.app.auth_client = AuthClient(self.app.api_client)

                        self.query_one("#device-status", Static).update(
                            "[#2dd4bf]\u2713 Authorized![/#2dd4bf]"
                        )
                        await asyncio.sleep(0.5)

                        from tui.screens.flow import FlowScreen
                        self.app.pop_screen()
                        self.app.push_screen(FlowScreen())
                        return

                    elif device_status == "expired":
                        self.query_one("#device-status", Static).update(
                            "[#ef4444]Code expired. Requesting new code...[/#ef4444]"
                        )
                        self._polling = False
                        await asyncio.sleep(1)
                        self._start_device_flow()
                        return

                except Exception:
                    pass

        except Exception as e:
            # Device flow not available -- just show password form
            self.query_one("#device-section").display = False
            self.query_one("#toggle-password-btn", Button).display = False
            self.query_one("#password-form").add_class("visible")
            self.query_one("#login-username", Input).focus()

    def _show_error(self, message: str) -> None:
        error_widget = self.query_one("#login-error", Static)
        error_widget.update(f"\u26a0  {message}")
        error_widget.add_class("visible")

    def _hide_error(self) -> None:
        error_widget = self.query_one("#login-error", Static)
        error_widget.update("")
        error_widget.remove_class("visible")

    def _show_loading(self) -> None:
        self.query_one("#login-loading").add_class("visible")
        self.query_one("#login-button", Button).display = False

    def _hide_loading(self) -> None:
        self.query_one("#login-loading").remove_class("visible")
        self.query_one("#login-button", Button).display = True

    async def _do_login(self) -> None:
        """Attempt to log in with the current credentials."""
        username = self.query_one("#login-username", Input).value.strip()
        password = self.query_one("#login-password", Input).value

        if not username or not password:
            self._show_error("Please enter email and password")
            return

        self._hide_error()
        self._show_loading()

        try:
            from tui.client.auth import AuthClient

            app = self.app
            auth_client = AuthClient(app.api_client)
            user = await auth_client.login(username, password)
            app.user = user
            app.auth_client = auth_client

            from tui.screens.flow import FlowScreen
            app.pop_screen()
            app.push_screen(FlowScreen())

        except Exception as e:
            detail = str(e)
            if hasattr(e, "detail") and e.detail:
                detail = e.detail
            self._show_error(detail)
            self._hide_loading()

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        if event.button.id == "login-button":
            await self._do_login()
        elif event.button.id == "toggle-password-btn":
            self._password_mode = not self._password_mode
            form = self.query_one("#password-form")
            btn = self.query_one("#toggle-password-btn", Button)
            if self._password_mode:
                form.add_class("visible")
                btn.label = "\u21bb  Use device code instead"
                self.query_one("#login-username", Input).focus()
            else:
                form.remove_class("visible")
                btn.label = "\u2328  Use password instead"

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle Enter key in input fields."""
        if event.input.id == "login-username":
            self.query_one("#login-password", Input).focus()
        elif event.input.id == "login-password":
            await self._do_login()

    def on_unmount(self) -> None:
        """Stop polling when screen is removed."""
        self._polling = False
