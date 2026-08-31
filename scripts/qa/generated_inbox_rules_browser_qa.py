#!/usr/bin/env python3
"""Generated-only browser acceptance for trainable Focused/Other rules.

Run after ``npm --prefix frontend run build`` with the workspace Playwright
environment. The script starts a loopback-only fixture, blocks every external
request, uses only ``.example.test`` identities, and writes screenshots under
an OS temporary directory. It never opens a real message or calls a provider,
Gmail, mail mutation, calendar, AI, worker, or terminal route.
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
)
SELECTOR_ASSUMPTIONS = {
    "focused_section": '[data-inbox-section="focused"]',
    "other_section": '[data-inbox-section="other"]',
    "row": '[data-email-row-id="{email_id}"]',
    "teach": '[data-shortcut="inbox.teachSplit"]',
    "rules": '[data-shortcut="inbox.manageSplitRules"]',
    "picker": 'role=dialog[name="Teach Split Inbox"]',
    "manager": 'role=dialog[name="Split Inbox rules"]',
    "commands": 'role=dialog[name="Commands"]',
}


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def api(base_url: str, method: str, path: str, body=None, expected=200):
    data = None if body is None else json.dumps(body).encode("utf-8")
    request = Request(  # noqa: S310 - generated loopback fixture only
        f"{base_url}{path}",
        data=data,
        method=method,
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
            raise AssertionError(f"Generated Inbox rules server exited early: {output}")
        try:
            api(base_url, "GET", "/api/build-version")
            return
        except Exception:
            time.sleep(0.03)
    raise AssertionError("Generated Inbox rules server did not become ready")


def reset(base_url: str, scenario="ready", current_user="generated-a"):
    return api(
        base_url,
        "POST",
        "/__qa/reset",
        {"scenario": scenario, "current_user": current_user},
    )


def set_scenario(base_url: str, scenario: str):
    return api(base_url, "POST", "/__qa/scenario", {"scenario": scenario})


def audit(base_url: str) -> dict:
    return api(base_url, "GET", "/__qa/audit")


def wait_for_audit(base_url: str, predicate, message: str) -> dict:
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        snapshot = audit(base_url)
        if predicate(snapshot):
            return snapshot
        time.sleep(0.02)
    raise AssertionError(message)


def wait_for_value(predicate, expected, message: str):
    deadline = time.monotonic() + 5
    latest = None
    while time.monotonic() < deadline:
        latest = predicate()
        if latest == expected:
            return latest
        time.sleep(0.03)
    raise AssertionError(f"{message}: expected {expected!r}, got {latest!r}")


def install_generated_storage(context: BrowserContext, view_mode="column") -> None:
    context.add_init_script(
        """
        localStorage.setItem('hideIgnored', 'true');
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


def wait_for_split(page: Page) -> None:
    expect(page.locator(SELECTOR_ASSUMPTIONS["focused_section"]).first).to_be_visible(timeout=10_000)
    expect(page.locator(SELECTOR_ASSUMPTIONS["other_section"]).first).to_be_visible(timeout=10_000)


def assert_visible_totals(page: Page, focused: int, other: int) -> None:
    wait_for_split(page)
    focused_text = page.locator(SELECTOR_ASSUMPTIONS["focused_section"]).first.inner_text()
    other_text = page.locator(SELECTOR_ASSUMPTIONS["other_section"]).first.inner_text()
    assert re.search(rf"\bFocused\s+{focused}\b", " ".join(focused_text.split())), focused_text
    assert re.search(rf"\bOther\s+{other}\b", " ".join(other_text.split())), other_text


def row_surface(page: Page, email_id: int) -> Locator:
    anchor = page.locator(SELECTOR_ASSUMPTIONS["row"].format(email_id=email_id)).first
    expect(anchor).to_be_visible()
    if anchor.evaluate("element => element.tagName === 'TR'"):
        return anchor
    return anchor.locator("xpath=..")


def open_teach(page: Page, email_id: int) -> Locator:
    surface = row_surface(page, email_id)
    dedicated = surface.locator(SELECTOR_ASSUMPTIONS["teach"])
    if dedicated.is_visible():
        dedicated.click()
    else:
        surface.get_by_role(
            "button",
            name=re.compile("Open Teach Split Inbox", re.I),
        ).click()
    dialog = page.get_by_role("dialog", name="Teach Split Inbox")
    expect(dialog).to_be_visible()
    return dialog


