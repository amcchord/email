"""Navigation sidebar widget with Unicode icons and modern styling."""

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
        color: #94a3b8;
    }
    SidebarItem:hover {
        background: #232440;
        color: #e2e8f0;
    }
    SidebarItem.active {
        background: #232440;
        color: #e2e8f0;
        text-style: bold;
        border-left: tall #6366f1;
    }
    """

    class Selected(Message):
        """Posted when a sidebar item is clicked."""
        def __init__(self, item_id: str, label: str) -> None:
            self.item_id = item_id
            self.label = label
            super().__init__()

    def __init__(self, label: str, item_id: str, icon: str = "", **kwargs) -> None:
        display_text = f" {icon}  {label}" if icon else f"   {label}"
        super().__init__(display_text, **kwargs)
        self.item_id = item_id
        self.label_text = label

    def on_click(self) -> None:
        self.post_message(self.Selected(self.item_id, self.label_text))


class SidebarDivider(Static):
    """A thin divider between sidebar sections."""

    DEFAULT_CSS = """
    SidebarDivider {
        width: 100%;
        height: 1;
        padding: 0 1;
        color: #3d3f5c;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__("\u2500" * 18, **kwargs)


class SidebarWidget(Widget):
    """Collapsible navigation sidebar with grouped sections.

    Shows navigation items with Unicode icons. Items are clickable
    and highlight with a left accent bar when active.
    """

    DEFAULT_CSS = """
    SidebarWidget {
        dock: left;
        width: 24;
        background: #1a1b2e;
        border-right: tall #3d3f5c;
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
        color: #6366f1;
        background: #1a1b2e;
    }
    SidebarWidget .sidebar-group-label {
        width: 100%;
        height: 1;
        padding: 0 1;
        color: #64748b;
        text-style: bold;
        margin: 1 0 0 0;
    }
    """

    collapsed = reactive(False)

    # Navigation items grouped: (id, label, icon)
    MAIN_NAV = [
        ("flow", "Flow", "\u25b6"),
        ("inbox", "Inbox", "\u2709"),
        ("calendar", "Calendar", "\u25a3"),
        ("todos", "Todos", "\u2611"),
    ]

    TOOLS_NAV = [
        ("stats", "Stats", "\u2261"),
        ("ai_insights", "AI Insights", "\u2726"),
        ("chat", "Chat", "\u2604"),
    ]

    META_NAV = [
        ("settings", "Settings", "\u2699"),
    ]

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._active_item: str | None = None

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static(" \u2501 Mail", classes="sidebar-header")

            yield Static("  [#64748b]NAVIGATE[/#64748b]", classes="sidebar-group-label")
            for item_id, label, icon in self.MAIN_NAV:
                yield SidebarItem(label, item_id, icon=icon, id=f"nav-{item_id}")

            yield SidebarDivider()

            yield Static("  [#64748b]TOOLS[/#64748b]", classes="sidebar-group-label")
            for item_id, label, icon in self.TOOLS_NAV:
                yield SidebarItem(label, item_id, icon=icon, id=f"nav-{item_id}")

            yield SidebarDivider()

            for item_id, label, icon in self.META_NAV:
                yield SidebarItem(label, item_id, icon=icon, id=f"nav-{item_id}")

    def set_active(self, item_id: str) -> None:
        """Highlight the given navigation item."""
        self._active_item = item_id
        all_items = self.MAIN_NAV + self.TOOLS_NAV + self.META_NAV
        for nav_id, _, _ in all_items:
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
