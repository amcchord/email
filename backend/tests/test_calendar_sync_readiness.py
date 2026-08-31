"""Focused readiness transitions for incremental calendar sync."""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

import backend.services.calendar_sync as calendar_sync
from backend.models.account import GoogleAccount
from backend.models.calendar import CalendarSyncStatus
from backend.services.calendar_sync import TRANSIENT_MESSAGE, CalendarSyncService
from backend.services.google_scopes import CALENDAR_READONLY_SCOPE


class _ScalarResult:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class _Session:
    def __init__(self, state):
        self.state = state

    async def execute(self, statement):
        entity = statement.column_descriptions[0].get("entity")
        if entity is GoogleAccount:
            return _ScalarResult(self.state.account)
        if entity is CalendarSyncStatus:
            return _ScalarResult(self.state.sync_status)
        raise AssertionError(f"Unexpected database statement: {statement}")

    def add(self, value):
        if isinstance(value, CalendarSyncStatus):
            self.state.sync_status = value
            return
        raise AssertionError(f"Unexpected database add: {value!r}")

    async def commit(self):
        self.state.commits += 1


def _state():
    recent = datetime.now(timezone.utc) - timedelta(minutes=1)
    return SimpleNamespace(
        account=SimpleNamespace(
            id=7,
            email="owner@example.test",
            scopes=json.dumps([CALENDAR_READONLY_SCOPE]),
        ),
        sync_status=SimpleNamespace(
            account_id=7,
            sync_token="before-token",
            last_full_sync=recent,
            last_incremental_sync=recent,
            status="completed",
            error_message=None,
            needs_reauth=False,
            started_at=recent,
            completed_at=recent,
        ),
        commits=0,
    )


def _install_session_factory(monkeypatch, state):
    @asynccontextmanager
    async def session_factory():
        yield _Session(state)

    monkeypatch.setattr(calendar_sync, "async_session", session_factory)


@pytest.mark.asyncio
async def test_incremental_sync_publishes_syncing_before_provider_then_completes(
    monkeypatch,
):
    state = _state()
    old_incremental = state.sync_status.last_incremental_sync
    observed = []

    class _Provider:
        async def list_events(self, **_kwargs):
            observed.append((state.sync_status.status, state.commits))
            return {"items": [], "nextSyncToken": "after-token"}

    service = CalendarSyncService(7)

    async def create_provider(_db, _account):
        return _Provider()

    monkeypatch.setattr(service, "_create_calendar_service", create_provider)
    _install_session_factory(monkeypatch, state)

    await service.incremental_sync()

    assert observed == [("syncing", 1)]
    assert state.sync_status.status == "completed"
    assert state.sync_status.sync_token == "after-token"
    assert state.sync_status.last_incremental_sync > old_incremental
    assert state.sync_status.error_message is None
    assert state.sync_status.needs_reauth is False


@pytest.mark.asyncio
async def test_incremental_failure_after_syncing_cannot_retain_recent_completed(
    monkeypatch,
):
    state = _state()
    state.events = []
    old_incremental = state.sync_status.last_incremental_sync
    observed = []

    class _Provider:
        async def list_events(self, **_kwargs):
            observed.append((state.sync_status.status, state.commits))
            if len(observed) == 1:
                return {
                    "items": [
                        {
                            "id": "partial-event",
                            "start": {"dateTime": "2026-08-31T09:00:00+00:00"},
                            "end": {"dateTime": "2026-08-31T09:30:00+00:00"},
                        }
                    ],
                    "nextPageToken": "page-2",
                }
            raise RuntimeError("scripted provider failure")

    service = CalendarSyncService(7)

    async def create_provider(_db, _account):
        return _Provider()

    async def record_upsert(_db, parsed):
        state.events.append(parsed)

    async def no_sleep(_seconds):
        return None

    monkeypatch.setattr(service, "_create_calendar_service", create_provider)
    monkeypatch.setattr(service, "_upsert_event", record_upsert)
    monkeypatch.setattr(calendar_sync.asyncio, "sleep", no_sleep)
    _install_session_factory(monkeypatch, state)

    with pytest.raises(RuntimeError, match="scripted provider failure"):
        await service.incremental_sync()

    assert observed == [("syncing", 1), ("syncing", 2)]
    assert [event["google_event_id"] for event in state.events] == ["partial-event"]
    assert state.sync_status.status == "error"
    assert state.sync_status.error_message == TRANSIENT_MESSAGE
    assert state.sync_status.needs_reauth is False
    assert state.sync_status.last_incremental_sync == old_incremental
    assert state.commits == 3
