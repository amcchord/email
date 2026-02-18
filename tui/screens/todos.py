"""Todos screen with CRUD operations, filtering, and keyboard navigation."""

from __future__ import annotations

import logging
from typing import Any

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.widgets import Static, Input
from textual import work

from tui.client.todos import TodosClient
from tui.screens.base import BaseScreen
from tui.widgets.todo_list import TodoListWidget

logger = logging.getLogger(__name__)

# Filter tabs
FILTERS = [
    ("all", "All"),
    ("pending", "Pending"),
    ("done", "Done"),
    ("dismissed", "Dismissed"),
]


class TodoFilterBar(Static):
    """A horizontal bar of filter tabs for the todos screen."""

    DEFAULT_CSS = """
    TodoFilterBar {
        width: 100%;
        height: 1;
        padding: 0 1;
        background: $surface;
    }
    """

    def __init__(self, active_filter: str = "all", **kwargs) -> None:
        self._active = active_filter
        parts = []
        for fid, label in FILTERS:
            if fid == active_filter:
                parts.append(f"[bold reverse] {label} [/bold reverse]")
            else:
                parts.append(f" [dim]{label}[/dim] ")
        super().__init__("  ".join(parts), **kwargs)

    def set_active(self, filter_id: str) -> None:
        """Set the active filter and re-render."""
        self._active = filter_id
        self._render()

    def _render(self) -> None:
        """Build the tab bar markup."""
        parts = []
        for fid, label in FILTERS:
            if fid == self._active:
                parts.append(f"[bold reverse] {label} [/bold reverse]")
            else:
                parts.append(f" [dim]{label}[/dim] ")
        self.update("  ".join(parts))


