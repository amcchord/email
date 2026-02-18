"""Settings screen with tabbed content for profile, accounts, AI, preferences, and admin."""

from __future__ import annotations

import logging
from typing import Any

from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, VerticalScroll
from textual.widgets import (
    Static,
    Button,
    Input,
    Select,
    TextArea,
    TabbedContent,
    TabPane,
    Label,
)

from tui.client.accounts import AccountsClient
from tui.client.admin import AdminClient
from tui.screens.base import BaseScreen

logger = logging.getLogger(__name__)

# AI model options matching backend ALLOWED_MODELS
AI_MODEL_OPTIONS = [
    ("Claude Opus 4.6", "claude-opus-4-6"),
    ("Claude Opus 4.6 Fast", "claude-opus-4-6-fast"),
    ("Claude Sonnet 4.5", "claude-sonnet-4-5-20250929"),
    ("Claude Haiku 4.5", "claude-haiku-4-5-20251001"),
]

THREAD_ORDER_OPTIONS = [
    ("Newest First", "newest_first"),
    ("Oldest First", "oldest_first"),
]


class SettingsScreen(BaseScreen):
    """Settings screen with tabs for profile, accounts, AI models, preferences, and admin."""

    SCREEN_TITLE = "Settings"
    SCREEN_NAV_ID = "settings"
    DEFAULT_SHORTCUTS = [
        ("Tab", "Switch tab"),
        ("r", "Refresh"),
        ("?", "Help"),
    ]

    BINDINGS = [
        *BaseScreen.BINDINGS,
        Binding("r", "refresh_settings", "Refresh", show=False),
    ]

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._accounts_client: AccountsClient | None = None
        self._admin_client: AdminClient | None = None
        self._is_admin: bool = False
        self._loaded_tabs: set[str] = set()

    def compose_content(self) -> ComposeResult:
        with TabbedContent(id="settings-tabs"):
            # Profile tab
            with TabPane("Profile", id="tab-profile"):
                yield VerticalScroll(
                    Static("[bold]Profile[/bold]", classes="settings-section-header"),
                    Horizontal(
                        Label("Name: ", classes="settings-label"),
                        Static("", id="profile-name", classes="settings-value"),
                        classes="settings-row",
                    ),
                    Horizontal(
                        Label("Email: ", classes="settings-label"),
                        Static("", id="profile-email", classes="settings-value"),
                        classes="settings-row",
                    ),
                    Static("\n[bold]About Me[/bold]", classes="settings-section-header"),
                    TextArea(id="about-me-text"),
                    Horizontal(
                        Button("Save About Me", id="btn-save-about", variant="primary"),
                        classes="settings-button-row",
                    ),
                    id="profile-scroll",
                )

            # Accounts tab
            with TabPane("Accounts", id="tab-accounts"):
                yield VerticalScroll(
                    Static("[bold]Connected Accounts[/bold]", classes="settings-section-header"),
                    Static("[dim]Loading accounts...[/dim]", id="accounts-list"),
                    id="accounts-scroll",
                )

            # AI Models tab
            with TabPane("AI Models", id="tab-ai"):
                yield VerticalScroll(
                    Static("[bold]AI Model Preferences[/bold]", classes="settings-section-header"),
                    Static("[dim]Configure which models are used for each AI task.[/dim]\n"),
                    Horizontal(
                        Label("Chat Plan: ", classes="settings-label"),
                        Select(AI_MODEL_OPTIONS, id="ai-chat-plan", allow_blank=False),
                        classes="settings-row",
                    ),
                    Horizontal(
                        Label("Chat Execute: ", classes="settings-label"),
                        Select(AI_MODEL_OPTIONS, id="ai-chat-execute", allow_blank=False),
                        classes="settings-row",
                    ),
                    Horizontal(
                        Label("Chat Verify: ", classes="settings-label"),
                        Select(AI_MODEL_OPTIONS, id="ai-chat-verify", allow_blank=False),
                        classes="settings-row",
                    ),
                    Horizontal(
                        Label("Agentic: ", classes="settings-label"),
                        Select(AI_MODEL_OPTIONS, id="ai-agentic", allow_blank=False),
                        classes="settings-row",
                    ),
                    Horizontal(
                        Label("Custom Prompt: ", classes="settings-label"),
                        Select(AI_MODEL_OPTIONS, id="ai-custom-prompt", allow_blank=False),
                        classes="settings-row",
                    ),
                    Horizontal(
                        Button("Save AI Preferences", id="btn-save-ai", variant="primary"),
                        classes="settings-button-row",
                    ),
                    id="ai-scroll",
                )

            # Preferences tab
            with TabPane("Preferences", id="tab-prefs"):
                yield VerticalScroll(
                    Static("[bold]UI Preferences[/bold]", classes="settings-section-header"),
                    Horizontal(
                        Label("Thread Order: ", classes="settings-label"),
                        Select(THREAD_ORDER_OPTIONS, id="pref-thread-order", allow_blank=False),
                        classes="settings-row",
                    ),
                    Horizontal(
                        Button("Save Preferences", id="btn-save-prefs", variant="primary"),
                        classes="settings-button-row",
                    ),
                    id="prefs-scroll",
                )

            # Admin tab (hidden for non-admins)
            with TabPane("Admin", id="tab-admin"):
                yield VerticalScroll(
                    Static("[bold]Application Settings[/bold]", classes="settings-section-header"),
                    Static("[dim]Loading settings...[/dim]", id="admin-settings-list"),
                    Static("\n[bold]Edit Setting[/bold]", classes="settings-section-header"),
                    Horizontal(
                        Label("Key: ", classes="settings-label"),
                        Input(placeholder="setting_key", id="admin-setting-key"),
                        classes="settings-row",
                    ),
                    Horizontal(
                        Label("Value: ", classes="settings-label"),
                        Input(placeholder="setting_value", id="admin-setting-value"),
                        classes="settings-row",
                    ),
                    Horizontal(
                        Label("Description: ", classes="settings-label"),
                        Input(placeholder="optional description", id="admin-setting-desc"),
                        classes="settings-row",
                    ),
                    Horizontal(
                        Button("Save Setting", id="btn-save-setting", variant="primary"),
                        Button("Delete Setting", id="btn-delete-setting", variant="error"),
                        classes="settings-button-row",
                    ),
                    Static("\n[bold]Data Management[/bold]", classes="settings-section-header"),
                    Horizontal(
                        Button("Delete AI Analyses", id="btn-delete-analyses", variant="warning"),
                        Button("Rebuild Search Index", id="btn-rebuild-index", variant="warning"),
                        classes="settings-button-row",
                    ),
                    id="admin-scroll",
                )

        yield Static("", id="settings-status")

    def on_mount(self) -> None:
        """Initialize clients and load profile data."""
        super().on_mount()
        self._accounts_client = AccountsClient(self.app.api_client)
        self._admin_client = AdminClient(self.app.api_client)
        self._is_admin = self.app.user.get("is_admin", False) if self.app.user else False

        # Hide admin tab if not admin
        if not self._is_admin:
            try:
                tabs = self.query_one("#settings-tabs", TabbedContent)
                tabs.hide_tab("tab-admin")
            except Exception:
                pass

        # Load profile tab data
        self._load_profile()

    def on_tabbed_content_tab_activated(
        self, event: TabbedContent.TabActivated
    ) -> None:
        """Load data when a tab is activated."""
        tab_id = event.pane.id or ""
        tab_name = tab_id.replace("tab-", "")
        if tab_name not in self._loaded_tabs:
            self._dispatch_tab_load(tab_name)

    def _dispatch_tab_load(self, tab_name: str) -> None:
        """Load data for the given tab."""
        if tab_name == "profile":
            self._load_profile()
        elif tab_name == "accounts":
            self._load_accounts()
        elif tab_name == "ai":
            self._load_ai_preferences()
        elif tab_name == "prefs":
            self._load_ui_preferences()
        elif tab_name == "admin":
            self._load_admin_settings()

    # ── Profile Tab ───────────────────────────────────────────

    @work(exclusive=True, group="load-profile")
    async def _load_profile(self) -> None:
        """Fetch and display profile data."""
        try:
            me = await self.app.api_client.get("/auth/me")
            about = await self.app.api_client.get("/auth/about-me")
            self._render_profile(me, about)
            self._loaded_tabs.add("profile")
        except Exception as e:
            logger.debug("Failed to load profile", exc_info=True)
            self._update_status(f"Profile error: {e}")

    def _render_profile(self, me: dict[str, Any], about: dict[str, Any]) -> None:
        """Render profile data into widgets."""
        try:
            name = me.get("display_name", "") or me.get("username", "")
            email = me.get("email", "") or ""
            self.query_one("#profile-name", Static).update(name)
            self.query_one("#profile-email", Static).update(email)

            about_text = about.get("about_me", "") or ""
            text_area = self.query_one("#about-me-text", TextArea)
            text_area.load_text(about_text)
        except Exception:
            logger.debug("Failed to render profile", exc_info=True)

    # ── Accounts Tab ──────────────────────────────────────────

    @work(exclusive=True, group="load-accounts")
    async def _load_accounts(self) -> None:
        """Fetch and display connected accounts."""
        if self._accounts_client is None:
            return
        try:
            accounts = await self._accounts_client.list_accounts()
            self._render_accounts(accounts)
            self._loaded_tabs.add("accounts")
        except Exception as e:
            logger.debug("Failed to load accounts", exc_info=True)
            self._set_content("#accounts-list", f"[red]Error: {e}[/red]")

    def _render_accounts(self, accounts: list[dict[str, Any]]) -> None:
        """Render accounts list."""
        if not accounts:
            self._set_content("#accounts-list", "[dim]No accounts connected[/dim]")
            return

        lines = []
        for acct in accounts:
            email = acct.get("email", "unknown")
            label = acct.get("short_label", "")
            desc = acct.get("description", "") or ""
            is_active = acct.get("is_active", True)
            acct_id = acct.get("id", 0)

            status_icon = "[green]●[/green]" if is_active else "[red]●[/red]"
            label_part = f" [{label}]" if label else ""
            desc_part = f"  [dim]{desc}[/dim]" if desc else ""

            lines.append(
                f"  {status_icon} [bold]{email}[/bold]{label_part}{desc_part}"
            )
            lines.append(
                f"    [dim]ID: {acct_id} | "
                f"Press 'r' to refresh accounts[/dim]"
            )
            lines.append("")

        self._set_content("#accounts-list", "\n".join(lines))

        # Add sync buttons dynamically
        try:
            scroll = self.query_one("#accounts-scroll", VerticalScroll)
            # Remove old sync buttons
            for btn in scroll.query("Button"):
                btn.remove()

            for acct in accounts:
                acct_id = acct.get("id", 0)
                email = acct.get("email", "unknown")
                btn = Button(
                    f"Sync {email}",
                    id=f"btn-sync-{acct_id}",
                    variant="default",
                    classes="account-sync-btn",
                )
                scroll.mount(btn)
        except Exception:
            logger.debug("Failed to add sync buttons", exc_info=True)

    # ── AI Models Tab ─────────────────────────────────────────

    @work(exclusive=True, group="load-ai")
    async def _load_ai_preferences(self) -> None:
        """Fetch and display AI model preferences."""
        try:
            prefs = await self.app.api_client.get("/auth/ai-preferences")
            self._render_ai_preferences(prefs)
            self._loaded_tabs.add("ai")
        except Exception as e:
            logger.debug("Failed to load AI preferences", exc_info=True)
            self._update_status(f"AI prefs error: {e}")

    def _render_ai_preferences(self, prefs: dict[str, Any]) -> None:
        """Set select widget values from preferences."""
        field_map = {
            "#ai-chat-plan": "chat_plan_model",
            "#ai-chat-execute": "chat_execute_model",
            "#ai-chat-verify": "chat_verify_model",
            "#ai-agentic": "agentic_model",
            "#ai-custom-prompt": "custom_prompt_model",
        }
        for widget_id, pref_key in field_map.items():
            try:
                select_widget = self.query_one(widget_id, Select)
                value = prefs.get(pref_key, "claude-opus-4-6")
                select_widget.value = value
            except Exception:
                pass

    # ── Preferences Tab ───────────────────────────────────────

    @work(exclusive=True, group="load-prefs")
    async def _load_ui_preferences(self) -> None:
        """Fetch and display UI preferences."""
        try:
            prefs = await self.app.api_client.get("/auth/ui-preferences")
            self._render_ui_preferences(prefs)
            self._loaded_tabs.add("prefs")
        except Exception as e:
            logger.debug("Failed to load UI preferences", exc_info=True)
            self._update_status(f"Preferences error: {e}")

    def _render_ui_preferences(self, prefs: dict[str, Any]) -> None:
        """Set select widget values from preferences."""
        try:
            select_widget = self.query_one("#pref-thread-order", Select)
            select_widget.value = prefs.get("thread_order", "newest_first")
        except Exception:
            pass

    # ── Admin Tab ─────────────────────────────────────────────

    @work(exclusive=True, group="load-admin")
    async def _load_admin_settings(self) -> None:
        """Fetch and display admin settings."""
        if self._admin_client is None:
            return
        try:
            settings = await self._admin_client.get_settings()
            self._render_admin_settings(settings)
            self._loaded_tabs.add("admin")
        except Exception as e:
            logger.debug("Failed to load admin settings", exc_info=True)
            self._set_content("#admin-settings-list", f"[red]Error: {e}[/red]")

    def _render_admin_settings(self, settings: list[dict[str, Any]]) -> None:
        """Render admin settings list."""
        if not settings:
            self._set_content("#admin-settings-list", "[dim]No settings configured[/dim]")
            return

        lines = []
        for s in settings:
            key = s.get("key", "?")
            value = s.get("value", "")
            is_secret = s.get("is_secret", False)
            desc = s.get("description", "") or ""

            secret_tag = " [yellow](secret)[/yellow]" if is_secret else ""
            desc_part = f"  [dim]{desc}[/dim]" if desc else ""

            lines.append(f"  [bold]{key}[/bold]{secret_tag}: {value}{desc_part}")

        self._set_content("#admin-settings-list", "\n".join(lines))

    # ── Button Handlers ───────────────────────────────────────

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses across all tabs."""
        button_id = event.button.id or ""

        if button_id == "btn-save-about":
            self._save_about_me()
        elif button_id == "btn-save-ai":
            self._save_ai_preferences()
        elif button_id == "btn-save-prefs":
            self._save_ui_preferences()
        elif button_id == "btn-save-setting":
            self._save_admin_setting()
        elif button_id == "btn-delete-setting":
            self._delete_admin_setting()
        elif button_id == "btn-delete-analyses":
            self._delete_ai_analyses()
        elif button_id == "btn-rebuild-index":
            self._rebuild_search_index()
        elif button_id.startswith("btn-sync-"):
            try:
                acct_id = int(button_id.replace("btn-sync-", ""))
                self._trigger_sync(acct_id)
            except ValueError:
                pass

    @work(exclusive=True, group="save-about")
    async def _save_about_me(self) -> None:
        """Save the about me text."""
        try:
            text_area = self.query_one("#about-me-text", TextArea)
            text = text_area.text
            await self.app.api_client.put(
                "/auth/about-me", json_data={"about_me": text}
            )
            self.notify("About Me saved", severity="information")
            self._update_status("About Me saved")
        except Exception as e:
            self.notify(f"Save failed: {e}", severity="error")

    @work(exclusive=True, group="save-ai")
    async def _save_ai_preferences(self) -> None:
        """Save AI model preferences."""
        try:
            payload = {}
            field_map = {
                "#ai-chat-plan": "chat_plan_model",
                "#ai-chat-execute": "chat_execute_model",
                "#ai-chat-verify": "chat_verify_model",
                "#ai-agentic": "agentic_model",
                "#ai-custom-prompt": "custom_prompt_model",
            }
            for widget_id, pref_key in field_map.items():
                try:
                    select_widget = self.query_one(widget_id, Select)
                    if select_widget.value is not Select.BLANK:
                        payload[pref_key] = select_widget.value
                except Exception:
                    pass

            await self.app.api_client.put(
                "/auth/ai-preferences", json_data=payload
            )
            self.notify("AI preferences saved", severity="information")
            self._update_status("AI preferences saved")
        except Exception as e:
            self.notify(f"Save failed: {e}", severity="error")

    @work(exclusive=True, group="save-prefs")
    async def _save_ui_preferences(self) -> None:
        """Save UI preferences."""
        try:
            select_widget = self.query_one("#pref-thread-order", Select)
            value = select_widget.value
            if value is Select.BLANK:
                value = "newest_first"
            await self.app.api_client.put(
                "/auth/ui-preferences", json_data={"thread_order": value}
            )
            self.notify("Preferences saved", severity="information")
            self._update_status("Preferences saved")
        except Exception as e:
            self.notify(f"Save failed: {e}", severity="error")

    @work(exclusive=True, group="save-setting")
    async def _save_admin_setting(self) -> None:
        """Save an admin setting."""
        if self._admin_client is None:
            return
        try:
            key = self.query_one("#admin-setting-key", Input).value.strip()
            value = self.query_one("#admin-setting-value", Input).value.strip()
            desc = self.query_one("#admin-setting-desc", Input).value.strip()

            if not key:
                self.notify("Key is required", severity="warning")
                return

            await self._admin_client.update_setting(
                key=key,
                value=value,
                is_secret=False,
                description=desc or None,
            )
            self.notify(f"Setting '{key}' saved", severity="information")
            # Reload settings list
            self._loaded_tabs.discard("admin")
            self._load_admin_settings()
        except Exception as e:
            self.notify(f"Save failed: {e}", severity="error")

    @work(exclusive=True, group="delete-setting")
    async def _delete_admin_setting(self) -> None:
        """Delete an admin setting."""
        if self._admin_client is None:
            return
        try:
            key = self.query_one("#admin-setting-key", Input).value.strip()
            if not key:
                self.notify("Key is required", severity="warning")
                return

            await self._admin_client.delete_setting(key)
            self.notify(f"Setting '{key}' deleted", severity="information")
            # Clear inputs
            self._clear_admin_inputs()
            # Reload settings list
            self._loaded_tabs.discard("admin")
            self._load_admin_settings()
        except Exception as e:
            self.notify(f"Delete failed: {e}", severity="error")

    def _clear_admin_inputs(self) -> None:
        """Clear admin setting input fields."""
        try:
            self.query_one("#admin-setting-key", Input).value = ""
            self.query_one("#admin-setting-value", Input).value = ""
            self.query_one("#admin-setting-desc", Input).value = ""
        except Exception:
            pass

    @work(exclusive=True, group="sync-account")
    async def _trigger_sync(self, account_id: int) -> None:
        """Trigger sync for a specific account."""
        if self._accounts_client is None:
            return
        try:
            result = await self._accounts_client.trigger_sync(account_id)
            msg = result.get("message", "Sync started")
            self.notify(msg, severity="information")
            self._update_status(msg)
        except Exception as e:
            self.notify(f"Sync failed: {e}", severity="error")

    @work(exclusive=True, group="delete-analyses")
    async def _delete_ai_analyses(self) -> None:
        """Delete all AI analyses (admin action)."""
        try:
            # The backend may not have this endpoint yet; handle gracefully
            result = await self.app.api_client.delete("/admin/ai-analyses")
            msg = result.get("message", "AI analyses deleted") if result else "Done"
            self.notify(msg, severity="information")
        except Exception as e:
            self.notify(f"Failed: {e}", severity="error")

    @work(exclusive=True, group="rebuild-index")
    async def _rebuild_search_index(self) -> None:
        """Rebuild search index (admin action)."""
        try:
            # The backend may not have this endpoint yet; handle gracefully
            result = await self.app.api_client.post("/admin/rebuild-index")
            msg = result.get("message", "Search index rebuild started") if result else "Done"
            self.notify(msg, severity="information")
        except Exception as e:
            self.notify(f"Failed: {e}", severity="error")

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
            self.query_one("#settings-status", Static).update(text)
        except Exception:
            pass

    # ── Actions ──────────────────────────────────────────────

    def action_refresh_settings(self) -> None:
        """Refresh data for the current tab."""
        # Determine active tab from TabbedContent
        try:
            tabs = self.query_one("#settings-tabs", TabbedContent)
            active_pane = tabs.active_pane
            if active_pane:
                tab_name = (active_pane.id or "").replace("tab-", "")
                self._loaded_tabs.discard(tab_name)
                self._dispatch_tab_load(tab_name)
        except Exception:
            pass
