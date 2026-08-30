import base64
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI

import backend.routers.compose as compose_router
from backend.database import get_db
from backend.routers.auth import get_current_user
from backend.services.drafts import DraftNotFound, DraftSourceExists


NOW = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)


def _draft(*, state="pending", with_attachment=False):
    attachment_content = b"generated attachment"
    future_deadline = datetime(2099, 1, 1, tzinfo=timezone.utc)
    return SimpleNamespace(
        id=41,
        client_draft_id=uuid4(),
        account_id=7,
        source_email_id_snapshot=None,
        revision=1,
        synced_revision=None,
        state=state,
        next_attempt_at=NOW,
        attempt_count=0,
        discard_at=future_deadline if state == "discard_pending" else None,
        discard_undo_until=future_deadline if state == "discard_pending" else None,
        linked_send_id=None,
        error_code=None,
        error_message=None,
        attachment_count=1 if with_attachment else 0,
        attachment_bytes=len(attachment_content) if with_attachment else 0,
        created_at=NOW,
        updated_at=NOW,
        synced_at=None,
        discarded_at=None,
        payload={
            "to": ["recipient@example.test"],
            "cc": [],
            "bcc": [],
            "subject": "Generated draft",
            "body_html": "<p>Generated</p>",
            "body_text": "Generated",
            "in_reply_to": None,
            "references": None,
            "thread_id": None,
        },
        attachments=[SimpleNamespace(
            attachment_id=uuid4(),
            filename="generated.txt",
            content_type="text/plain",
            size_bytes=len(attachment_content),
            sha256="a" * 64,
            content=attachment_content,
            sort_order=0,
        )] if with_attachment else [],
    )


@pytest.fixture
def app():
    app = FastAPI()
    app.include_router(compose_router.router)

    async def fake_db():
        yield SimpleNamespace()

    async def fake_user():
        return SimpleNamespace(id=5)

    app.dependency_overrides[get_db] = fake_db
    app.dependency_overrides[get_current_user] = fake_user
    return app


@pytest.fixture(autouse=True)
def no_redis(monkeypatch):
    async def noop():
        return None

    monkeypatch.setattr(compose_router, "try_enqueue_draft_drain", noop)


@pytest.mark.asyncio
async def test_post_draft_returns_202_metadata_without_content(app, monkeypatch):
    draft = _draft()

    async def stage(_db, *, user_id, request):
        assert user_id == 5
        draft.client_draft_id = request.client_draft_id
        return draft, True

    monkeypatch.setattr(compose_router, "stage_draft_upsert", stage)
    payload = {
        "client_draft_id": str(uuid4()),
        "revision": 1,
        "mutation_id": str(uuid4()),
        "account_id": 7,
        "to": ["recipient@example.test"],
        "subject": "Generated draft",
        "body_text": "secret body",
    }
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="https://test",
    ) as client:
        response = await client.post("/api/compose/draft", json=payload)

    assert response.status_code == 202
    body = response.json()
    assert body["client_draft_id"] == payload["client_draft_id"]
    assert body["state"] == "pending"
    assert "body_text" not in body
    assert "attachments" not in body
    assert "payload" not in body


@pytest.mark.asyncio
async def test_owned_detail_is_resumable_but_unknown_email_draft_is_404(app, monkeypatch):
    detail = _draft(state="synced", with_attachment=True)

    async def get_owned(_db, *, user_id, client_draft_id, include_attachments):
        assert user_id == 5
        assert include_attachments is True
        detail.client_draft_id = client_draft_id
        return detail

    async def unknown_external(*_args, **_kwargs):
        raise DraftNotFound("Draft is not managed by this app")

    monkeypatch.setattr(compose_router, "get_draft_session", get_owned)
    monkeypatch.setattr(compose_router, "get_draft_session_for_email", unknown_external)
    client_draft_id = uuid4()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="https://test",
    ) as client:
        response = await client.get(
            f"/api/compose/drafts/by-client-id/{client_draft_id}"
        )
        unknown = await client.get("/api/compose/drafts/by-email/999")

    assert response.status_code == 200
    body = response.json()
    assert body["body_text"] == "Generated"
    assert base64.b64decode(body["attachments"][0]["data_base64"]) == b"generated attachment"
    assert unknown.status_code == 404
    assert unknown.json()["detail"]["code"] == "draft_not_found"


