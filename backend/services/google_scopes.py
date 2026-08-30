"""Shared Google data scopes used by every refresh-capable service.

Google can issue an access token for only the scopes requested during refresh.
Gmail and Calendar share one stored token, so either service must preserve the
complete data-scope grant recorded for that account.
"""

import json


GMAIL_RUNTIME_SCOPES = (
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.labels",
)
CALENDAR_READONLY_SCOPE = "https://www.googleapis.com/auth/calendar.readonly"
GOOGLE_DATA_SCOPES = (*GMAIL_RUNTIME_SCOPES, CALENDAR_READONLY_SCOPE)


def runtime_scopes_for_account(serialized_scopes: str | None) -> list[str]:
    """Return refresh scopes without inventing an unrecorded Calendar grant."""
    try:
        authorized = set(json.loads(serialized_scopes or "[]"))
    except (json.JSONDecodeError, TypeError):
        authorized = set()

    scopes = list(GMAIL_RUNTIME_SCOPES)
    if CALENDAR_READONLY_SCOPE in authorized:
        scopes.append(CALENDAR_READONLY_SCOPE)
    return scopes
