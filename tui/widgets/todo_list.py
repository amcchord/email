"""Todo list widget using ListView with custom ListItem rendering."""

from __future__ import annotations

from typing import Any

from textual.app import ComposeResult
from textual.widgets import ListItem, ListView, Static

from tui.utils.date_format import relative_date


# Status indicators
STATUS_INDICATORS = {
    "pending": "[ ]",
    "done": "[x]",
    "dismissed": "[-]",
}

# Source badge markup
SOURCE_BADGES = {
    "manual": "[dim](manual)[/dim]",
    "ai": "[cyan](ai)[/cyan]",
    "ai_action_item": "[cyan](ai)[/cyan]",
}


class TodoItem(ListItem):
    """A single todo item in the list.

    Displays status checkbox, title, source badge, and relative date.
    """

    DEFAULT_CSS = """
    TodoItem {
        width: 100%;
        height: auto;
        padding: 0 1;
    }
    TodoItem > .todo-content {
        width: 100%;
        height: auto;
    }
    """

    def __init__(
        self,
        todo_data: dict[str, Any],
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.todo_data = todo_data

    def compose(self) -> ComposeResult:
        todo = self.todo_data
        status = todo.get("status", "pending")
        title = todo.get("title", "(untitled)")
        source = todo.get("source", "")
        created_at = todo.get("created_at", "")
        email_id = todo.get("email_id")

        indicator = STATUS_INDICATORS.get(status, "[ ]")
        source_badge = SOURCE_BADGES.get(source, "")
        date_str = relative_date(created_at)

        # Style based on status
        if status == "done":
            title_markup = f"[dim strikethrough]{title}[/dim strikethrough]"
            indicator_markup = f"[green]{indicator}[/green]"
        elif status == "dismissed":
            title_markup = f"[dim]{title}[/dim]"
            indicator_markup = f"[yellow]{indicator}[/yellow]"
        else:
            title_markup = f"[bold]{title}[/bold]"
            indicator_markup = indicator

        # Email link indicator
        email_hint = "  [blue]@[/blue]" if email_id else ""

        content = (
            f"{indicator_markup} {title_markup}"
            f"  {source_badge}{email_hint}"
            f"  [dim]{date_str}[/dim]"
        )

        yield Static(content, classes="todo-content")


class TodoListWidget(ListView):
    """A ListView-based widget for displaying todo items.

    Provides methods to load todos and get the selected item.
    """

    DEFAULT_CSS = """
    TodoListWidget {
        height: 1fr;
        width: 100%;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._todos: list[dict[str, Any]] = []

    def load_todos(self, todos: list[dict[str, Any]]) -> None:
        """Clear and repopulate with a list of todo dicts."""
        self._todos = todos
        self.clear()

        if not todos:
            self.append(
                ListItem(
                    Static("[dim italic]  No todos[/dim italic]"),
                )
            )
            return

        for todo in todos:
            self.append(TodoItem(todo_data=todo))

    def get_selected_todo(self) -> dict[str, Any] | None:
        """Return the todo data dict for the currently highlighted item."""
        if self.index is None:
            return None
        try:
            item = self.children[self.index]
            if isinstance(item, TodoItem):
                return item.todo_data
        except (IndexError, TypeError):
            pass
        return None
