"""Navigation sidebar widget."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static


class SidebarItem(Static):
    """A single clickable navigation item in the sidebar."""

    DEFAULT_CSS = """
    SidebarItem {
        width: 100%;
        height: 1;
        padding: 0 1;
        color: $text;
    }
    SidebarItem:hover {
        background: $accent 30%;
    }
    SidebarItem.active {
        background: $accent;
        color: #ffffff;
        text-style: bold;
    }
    """

    class Selected(Message):
        """Posted when a sidebar item is clicked."""
        def __init__(self, item_id: str, label: str) -> None:
            self.item_id = item_id
            self.label = label
            super().__init__()

    def __init__(self, label: str, item_id: str, icon: str = "", **kwargs) -> None:
        display_text = f"{icon} {label}" if icon else label
        super().__init__(display_text, **kwargs)
        self.item_id = item_id
        self.label_text = label

    def on_click(self) -> None:
        self.post_message(self.Selected(self.item_id, self.label_text))


class SidebarWidget(Widget):
    """Collapsible navigation sidebar.

    Shows navigation items for the main screens. Each item is clickable
    and highlights when active. Can be collapsed/expanded with toggle.
    """

    DEFAULT_CSS = """
    SidebarWidget {
        dock: left;
        width: 22;
        background: $surface;
        border-right: solid $primary-background-darken-2;
    }
    SidebarWidget.collapsed {
        width: 0;
        display: none;
    }
    SidebarWidget .sidebar-header {
        width: 100%;
        height: 1;
        padding: 0 1;
        text-style: bold;
        color: $accent;
        background: $surface;
    }
    SidebarWidget .sidebar-separator {
        width: 100%;
        height: 1;
        color: $text-muted;
    }
    """

    collapsed = reactive(False)

    # Navigation items: (id, label, icon)
    NAV_ITEMS = [
        ("flow", "Flow", ">>"),
        ("inbox", "Inbox", "[]"),
        ("calendar", "Calendar", "::"),
        ("todos", "Todos", "**"),
        ("stats", "Stats", "##"),
        ("ai_insights", "AI Insights", "~~"),
        ("chat", "Chat", "<>"),
        ("settings", "Settings", "@@"),
    ]

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._active_item: str | None = None

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static(" Navigation", classes="sidebar-header")
            yield Static("---", classes="sidebar-separator")
            for item_id, label, icon in self.NAV_ITEMS:
                yield SidebarItem(label, item_id, icon=icon, id=f"nav-{item_id}")

    def set_active(self, item_id: str) -> None:
        """Highlight the given navigation item."""
        self._active_item = item_id
        for nav_id, _, _ in self.NAV_ITEMS:
            try:
                widget = self.query_one(f"#nav-{nav_id}", SidebarItem)
                if nav_id == item_id:
                    widget.add_class("active")
                else:
                    widget.remove_class("active")
            except Exception:
                pass

    def watch_collapsed(self, collapsed: bool) -> None:
        """React to collapsed state change."""
        if collapsed:
            self.add_class("collapsed")
        else:
            self.remove_class("collapsed")

    def toggle(self) -> None:
        """Toggle the sidebar collapsed state."""
        self.collapsed = not self.collapsed
