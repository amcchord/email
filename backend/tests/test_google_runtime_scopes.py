import json
from types import SimpleNamespace

from backend.services import gmail, google_calendar
from backend.services.google_scopes import (
    CALENDAR_READONLY_SCOPE,
    GMAIL_RUNTIME_SCOPES,
    runtime_scopes_for_account,
)


def test_gmail_and_calendar_refresh_preserve_the_same_recorded_scope_grant(monkeypatch):
    monkeypatch.setattr(gmail, "decrypt_value", lambda value: value)
    monkeypatch.setattr(google_calendar, "decrypt_value", lambda value: value)
    account = SimpleNamespace(
        encrypted_access_token="generated-access",
        encrypted_refresh_token="generated-refresh",
        scopes=json.dumps([*GMAIL_RUNTIME_SCOPES, CALENDAR_READONLY_SCOPE]),
    )

    gmail_credentials = gmail.GmailService(
        account,
        client_id="generated-client",
        client_secret="generated-secret",
    )._get_credentials()
    calendar_credentials = google_calendar.GoogleCalendarService(
        account,
        client_id="generated-client",
        client_secret="generated-secret",
    )._get_credentials()

    expected = [*GMAIL_RUNTIME_SCOPES, CALENDAR_READONLY_SCOPE]
    assert gmail_credentials.scopes == expected
    assert calendar_credentials.scopes == expected


def test_refresh_scope_helper_does_not_invent_calendar_for_legacy_accounts():
    assert runtime_scopes_for_account("[]") == list(GMAIL_RUNTIME_SCOPES)
    assert runtime_scopes_for_account("not-json") == list(GMAIL_RUNTIME_SCOPES)
    assert runtime_scopes_for_account(json.dumps([CALENDAR_READONLY_SCOPE])) == [
        *GMAIL_RUNTIME_SCOPES,
        CALENDAR_READONLY_SCOPE,
    ]
