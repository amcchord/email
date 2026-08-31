#!/usr/bin/env python3
"""Generated-only browser acceptance for Share Availability.

Run after ``npm --prefix frontend run build`` with the workspace Playwright
environment. The script starts its loopback fixture, blocks every non-local
request, and writes only generated-data screenshots to a temporary directory
outside the repository.
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

from playwright.sync_api import Browser, BrowserContext, Locator, Page, expect, sync_playwright


ROOT = Path(__file__).resolve().parents[2]
VIEWPORT_DESKTOP = {"width": 1280, "height": 800}
VIEWPORT_MOBILE = {"width": 390, "height": 844}
SOURCE_SUBJECT = "Generated request for meeting times"
INSERTION_INTRO = "Here are a few times that work for me"
SAFETY_COUNTERS = (
    "provider_reads",
    "provider_calls",
    "provider_writes",
    "email_sends",
    "mail_mutations",
    "calendar_writes",
    "event_creations",
    "event_holds",
    "unexpected_writes",
    "unknown_routes",
    "external_network_calls",
)
SELECTOR_ASSUMPTIONS = {
    "trigger": 'role=button[name="Share availability"]',
    "dialog": 'role=dialog[name="Share availability"]',
    "accounts_group": 'role=group[name="Calendars to check"]',
    "date_range": 'label="Date range"',
    "meeting_length": 'label="Meeting length"',
    "workday_start": 'label="Workday starts"',
    "workday_end": 'label="Workday ends"',
    "include_weekends": 'label="Include weekends"',
    "time_zone": 'label="Time zone"',
    "check": 'role=button[name="Check availability"]',
    "available_times": 'role=region[name="Available times"]',
    "insert": 'role=button[name="Insert selected times"]',
    "compose_editor": 'role=combobox[name="Message body"]',
    "reader_editor": 'role=combobox[name="Reply message"]',
    "flow_editor": 'role=combobox[name="Reply body"]',
}


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def api(base_url: str, method: str, path: str, body=None, expected=200):
    data = None if body is None else json.dumps(body).encode("utf-8")
    request = Request(
        f"{base_url}{path}",
        data=data,
        method=method,
        headers={} if data is None else {"Content-Type": "application/json"},
    )
    try:
        with urlopen(request, timeout=4) as response:  # noqa: S310 - loopback fixture
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
            raise AssertionError(f"Generated server exited early: {output}")
        try:
            api(base_url, "GET", "/api/build-version")
            return
        except Exception:
            time.sleep(0.03)
    raise AssertionError("Generated Share Availability server did not become ready")


def reset(base_url: str, scenario="ready", current_user="generated-a"):
    return api(
        base_url,
        "POST",
        "/__qa/reset",
        {"scenario": scenario, "current_user": current_user},
    )


def audit(base_url: str):
    return api(base_url, "GET", "/__qa/audit")


def wait_for_audit(base_url: str, predicate, message: str, timeout=4.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = audit(base_url)
        if predicate(value):
            return value
        time.sleep(0.03)
    raise AssertionError(message)


def assert_safe_audit(value, *, allow_unknown=False) -> None:
    assert value["localhost_only"] is True
    assert value["fixture_domains"] == ["example.test"]
    for counter in SAFETY_COUNTERS:
        if allow_unknown and counter == "unknown_routes":
            continue
        assert value["counters"][counter] == 0, f"{counter}: {value}"


def make_context(
    browser: Browser,
    base_url: str,
    blocked_external: list[str],
    viewport: dict[str, int],
) -> BrowserContext:
    context = browser.new_context(viewport=viewport, locale="en-US", timezone_id="America/New_York")
    context.clock.install(time="2026-08-31T17:00:00.000Z")
    context.route(
        "**/*",
        lambda route: route.continue_()
        if route.request.url.startswith(base_url)
        else (blocked_external.append(route.request.url), route.abort())[1],
    )
    return context


def set_contenteditable_caret(editor: Locator, offset: int) -> None:
    editor.evaluate(
        """(element, requestedOffset) => {
          const walker = document.createTreeWalker(element, NodeFilter.SHOW_TEXT);
          let remaining = requestedOffset;
          let node = walker.nextNode();
          while (node && remaining > node.textContent.length) {
            remaining -= node.textContent.length;
            node = walker.nextNode();
          }
          if (!node) throw new Error('Generated QA caret is outside the editor text');
          const selection = window.getSelection();
          const range = document.createRange();
          range.setStart(node, Math.min(remaining, node.textContent.length));
          range.collapse(true);
          selection.removeAllRanges();
          selection.addRange(range);
          element.focus();
        }""",
        offset,
    )


def assert_inserted_at_caret(value: str, before: str, after: str) -> None:
    before_index = value.find(before)
    snapshot_index = value.find(INSERTION_INTRO)
    after_index = value.find(after)
    assert before_index >= 0, value
    assert snapshot_index > before_index, value
    assert after_index > snapshot_index, value
    assert "America/New_York" in value, value
    assert "30 minutes" in value, value
    assert "Tuesday, September 1, 2026" in value, value
    assert "owner@example.test" not in value, value
    assert "projects@example.test" not in value, value
    assert "Last synced" not in value, value


def picker(page: Page) -> Locator:
    value = page.get_by_role("dialog", name="Share availability")
    expect(value).to_be_visible()
    return value


def open_picker(page: Page) -> Locator:
    trigger = page.get_by_role("button", name="Share availability", exact=True)
    expect(trigger).to_be_visible()
    expect(trigger).to_be_enabled()
    trigger.click()
    value = picker(page)
    expect(value.get_by_role("group", name="Calendars to check")).to_be_visible()
    expect(value.get_by_label("Date range")).to_be_visible()
    expect(value.get_by_label("Meeting length")).to_be_visible()
    expect(value.get_by_label("Workday starts")).to_be_visible()
    expect(value.get_by_label("Workday ends")).to_be_visible()
    expect(value.get_by_label("Include weekends")).to_be_visible()
    expect(value.get_by_label("Time zone")).to_be_visible()
    return value


def close_picker_with_escape(page: Page, *, assert_focus=True) -> None:
    dialog = picker(page)
    page.keyboard.press("Escape")
    expect(dialog).not_to_be_visible()
    if assert_focus:
        expect(page.get_by_role("button", name="Share availability", exact=True)).to_be_focused()


def check_ready(dialog: Locator) -> Locator:
    dialog.get_by_role("button", name="Check availability", exact=True).click()
    available = dialog.get_by_role("region", name="Available times")
    expect(available).to_contain_text("Snapshot ready", timeout=10_000)
    expect(available.get_by_text("owner@example.test", exact=True)).to_be_visible()
    expect(available.get_by_text("Ready", exact=True).first).to_be_visible()
    expect(available.locator("fieldset input[type=checkbox]").first).to_be_visible()
    return available


def select_first_slot_and_insert(dialog: Locator) -> None:
    available = dialog.get_by_role("region", name="Available times")
    slots = available.locator("fieldset input[type=checkbox]")
    expect(slots.first).to_be_visible()
    slots.first.check()
    expect(dialog.get_by_text("1 time selected", exact=True)).to_be_visible()
    insert = dialog.get_by_role("button", name="Insert selected times", exact=True)
    expect(insert).to_be_enabled()
    insert.click()
    expect(dialog).not_to_be_visible()


def wait_for_compose(page: Page, base_url: str) -> Locator:
    page.goto(f"{base_url}/?page=compose", wait_until="domcontentloaded")
    editor = page.get_by_role("combobox", name="Message body")
    expect(editor).to_be_visible(timeout=12_000)
    expect(page.get_by_role("button", name="Share availability", exact=True)).to_be_enabled()
    return editor


def assert_compose_journey(page: Page, base_url: str, screenshot: Path) -> dict:
    reset(base_url)
    editor = wait_for_compose(page, base_url)
    original = "Compose before. Compose after."
    editor.fill(original)
    set_contenteditable_caret(editor, len("Compose before."))

    dialog = open_picker(page)
    accounts = dialog.get_by_role("group", name="Calendars to check")
    primary = accounts.get_by_role("checkbox", name=re.compile(r"Primary.*owner@example\.test"))
    projects = accounts.get_by_role("checkbox", name=re.compile(r"Projects.*projects@example\.test"))
    expect(primary).to_be_checked()
    expect(primary).to_be_disabled()
    expect(projects).to_be_checked()

    # Account choice invalidates the result, and checking one account sends the
    # exact requested scope without changing the editor.
    projects.uncheck()
    available = check_ready(dialog)
    expect(available.get_by_text("projects@example.test", exact=True)).to_have_count(0)
    assert editor.inner_text() == original
    latest = audit(base_url)["requests"][-1]
    assert latest["action"] == "calendar.availability"
    assert latest["account_ids"] == [1]

    projects.check()
    expect(available.get_by_text("owner@example.test", exact=True)).to_have_count(0)
    available = check_ready(dialog)
    expect(available.get_by_text("projects@example.test", exact=True)).to_be_visible()
    latest = audit(base_url)["requests"][-1]
    assert latest["account_ids"] == [1, 2]
    slots = available.locator("fieldset input[type=checkbox]")
    expect(slots).to_have_count(3)
    slots.nth(0).check()
    slots.nth(2).check()
    expect(dialog.get_by_text("2 times selected", exact=True)).to_be_visible()
    assert editor.inner_text() == original

    dialog.screenshot(path=str(screenshot))
    dialog.get_by_role("button", name="Insert selected times", exact=True).click()
    expect(dialog).not_to_be_visible()
    expect(page.get_by_text("Availability snapshot inserted", exact=True)).to_be_visible()
    value = editor.inner_text()
    assert_inserted_at_caret(value, "Compose before.", "Compose after.")
    assert value.count(INSERTION_INTRO) == 1
    page.get_by_role("button", name="Save Draft", exact=True).click()

    # Escape closes without inserting a second snapshot and restores trigger
    # focus. The platform shortcut opens the same dialog.
    dialog = open_picker(page)
    close_picker_with_escape(page)
    assert editor.inner_text().count(INSERTION_INTRO) == 1
    editor.focus()
    page.keyboard.press("Meta+Shift+a" if platform.system() == "Darwin" else "Control+Shift+a")
    expect(page.get_by_role("dialog", name="Share availability")).to_be_visible()
    page.get_by_role("dialog", name="Share availability").get_by_role("button", name="Cancel").click()

    value_audit = wait_for_audit(
        base_url,
        lambda value: value["counters"]["allowed_draft_writes"] >= 1,
        "Compose draft did not persist generated inserted content",
    )
    assert value_audit["counters"]["availability_requests"] == 2
    assert value_audit["counters"]["allowed_draft_writes"] >= 1
    assert_safe_audit(value_audit)
    return value_audit


def assert_reader_journey(page: Page, base_url: str) -> dict:
    reset(base_url)
    page.goto(f"{base_url}/?view=email&id=101", wait_until="domcontentloaded")
    reply = page.get_by_role("button", name="Reply", exact=True)
    expect(reply).to_be_visible(timeout=12_000)
    reply.click()
    editor = page.get_by_role("combobox", name="Reply message")
    expect(editor).to_be_visible(timeout=12_000)
    original = "Reader before. Reader after."
    editor.fill(original)
    editor.evaluate("(element, offset) => element.setSelectionRange(offset, offset)", len("Reader before."))
    dialog = open_picker(page)
    assert editor.input_value() == original
    check_ready(dialog)
    assert editor.input_value() == original
    select_first_slot_and_insert(dialog)
    value = editor.input_value()
    assert_inserted_at_caret(value, "Reader before.", "Reader after.")
    assert value.count(INSERTION_INTRO) == 1
    page.get_by_role("button", name="Close and keep reply", exact=True).click()
    expect(editor).not_to_be_visible()
    value_audit = wait_for_audit(
        base_url,
        lambda value: value["counters"]["allowed_draft_writes"] >= 1,
        "Reader reply draft did not persist generated inserted content",
    )
    assert value_audit["counters"]["availability_requests"] == 1
    assert value_audit["counters"]["allowed_draft_writes"] >= 1
    assert_safe_audit(value_audit)
    return value_audit


def assert_flow_journey(page: Page, base_url: str) -> dict:
    reset(base_url)
    page.goto(f"{base_url}/?page=flow", wait_until="domcontentloaded")
    open_reply = page.get_by_role(
        "button",
        name=f"Open {SOURCE_SUBJECT} from Generated Scheduling Requester",
    )
    expect(open_reply).to_be_visible(timeout=12_000)
    open_reply.click()
    editor = page.get_by_role("combobox", name="Reply body")
    expect(editor).to_be_visible(timeout=12_000)
    original = "Flow before. Flow after."
    editor.fill(original)
    set_contenteditable_caret(editor, len("Flow before."))
    dialog = open_picker(page)
    check_ready(dialog)
    assert editor.inner_text() == original
    select_first_slot_and_insert(dialog)
    value = editor.inner_text()
    assert_inserted_at_caret(value, "Flow before.", "Flow after.")
    assert value.count(INSERTION_INTRO) == 1
    page.get_by_role("button", name="Back to Flow", exact=True).click()
    expect(editor).not_to_be_visible()
    value_audit = wait_for_audit(
        base_url,
        lambda value: value["counters"]["allowed_draft_writes"] >= 1,
        "Flow reply draft did not persist generated inserted content",
    )
    assert value_audit["counters"]["availability_requests"] == 1
    assert value_audit["counters"]["allowed_draft_writes"] >= 1
    assert_safe_audit(value_audit)
    return value_audit


def assert_fail_closed_scenarios(page: Page, base_url: str) -> list[dict]:
    captured = []
    cases = (
        ("stale", "saved calendar snapshot is stale"),
        ("reauthorization-required", "Calendar access must be reconnected"),
        ("no-full", "first calendar sync is incomplete"),
    )
    for scenario, expected_text in cases:
        reset(base_url, scenario)
        editor = wait_for_compose(page, base_url)
        editor.fill(f"{scenario} must remain unchanged")
        dialog = open_picker(page)
        dialog.get_by_role("button", name="Check availability", exact=True).click()
        expect(dialog.get_by_text(re.compile(expected_text, re.IGNORECASE))).to_be_visible()
        expect(dialog.get_by_text("Calendar coverage is incomplete", exact=False)).to_be_visible()
        expect(dialog.get_by_role("button", name="Insert selected times", exact=True)).to_be_disabled()
        assert editor.inner_text() == f"{scenario} must remain unchanged"
        close_picker_with_escape(page, assert_focus=False)
        value_audit = audit(base_url)
        assert value_audit["counters"]["incomplete_coverage_responses"] == 1
        assert_safe_audit(value_audit)
        captured.append(value_audit)

    reset(base_url, "fail-once")
    editor = wait_for_compose(page, base_url)
    editor.fill("Fail once remains unchanged")
    dialog = open_picker(page)
    dialog.get_by_role("button", name="Check availability", exact=True).click()
    alert = dialog.get_by_role("alert")
    expect(alert).to_be_visible()
    expect(alert).to_contain_text("temporarily unavailable")
    assert editor.inner_text() == "Fail once remains unchanged"
    alert.get_by_role("button", name="Retry", exact=True).click()
    expect(dialog.get_by_role("region", name="Available times").locator("fieldset input[type=checkbox]").first).to_be_visible()
    close_picker_with_escape(page, assert_focus=False)
    value_audit = audit(base_url)
    assert value_audit["counters"]["availability_requests"] == 2
    assert value_audit["counters"]["transient_failures"] == 1
    assert_safe_audit(value_audit)
    captured.append(value_audit)
    return captured


def assert_slow_session(page: Page, base_url: str) -> dict:
    reset(base_url)
    wait_for_compose(page, base_url)
    reset(base_url, "slow-session")
    dialog = open_picker(page)
    dialog.get_by_role("button", name="Check availability", exact=True).click()
    expect(dialog.get_by_text("Checking saved calendars…", exact=True)).to_be_visible()
    api(base_url, "POST", "/__qa/session", {"current_user": "generated-b"})
    page.reload(wait_until="domcontentloaded")
    expect(page.get_by_role("combobox", name="Message body")).to_be_visible(timeout=12_000)
    expect(page.get_by_role("button", name="Share availability", exact=True)).to_be_enabled()
    user_b_dialog = open_picker(page)
    expect(user_b_dialog.get_by_text("availability-user-b@example.test", exact=True)).to_be_visible()
    expect(user_b_dialog.get_by_text("owner@example.test", exact=True)).to_have_count(0)
    expect(user_b_dialog.get_by_text("projects@example.test", exact=True)).to_have_count(0)
    page.wait_for_timeout(750)
    expect(user_b_dialog.get_by_role("region", name="Available times").locator("fieldset")).to_have_count(0)
    user_b_dialog.get_by_role("button", name="Cancel", exact=True).click()
    value_audit = audit(base_url)
    assert value_audit["counters"]["slow_availability_requests"] == 1
    assert value_audit["counters"]["stale_session_responses"] == 1
    assert value_audit["counters"]["availability_successes"] == 1
    assert_safe_audit(value_audit)
    return value_audit


def assert_mobile(page: Page, base_url: str, screenshot: Path) -> dict:
    reset(base_url)
    editor = wait_for_compose(page, base_url)
    original = "Mobile before. Mobile after."
    editor.fill(original)
    set_contenteditable_caret(editor, len("Mobile before."))
    dialog = open_picker(page)
    expect(dialog.get_by_label("Date range")).to_have_value("7")
    expect(dialog.get_by_label("Meeting length")).to_have_value("30")
    available = check_ready(dialog)
    available.locator("fieldset input[type=checkbox]").first.check()
    bounds = dialog.bounding_box()
    assert bounds is not None
    assert bounds["x"] >= -0.5 and bounds["y"] >= -0.5, bounds
    assert bounds["x"] + bounds["width"] <= 390.5, bounds
    assert bounds["y"] + bounds["height"] <= 844.5, bounds
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    dialog.screenshot(path=str(screenshot))
    dialog.get_by_role("button", name="Insert selected times", exact=True).click()
    expect(dialog).not_to_be_visible()
    value = editor.inner_text()
    assert_inserted_at_caret(value, "Mobile before.", "Mobile after.")
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    value_audit = audit(base_url)
    assert value_audit["counters"]["availability_requests"] == 1
    assert_safe_audit(value_audit)
    return value_audit


def main() -> None:
    dist = ROOT / "frontend" / "dist" / "index.html"
    if not dist.exists():
        raise SystemExit("frontend/dist is missing; run `npm --prefix frontend run build` first")

    screenshot_dir = Path(tempfile.mkdtemp(prefix="generated-share-availability-qa-"))
    desktop_screenshot = screenshot_dir / "desktop-compose-picker.png"
    mobile_screenshot = screenshot_dir / "mobile-390x844-picker.png"
    port = free_port()
    base_url = f"http://127.0.0.1:{port}"
    process = subprocess.Popen(
        ["node", "scripts/qa/generated_share_availability_server.mjs", str(port)],
        cwd=ROOT,
        env={**os.environ, "QA_PORT": str(port)},
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    blocked_external: list[str] = []
    audits = []
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

            desktop = make_context(browser, base_url, blocked_external, VIEWPORT_DESKTOP)
            audits.append(assert_compose_journey(desktop.new_page(), base_url, desktop_screenshot))
            desktop.close()

            reader = make_context(browser, base_url, blocked_external, VIEWPORT_DESKTOP)
            audits.append(assert_reader_journey(reader.new_page(), base_url))
            reader.close()

            flow = make_context(browser, base_url, blocked_external, VIEWPORT_DESKTOP)
            audits.append(assert_flow_journey(flow.new_page(), base_url))
            flow.close()

            scenarios = make_context(browser, base_url, blocked_external, VIEWPORT_DESKTOP)
            scenario_page = scenarios.new_page()
            audits.extend(assert_fail_closed_scenarios(scenario_page, base_url))
            scenarios.close()

            slow = make_context(browser, base_url, blocked_external, VIEWPORT_DESKTOP)
            audits.append(assert_slow_session(slow.new_page(), base_url))
            slow.close()

            mobile = make_context(browser, base_url, blocked_external, VIEWPORT_MOBILE)
            audits.append(assert_mobile(mobile.new_page(), base_url, mobile_screenshot))
            mobile.close()
            browser.close()

        assert not blocked_external, f"external browser requests: {blocked_external}"
        assert desktop_screenshot.is_file() and desktop_screenshot.stat().st_size > 0
        assert mobile_screenshot.is_file() and mobile_screenshot.stat().st_size > 0
        for value_audit in audits:
            assert_safe_audit(value_audit)
        reported_counters = (
            "availability_requests",
            "availability_successes",
            "incomplete_coverage_responses",
            "transient_failures",
            "slow_availability_requests",
            "stale_session_responses",
            "allowed_draft_writes",
            *SAFETY_COUNTERS,
        )
        aggregate_counters = {
            name: sum(value["counters"][name] for value in audits)
            for name in reported_counters
        }
        print(json.dumps({
            "generated_only": True,
            "desktop_compose": True,
            "desktop_reader_reply": True,
            "desktop_flow_reply": True,
            "mobile_390x844_compose": True,
            "explicit_caret_insertion": True,
            "account_and_slot_selection": True,
            "close_escape_focus_restore": True,
            "fail_closed_states": ["stale", "reauthorization_required", "sync_incomplete"],
            "fail_once_retry": True,
            "slow_session_isolation": True,
            "blocked_external_requests": len(blocked_external),
            "allowed_write_kind": "generated compose draft state only",
            "zero_email_send_provider_calendar_event_hold_external_side_effects": True,
            "aggregate_fixture_counters": aggregate_counters,
            "screenshots": [str(desktop_screenshot), str(mobile_screenshot)],
            "selector_assumptions": SELECTOR_ASSUMPTIONS,
        }, indent=2))
    finally:
        process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()


if __name__ == "__main__":
    main()