def choose_rule(dialog: Locator, scope_text: str, placement: str) -> None:
    dialog.get_by_role("radio", name=re.compile(scope_text, re.I)).check()
    dialog.get_by_role("radio", name=placement, exact=True).check()


def assert_zero_external_operations(snapshot: dict) -> None:
    assert snapshot["generated_only"] is True
    assert snapshot["localhost_only"] is True
    assert snapshot["fixture_domains"] == ["example.test"]
    for counter in ZERO_OPERATION_COUNTERS:
        assert snapshot["counters"][counter] == 0, (counter, snapshot["counters"][counter])
    assert snapshot["counters"]["unexpected_writes"] == 0


def assert_column_create_undo_and_manager(
    page: Page,
    base_url: str,
    screenshots: Path,
) -> list[dict]:
    snapshots = []
    reset(base_url)
    page.goto(f"{base_url}/?page=inbox&qa=rules-column", wait_until="domcontentloaded")
    assert_visible_totals(page, 4, 2)

    # Loading the server-derived choices and cancelling is a provable zero-write path.
    dialog = open_teach(page, 101)
    expect(dialog).to_contain_text("focused-primary@example.test")
    expect(dialog).to_contain_text("Gmail is unchanged")
    dialog.screenshot(path=str(screenshots / "desktop-column-teach-picker.png"))
    dialog.get_by_role("button", name="Cancel", exact=True).click()
    expect(dialog).not_to_be_visible()
    snapshot = audit(base_url)
    assert snapshot["counters"]["expected_rule_writes"] == 0
    snapshots.append(snapshot)

    # One exact-conversation instruction refreshes coherent totals, survives the
    # authoritative reload, and is immediately reversible from the shared toast.
    dialog = open_teach(page, 101)
    choose_rule(dialog, "This conversation", "Other")
    dialog.get_by_role("button", name="Save rule").click()
    expect(dialog).not_to_be_visible()
    assert_visible_totals(page, 3, 3)
    page.get_by_role("button", name="Undo rule change").click()
    assert_visible_totals(page, 4, 2)
    assert api(base_url, "GET", "/api/inbox-placement-rules")["items"] == []

    # Sender scope affects both existing account-one anchors, never the same
    # sender in account two, and persists through a full document reload.
    dialog = open_teach(page, 101)
    choose_rule(dialog, "This sender", "Other")
    dialog.get_by_role("button", name="Save rule").click()
    expect(dialog).not_to_be_visible()
    assert_visible_totals(page, 2, 4)
    resolved = {item["email_id"]: item for item in audit(base_url)["resolved"]}
    assert resolved[101]["rule_scope"] == "sender"
    assert resolved[102]["rule_scope"] == "sender"
    assert resolved[201]["source"] == "system"
    page.reload(wait_until="domcontentloaded")
    assert_visible_totals(page, 2, 4)
    assert "Personal sender rule" in row_surface(page, 101).inner_text()

    # The first-class manager edits placement, disables/re-enables, and requires
    # a deliberate confirmation before deletion.
    page.locator(SELECTOR_ASSUMPTIONS["rules"]).first.click()
    manager = page.get_by_role("dialog", name="Split Inbox rules")
    expect(manager).to_be_visible()
    expect(manager).to_contain_text("local Inbox view only")
    article = manager.locator("article").filter(has_text="alex@sender.example.test")
    expect(article).to_be_visible()
    article.get_by_label("Place future matches in").select_option("focused")
    article.get_by_role("button", name="Save changes").click()
    wait_for_value(
        lambda: api(base_url, "GET", "/api/emails/conversations/split")["focused"]["total"],
        4,
        "manager placement edit did not refresh exact totals",
    )

    article = manager.locator("article").filter(has_text="alex@sender.example.test")
    article.get_by_label("Rule enabled").uncheck()
    article.get_by_role("button", name="Save changes").click()
    wait_for_value(
        lambda: api(base_url, "GET", "/api/inbox-placement-rules")["items"][0]["enabled"],
        False,
        "manager disable did not persist",
    )

    article = manager.locator("article").filter(has_text="alex@sender.example.test")
    article.get_by_role("button", name="Delete", exact=True).click()
    expect(article).to_contain_text("Delete this exact-account rule?")
    article.get_by_role("button", name="Cancel delete").click()
    expect(article).not_to_contain_text("Delete this exact-account rule?")
    article.get_by_role("button", name="Delete", exact=True).click()
    article.get_by_role("button", name="Delete rule").click()
    expect(manager).to_contain_text("No personal rules for this account filter")
    manager.get_by_role("button", name="Done").click()
    assert_visible_totals(page, 4, 2)
    snapshots.append(audit(base_url))
    return snapshots