class TodoScreen(BaseScreen):
    """Todos screen with input, filter tabs, list, and keyboard controls.

    Supports creating, toggling, and deleting todos.
    """

    SCREEN_TITLE = "Todos"
    SCREEN_NAV_ID = "todos"
    DEFAULT_SHORTCUTS = [
        ("n", "New"),
        ("j/k", "Nav"),
        ("Space", "Toggle"),
        ("#", "Delete"),
        ("Tab", "Filter"),
        ("?", "Help"),
    ]

    BINDINGS = [
        *BaseScreen.BINDINGS,
        Binding("n", "new_todo", "New todo", show=False),
        Binding("j", "cursor_down", "Down", show=False),
        Binding("k", "cursor_up", "Up", show=False),
        Binding("space", "toggle_status", "Toggle status", show=False),
        Binding("number_sign", "delete_todo", "Delete", show=False),
        Binding("enter", "open_linked_email", "Open email", show=False),
        Binding("tab", "next_filter", "Next filter", show=False),
        Binding("shift+tab", "prev_filter", "Prev filter", show=False),
        Binding("x", "dismiss_todo", "Dismiss", show=False),
        Binding("escape", "cancel_input", "Cancel", show=False),
    ]

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._todos_client: TodosClient | None = None
        self._todos: list[dict[str, Any]] = []
        self._active_filter: str = "all"
        self._input_focused: bool = False

    def compose_content(self) -> ComposeResult:
        with Vertical(id="todos-container"):
            yield Input(
                placeholder="Add new todo... (press n to focus)",
                id="todo-input",
            )
            yield TodoFilterBar(active_filter="all", id="todo-filter-bar")
            yield TodoListWidget(id="todo-list")
            yield Static("Loading...", id="todos-status")

    def on_mount(self) -> None:
        """Initialize todos client and load data."""
        super().on_mount()
        self._todos_client = TodosClient(self.app.api_client)
        self._load_todos()

    def _get_list(self) -> TodoListWidget | None:
        """Get the todo list widget."""
        try:
            return self.query_one("#todo-list", TodoListWidget)
        except Exception:
            return None

    def _update_status(self, text: str | None = None) -> None:
        """Update the status bar."""
        if text is None:
            total = len(self._todos)
            pending = sum(1 for t in self._todos if t.get("status") == "pending")
            done = sum(1 for t in self._todos if t.get("status") == "done")
            filter_label = dict(FILTERS).get(self._active_filter, "All")
            text = (
                f"{filter_label} | "
                f"{total} total | "
                f"{pending} pending | "
                f"{done} done"
            )
        try:
            self.query_one("#todos-status", Static).update(text)
        except Exception:
            pass

    @work(exclusive=True)
    async def _load_todos(self) -> None:
        """Fetch todos from the API and populate the list."""
        if self._todos_client is None:
            return

        try:
            self._update_status("Loading...")
            status_filter = self._active_filter if self._active_filter != "all" else None
            result = await self._todos_client.list_todos(status=status_filter)
            self._todos = result.get("todos", [])

            self._apply_todos()
            self._update_status()
        except Exception as e:
            logger.debug("Failed to load todos", exc_info=True)
            self._update_status(f"[red]Error: {e}[/red]")

    def _apply_todos(self) -> None:
        """Apply loaded todos to the list widget (main thread only)."""
        todo_list = self._get_list()
        if todo_list is not None:
            todo_list.load_todos(self._todos)

    def _get_selected_todo(self) -> dict[str, Any] | None:
        """Get the currently selected todo data."""
        todo_list = self._get_list()
        if todo_list is not None:
            return todo_list.get_selected_todo()
        return None

    # ── Input handling ─────────────────────────────────────────

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle enter on the new todo input."""
        if event.input.id == "todo-input":
            title = event.input.value.strip()
            if title:
                self._create_todo(title)
                event.input.value = ""
            # Move focus back to the list
            todo_list = self._get_list()
            if todo_list is not None:
                todo_list.focus()
            self._input_focused = False

    # ── Filter navigation ──────────────────────────────────────

    def _set_filter(self, filter_id: str) -> None:
        """Switch the active filter and reload."""
        self._active_filter = filter_id
        try:
            bar = self.query_one("#todo-filter-bar", TodoFilterBar)
            bar.set_active(filter_id)
        except Exception:
            pass
        self._load_todos()

    def action_next_filter(self) -> None:
        """Move to the next filter tab."""
        filter_ids = [f[0] for f in FILTERS]
        current_idx = filter_ids.index(self._active_filter) if self._active_filter in filter_ids else 0
        next_idx = (current_idx + 1) % len(filter_ids)
        self._set_filter(filter_ids[next_idx])

    def action_prev_filter(self) -> None:
        """Move to the previous filter tab."""
        filter_ids = [f[0] for f in FILTERS]
        current_idx = filter_ids.index(self._active_filter) if self._active_filter in filter_ids else 0
        prev_idx = (current_idx - 1) % len(filter_ids)
        self._set_filter(filter_ids[prev_idx])

    # ── Keyboard actions ───────────────────────────────────────

    def action_new_todo(self) -> None:
        """Focus the new todo input."""
        try:
            inp = self.query_one("#todo-input", Input)
            inp.focus()
            self._input_focused = True
        except Exception:
            pass

    def action_cursor_down(self) -> None:
        """Move cursor down in the todo list."""
        todo_list = self._get_list()
        if todo_list is not None:
            todo_list.action_cursor_down()

    def action_cursor_up(self) -> None:
        """Move cursor up in the todo list."""
        todo_list = self._get_list()
        if todo_list is not None:
            todo_list.action_cursor_up()

    def action_toggle_status(self) -> None:
        """Toggle the selected todo between pending and done."""
        todo = self._get_selected_todo()
        if todo is None or not todo.get("id"):
            return

        current_status = todo.get("status", "pending")
        new_status = "done" if current_status == "pending" else "pending"
        self._update_todo_status(todo["id"], new_status)

    def action_dismiss_todo(self) -> None:
        """Dismiss the selected todo."""
        todo = self._get_selected_todo()
        if todo is None or not todo.get("id"):
            return
        self._update_todo_status(todo["id"], "dismissed")

    def action_delete_todo(self) -> None:
        """Delete the selected todo."""
        todo = self._get_selected_todo()
        if todo is None or not todo.get("id"):
            return
        self._delete_todo(todo["id"])

    def action_open_linked_email(self) -> None:
        """Open the email linked to the selected todo."""
        todo = self._get_selected_todo()
        if todo is None:
            return

        email_id = todo.get("email_id")
        if email_id:
            from tui.screens.email_view import EmailViewScreen
            self.app.push_screen(EmailViewScreen(email_id=email_id))
        else:
            self.notify("No linked email", severity="warning")

    def action_cancel_input(self) -> None:
        """Cancel input and return focus to the list."""
        if self._input_focused:
            try:
                inp = self.query_one("#todo-input", Input)
                inp.value = ""
            except Exception:
                pass
            self._input_focused = False
            todo_list = self._get_list()
            if todo_list is not None:
                todo_list.focus()

    # ── CRUD workers ───────────────────────────────────────────

    @work(exclusive=True, group="todo-action")
    async def _create_todo(self, title: str) -> None:
        """Create a new todo via the API."""
        if self._todos_client is None:
            return
        try:
            await self._todos_client.create_todo(title=title, source="manual")
            self.notify("Todo created", severity="information")
            self._load_todos()
        except Exception as e:
            self.notify(f"Failed to create todo: {e}", severity="error")

    @work(exclusive=True, group="todo-action")
    async def _update_todo_status(self, todo_id: int, new_status: str) -> None:
        """Update a todo's status via the API."""
        if self._todos_client is None:
            return
        try:
            await self._todos_client.update_todo(todo_id, status=new_status)
            self.notify(f"Todo {new_status}", severity="information")
            self._load_todos()
        except Exception as e:
            self.notify(f"Update failed: {e}", severity="error")

    @work(exclusive=True, group="todo-action")
    async def _delete_todo(self, todo_id: int) -> None:
        """Delete a todo via the API."""
        if self._todos_client is None:
            return
        try:
            await self._todos_client.delete_todo(todo_id)
            self.notify("Todo deleted", severity="information")
            self._load_todos()
        except Exception as e:
            self.notify(f"Delete failed: {e}", severity="error")
