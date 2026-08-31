#!/usr/bin/env python3
"""Generated-only browser acceptance for touch-first Inbox triage.

Run this after the frozen frontend has been built. The script starts its own
loopback-only fixture, blocks every non-loopback request, uses exactly two
``.example.test`` accounts, and writes screenshots only to an OS temporary
directory. It never opens a real message and never gives the fixture a
provider, Gmail, send, calendar, AI, worker, terminal, or outbound-network
capability.

Frozen integration hooks exercised by this acceptance harness:

* row wrapper: ``[data-triage-row-id]``
* gesture state: ``data-swipe-state=idle|tracking|armed``
* resolved gesture: ``data-swipe-action``
* settings trigger: ``[data-shortcut="inbox.swipeSettings"]`` (the command
  palette is the desktop-accessible route to the same registered action)
* selected row: ``aria-selected=true``
* bulk surface: ``[data-triage-bulk-bar]``
* narrow-screen fallback: ``Actions for <generated subject>``

The fixture self-test proves its API semantics independently. This browser
journey proves the shipped SPA consumes that contract coherently on desktop
list/table layouts and at 390x844.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import platform
import re
import socket
import subprocess
import tempfile
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from playwright.sync_api import BrowserContext, Locator, Page, expect, sync_playwright


ROOT = Path(__file__).resolve().parents[2]
SERVER = ROOT / "scripts/qa/generated_touch_triage_server.mjs"
ZERO_OPERATION_COUNTERS = (
    "provider_reads",
    "provider_calls",
    "provider_writes",
    "gmail_reads",
    "gmail_writes",
    "email_sends",
    "mail_mutations",
    "calendar_reads",
    "calendar_writes",
    "ai_calls",
    "worker_jobs",
    "terminal_reads",
    "terminal_operations",
    "external_network_calls",
    "unexpected_writes",
    "unknown_routes",
)
REJECTED_OPERATION_COUNTERS = (
    "rejected_provider_attempts",
    "rejected_gmail_attempts",
    "rejected_mail_attempts",
    "rejected_calendar_attempts",
    "rejected_ai_attempts",
    "rejected_worker_attempts",
    "rejected_terminal_attempts",
)
INTEGRATION_HOOKS = {
    "row": '[data-triage-row-id="{email_id}"]',
    "swipe_state": "data-swipe-state",
    "swipe_action": "data-swipe-action",
    "settings": '[data-shortcut="inbox.swipeSettings"]',
    "selected": '[data-triage-row-id][aria-selected="true"]',
    "bulk": "[data-triage-bulk-bar]",
    "fallback": "Actions for <generated subject>",
}


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def api(base_url: str, method: str, path: str, body=None, expected=200):
    data = None if body is None else json.dumps(body).encode("utf-8")
    request = Request(  # noqa: S310 - exact loopback generated fixture
        f"{base_url}{path}",
        method=method,
        data=data,
        headers={} if data is None else {"Content-Type": "application/json"},
    )
    try:
        with urlopen(request, timeout=4) as response:  # noqa: S310
            status = response.status
            text = response.read().decode("utf-8")
    except HTTPError as error:
        status = error.code
        text = error.read().decode("utf-8")
    assert status == expected, f"{method} {path}: expected {expected}, got {status}: {text}"
    return json.loads(text) if text else None


def wait_for_server(base_url: str, process: subprocess.Popen) -> None:
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        if process.poll() is not None:
            output = process.stdout.read() if process.stdout else ""
            raise AssertionError(f"Generated touch triage server exited early: {output}")
        try:
            api(base_url, "GET", "/api/health")
            return
        except Exception:
            time.sleep(0.03)
    raise AssertionError("Generated touch triage server did not become ready")


def reset(base_url: str, scenario="ready") -> dict:
    return api(
        base_url,
        "POST",
        "/__qa/reset",
        {"scenario": scenario, "current_user": "generated-a"},
    )


def set_scenario(base_url: str, scenario: str) -> dict:
    return api(base_url, "POST", "/__qa/scenario", {"scenario": scenario})


def emit(base_url: str, event_type="emails_updated") -> dict:
    return api(base_url, "POST", "/__qa/emit", {"type": event_type})


def audit(base_url: str) -> dict:
    return api(base_url, "GET", "/__qa/audit")


def wait_for_audit(base_url: str, predicate, message: str, timeout=4) -> dict:
    deadline = time.monotonic() + timeout
    latest = None
    while time.monotonic() < deadline:
        latest = audit(base_url)
        if predicate(latest):
            return latest
        time.sleep(0.025)
    raise AssertionError(f"{message}: {latest}")


def install_generated_storage(context: BrowserContext, view_mode="column") -> None:
    context.add_init_script(
        """
        localStorage.setItem('hideIgnored', 'false');
        localStorage.setItem('viewMode', %s);
        localStorage.setItem('pageSize', '50');
        localStorage.setItem('colorScheme', 'light');
        """ % json.dumps(view_mode)
    )


def attach_diagnostics(page: Page, browser_errors: list[str]) -> None:
    page.on("pageerror", lambda error: browser_errors.append(f"pageerror: {error}"))
    page.on(
        "console",
        lambda message: browser_errors.append(f"console: {message.text}")
        if message.type == "error"
        else None,
    )


def assert_generated_boundary(snapshot: dict) -> None:
    assert snapshot["generated_only"] is True
    assert snapshot["localhost_only"] is True
    assert snapshot["fixture_domains"] == ["example.test"]
    serialized = json.dumps(snapshot).lower()
    assert "@gmail.com" not in serialized
    for counter in ZERO_OPERATION_COUNTERS + REJECTED_OPERATION_COUNTERS:
        assert snapshot["counters"][counter] == 0, (counter, snapshot["counters"][counter])


def assert_writes(snapshot: dict, *, preferences: int, mail_actions: int, snoozes: int) -> None:
    assert snapshot["counters"]["expected_preference_writes"] == preferences
    assert snapshot["counters"]["expected_mail_action_writes"] == mail_actions
    assert snapshot["counters"]["expected_snooze_writes"] == snoozes
    assert_generated_boundary(snapshot)


def row(page: Page, email_id: int) -> Locator:
    result = page.locator(INTEGRATION_HOOKS["row"].format(email_id=email_id)).first
    expect(result).to_be_visible(timeout=10_000)
    return result


def wait_for_inbox(page: Page, email_id=101) -> None:
    expect(page.get_by_text("Generated swipe archive target", exact=True)).to_be_visible(timeout=10_000)
    row(page, email_id)


def selected_count(page: Page) -> int:
    return page.locator(INTEGRATION_HOOKS["selected"]).count()


def wait_for_selected_count(page: Page, expected_count: int) -> None:
    locator = page.locator(INTEGRATION_HOOKS["selected"])
    expect(locator).to_have_count(expected_count, timeout=5_000)


def bulk_bar(page: Page) -> Locator:
    result = page.locator(INTEGRATION_HOOKS["bulk"])
    expect(result).to_be_visible()
    return result


def select_subject(page: Page, subject: str, *, shift=False) -> None:
    page.get_by_role("button", name=f"Select {subject}", exact=True).click(
        modifiers=["Shift"] if shift else None,
    )


def open_swipe_settings(page: Page) -> Locator:
    """Open through the frozen mobile trigger or desktop command registry."""
    direct = page.locator(INTEGRATION_HOOKS["settings"])
    if direct.count() and direct.first.is_visible():
        direct.first.click()
    else:
        page.keyboard.press("Meta+k" if platform.system() == "Darwin" else "Control+k")
        commands = page.get_by_role("dialog", name="Commands")
        expect(commands).to_be_visible()
        commands.get_by_role("combobox").fill("Customize inbox swipes")
        commands.get_by_role("option", name=re.compile("Customize inbox swipes", re.I)).click()
    dialog = page.get_by_role("dialog", name="Swipe actions")
    expect(dialog).to_be_visible()
    return dialog


def dispatch_touch_swipe(
    target_row: Locator,
    *,
    delta_x: float,
    delta_y: float = 0,
    cancel=False,
    interactive=False,
) -> dict:
    """Dispatch one deterministic primary-touch pointer sequence.

    The returned state is sampled after the move but before pointerup/cancel,
    proving the stable state/action hooks independently of the resulting API
    side effect.
    """
    return target_row.evaluate(
        """
        (shell, options) => {
          const surface = options.interactive
            ? shell.querySelector('button[aria-label^="Actions for "]')
            : (shell.querySelector('[data-swipe-surface]') || shell.firstElementChild || shell);
          if (!surface) throw new Error('Generated swipe target is missing');
          const rect = surface.getBoundingClientRect();
          const startX = rect.left + Math.min(Math.max(rect.width * 0.5, 12), Math.max(12, rect.width - 12));
          const startY = rect.top + Math.min(Math.max(rect.height * 0.5, 12), Math.max(12, rect.height - 12));
          const dispatch = (type, x, y, buttons) => surface.dispatchEvent(new PointerEvent(type, {
            bubbles: true,
            cancelable: true,
            composed: true,
            pointerId: 73,
            pointerType: 'touch',
            isPrimary: true,
            button: 0,
            buttons,
            clientX: x,
            clientY: y,
          }));
          dispatch('pointerdown', startX, startY, 1);
          dispatch('pointermove', startX + options.deltaX, startY + options.deltaY, 1);
          const moved = {
            state: shell.dataset.swipeState,
            action: shell.dataset.swipeAction,
          };
          dispatch(options.cancel ? 'pointercancel' : 'pointerup', startX + options.deltaX, startY + options.deltaY, 0);
          return {
            ...moved,
            finalState: shell.dataset.swipeState,
            finalAction: shell.dataset.swipeAction,
          };
        }
        """,
        {
            "deltaX": delta_x,
            "deltaY": delta_y,
            "cancel": cancel,
            "interactive": interactive,
        },
    )


def assert_settings_and_selection(
    page: Page,
    base_url: str,
    screenshots: Path,
) -> list[dict]:
    snapshots = []
    reset(base_url)
    page.goto(f"{base_url}/?page=inbox&qa=touch-desktop", wait_until="domcontentloaded")
    wait_for_inbox(page)

    # Desktop discovers the registered action through the keyboard command
    # palette. Cancel is a strict zero-write path.
    dialog = open_swipe_settings(page)
    expect(dialog.get_by_label("Swipe left")).to_have_value("archive")
    expect(dialog.get_by_label("Swipe right")).to_have_value("snooze")
    dialog.get_by_label("Swipe left").select_option("toggle_read")
    dialog.get_by_label("Swipe right").select_option("toggle_star")
    dialog.get_by_role("button", name="Cancel", exact=True).click()
    expect(dialog).not_to_be_visible()
    snapshot = audit(base_url)
    assert_writes(snapshot, preferences=0, mail_actions=0, snoozes=0)
    snapshots.append(snapshot)

    dialog = open_swipe_settings(page)
    dialog.get_by_label("Swipe left").select_option("toggle_read")
    dialog.get_by_label("Swipe right").select_option("toggle_star")
    dialog.screenshot(path=str(screenshots / "desktop-swipe-settings.png"))
    dialog.get_by_role("button", name="Save swipe actions").click()
    expect(dialog).not_to_be_visible()
    snapshot = wait_for_audit(
        base_url,
        lambda value: value["counters"]["expected_preference_writes"] == 1,
        "saved swipe preferences were not written exactly once",
    )
    assert snapshot["preferences"]["swipe_left_action"] == "toggle_read"
    assert snapshot["preferences"]["swipe_right_action"] == "toggle_star"
    assert_writes(snapshot, preferences=1, mail_actions=0, snoozes=0)
    snapshots.append(snapshot)

    # Range selection spans the four primary rows, survives a same-dataset SSE
    # refresh and a list/table switch, then supports select-loaded and clear.
    select_subject(page, "Generated swipe archive target")
    select_subject(page, "Generated toggle star target", shift=True)
    wait_for_selected_count(page, 4)
    expect(bulk_bar(page)).to_have_attribute(
        "aria-label", "Bulk actions for 4 selected conversations"
    )
    before_reads = audit(base_url)["counters"]["conversation_reads"]
    emit(base_url)
    wait_for_audit(
        base_url,
        lambda value: value["counters"]["conversation_reads"] > before_reads,
        "same-dataset refresh did not run",
    )
    wait_for_selected_count(page, 4)
    page.get_by_role("button", name="Toggle view mode").click()
    expect(page.get_by_role("table")).to_be_visible()
    wait_for_selected_count(page, 4)
    page.screenshot(path=str(screenshots / "desktop-table-range-selection.png"), full_page=True)

    bulk_bar(page).get_by_role("button", name="Clear selection").click()
    wait_for_selected_count(page, 0)
    page.get_by_role("button", name="Select all loaded conversations").click()
    wait_for_selected_count(page, 6)
    expect(bulk_bar(page)).to_have_attribute(
        "aria-label", "Bulk actions for 6 selected conversations"
    )
    bulk_bar(page).get_by_role("button", name="Clear selection").click()
    wait_for_selected_count(page, 0)

    # Account and mailbox changes are different datasets and must clear the
    # selection without creating a mutation.
    select_subject(page, "Generated swipe archive target")
    wait_for_selected_count(page, 1)
    page.locator('button[title="Generated Touch Secondary"]:visible').click()
    expect(page.get_by_text("Generated secondary account one", exact=True)).to_be_visible()
    wait_for_selected_count(page, 0)
    select_subject(page, "Generated secondary account one")
    wait_for_selected_count(page, 1)
    page.get_by_role("button", name="Trash", exact=True).click()
    wait_for_selected_count(page, 0)
    snapshot = audit(base_url)
    assert_writes(snapshot, preferences=1, mail_actions=0, snoozes=0)
    snapshots.append(snapshot)
    return snapshots


def assert_archive_snooze_and_alternate_actions(
    page: Page,
    base_url: str,
    screenshots: Path,
) -> list[dict]:
    snapshots = []

    # The first archive response is deliberately lost. The SPA reconciles the
    # same idempotency key, observes one create, and exposes exact Undo.
    reset(base_url, "lost-action-once")
    page.goto(f"{base_url}/?page=inbox&qa=touch-archive", wait_until="domcontentloaded")
    wait_for_inbox(page)
    gesture = dispatch_touch_swipe(row(page, 101), delta_x=-118)
    assert gesture["state"] == "armed", gesture
    assert gesture["action"] == "archive", gesture
    assert gesture["finalState"] == "idle", gesture
    snapshot = wait_for_audit(
        base_url,
        lambda value: value["counters"]["mail_action_creates"] == 1,
        "archive did not commit",
    )
    expect(page.locator(INTEGRATION_HOOKS["row"].format(email_id=101))).to_have_count(0)
    assert snapshot["counters"]["lost_action_responses"] == 1
    assert snapshot["counters"]["mail_action_creates"] == 1
    assert snapshot["counters"]["mail_action_lookups"] >= 1
    assert snapshot["inbox_totals"]["all"] == 5
    page.screenshot(path=str(screenshots / "mobile-left-archive-staged.png"), full_page=True)
    page.get_by_role("button", name="Undo", exact=True).click()
    row(page, 101)
    snapshot = wait_for_audit(
        base_url,
        lambda value: value["counters"]["mail_action_undos"] == 1,
        "archive Undo did not restore the exact row",
    )
    assert snapshot["counters"]["mail_action_creates"] == 1
    assert snapshot["inbox_totals"]["all"] == 6
    assert_writes(snapshot, preferences=0, mail_actions=2, snoozes=0)
    snapshots.append(snapshot)

    # Opening and closing the snooze picker is zero-write. Only an explicit
    # generated quick time creates the snooze and its local staged archive.
    reset(base_url)
    page.reload(wait_until="domcontentloaded")
    wait_for_inbox(page)
    gesture = dispatch_touch_swipe(row(page, 102), delta_x=118)
    assert gesture["state"] == "armed", gesture
    assert gesture["action"] == "snooze", gesture
    picker = page.get_by_role("dialog", name="Snooze email")
    expect(picker).to_be_visible()
    assert_writes(audit(base_url), preferences=0, mail_actions=0, snoozes=0)
    picker.get_by_role("button", name="Close snooze picker").click()
    expect(picker).not_to_be_visible()
    assert_writes(audit(base_url), preferences=0, mail_actions=0, snoozes=0)

    dispatch_touch_swipe(row(page, 102), delta_x=118)
    expect(picker).to_be_visible()
    picker.locator("[data-first-choice]").click()
    expect(picker).not_to_be_visible()
    snapshot = wait_for_audit(
        base_url,
        lambda value: value["counters"]["snooze_creates"] == 1,
        "explicit generated snooze time did not commit",
    )
    assert snapshot["counters"]["mail_action_creates"] == 1
    assert snapshot["counters"]["snooze_archive_action_writes"] == 1
    assert snapshot["inbox_totals"]["all"] == 5
    expect(page.locator(INTEGRATION_HOOKS["row"].format(email_id=102))).to_have_count(0)
    assert_writes(snapshot, preferences=0, mail_actions=1, snoozes=1)
    page.screenshot(path=str(screenshots / "mobile-right-snooze-committed.png"), full_page=True)
    snapshots.append(snapshot)

    # Alternate preference values reuse the ordinary staged mail-action API;
    # neither action removes the row.
    reset(base_url)
    api(base_url, "PUT", "/api/auth/ui-preferences", {
        "swipe_left_action": "toggle_read",
        "swipe_right_action": "toggle_star",
    })
    page.reload(wait_until="domcontentloaded")
    wait_for_inbox(page)
    left = dispatch_touch_swipe(row(page, 103), delta_x=-118)
    right = dispatch_touch_swipe(row(page, 104), delta_x=118)
    assert (left["state"], left["action"]) == ("armed", "toggle_read"), left
    assert (right["state"], right["action"]) == ("armed", "toggle_star"), right
    snapshot = wait_for_audit(
        base_url,
        lambda value: value["counters"]["mail_action_creates"] == 2,
        "alternate swipe actions did not commit",
    )
    assert [operation["action"] for operation in snapshot["operations"]] == ["mark_read", "star"]
    row(page, 103)
    row(page, 104)
    assert_writes(snapshot, preferences=1, mail_actions=2, snoozes=0)
    snapshots.append(snapshot)
    return snapshots


def assert_zero_write_gestures_and_dataset_guards(
    page: Page,
    base_url: str,
    screenshots: Path,
) -> list[dict]:
    snapshots = []
    reset(base_url)
    page.reload(wait_until="domcontentloaded")
    wait_for_inbox(page)

    short = dispatch_touch_swipe(row(page, 101), delta_x=-30)
    vertical = dispatch_touch_swipe(row(page, 102), delta_x=18, delta_y=112)
    cancelled = dispatch_touch_swipe(row(page, 103), delta_x=-118, cancel=True)
    interactive = dispatch_touch_swipe(row(page, 104), delta_x=118, interactive=True)
    assert short["state"] != "armed", short
    assert vertical["state"] != "armed", vertical
    assert cancelled["state"] == "armed", cancelled
    assert interactive["state"] == "idle", interactive
    for gesture in (short, vertical, cancelled, interactive):
        assert gesture["finalState"] == "idle", gesture
    snapshot = audit(base_url)
    assert_writes(snapshot, preferences=0, mail_actions=0, snoozes=0)
    snapshots.append(snapshot)
    page.screenshot(path=str(screenshots / "mobile-safe-gesture-boundaries.png"), full_page=True)

    # Trash is a protected dataset. It may render a generated row, but the
    # swipe controller must remain disabled and perform no local write.
    page.get_by_role("button", name="Toggle sidebar").click()
    page.get_by_role("button", name="Trash", exact=True).click()
    protected = row(page, 301)
    gesture = dispatch_touch_swipe(protected, delta_x=-118)
    assert gesture["state"] == "idle", gesture
    snapshot = audit(base_url)
    assert_writes(snapshot, preferences=0, mail_actions=0, snoozes=0)
    snapshots.append(snapshot)

    # Hold a merged-Inbox refresh, change account while it is in flight, and
    # prove the stale merged response cannot overwrite account-two rows or keep
    # a selection. This is client dataset invalidation, so the server session
    # generation intentionally remains unchanged.
    reset(base_url)
    page.goto(f"{base_url}/?page=inbox&qa=touch-stale-dataset", wait_until="domcontentloaded")
    wait_for_inbox(page)
    select_subject(page, "Generated swipe archive target")
    wait_for_selected_count(page, 1)
    set_scenario(base_url, "slow-dataset")
    emit(base_url)
    wait_for_audit(
        base_url,
        lambda value: value["counters"]["dataset_delays"] == 1,
        "slow merged-Inbox response did not begin",
    )
    page.get_by_role("button", name="Toggle sidebar").click()
    page.locator('button[title="Generated Touch Secondary"]:visible').click()
    expect(page.get_by_text("Generated secondary account one", exact=True)).to_be_visible()
    wait_for_selected_count(page, 0)
    page.wait_for_timeout(650)
    expect(page.get_by_text("Generated secondary account one", exact=True)).to_be_visible()
    expect(page.get_by_text("Generated swipe archive target", exact=True)).to_have_count(0)
    snapshot = audit(base_url)
    assert snapshot["counters"]["dataset_delays"] == 1
    assert_writes(snapshot, preferences=0, mail_actions=0, snoozes=0)
    snapshots.append(snapshot)

    # Hold one final refresh and perform a real app logout. The stale response
    # crosses the server session generation, the old selection disappears, and
    # no delayed result can reopen authenticated mail state.
    reset(base_url)
    page.goto(f"{base_url}/?page=inbox&qa=touch-stale-session", wait_until="domcontentloaded")
    wait_for_inbox(page)
    select_subject(page, "Generated swipe archive target")
    expect(bulk_bar(page)).to_be_visible()
    set_scenario(base_url, "slow-dataset")
    emit(base_url)
    wait_for_audit(
        base_url,
        lambda value: value["counters"]["dataset_delays"] == 1,
        "slow pre-logout response did not begin",
    )
    page.get_by_role("button", name=re.compile("More app sections")).click()
    page.get_by_role("button", name="Log out", exact=True).click()
    expect(page.get_by_text("Sign in to your account")).to_be_visible(timeout=10_000)
    page.wait_for_timeout(650)
    expect(page.locator(INTEGRATION_HOOKS["bulk"])).to_have_count(0)
    expect(page.locator("[data-triage-row-id]")).to_have_count(0)
    snapshot = audit(base_url)
    assert snapshot["counters"]["session_changes"] == 1
    assert snapshot["counters"]["stale_dataset_responses"] == 1
    assert_writes(snapshot, preferences=0, mail_actions=0, snoozes=0)
    snapshots.append(snapshot)
    return snapshots


def main() -> None:
    if not (ROOT / "frontend/dist/index.html").is_file():
        raise SystemExit("frontend/dist is missing; run `npm --prefix frontend run build` first")

    port = free_port()
    base_url = f"http://127.0.0.1:{port}"
    screenshots = Path(tempfile.mkdtemp(prefix="generated-touch-triage-qa-"))
    process = subprocess.Popen(
        ["node", str(SERVER)],
        cwd=ROOT,
        env={**os.environ, "QA_TOUCH_TRIAGE_PORT": str(port)},
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    blocked_external: list[str] = []
    browser_errors: list[str] = []
    snapshots: list[dict] = []

    def route_generated_only(route) -> None:
        request_url = route.request.url
        if request_url.startswith(base_url) or request_url.startswith(("data:", "blob:")):
            route.continue_()
            return
        blocked_external.append(request_url)
        route.abort()

    try:
        wait_for_server(base_url, process)
        with sync_playwright() as playwright:
            chrome_path = os.environ.get(
                "QA_CHROME_PATH",
                "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            )
            launch_options = {"headless": True}
            if Path(chrome_path).is_file():
                launch_options["executable_path"] = chrome_path
            browser = playwright.chromium.launch(**launch_options)

            desktop = browser.new_context(
                viewport={"width": 1440, "height": 900},
                timezone_id="America/New_York",
            )
            install_generated_storage(desktop, "column")
            desktop.route("**/*", route_generated_only)
            desktop_page = desktop.new_page()
            attach_diagnostics(desktop_page, browser_errors)
            snapshots.extend(assert_settings_and_selection(desktop_page, base_url, screenshots))
            desktop.close()

            mobile = browser.new_context(
                viewport={"width": 390, "height": 844},
                has_touch=True,
                is_mobile=True,
                timezone_id="America/New_York",
            )
            install_generated_storage(mobile, "column")
            mobile.route("**/*", route_generated_only)
            mobile_page = mobile.new_page()
            attach_diagnostics(mobile_page, browser_errors)
            snapshots.extend(
                assert_archive_snooze_and_alternate_actions(
                    mobile_page, base_url, screenshots
                )
            )
            snapshots.extend(
                assert_zero_write_gestures_and_dataset_guards(
                    mobile_page, base_url, screenshots
                )
            )
            mobile.close()
            browser.close()

        assert not blocked_external, f"external browser requests were blocked: {blocked_external}"
        assert not browser_errors, f"browser errors: {browser_errors}"
        for snapshot in snapshots:
            assert_generated_boundary(snapshot)
        screenshot_files = sorted(path for path in screenshots.iterdir() if path.is_file())
        assert len(screenshot_files) >= 5
        assert all(path.stat().st_size > 0 for path in screenshot_files)
        print(json.dumps({
            "generated_only": True,
            "two_account_example_test_fixture": True,
            "desktop_list_and_table": True,
            "mobile_390x844": True,
            "preferences_defaults_update_cancel": True,
            "left_archive_exactly_once_and_undo": True,
            "right_snooze_explicit_time_only": True,
            "toggle_read_and_toggle_star": True,
            "short_vertical_cancel_interactive_zero_writes": True,
            "protected_mailbox_zero_writes": True,
            "selection_refresh_list_table_range_loaded_clear": True,
            "account_mailbox_session_selection_clear": True,
            "stale_dataset_and_session_guarded": True,
            "blocked_external_requests": len(blocked_external),
            "zero_provider_gmail_send_calendar_ai_worker_terminal_operations": True,
            "screenshots": [str(path) for path in screenshot_files],
            "integration_hooks": INTEGRATION_HOOKS,
        }, indent=2))
    finally:
        process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()


if __name__ == "__main__":
    main()