def assert_table_precedence_and_commands(page: Page, base_url: str, screenshots: Path) -> dict:
    reset(base_url, scenario="precedence")
    page.goto(f"{base_url}/?page=inbox&qa=rules-table", wait_until="domcontentloaded")
    assert_visible_totals(page, 2, 4)
    assert "Personal conversation rule" in row_surface(page, 101).inner_text()
    assert "Personal sender rule" in row_surface(page, 102).inner_text()
    assert "Personal domain rule" in row_surface(page, 103).inner_text()
    assert "Subscription" in row_surface(page, 104).inner_text()
    assert "Personal" not in row_surface(page, 104).inner_text(), "exact domain rule matched a subdomain"
    assert "Personal" not in row_surface(page, 201).inner_text(), "account-one rule crossed accounts"

    row_surface(page, 102).focus()
    page.keyboard.press("Meta+k" if platform.system() == "Darwin" else "Control+k")
    commands = page.get_by_role("dialog", name="Commands")
    expect(commands).to_be_visible()
    commands.get_by_role("combobox").fill("Teach Split Inbox")
    commands.get_by_role("option", name=re.compile("Teach Split Inbox", re.I)).click()
    picker = page.get_by_role("dialog", name="Teach Split Inbox")
    expect(picker).to_be_visible()
    expect(picker).to_contain_text("Existing rule: Focused")
    page.keyboard.press("Escape")
    expect(picker).not_to_be_visible()
    page.screenshot(path=str(screenshots / "desktop-table-precedence.png"), full_page=True)
    return audit(base_url)


def assert_error_conflict_retry_and_slow_session(page: Page, base_url: str) -> list[dict]:
    snapshots = []
    reset(base_url, scenario="fail-once")
    page.goto(f"{base_url}/?page=inbox&qa=rules-errors", wait_until="domcontentloaded")
    dialog = open_teach(page, 101)
    expect(dialog.get_by_role("alert")).to_contain_text("temporarily unavailable")
    dialog.get_by_role("button", name="Try again").click()
    expect(dialog).to_contain_text("What should this rule match?")

    set_scenario(base_url, "conflict-once")
    choose_rule(dialog, "This conversation", "Other")
    dialog.get_by_role("button", name="Save rule").click()
    expect(dialog.get_by_role("alert")).to_contain_text("changed in another session")
    dialog.get_by_role("button", name="Reload latest choices").click()
    expect(dialog).to_contain_text("What should this rule match?")
    dialog.get_by_role("button", name="Save rule").click()
    expect(dialog).not_to_be_visible()
    assert_visible_totals(page, 3, 3)
    snapshots.append(audit(base_url))

    reset(base_url, scenario="error")
    page.reload(wait_until="domcontentloaded")
    dialog = open_teach(page, 101)
    expect(dialog.get_by_role("alert")).to_contain_text("unavailable")
    set_scenario(base_url, "ready")
    dialog.get_by_role("button", name="Try again").click()
    expect(dialog).to_contain_text("What should this rule match?")
    dialog.get_by_role("button", name="Cancel").click()
    snapshots.append(audit(base_url))

    # A delayed ledger response is invalidated by a real authenticated-session
    # transition and page teardown; it may never reopen the old manager.
    reset(base_url, scenario="slow-session")
    page.reload(wait_until="domcontentloaded")
    wait_for_split(page)
    page.locator(SELECTOR_ASSUMPTIONS["rules"]).first.click()
    wait_for_audit(
        base_url,
        lambda value: value["counters"]["delayed_requests"] == 1,
        "delayed rule-manager request did not begin",
    )
    api(base_url, "POST", "/__qa/session", {"current_user": "anonymous"})
    page.reload(wait_until="domcontentloaded")
    expect(page.get_by_text("Sign in to your account")).to_be_visible()
    time.sleep(0.75)
    expect(page.get_by_role("dialog", name="Split Inbox rules")).to_have_count(0)
    slow_audit = audit(base_url)
    assert slow_audit["counters"]["stale_session_responses"] == 1
    snapshots.append(slow_audit)

    reset(base_url)
    page.reload(wait_until="domcontentloaded")
    wait_for_split(page)
    return snapshots


