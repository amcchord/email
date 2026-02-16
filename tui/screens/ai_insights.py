"""AI Insights screen with tabbed views for trends, subscriptions, threads, and coverage."""

from __future__ import annotations

import logging
from typing import Any

from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.widgets import (
    Static,
    DataTable,
    TabbedContent,
    TabPane,
    Button,
)

from tui.client.ai import AIClient
from tui.screens.base import BaseScreen

logger = logging.getLogger(__name__)


class AIInsightsScreen(BaseScreen):
    """AI Insights screen with tabbed content for trends, subscriptions, threads, and coverage."""

    SCREEN_TITLE = "AI Insights"
    SCREEN_NAV_ID = "ai_insights"
    DEFAULT_SHORTCUTS = [
        ("Tab", "Switch tab"),
        ("j/k", "Scroll"),
        ("r", "Refresh"),
        ("?", "Help"),
    ]

    BINDINGS = [
        *BaseScreen.BINDINGS,
        Binding("j", "scroll_down", "Scroll down", show=False),
        Binding("k", "scroll_up", "Scroll up", show=False),
        Binding("r", "refresh_tab", "Refresh", show=False),
    ]

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._ai_client: AIClient | None = None
        self._active_tab: str = "trends"
        self._loaded_tabs: set[str] = set()

    def compose_content(self) -> ComposeResult:
        with TabbedContent(id="insights-tabs"):
            with TabPane("Trends", id="tab-trends"):
                yield VerticalScroll(
                    Static("[dim]Loading trends...[/dim]", id="trends-content"),
                    id="trends-scroll",
                )

            with TabPane("Subscriptions", id="tab-subscriptions"):
                yield VerticalScroll(
                    DataTable(id="subs-table"),
                    id="subs-scroll",
                )

            with TabPane("Threads", id="tab-threads"):
                yield VerticalScroll(
                    Static("[dim]Loading threads...[/dim]", id="threads-content"),
                    id="threads-scroll",
                )

            with TabPane("Coverage", id="tab-coverage"):
                yield VerticalScroll(
                    Static("[dim]Loading coverage...[/dim]", id="coverage-content"),
                    Button("Auto-Categorize (30 days)", id="btn-categorize-30", variant="primary"),
                    Button("Auto-Categorize (All)", id="btn-categorize-all"),
                    id="coverage-scroll",
                )

        yield Static("", id="insights-status")

    def on_mount(self) -> None:
        """Initialize AI client and load first tab."""
        super().on_mount()
        self._ai_client = AIClient(self.app.api_client)

        # Set up subscriptions table columns
        try:
            table = self.query_one("#subs-table", DataTable)
            table.add_columns("Sender", "Domain", "Count")
            table.cursor_type = "row"
        except Exception:
            pass

        # Load the active tab
        self._load_tab("trends")

    def on_tabbed_content_tab_activated(
        self, event: TabbedContent.TabActivated
    ) -> None:
        """Load data when a tab is activated."""
        tab_id = event.pane.id or ""
        tab_name = tab_id.replace("tab-", "")
        self._active_tab = tab_name
        if tab_name not in self._loaded_tabs:
            self._load_tab(tab_name)

    def _load_tab(self, tab_name: str) -> None:
        """Dispatch data loading for the given tab."""
        if tab_name == "trends":
            self._load_trends()
        elif tab_name == "subscriptions":
            self._load_subscriptions()
        elif tab_name == "threads":
            self._load_threads()
        elif tab_name == "coverage":
            self._load_coverage()

    # ── Trends Tab ───────────────────────────────────────────

    @work(exclusive=True, group="load-trends")
    async def _load_trends(self) -> None:
        """Fetch and display trends data."""
        if self._ai_client is None:
            return
        try:
            data = await self._ai_client.get_trends()
            self.call_from_thread(self._render_trends, data)
            self._loaded_tabs.add("trends")
        except Exception as e:
            logger.debug("Failed to load trends", exc_info=True)
            self.call_from_thread(
                self._set_content, "#trends-content", f"[red]Error: {e}[/red]"
            )

    def _render_trends(self, data: dict[str, Any]) -> None:
        """Render trends data."""
        lines = []

        # Summary
        summary = data.get("summary")
        if summary:
            lines.append(f"[bold yellow]{summary}[/bold yellow]\n")

        # Needs attention
        needs = data.get("needs_attention", [])
        if needs:
            lines.append(f"[bold]Needs Attention ({len(needs)})[/bold]")
            for item in needs[:10]:
                from_name = item.get("from_name", "Unknown")
                subject = item.get("subject", "(no subject)")
                category = item.get("category", "")
                priority = item.get("priority", 0)

                priority_marker = "[red]![/red] " if priority >= 4 else ""
                cat_label = f"[dim]{category}[/dim]" if category else ""
                lines.append(
                    f"  {priority_marker}[bold]{from_name}[/bold]: {subject}  {cat_label}"
                )
            lines.append("")

        # Top topics
        topics = data.get("top_topics", [])
        if topics:
            lines.append("[bold]Top Topics[/bold]")
            for topic in topics[:10]:
                name = topic.get("topic", "?")
                count = topic.get("count", 0)
                lines.append(f"  {name}  [dim]({count})[/dim]")
            lines.append("")

        # Urgent senders
        senders = data.get("urgent_senders", [])
        if senders:
            lines.append("[bold]Frequent Urgent Senders[/bold]")
            for sender in senders[:10]:
                name = sender.get("name", sender.get("address", "?"))
                count = sender.get("count", 0)
                lines.append(f"  {name}  [dim]({count} urgent)[/dim]")
            lines.append("")

        # Category distribution over time
        cat_data = data.get("category_over_time", [])
        if cat_data:
            # Group by category
            cat_totals: dict[str, int] = {}
            for entry in cat_data:
                cat = entry.get("category", "unknown")
                count = entry.get("count", 0)
                cat_totals[cat] = cat_totals.get(cat, 0) + count

            lines.append("[bold]Category Distribution (14 days)[/bold]")
            sorted_cats = sorted(
                cat_totals.items(), key=lambda x: x[1], reverse=True
            )
            total = sum(v for _, v in sorted_cats) or 1
            for cat, count in sorted_cats:
                pct = count / total * 100
                label = cat.replace("_", " ").title()
                lines.append(f"  {label:<20s}  {count:>5,}  ({pct:.1f}%)")

        # Totals
        total_analyzed = data.get("total_analyzed", 0)
        total_unanalyzed = data.get("total_unanalyzed", 0)
        if total_analyzed or total_unanalyzed:
            lines.append("")
            lines.append(
                f"[dim]Analyzed: {total_analyzed:,} | "
                f"Unanalyzed: {total_unanalyzed:,}[/dim]"
            )

        content = "\n".join(lines) if lines else "[dim]No trend data available[/dim]"
        self._set_content("#trends-content", content)

    # ── Subscriptions Tab ────────────────────────────────────

    @work(exclusive=True, group="load-subs")
    async def _load_subscriptions(self) -> None:
        """Fetch and display subscriptions data."""
        if self._ai_client is None:
            return
        try:
            data = await self._ai_client.get_subscriptions()
            self.call_from_thread(self._render_subscriptions, data)
            self._loaded_tabs.add("subscriptions")
        except Exception as e:
            logger.debug("Failed to load subscriptions", exc_info=True)
            self.call_from_thread(
                self._update_status, f"Subscriptions error: {e}"
            )

    def _render_subscriptions(self, data: dict[str, Any]) -> None:
        """Render subscriptions into the DataTable."""
        try:
            table = self.query_one("#subs-table", DataTable)
            table.clear()

            senders = data.get("senders", [])
            if not senders:
                # Show in status instead
                self._update_status("No subscription data found")
                return

            for sender in senders:
                from_name = sender.get("from_name", "Unknown")
                domain = sender.get("domain", "")
                count = sender.get("count", 0)
                table.add_row(from_name, domain, str(count))

            self._update_status(
                f"{len(senders)} subscription senders, {data.get('total', 0)} total emails"
            )
        except Exception:
            logger.debug("Failed to render subscriptions", exc_info=True)

    # ── Threads Tab ──────────────────────────────────────────

    @work(exclusive=True, group="load-threads")
    async def _load_threads(self) -> None:
        """Fetch and display thread digests."""
        if self._ai_client is None:
            return
        try:
            data = await self._ai_client.get_digests(page_size=30)
            self.call_from_thread(self._render_threads, data)
            self._loaded_tabs.add("threads")
        except Exception as e:
            logger.debug("Failed to load threads", exc_info=True)
            self.call_from_thread(
                self._set_content, "#threads-content", f"[red]Error: {e}[/red]"
            )

    def _render_threads(self, data: dict[str, Any]) -> None:
        """Render thread digests."""
        digests = data.get("digests", [])
        if not digests:
            self._set_content(
                "#threads-content", "[dim]No thread digests available[/dim]"
            )
            return

        lines = [f"[bold]Active Thread Digests ({len(digests)})[/bold]\n"]
        for digest in digests:
            subject = digest.get("subject", "(no subject)")
            conv_type = digest.get("conversation_type", "")
            summary = digest.get("summary", "")
            msg_count = digest.get("message_count", 0)
            participants = digest.get("participants", [])
            is_resolved = digest.get("is_resolved", False)

            resolved_marker = (
                "[green]resolved[/green]"
                if is_resolved
                else "[yellow]active[/yellow]"
            )
            type_label = f"[dim]{conv_type}[/dim]" if conv_type else ""
            participant_count = len(participants) if isinstance(participants, list) else 0

            lines.append(f"  [bold]{subject}[/bold]  {resolved_marker}")
            lines.append(
                f"    {msg_count} messages, {participant_count} participants  {type_label}"
            )
            if summary:
                # Truncate summary
                short_summary = summary[:120]
                if len(summary) > 120:
                    short_summary += "..."
                lines.append(f"    [dim italic]{short_summary}[/dim italic]")
            lines.append("")

        self._set_content("#threads-content", "\n".join(lines))

    # ── Coverage Tab ─────────────────────────────────────────

    @work(exclusive=True, group="load-coverage")
    async def _load_coverage(self) -> None:
        """Fetch and display AI analysis coverage stats."""
        if self._ai_client is None:
            return
        try:
            data = await self._ai_client.get_stats()
            self.call_from_thread(self._render_coverage, data)
            self._loaded_tabs.add("coverage")
        except Exception as e:
            logger.debug("Failed to load coverage", exc_info=True)
            self.call_from_thread(
                self._set_content,
                "#coverage-content",
                f"[red]Error: {e}[/red]",
            )

    def _render_coverage(self, data: dict[str, Any]) -> None:
        """Render AI analysis coverage information."""
        total = data.get("total_emails", 0)
        analyzed = data.get("total_analyzed", 0)
        models = data.get("models", {})
        unanalyzed = data.get("unanalyzed", {})

        pct = (analyzed / total * 100) if total > 0 else 0

        lines = [
            "[bold]AI Analysis Statistics[/bold]\n",
            f"  Total Emails:   {total:,}",
            f"  Analyzed:       {analyzed:,}  ({pct:.1f}%)",
            f"  Unanalyzed:     {total - analyzed:,}",
            "",
        ]

        if unanalyzed:
            lines.append("[bold]Unanalyzed by Period:[/bold]")
            period_labels = {
                "30d": "Last 30 days",
                "90d": "Last 90 days",
                "1y": "Last year",
                "all": "All time",
            }
            for period, count in unanalyzed.items():
                label = period_labels.get(period, period)
                lines.append(f"  {label:<15s}  {count:,}")
            lines.append("")

        if models:
            lines.append("[bold]Analyzed by Model:[/bold]")
            for model_name, count in sorted(
                models.items(), key=lambda x: x[1], reverse=True
            ):
                lines.append(f"  {model_name:<30s}  {count:,}")

        self._set_content("#coverage-content", "\n".join(lines))

    # ── Button handlers ──────────────────────────────────────

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        if event.button.id == "btn-categorize-30":
            self._trigger_categorize(days=30)
        elif event.button.id == "btn-categorize-all":
            self._trigger_categorize(days=None)

    @work(exclusive=True, group="categorize")
    async def _trigger_categorize(self, days: int | None = None) -> None:
        """Trigger auto-categorization."""
        if self._ai_client is None:
            return
        try:
            result = await self._ai_client.auto_categorize(days=days)
            msg = result.get("message", "Categorization queued")
            self.call_from_thread(self.notify, msg, severity="information")
            self.call_from_thread(self._update_status, msg)
        except Exception as e:
            self.call_from_thread(
                self.notify, f"Categorize failed: {e}", severity="error"
            )

    # ── Helpers ──────────────────────────────────────────────

    def _set_content(self, widget_id: str, text: str) -> None:
        """Update a Static widget's content."""
        try:
            self.query_one(widget_id, Static).update(text)
        except Exception:
            pass

    def _update_status(self, text: str) -> None:
        """Update the status bar."""
        try:
            self.query_one("#insights-status", Static).update(text)
        except Exception:
            pass

    # ── Actions ──────────────────────────────────────────────

    def action_scroll_down(self) -> None:
        """Scroll down in the active tab."""
        scroll_ids = {
            "trends": "#trends-scroll",
            "subscriptions": "#subs-scroll",
            "threads": "#threads-scroll",
            "coverage": "#coverage-scroll",
        }
        scroll_id = scroll_ids.get(self._active_tab, "#trends-scroll")
        try:
            self.query_one(scroll_id, VerticalScroll).scroll_down()
        except Exception:
            pass

    def action_scroll_up(self) -> None:
        """Scroll up in the active tab."""
        scroll_ids = {
            "trends": "#trends-scroll",
            "subscriptions": "#subs-scroll",
            "threads": "#threads-scroll",
            "coverage": "#coverage-scroll",
        }
        scroll_id = scroll_ids.get(self._active_tab, "#trends-scroll")
        try:
            self.query_one(scroll_id, VerticalScroll).scroll_up()
        except Exception:
            pass

    def action_refresh_tab(self) -> None:
        """Refresh the active tab's data."""
        self._loaded_tabs.discard(self._active_tab)
        self._load_tab(self._active_tab)