@pytest.mark.asyncio
async def test_exact_owned_source_lookup_and_metadata_only_recent_list(app, monkeypatch):
    detail = _draft(state="synced")
    detail.source_email_id_snapshot = 812

    async def get_source(_db, *, user_id, account_id, source_email_id):
        assert (user_id, account_id, source_email_id) == (5, 7, 812)
        return detail

    async def recent(_db, *, user_id, limit):
        assert (user_id, limit) == (5, 4)
        return [detail]

    monkeypatch.setattr(compose_router, "get_draft_session_for_source_email", get_source)
    monkeypatch.setattr(compose_router, "recent_draft_sessions", recent)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="https://test",
    ) as client:
        source = await client.get("/api/compose/drafts/by-source-email/812?account_id=7")
        summary = await client.get("/api/compose/drafts/recent?limit=4")

    assert source.status_code == 200
    assert source.json()["client_draft_id"] == str(detail.client_draft_id)
    assert summary.status_code == 200
    assert summary.json()[0]["client_draft_id"] == str(detail.client_draft_id)
    assert "subject" not in summary.json()[0]
    assert "body_preview" not in summary.json()[0]
    assert "to" not in summary.json()[0]
    assert "provider_message_id" not in summary.json()[0]
    assert "attachments" not in summary.json()[0]


@pytest.mark.asyncio
async def test_source_convergence_uses_stable_conflict_code(app, monkeypatch):
    async def occupied(*_args, **_kwargs):
        raise DraftSourceExists("A reply draft already exists for this message")

    monkeypatch.setattr(compose_router, "stage_draft_upsert", occupied)
    payload = {
        "client_draft_id": str(uuid4()),
        "revision": 1,
        "mutation_id": str(uuid4()),
        "account_id": 7,
        "to": ["recipient@example.test"],
        "subject": "Re: Generated",
        "body_text": "Generated reply",
    }
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="https://test",
    ) as client:
        response = await client.post("/api/compose/draft", json=payload)

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "draft_source_exists"


@pytest.mark.asyncio
async def test_discard_returns_server_deadline_and_undo_transitions_active(app, monkeypatch):
    pending = _draft(state="discard_pending")
    restored = _draft(state="synced")
    restored.client_draft_id = pending.client_draft_id

    async def discard(_db, *, user_id, client_draft_id, mutation_id):
        assert user_id == 5 and mutation_id
        pending.client_draft_id = client_draft_id
        return pending

    async def undo(_db, *, user_id, client_draft_id, mutation_id):
        assert user_id == 5 and mutation_id
        restored.client_draft_id = client_draft_id
        return restored

    monkeypatch.setattr(compose_router, "discard_draft_session", discard)
    monkeypatch.setattr(compose_router, "undo_discard_draft_session", undo)
    mutation = {"mutation_id": str(uuid4())}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="https://test",
    ) as client:
        discarded = await client.post(
            f"/api/compose/drafts/{pending.client_draft_id}/discard",
            json=mutation,
        )
        restored_response = await client.post(
            f"/api/compose/drafts/{pending.client_draft_id}/undo-discard",
            json={"mutation_id": str(uuid4())},
        )

    assert discarded.status_code == 202
    assert discarded.json()["state"] == "discard_pending"
    assert discarded.json()["can_undo_discard"] is True
    assert discarded.json()["discard_undo_until"]
    assert restored_response.status_code == 200
    assert restored_response.json()["state"] == "synced"
    assert restored_response.json()["can_undo_discard"] is False