def assert_mobile(page: Page, base_url: str, screenshots: Path) -> dict:
    reset(base_url)
    page.goto(f"{base_url}/?page=inbox&qa=rules-mobile", wait_until="domcontentloaded")
    assert_visible_totals(page, 4, 2)
    dialog = open_teach(page, 103)
    choose_rule(dialog, "This exact domain", "Other")
    bounds = dialog.bounding_box()
    assert bounds is not None
    assert bounds["x"] >= 0 and bounds["y"] >= 0, bounds
    assert bounds["x"] + bounds["width"] <= 390.5, bounds
    assert bounds["y"] + bounds["height"] <= 844.5, bounds
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    dialog.screenshot(path=str(screenshots / "mobile-390x844-domain-rule.png"))
    dialog.get_by_role("button", name="Save rule").click()
    expect(dialog).not_to_be_visible()
    assert_visible_totals(page, 1, 5)
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    resolved = {item["email_id"]: item for item in audit(base_url)["resolved"]}
    assert resolved[103]["rule_scope"] == "domain"
    assert resolved[104]["rule_scope"] is None
    assert resolved[201]["rule_scope"] is None
    return audit(base_url)


def main() -> None:
    if not (ROOT / "frontend" / "dist" / "index.html").is_file():
        raise SystemExit("frontend/dist is missing; run `npm --prefix frontend run build` first")

    port = free_port()
    base_url = f"http://127.0.0.1:{port}"
    screenshots = Path(tempfile.mkdtemp(prefix="generated-inbox-rules-qa-"))
    process = subprocess.Popen(
        ["node", "scripts/qa/generated_inbox_rules_server.mjs"],
        cwd=ROOT,
        env={**os.environ, "QA_PORT": str(port)},
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

            column = browser.new_context(viewport={"width": 1280, "height": 800})
            install_generated_storage(column, "column")
            column.route("**/*", route_generated_only)
            page = column.new_page()
            attach_diagnostics(page, browser_errors)
            snapshots.extend(assert_column_create_undo_and_manager(page, base_url, screenshots))
            snapshots.extend(assert_error_conflict_retry_and_slow_session(page, base_url))
            column.close()

            table = browser.new_context(viewport={"width": 1440, "height": 900})
            install_generated_storage(table, "table")
            table.route("**/*", route_generated_only)
            table_page = table.new_page()
            attach_diagnostics(table_page, browser_errors)
            snapshots.append(assert_table_precedence_and_commands(table_page, base_url, screenshots))
            table.close()

            mobile = browser.new_context(viewport={"width": 390, "height": 844})
            install_generated_storage(mobile, "column")
            mobile.route("**/*", route_generated_only)
            mobile_page = mobile.new_page()
            attach_diagnostics(mobile_page, browser_errors)
            snapshots.append(assert_mobile(mobile_page, base_url, screenshots))
            mobile.close()
            browser.close()

        assert not blocked_external, f"external browser requests were blocked: {blocked_external}"
        assert not browser_errors, f"browser errors: {browser_errors}"
        for snapshot in snapshots:
            assert_zero_external_operations(snapshot)
        assert all(path.is_file() and path.stat().st_size > 0 for path in screenshots.iterdir())
        print(json.dumps({
            "generated_only": True,
            "desktop_column": True,
            "desktop_table": True,
            "mobile_390x844": True,
            "command_palette_keyboard": True,
            "cancel_zero_writes": True,
            "conversation_sender_domain_precedence": True,
            "cross_account_isolation": True,
            "subdomain_non_match": True,
            "reload_persistence": True,
            "immediate_undo": True,
            "manager_edit_enable_delete_confirm": True,
            "conflict_network_retry_slow_session_error": True,
            "exact_totals": True,
            "blocked_external_requests": len(blocked_external),
            "zero_provider_gmail_mail_calendar_ai_worker_terminal_operations": True,
            "screenshots": sorted(str(path) for path in screenshots.iterdir()),
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
