"""Flow dashboard screen - main workflow view with multiple sections."""

from __future__ import annotations

import logging
from typing import Any

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.widgets import Static, ListItem, ListView
from textual import work

from tui.client.ai import AIClient
from tui.screens.base import BaseScreen
from tui.utils.date_format import relative_date

logger = logging.getLogger(__name__)

# Section identifiers
SECTIONS = ["needs_reply", "awaiting", "threads", "events", "todos"]


class FlowSectionHeader(Static):
    """A styled section header for flow dashboard sections."""

    DEFAULT_CSS = """
    FlowSectionHeader {
        width: 100%;
        height: 1;
        background: $accent 30%;
        color: $text;
        text-style: bold;
        padding: 0 1;
        margin: 1 0 0 0;
    }
    """


class FlowItem(ListItem):
    """A single item in a flow section list."""

    DEFAULT_CSS = """
    FlowItem {
        width: 100%;
        height: auto;
        padding: 0 1;
    }
    FlowItem > .flow-item-content {
        width: 100%;
        height: auto;
    }
    """

    def __init__(
        self,
        content: str,
        item_data: dict[str, Any] | None = None,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._content = content
        self.item_data = item_data or {}

    def compose(self) -> ComposeResult:
        yield Static(self._content, classes="flow-item-content")


class FlowScreen(BaseScreen):
    """Flow dashboard with five sections: needs reply, awaiting response,
    active threads, upcoming events, and pending todos.
    """

    SCREEN_TITLE = "Flow"
    SCREEN_NAV_ID = "flow"
    DEFAULT_SHORTCUTS = [
        ("j/k", "Nav"),
        ("Tab", "Section"),
        ("Enter", "Open"),
        ("i", "Ignore"),
        ("z", "Snooze"),
        ("c", "Compose"),
        ("?", "Help"),
    ]

    BINDINGS = [
        *BaseScreen.BINDINGS,
        Binding("j", "cursor_down", "Down", show=False),
        Binding("k", "cursor_up", "Up", show=False),
        Binding("tab", "next_section", "Next section", show=False),
        Binding("shift+tab", "prev_section", "Prev section", show=False),
        Binding("enter", "open_item", "Open", show=False),
        Binding("o", "open_item", "Open", show=False),
        Binding("i", "ignore_item", "Ignore", show=False),
        Binding("z", "snooze_item", "Snooze", show=False),
        Binding("S", "skip_item", "Skip", show=False),
        Binding("n", "new_chat", "New chat", show=False),
        Binding("1", "select_reply_1", "Reply 1", show=False),
        Binding("2", "select_reply_2", "Reply 2", show=False),
        Binding("3", "select_reply_3", "Reply 3", show=False),
        Binding("4", "select_reply_4", "Reply 4", show=False),
        Binding("0", "custom_reply", "Custom reply", show=False),
        Binding("escape", "deselect", "Deselect", show=False),
    ]

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._ai_client: AIClient | None = None
        self._current_section_idx: int = 0
        self._needs_reply_data: list[dict[str, Any]] = []
        self._awaiting_data: list[dict[str, Any]] = []
        self._threads_data: list[dict[str, Any]] = []
        self._events_data: list[dict[str, Any]] = []
        self._todos_data: list[dict[str, Any]] = []

    def compose_content(self) -> ComposeResult:
        with VerticalScroll(id="flow-scroll"):
            # Section 1: Needs Reply
            yield FlowSectionHeader("Needs Reply", id="section-header-needs-reply")
            yield ListView(id="flow-needs-reply")

            # Section 2: Awaiting Response
            yield FlowSectionHeader("Awaiting Response", id="section-header-awaiting")
            yield ListView(id="flow-awaiting")

            # Section 3: Active Threads
            yield FlowSectionHeader("Active Threads", id="section-header-threads")
            yield ListView(id="flow-threads")

            # Section 4: Upcoming Events
            yield FlowSectionHeader("Upcoming Events", id="section-header-events")
            yield ListView(id="flow-events")

            # Section 5: Pending Todos
            yield FlowSectionHeader("Pending Todos", id="section-header-todos")
            yield ListView(id="flow-todos")

            # Status bar
            yield Static("Loading...", id="flow-status")

    def on_mount(self) -> None:
        """Initialize AI client and fetch all data."""
        super().on_mount()
        self._ai_client = AIClient(self.app.api_client)
        self._load_all_data()

    @work(exclusive=True)
    async def _load_all_data(self) -> None:
        """Fetch all five data sources."""
        import asyncio

        if self._ai_client is None:
            return

        # Fetch all data in parallel
        results = await asyncio.gather(
            self._fetch_needs_reply(),
            self._fetch_awaiting(),
            self._fetch_threads(),
            self._fetch_events(),
            self._fetch_todos(),
            return_exceptions=True,
        )

        # Update status
        errors = [r for r in results if isinstance(r, Exception)]
        if errors:
            error_msgs = "; ".join(str(e) for e in errors)
            self._update_status(f"Some sections failed: {error_msgs}")
        else:
            counts = []
            if self._needs_reply_data:
                counts.append(f"{len(self._needs_reply_data)} needs reply")
            if self._awaiting_data:
                counts.append(f"{len(self._awaiting_data)} awaiting")
            if self._threads_data:
                counts.append(f"{len(self._threads_data)} threads")
            if self._events_data:
                counts.append(f"{len(self._events_data)} events")
            if self._todos_data:
                counts.append(f"{len(self._todos_data)} todos")
            status_text = " | ".join(counts) if counts else "All caught up!"
            self._update_status(status_text)

    async def _fetch_needs_reply(self) -> None:
        """Fetch needs-reply emails and populate the list."""
        try:
            result = await self._ai_client.get_needs_reply(page_size=20)
            self._needs_reply_data = result.get("emails", [])
            self._populate_needs_reply()
        except Exception as e:
            logger.debug("Failed to fetch needs-reply", exc_info=True)
            self._set_section_empty("flow-needs-reply", f"Error: {e}")
            raise

    async def _fetch_awaiting(self) -> None:
        """Fetch awaiting-response emails and populate the list."""
        try:
            result = await self._ai_client.get_awaiting_response(page_size=20)
            self._awaiting_data = result.get("emails", [])
            self._populate_awaiting()
        except Exception as e:
            logger.debug("Failed to fetch awaiting", exc_info=True)
            self._set_section_empty("flow-awaiting", f"Error: {e}")
            raise

    async def _fetch_threads(self) -> None:
        """Fetch active threads and populate the list."""
        try:
            result = await self._ai_client.get_threads(page_size=10)
            self._threads_data = result.get("threads", [])
            self._populate_threads()
        except Exception as e:
            logger.debug("Failed to fetch threads", exc_info=True)
            self._set_section_empty("flow-threads", f"Error: {e}")
            raise

    async def _fetch_events(self) -> None:
        """Fetch upcoming events and populate the list."""
        try:
            result = await self.app.api_client.get(
                "/calendar/upcoming", params={"days": 7}
            )
            self._events_data = result.get("events", [])
            self._populate_events()
        except Exception as e:
            logger.debug("Failed to fetch events", exc_info=True)
            self._set_section_empty("flow-events", f"No events available")
            # Don't re-raise; calendar is optional

    async def _fetch_todos(self) -> None:
        """Fetch pending todos and populate the list."""
        try:
            result = await self.app.api_client.get(
                "/todos/", params={"status": "pending"}
            )
            self._todos_data = result.get("items", [])
            self._populate_todos()
        except Exception as e:
            logger.debug("Failed to fetch todos", exc_info=True)
            self._set_section_empty("flow-todos", f"No todos available")
            # Don't re-raise; todos are optional

    # ── Populate sections ─────────────────────────────────────

    def _populate_needs_reply(self) -> None:
        """Render needs-reply emails into the list."""
        try:
            listview = self.query_one("#flow-needs-reply", ListView)
            listview.clear()

            if not self._needs_reply_data:
                listview.append(FlowItem("  No emails needing reply", item_data={}))
                return

            for email in self._needs_reply_data:
                from_name = email.get("from_name", email.get("from_address", "Unknown"))
                subject = email.get("subject", "(no subject)")
                time_ago = relative_date(email.get("date"))
                summary = email.get("summary", "")
                priority = email.get("priority", 0)

                # Build display with reply options hint
                reply_options = email.get("reply_options") or []
                options_hint = ""
                if reply_options:
                    options_hint = f"  [dim][1-{len(reply_options)}] reply options[/dim]"

                priority_indicator = ""
                if priority and priority >= 4:
                    priority_indicator = "[red]![/red] "

                content = (
                    f"{priority_indicator}[bold]{from_name}[/bold]  "
                    f"[dim]{time_ago}[/dim]\n"
                    f"  {subject}\n"
                    f"  [dim italic]{summary[:100]}[/dim italic]"
                    f"{options_hint}"
                )

                listview.append(FlowItem(content, item_data=email))
        except Exception:
            logger.debug("Failed to populate needs-reply", exc_info=True)

    def _populate_awaiting(self) -> None:
        """Render awaiting-response emails into the list."""
        try:
            listview = self.query_one("#flow-awaiting", ListView)
            listview.clear()

            if not self._awaiting_data:
                listview.append(FlowItem("  No emails awaiting response", item_data={}))
                return

            for email in self._awaiting_data:
                to_name = email.get("to_name", "Unknown")
                subject = email.get("subject", "(no subject)")
                time_ago = relative_date(email.get("date"))

                content = (
                    f"[bold]{to_name}[/bold]  [dim]{time_ago}[/dim]\n"
                    f"  {subject}"
                )

                listview.append(FlowItem(content, item_data=email))
        except Exception:
            logger.debug("Failed to populate awaiting", exc_info=True)

    def _populate_threads(self) -> None:
        """Render active threads into the list."""
        try:
            listview = self.query_one("#flow-threads", ListView)
            listview.clear()

            if not self._threads_data:
                listview.append(FlowItem("  No active threads", item_data={}))
                return

            for thread in self._threads_data:
                subject = thread.get("subject", "(no subject)")
                msg_count = thread.get("message_count", 0)
                participants = thread.get("participants", [])
                participant_count = len(participants)
                time_ago = relative_date(thread.get("latest_date"))
                has_unread = thread.get("has_unread", False)

                unread_marker = "[bold yellow]*[/bold yellow] " if has_unread else "  "
                needs_reply = "[red]![/red] " if thread.get("needs_reply") else ""

                participant_names = ", ".join(
                    p.get("name", p.get("address", ""))[:15]
                    for p in participants[:3]
                )
                if participant_count > 3:
                    participant_names += f" +{participant_count - 3}"

                content = (
                    f"{unread_marker}{needs_reply}[bold]{subject}[/bold]  "
                    f"[dim]{time_ago}[/dim]\n"
                    f"  {participant_names}  "
                    f"[dim]{msg_count} messages[/dim]"
                )

                listview.append(FlowItem(content, item_data=thread))
        except Exception:
            logger.debug("Failed to populate threads", exc_info=True)

    def _populate_events(self) -> None:
        """Render upcoming events into the list."""
        try:
            listview = self.query_one("#flow-events", ListView)
            listview.clear()

            if not self._events_data:
                listview.append(FlowItem("  No upcoming events", item_data={}))
                return

            for event in self._events_data:
                summary = event.get("summary", "(no title)")
                location = event.get("location", "")
                is_all_day = event.get("is_all_day", False)
                start = event.get("start_time", "")

                time_str = "All day" if is_all_day else relative_date(start)
                loc_str = f"  @ {location}" if location else ""

                content = (
                    f"  [bold]{time_str}[/bold]  {summary}"
                    f"[dim]{loc_str}[/dim]"
                )

                listview.append(FlowItem(content, item_data=event))
        except Exception:
            logger.debug("Failed to populate events", exc_info=True)

    def _populate_todos(self) -> None:
        """Render pending todos into the list."""
        try:
            listview = self.query_one("#flow-todos", ListView)
            listview.clear()

            if not self._todos_data:
                listview.append(FlowItem("  No pending todos", item_data={}))
                return

            for todo in self._todos_data:
                title = todo.get("title", "(untitled)")
                status = todo.get("status", "pending")
                source = todo.get("source", "")

                checkbox = "[ ]" if status == "pending" else "[x]"
                source_hint = f"  [dim]from: {source}[/dim]" if source else ""

                content = f"  {checkbox} {title}{source_hint}"

                listview.append(FlowItem(content, item_data=todo))
        except Exception:
            logger.debug("Failed to populate todos", exc_info=True)

    def _set_section_empty(self, list_id: str, message: str) -> None:
        """Set a section to show an empty/error message."""
        try:
            listview = self.query_one(f"#{list_id}", ListView)
            listview.clear()
            listview.append(FlowItem(f"  [dim]{message}[/dim]", item_data={}))
        except Exception:
            pass

    def _update_status(self, text: str) -> None:
        """Update the status bar text."""
        try:
            self.query_one("#flow-status", Static).update(text)
        except Exception:
            pass

    # ── Section navigation ────────────────────────────────────

    def _get_section_list_ids(self) -> list[str]:
        """Get the ListView IDs for each section."""
        return [
            "flow-needs-reply",
            "flow-awaiting",
            "flow-threads",
            "flow-events",
            "flow-todos",
        ]

    def _get_current_listview(self) -> ListView | None:
        """Get the currently focused section's ListView."""
        list_ids = self._get_section_list_ids()
        if 0 <= self._current_section_idx < len(list_ids):
            try:
                return self.query_one(f"#{list_ids[self._current_section_idx]}", ListView)
            except Exception:
                pass
        return None

    def _focus_section(self, idx: int) -> None:
        """Focus a section by index."""
        list_ids = self._get_section_list_ids()
        if 0 <= idx < len(list_ids):
            self._current_section_idx = idx
            try:
                listview = self.query_one(f"#{list_ids[idx]}", ListView)
                listview.focus()
                # Scroll the section header into view
                header_ids = [
                    "section-header-needs-reply",
                    "section-header-awaiting",
                    "section-header-threads",
                    "section-header-events",
                    "section-header-todos",
                ]
                header = self.query_one(f"#{header_ids[idx]}", FlowSectionHeader)
                header.scroll_visible()
            except Exception:
                pass

    def action_next_section(self) -> None:
        """Move to the next section."""
        new_idx = (self._current_section_idx + 1) % len(SECTIONS)
        self._focus_section(new_idx)

    def action_prev_section(self) -> None:
        """Move to the previous section."""
        new_idx = (self._current_section_idx - 1) % len(SECTIONS)
        self._focus_section(new_idx)

    # ── Item navigation ───────────────────────────────────────

    def action_cursor_down(self) -> None:
        """Move cursor down in the current section."""
        lv = self._get_current_listview()
        if lv is not None:
            lv.action_cursor_down()

    def action_cursor_up(self) -> None:
        """Move cursor up in the current section."""
        lv = self._get_current_listview()
        if lv is not None:
            lv.action_cursor_up()

    # ── Item actions ──────────────────────────────────────────

    def _get_selected_item_data(self) -> dict[str, Any] | None:
        """Get the data dict for the currently highlighted item."""
        lv = self._get_current_listview()
        if lv is None or lv.index is None:
            return None
        try:
            item = lv.children[lv.index]
            if isinstance(item, FlowItem):
                return item.item_data
        except (IndexError, TypeError):
            pass
        return None

    def action_open_item(self) -> None:
        """Open the selected item in detail view."""
        data = self._get_selected_item_data()
        if not data:
            return

        section = SECTIONS[self._current_section_idx]

        if section in ("needs_reply", "awaiting"):
            email_id = data.get("id")
            if email_id:
                from tui.screens.email_view import EmailViewScreen
                self.app.push_screen(EmailViewScreen(email_id=email_id))

        elif section == "threads":
            # Open the first email in the thread
            thread_id = data.get("thread_id")
            if thread_id:
                # We don't have a direct thread screen, so we push
                # to the inbox filtered by thread (or use email view)
                self.notify(
                    f"Thread: {data.get('subject', '')}",
                    severity="information",
                )

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Handle Enter/click on a list item."""
        self.action_open_item()

    @work(exclusive=True, group="action")
    async def action_ignore_item(self) -> None:
        """Ignore a needs-reply item."""
        if self._current_section_idx != 0:
            return
        data = self._get_selected_item_data()
        if not data or not data.get("id"):
            return
        if self._ai_client is None:
            return
        try:
            await self._ai_client.ignore_needs_reply(data["id"])
            self.notify("Ignored", severity="information")
            # Refresh needs-reply section
            self._load_needs_reply()
        except Exception as e:
            self.notify(f"Ignore failed: {e}", severity="error")

    @work(exclusive=True, group="action")
    async def action_snooze_item(self) -> None:
        """Snooze a needs-reply item for 1 hour."""
        if self._current_section_idx != 0:
            return
        data = self._get_selected_item_data()
        if not data or not data.get("id"):
            return
        if self._ai_client is None:
            return
        try:
            await self._ai_client.snooze_needs_reply(data["id"], duration="1h")
            self.notify("Snoozed for 1 hour", severity="information")
            # Refresh needs-reply section
            self._load_needs_reply()
        except Exception as e:
            self.notify(f"Snooze failed: {e}", severity="error")

    def action_skip_item(self) -> None:
        """Skip to the next item in the current section."""
        self.action_cursor_down()

    def action_new_chat(self) -> None:
        """Placeholder for new chat action."""
        self.notify("Chat - coming soon", severity="information")

    def _reply_with_option(self, option_idx: int) -> None:
        """Select an AI reply option and push compose with pre-filled data."""
        if self._current_section_idx != 0:
            return
        data = self._get_selected_item_data()
        if not data or not data.get("id"):
            return

        reply_options = data.get("reply_options") or []
        if option_idx >= len(reply_options):
            self.notify(
                f"No reply option {option_idx + 1} available",
                severity="warning",
            )
            return

        option = reply_options[option_idx]
        # reply_options can be either strings or dicts with "text" key
        if isinstance(option, dict):
            reply_text = option.get("text", option.get("body", str(option)))
        else:
            reply_text = str(option)

        from tui.screens.compose import ComposeScreen
        self.app.push_screen(
            ComposeScreen(
                reply_data=data,
                initial_body=reply_text,
            )
        )

    def action_select_reply_1(self) -> None:
        """Select AI reply option 1."""
        self._reply_with_option(0)

    def action_select_reply_2(self) -> None:
        """Select AI reply option 2."""
        self._reply_with_option(1)

    def action_select_reply_3(self) -> None:
        """Select AI reply option 3."""
        self._reply_with_option(2)

    def action_select_reply_4(self) -> None:
        """Select AI reply option 4."""
        self._reply_with_option(3)

    def action_custom_reply(self) -> None:
        """Push compose screen for a custom reply to the selected needs-reply item."""
        if self._current_section_idx != 0:
            return
        data = self._get_selected_item_data()
        if not data or not data.get("id"):
            return
        from tui.screens.compose import ComposeScreen
        self.app.push_screen(ComposeScreen(reply_data=data))

    def action_deselect(self) -> None:
        """Deselect current item / no-op for back."""
        pass

    @work(exclusive=True, group="refresh-section")
    async def _load_needs_reply(self) -> None:
        """Refresh just the needs-reply section."""
        if self._ai_client is None:
            return
        try:
            result = await self._ai_client.get_needs_reply(page_size=20)
            self._needs_reply_data = result.get("emails", [])
            self._populate_needs_reply()
        except Exception:
            logger.debug("Failed to refresh needs-reply", exc_info=True)
