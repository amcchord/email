"""Base screen class with common app shell layout."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Static

from tui.widgets.header import HeaderWidget
from tui.widgets.footer import FooterWidget
from tui.widgets.sidebar import SidebarWidget


class BaseScreen(Screen):
    """Base screen providing the common app shell layout.

    Layout:
        - HeaderWidget docked at top
        - SidebarWidget docked at left
        - Content area in center (filled by subclasses via compose_content)
        - FooterWidget docked at bottom

    Subclasses should override `compose_content()` to provide the main
    content area widgets.
    """

    # Subclasses can set these
    SCREEN_TITLE: str = ""
    SCREEN_NAV_ID: str = ""
    DEFAULT_SHORTCUTS: list[tuple[str, str]] = [
        ("g f", "Flow"),
        ("g i", "Inbox"),
        ("[", "Sidebar"),
        (".", "Theme"),
        ("?", "Help"),
    ]

    def compose(self) -> ComposeResult:
        app = self.app
        user_name = ""
        if hasattr(app, "user") and app.user:
            user_name = app.user.get("display_name", "") or app.user.get("username", "")

        yield HeaderWidget(
            screen_title=self.SCREEN_TITLE,
            user_name=user_name,
            id="app-header",
        )
        yield SidebarWidget(id="app-sidebar")
        yield Vertical(
            *self.compose_content(),
            id="content-area",
            classes="content-area",
        )
        yield FooterWidget(
            shortcuts=self.DEFAULT_SHORTCUTS,
            id="app-footer",
        )

    def compose_content(self) -> ComposeResult:
        """Override in subclasses to provide content widgets.

        Should yield Widget instances for the main content area.
        """
        yield Static("Content area", classes="placeholder-label")

    def on_mount(self) -> None:
        """Set sidebar active item when screen mounts."""
        if self.SCREEN_NAV_ID:
            try:
                sidebar = self.query_one("#app-sidebar", SidebarWidget)
                sidebar.set_active(self.SCREEN_NAV_ID)
            except Exception:
                pass

    def action_toggle_sidebar(self) -> None:
        """Toggle the sidebar visibility."""
        try:
            sidebar = self.query_one("#app-sidebar", SidebarWidget)
            sidebar.toggle()
        except Exception:
            pass

    BINDINGS = [
        ("left_square_bracket", "toggle_sidebar", "Toggle sidebar"),
    ]
