"""Flow dashboard screen - main workflow view with modern paneled sections."""

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

SECTIONS = ["needs_reply", "awaiting", "threads", "events", "todos"]

# Unicode icons for section headers
SECTION_ICONS = {
    "needs_reply": "\u2709",
    "awaiting": "\u21bb",
    "threads": "\u2637",
    "events": "\u25a3",
    "todos": "\u2611",
}


class FlowSectionHeader(Static):
    """A styled section header inside a bordered panel."""

    DEFAULT_CSS = """
    FlowSectionHeader {
        width: 100%;
        height: 1;
        background: #232440;
        color: #e2e8f0;
        text-style: bold;
        padding: 0 1;
    }
    """


class FlowItem(ListItem):
    """A single item in a flow section list with priority support."""

    DEFAULT_CSS = """
    FlowItem {
        width: 100%;
        height: auto;
        padding: 0 1;
        background: #1a1b2e;
    }
    FlowItem > .flow-item-content {
        width: 100%;
        height: auto;
    }
    FlowItem.priority-high {
        border-left: tall #ef4444;
    }
    FlowItem.priority-medium {
        border-left: tall #f59e0b;
    }
    """

    def __init__(
        self,
        content: str,
        item_data: dict[str, Any] | None = None,
        priority_class: str = "",
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._content = content
        self.item_data = item_data or {}
        self._priority_class = priority_class

    def compose(self) -> ComposeResult:
        yield Static(self._content, classes="flow-item-content")

    def on_mount(self) -> None:
        if self._priority_class:
            self.add_class(self._priority_class)


class FlowScreen(BaseScreen):
    """Flow dashboard with five sections in bordered panels."""

    SCREEN_TITLE = "Flow"
    SCREEN_NAV_ID = "flow"
    DEFAULT_SHORTCUTS = [
        ("j/k", "Nav"),
        ("Tab", "Section"),
        ("Enter", "Open"),
        ("1-4", "Reply"),
        ("i", "Ignore"),
        ("z", "Snooze"),
        ("c", "Compose"),
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
            with Vertical(classes="flow-section-panel"):
                yield FlowSectionHeader(
                    "\u2709  Needs Reply",
                    id="section-header-needs-reply",
                )
                yield ListView(id="flow-needs-reply")

            # Section 2: Awaiting Response
            with Vertical(classes="flow-section-panel"):
                yield FlowSectionHeader(
                    "\u21bb  Awaiting Response",
                    id="section-header-awaiting",
                )
                yield ListView(id="flow-awaiting")

            # Section 3: Active Threads
            with Vertical(classes="flow-section-panel"):
                yield FlowSectionHeader(
                    "\u2637  Active Threads",
                    id="section-header-threads",
                )
                yield ListView(id="flow-threads")

            # Section 4: Upcoming Events
            with Vertical(classes="flow-section-panel"):
                yield FlowSectionHeader(
                    "\u25a3  Upcoming Events",
                    id="section-header-events",
                )
                yield ListView(id="flow-events")

            # Section 5: Pending Todos
            with Vertical(classes="flow-section-panel"):
                yield FlowSectionHeader(
                    "\u2611  Pending Todos",
                    id="section-header-todos",
                )
                yield ListView(id="flow-todos")

            yield Static("Loading...", id="flow-status")

    def on_mount(self) -> None:
        """Initialize AI client and fetch all data."""
        super().on_mount()
        self._ai_client = AIClient(self.app.api_client)
        self._load_all_data()

    @work(exclusive=True)
    async def _load_all_data(self) -> None:
        """Fetch all five data sources in parallel."""
        import asyncio

        if self._ai_client is None:
            return

        results = await asyncio.gather(
            self._fetch_needs_reply(),
            self._fetch_awaiting(),
            self._fetch_threads(),
            self._fetch_events(),
            self._fetch_todos(),
            return_exceptions=True,
        )

        errors = [r for r in results if isinstance(r, Exception)]

        def _update_ui_after_load():
            if errors:
                error_msgs = "; ".join(str(e) for e in errors)
                self._update_status(f"[#ef4444]\u26a0[/#ef4444] Some sections failed: {error_msgs}")
            else:
                counts = []
                if self._needs_reply_data:
                    counts.append(f"[#2dd4bf]{len(self._needs_reply_data)}[/#2dd4bf] needs reply")
                if self._awaiting_data:
                    counts.append(f"[#2dd4bf]{len(self._awaiting_data)}[/#2dd4bf] awaiting")
                if self._threads_data:
                    counts.append(f"[#2dd4bf]{len(self._threads_data)}[/#2dd4bf] threads")
                if self._events_data:
                    counts.append(f"[#2dd4bf]{len(self._events_data)}[/#2dd4bf] events")
                if self._todos_data:
                    counts.append(f"[#2dd4bf]{len(self._todos_data)}[/#2dd4bf] todos")
                if counts:
                    status_text = " \u2502 ".join(counts)
                else:
                    status_text = "[#2dd4bf]\u2713[/#2dd4bf] All caught up!"
                self._update_status(status_text)

            self._update_section_header("needs-reply", "Needs Reply", len(self._needs_reply_data))
            self._update_section_header("awaiting", "Awaiting Response", len(self._awaiting_data))
            self._update_section_header("threads", "Active Threads", len(self._threads_data))
            self._update_section_header("events", "Upcoming Events", len(self._events_data))
            self._update_section_header("todos", "Pending Todos", len(self._todos_data))

        _update_ui_after_load()

    def _update_section_header(self, section_key: str, title: str, count: int) -> None:
        """Update a section header with its count."""
        icon = SECTION_ICONS.get(section_key.replace("-", "_"), "\u2022")
        count_str = f" [#2dd4bf]({count})[/#2dd4bf]" if count else ""
        try:
            header = self.query_one(f"#section-header-{section_key}", FlowSectionHeader)
            header.update(f"{icon}  {title}{count_str}")
        except Exception:
            pass

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
            self._set_section_empty("flow-events", "No events available")

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
            self._set_section_empty("flow-todos", "No todos available")

    # ── Populate sections ─────────────────────────────────────

    def _populate_needs_reply(self) -> None:
        """Render needs-reply emails with inline reply previews."""
        try:
            listview = self.query_one("#flow-needs-reply", ListView)
            listview.clear()

            if not self._needs_reply_data:
                listview.append(FlowItem(
                    "  [#2dd4bf]\u2713[/#2dd4bf] All caught up! Press [reverse] c [/reverse] to compose",
                    item_data={},
                ))
                return

            for email in self._needs_reply_data:
                from_name = email.get("from_name", email.get("from_address", "Unknown"))
                subject = email.get("subject", "(no subject)")
                time_ago = relative_date(email.get("date"))
                summary = email.get("summary", "")
                priority = email.get("priority", 0)

                # Priority class for left-bar indicator
                priority_class = ""
                if priority and priority >= 4:
                    priority_class = "priority-high"
                elif priority and priority >= 3:
                    priority_class = "priority-medium"

                priority_indicator = ""
                if priority and priority >= 4:
                    priority_indicator = "[#ef4444]\u25cf[/#ef4444] "
                elif priority and priority >= 3:
                    priority_indicator = "[#f59e0b]\u25cf[/#f59e0b] "

                # Build reply options preview
                reply_options = email.get("reply_options") or []
                options_lines = ""
                if reply_options:
                    for i, opt in enumerate(reply_options[:4], 1):
                        opt_text = opt
                        if isinstance(opt, dict):
                            opt_text = opt.get("text", opt.get("body", str(opt)))
                        preview = str(opt_text)[:50].replace("\n", " ")
                        options_lines += f"\n    [#64748b][reverse] {i} [/reverse] {preview}[/#64748b]"

                content = (
                    f"  {priority_indicator}[bold]{from_name}[/bold]  "
                    f"[#94a3b8]{time_ago}[/#94a3b8]\n"
                    f"  {subject}\n"
                    f"  [#64748b italic]{summary[:80]}[/#64748b italic]"
                    f"{options_lines}"
                )

                listview.append(FlowItem(content, item_data=email, priority_class=priority_class))
        except Exception:
            logger.debug("Failed to populate needs-reply", exc_info=True)

    def _populate_awaiting(self) -> None:
        """Render awaiting-response emails."""
        try:
            listview = self.query_one("#flow-awaiting", ListView)
            listview.clear()

            if not self._awaiting_data:
                listview.append(FlowItem(
                    "  [#64748b]No emails awaiting response[/#64748b]",
                    item_data={},
                ))
                return

            for email in self._awaiting_data:
                to_name = email.get("to_name", "Unknown")
                subject = email.get("subject", "(no subject)")
                time_ago = relative_date(email.get("date"))

                content = (
                    f"  [bold]{to_name}[/bold]  [#94a3b8]{time_ago}[/#94a3b8]\n"
                    f"  {subject}"
                )

                listview.append(FlowItem(content, item_data=email))
        except Exception:
            logger.debug("Failed to populate awaiting", exc_info=True)

    def _populate_threads(self) -> None:
        """Render active threads."""
        try:
            listview = self.query_one("#flow-threads", ListView)
            listview.clear()

            if not self._threads_data:
                listview.append(FlowItem(
                    "  [#64748b]No active threads[/#64748b]",
                    item_data={},
                ))
                return

            for thread in self._threads_data:
                subject = thread.get("subject", "(no subject)")
                msg_count = thread.get("message_count", 0)
                participants = thread.get("participants", [])
                participant_count = len(participants)
                time_ago = relative_date(thread.get("latest_date"))
                has_unread = thread.get("has_unread", False)

                unread_marker = "[#f59e0b bold]\u25cf[/#f59e0b bold] " if has_unread else "  "
                needs_reply = "[#ef4444]\u25cf[/#ef4444] " if thread.get("needs_reply") else ""

                participant_names = ", ".join(
                    p.get("name", p.get("address", ""))[:15]
                    for p in participants[:3]
                )
                if participant_count > 3:
                    participant_names += f" +{participant_count - 3}"

                content = (
                    f"  {unread_marker}{needs_reply}[bold]{subject}[/bold]  "
                    f"[#94a3b8]{time_ago}[/#94a3b8]\n"
                    f"  {participant_names}  "
                    f"[#64748b]{msg_count} messages[/#64748b]"
                )

                listview.append(FlowItem(content, item_data=thread))
        except Exception:
            logger.debug("Failed to populate threads", exc_info=True)

    def _populate_events(self) -> None:
        """Render upcoming events."""
        try:
            listview = self.query_one("#flow-events", ListView)
            listview.clear()

            if not self._events_data:
                listview.append(FlowItem(
                    "  [#64748b]No upcoming events[/#64748b]",
                    item_data={},
                ))
                return

            for event in self._events_data:
                summary = event.get("summary", "(no title)")
                location = event.get("location", "")
                is_all_day = event.get("is_all_day", False)
                start = event.get("start_time", "")

                time_str = "All day" if is_all_day else relative_date(start)
                loc_str = f"  [#64748b]@ {location}[/#64748b]" if location else ""

                content = (
                    f"  [#6366f1 bold]{time_str}[/#6366f1 bold]  {summary}"
                    f"{loc_str}"
                )

                listview.append(FlowItem(content, item_data=event))
        except Exception:
            logger.debug("Failed to populate events", exc_info=True)

    def _populate_todos(self) -> None:
        """Render pending todos."""
        try:
            listview = self.query_one("#flow-todos", ListView)
            listview.clear()

            if not self._todos_data:
                listview.append(FlowItem(
                    "  [#2dd4bf]\u2713[/#2dd4bf] No pending todos",
                    item_data={},
                ))
                return

            for todo in self._todos_data:
                title = todo.get("title", "(untitled)")
                status = todo.get("status", "pending")
                source = todo.get("source", "")

                if status == "pending":
                    checkbox = "[#94a3b8]\u2610[/#94a3b8]"
                else:
                    checkbox = "[#2dd4bf]\u2611[/#2dd4bf]"
                source_hint = f"  [#64748b]from: {source}[/#64748b]" if source else ""

                content = f"  {checkbox} {title}{source_hint}"

                listview.append(FlowItem(content, item_data=todo))
        except Exception:
            logger.debug("Failed to populate todos", exc_info=True)

    def _set_section_empty(self, list_id: str, message: str) -> None:
        """Set a section to show an empty/error message."""
        try:
            listview = self.query_one(f"#{list_id}", ListView)
            listview.clear()
            listview.append(FlowItem(f"  [#64748b]{message}[/#64748b]", item_data={}))
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
        return [
            "flow-needs-reply",
            "flow-awaiting",
            "flow-threads",
            "flow-events",
            "flow-todos",
        ]

    def _get_current_listview(self) -> ListView | None:
        list_ids = self._get_section_list_ids()
        if 0 <= self._current_section_idx < len(list_ids):
            try:
                return self.query_one(f"#{list_ids[self._current_section_idx]}", ListView)
            except Exception:
                pass
        return None

    def _focus_section(self, idx: int) -> None:
        list_ids = self._get_section_list_ids()
        if 0 <= idx < len(list_ids):
            self._current_section_idx = idx
            try:
                listview = self.query_one(f"#{list_ids[idx]}", ListView)
                listview.focus()
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
        new_idx = (self._current_section_idx + 1) % len(SECTIONS)
        self._focus_section(new_idx)

    def action_prev_section(self) -> None:
        new_idx = (self._current_section_idx - 1) % len(SECTIONS)
        self._focus_section(new_idx)

    # ── Item navigation ───────────────────────────────────────

    def action_cursor_down(self) -> None:
        lv = self._get_current_listview()
        if lv is not None:
            lv.action_cursor_down()

    def action_cursor_up(self) -> None:
        lv = self._get_current_listview()
        if lv is not None:
            lv.action_cursor_up()

    # ── Item actions ──────────────────────────────────────────

    def _get_selected_item_data(self) -> dict[str, Any] | None:
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
            thread_id = data.get("thread_id")
            if thread_id:
                self.notify(
                    f"Thread: {data.get('subject', '')}",
                    severity="information",
                )

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        self.action_open_item()

    @work(exclusive=True, group="action")
    async def action_ignore_item(self) -> None:
        if self._current_section_idx != 0:
            return
        data = self._get_selected_item_data()
        if not data or not data.get("id"):
            return
        if self._ai_client is None:
            return
        try:
            await self._ai_client.ignore_needs_reply(data["id"])
            self.notify("\u2713 Ignored", severity="information")
            self._load_needs_reply()
        except Exception as e:
            self.notify(f"Ignore failed: {e}", severity="error")

    @work(exclusive=True, group="action")
    async def action_snooze_item(self) -> None:
        if self._current_section_idx != 0:
            return
        data = self._get_selected_item_data()
        if not data or not data.get("id"):
            return
        if self._ai_client is None:
            return
        try:
            await self._ai_client.snooze_needs_reply(data["id"], duration="1h")
            self.notify("\u23f0 Snoozed for 1 hour", severity="information")
            self._load_needs_reply()
        except Exception as e:
            self.notify(f"Snooze failed: {e}", severity="error")

    def action_skip_item(self) -> None:
        self.action_cursor_down()

    def action_new_chat(self) -> None:
        self.notify("Chat - coming soon", severity="information")

    def _reply_with_option(self, option_idx: int) -> None:
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
        self._reply_with_option(0)

    def action_select_reply_2(self) -> None:
        self._reply_with_option(1)

    def action_select_reply_3(self) -> None:
        self._reply_with_option(2)

    def action_select_reply_4(self) -> None:
        self._reply_with_option(3)

    def action_custom_reply(self) -> None:
        if self._current_section_idx != 0:
            return
        data = self._get_selected_item_data()
        if not data or not data.get("id"):
            return
        from tui.screens.compose import ComposeScreen
        self.app.push_screen(ComposeScreen(reply_data=data))

    def action_deselect(self) -> None:
        pass

    @work(exclusive=True, group="refresh-section")
    async def _load_needs_reply(self) -> None:
        if self._ai_client is None:
            return
        try:
            result = await self._ai_client.get_needs_reply(page_size=20)
            self._needs_reply_data = result.get("emails", [])
            self._populate_needs_reply()
            self._update_section_header("needs-reply", "Needs Reply", len(self._needs_reply_data))
        except Exception:
            logger.debug("Failed to refresh needs-reply", exc_info=True)
