#!/usr/bin/env python3
"""Generated-only browser acceptance for Saved Views / Custom Splits.

Run after ``npm --prefix frontend run build`` with the workspace Playwright
environment, normally ``.venv/bin/python scripts/qa/generated_saved_views_browser_qa.py``.
The script starts the localhost fixture itself and blocks non-local requests.

Selector assumptions are intentionally recorded here instead of changing app
code for QA: the eager search is ``#email-search-input``; the Saved Views
section exposes ``[data-saved-views-focus]``; management uses accessible button
and dialog names; the command palette is the existing ``Commands`` dialog.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import platform
import socket
import subprocess
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from playwright.sync_api import Page, expect, sync_playwright


ROOT = Path(__file__).resolve().parents[2]
PRIVATE_QUERY = (
    'from:renee+launch@example.test subject:"Quarterly & Planning" '
    'has:attachment -is:read in:inbox'
)
MODIFIED_QUERY = (
    'from:renee+launch@example.test subject:"Quarterly & Planning" '
    '-is:read in:inbox'
)
SELECTOR_ASSUMPTIONS = {
    "search": "#email-search-input",
    "saved_views_section": "[data-saved-views-focus]",
    "save_current": 'button:has-text("Save view")',
    "create_dialog": 'role=dialog[name="Save current search"]',
    "manage_dialog": 'role=dialog[name="Manage Saved View"]',
    "sidebar_item": 'role=button[name="Generated Browser View"]',
    "manage_button": 'role=button[name="Manage Generated Browser View"]',
    "command_dialog": 'role=dialog[name="Commands"]',
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
        with urlopen(request, timeout=3) as response:  # noqa: S310 - localhost fixture
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
    raise AssertionError("Generated search server did not become ready")


def reset(base_url: str, current_user="generated-a"):
    return api(
        base_url,
        "POST",
        "/api/test/saved-views/reset",
        {"current_user": current_user},
    )


def assert_private_query_not_in_page_url(page: Page) -> None:
    assert PRIVATE_QUERY not in page.url
    assert "Quarterly%20%26%20Planning" not in page.url
    assert "renee%2Blaunch%40example.test" not in page.url.lower()


def apply_search(page: Page, query: str) -> None:
    search = page.locator(SELECTOR_ASSUMPTIONS["search"])
    expect(search).to_be_visible()
    search.fill(query)
    search.press("Enter")
    expect(page.get_by_role("region", name="Search results summary")).to_be_visible()
    assert_private_query_not_in_page_url(page)


def create_browser_view(page: Page) -> None:
    apply_search(page, PRIVATE_QUERY)
    page.get_by_role("button", name="Save view", exact=True).click()
    dialog = page.get_by_role("dialog", name="Save current search")
    expect(dialog).to_be_visible()
    name = dialog.get_by_label("Name")
    expect(name).to_be_focused()
    name.fill("Generated Browser View")
    dialog.get_by_label("Account").select_option(label="search.primary@example.test")
    expect(dialog.get_by_label("Structured search")).to_have_value(PRIVATE_QUERY)
    dialog.get_by_role("button", name="Create view").click()
    expect(dialog).not_to_be_visible()
    expect(page.get_by_role("button", name="Generated Browser View", exact=True)).to_be_visible()
    assert_private_query_not_in_page_url(page)


def assert_desktop_journey(page: Page, base_url: str) -> None:
    reset(base_url)
    page.goto(f"{base_url}/?page=inbox", wait_until="domcontentloaded")
    expect(page.locator(SELECTOR_ASSUMPTIONS["saved_views_section"])).to_be_visible()
    create_browser_view(page)

    collection = api(base_url, "GET", "/api/saved-views")
    created = next(item for item in collection["items"] if item["name"] == "Generated Browser View")
    assert created["account_id"] == 1
    assert created["query"] == PRIVATE_QUERY

    page.get_by_role("button", name="Generated Browser View", exact=True).click()
    expect(page.locator(SELECTOR_ASSUMPTIONS["search"])).to_have_value(PRIVATE_QUERY)
    assert_private_query_not_in_page_url(page)

    apply_search(page, MODIFIED_QUERY)
    expect(page.get_by_role("button", name="Save changes", exact=True)).to_be_visible()

    page.get_by_role("button", name="Manage Generated Browser View").click()
    dialog = page.get_by_role("dialog", name="Manage Saved View")
    expect(dialog).to_be_visible()
    dialog.get_by_label("Name").fill("Generated Renamed View")
    dialog.get_by_role("button", name="Save changes").click()
    expect(dialog).not_to_be_visible()
    expect(page.get_by_role("button", name="Generated Renamed View", exact=True)).to_be_visible()

    page.get_by_role("button", name="Manage Generated Renamed View").click()
    dialog = page.get_by_role("dialog", name="Manage Saved View")
    dialog.get_by_role("button", name="Move up").click()
    expect(dialog.get_by_role("button", name="Move up")).to_be_enabled()
    dialog.get_by_role("button", name="Cancel").click()
    ordered = api(base_url, "GET", "/api/saved-views")["items"]
    assert next(item for item in ordered if item["name"] == "Generated Renamed View")["position"] == 1

    # Keyboard chord focuses the first-class section; command palette opens a
    # Saved View by its generated name without placing the query in the URL.
    page.keyboard.press("g")
    page.keyboard.press("v")
    expect(page.locator(SELECTOR_ASSUMPTIONS["saved_views_section"])).to_be_focused()
    page.keyboard.press("Meta+k" if platform.system() == "Darwin" else "Control+k")
    command = page.get_by_role("dialog", name="Commands")
    expect(command).to_be_visible()
    command.get_by_role("combobox").fill("Open Generated Renamed View")
    command.get_by_role("option", name="Open Generated Renamed View").click()
    expect(command).not_to_be_visible()
    expect(page.locator(SELECTOR_ASSUMPTIONS["search"])).to_have_value(PRIVATE_QUERY)
    assert_private_query_not_in_page_url(page)

    page.get_by_role("button", name="Manage Generated Renamed View").click()
    dialog = page.get_by_role("dialog", name="Manage Saved View")
    dialog.get_by_role("button", name="Delete", exact=True).click()
    expect(dialog.get_by_role("status")).to_contain_text("Press Delete again")
    dialog.get_by_role("button", name="Delete permanently").click()
    expect(dialog).not_to_be_visible()
    expect(page.get_by_role("button", name="Generated Renamed View", exact=True)).to_have_count(0)


def assert_error_conflict_and_stale_session(page: Page, base_url: str) -> None:
    reset(base_url)
    api(base_url, "POST", "/api/test/saved-views/scenario", {"scenario": "fail-next"})
    page.goto(f"{base_url}/?page=inbox&qa=retry", wait_until="domcontentloaded")
    alert = page.get_by_role("alert").filter(has_text="Saved Views unavailable")
    expect(alert).to_be_visible()
    alert.get_by_role("button", name="Retry").click()
    expect(alert).not_to_be_visible()
    page.reload(wait_until="domcontentloaded")
    expect(page.get_by_role("button", name="Generated Launch", exact=True)).to_be_visible()

    page.get_by_role("button", name="Manage Generated Launch").click()
    dialog = page.get_by_role("dialog", name="Manage Saved View")
    current = next(
        item for item in api(base_url, "GET", "/api/saved-views")["items"]
        if item["name"] == "Generated Launch"
    )
    api(base_url, "PUT", f"/api/saved-views/{current['id']}", {
        "revision": current["revision"],
        "name": "Generated External Winner",
        "account_id": current["account_id"],
        "query": current["query"],
    })
    dialog.get_by_label("Name").fill("Generated Stale Loser")
    dialog.get_by_role("button", name="Save changes").click()
    expect(dialog.get_by_role("alert")).to_contain_text("changed elsewhere")
    dialog.get_by_role("button", name="Reload Saved Views").click()
    expect(dialog).not_to_be_visible()
    expect(page.get_by_role("button", name="Generated External Winner", exact=True)).to_be_visible()

    # Change the generated authenticated identity in place. The browser must
    # render only User B's collection; the fixture self-test separately proves
    # a held User A response retains its captured identity after this switch.
    api(base_url, "POST", "/api/test/saved-views/session", {"current_user": "generated-b"})
    user_b_page = page.context.new_page()
    user_b_page.goto(f"{base_url}/?page=inbox&qa=user-b", wait_until="domcontentloaded")
    expect(user_b_page.get_by_role("button", name="Generated User B Only", exact=True)).to_be_visible()
    expect(user_b_page.get_by_role("button", name="Generated Secondary", exact=True)).to_have_count(0)
    user_b_page.wait_for_timeout(150)
    expect(user_b_page.get_by_role("button", name="Generated Secondary", exact=True)).to_have_count(0)
    user_b_page.close()


def assert_mobile(page: Page, base_url: str) -> None:
    reset(base_url)
    page.goto(f"{base_url}/?page=inbox&qa=mobile", wait_until="domcontentloaded")
    apply_search(page, PRIVATE_QUERY)
    page.get_by_role("button", name="Save view", exact=True).click()
    dialog = page.get_by_role("dialog", name="Save current search")
    expect(dialog).to_be_visible()
    expect(dialog.get_by_label("Name")).to_be_focused()
    bounds = dialog.bounding_box()
    assert bounds is not None
    assert bounds["x"] >= 0 and bounds["y"] >= 0, bounds
    assert bounds["x"] + bounds["width"] <= 390.5
    assert bounds["y"] + bounds["height"] <= 844.5
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    dialog.get_by_label("Name").fill("Generated Mobile View")
    dialog.get_by_label("Account").select_option(label="search.secondary@example.test")
    dialog.get_by_role("button", name="Create view").click()
    expect(dialog).not_to_be_visible()
    mobile = next(
        item for item in api(base_url, "GET", "/api/saved-views")["items"]
        if item["name"] == "Generated Mobile View"
    )
    assert mobile["account_id"] == 2
    assert mobile["query"] == PRIVATE_QUERY
    page.get_by_role("button", name="Toggle sidebar").click()
    expect(page.locator(SELECTOR_ASSUMPTIONS["saved_views_section"])).to_be_visible()
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    assert_private_query_not_in_page_url(page)


def main() -> None:
    dist = ROOT / "frontend" / "dist" / "index.html"
    if not dist.exists():
        raise SystemExit("frontend/dist is missing; run `npm --prefix frontend run build` first")

    port = free_port()
    base_url = f"http://127.0.0.1:{port}"
    process = subprocess.Popen(
        ["node", "scripts/qa/generated_search_server.mjs"],
        cwd=ROOT,
        env={**os.environ, "QA_PORT": str(port)},
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    blocked_external = []
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
            desktop = browser.new_context(viewport={"width": 1280, "height": 800})
            desktop.route(
                "**/*",
                lambda route: route.continue_()
                if route.request.url.startswith(base_url)
                else (blocked_external.append(route.request.url), route.abort())[1],
            )
            page = desktop.new_page()
            assert_desktop_journey(page, base_url)
            assert_error_conflict_and_stale_session(page, base_url)
            desktop.close()

            mobile = browser.new_context(viewport={"width": 390, "height": 844})
            mobile.route(
                "**/*",
                lambda route: route.continue_()
                if route.request.url.startswith(base_url)
                else (blocked_external.append(route.request.url), route.abort())[1],
            )
            assert_mobile(mobile.new_page(), base_url)
            mobile.close()
            browser.close()

        audit = api(base_url, "GET", "/api/test/saved-views-audit")
        assert not blocked_external, f"external browser requests: {blocked_external}"
        for counter in (
            "mail_mutations",
            "calendar_mutations",
            "provider_mutations",
            "provider_sends",
            "external_network_calls",
        ):
            assert audit["counters"][counter] == 0
        serialized_audit = json.dumps(audit)
        assert PRIVATE_QUERY not in serialized_audit
        print(json.dumps({
            "generated_only": True,
            "desktop": True,
            "mobile_390x844": True,
            "conflict_retry": True,
            "stale_session_isolation": True,
            "private_query_in_navigation_url": False,
            "blocked_external_requests": len(blocked_external),
            "zero_provider_mail_calendar_mutations": True,
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
