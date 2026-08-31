import base64
from datetime import datetime, timedelta, timezone
from email import policy
from email.parser import BytesParser
from types import SimpleNamespace
from uuid import uuid4

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from pydantic import ValidationError

import backend.services.drafts as draft_module
from backend.models.draft import (
    DRAFT_SESSION_STATES,
    DraftAttachment,
    DraftMutation,
    DraftSession,
)
from backend.models.outbound_message import OutboundMessage
from backend.routers.compose import router
from backend.schemas.email import (
    ComposeDraftRequest,
    DraftSessionDetailResponse,
    DraftSessionResponse,
)
from backend.services.drafts import (
    DRAFT_DISCARD_UNDO_SECONDS,
    _matched_provider_revision,
    _process_discard,
    _process_reconciliation,
    _process_upsert,
    draft_can_undo_discard,
    draft_request_hash,
)
from backend.services.gmail import GmailService
from backend.workers.tasks import CronWorkerSettings, drain_draft_sessions_task


NOW = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)


def _request(**overrides):
    values = {
        "client_draft_id": uuid4(),
        "revision": 1,
        "mutation_id": uuid4(),
        "account_id": 7,
        "to": ["recipient@example.test"],
        "subject": "Generated draft",
        "body_text": "Generated body",
    }
    values.update(overrides)
    return ComposeDraftRequest(**values)


def _draft(**overrides):
    client_draft_id = overrides.pop("client_draft_id", uuid4())
    values = {
        "id": 41,
        "client_draft_id": client_draft_id,
        "user_id": 5,
        "account_id": 7,
        "revision": 3,
        "synced_revision": None,
        "state": "syncing",
        "lease_operation": "upsert",
        "lease_token": uuid4(),
        "provider_draft_id": None,
        "provider_message_id": None,
        "provider_create_attempted_at": None,
        "rfc_message_id": f"<draft-{client_draft_id}@email.mcchord.net>",
        "payload": {
            "to": ["recipient@example.test"],
            "cc": [],
            "bcc": [],
            "subject": "Generated",
            "body_html": "",
            "body_text": "Generated",
            "thread_id": None,
            "in_reply_to": None,
            "references": None,
        },
        "attachments": [],
        "linked_send_id": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_draft_request_requires_stable_identity_revision_and_mutation():
    request = _request()
    assert request.revision == 1
    assert request.client_draft_id
    assert request.mutation_id

    for missing in ("client_draft_id", "revision", "mutation_id"):
        values = _request().model_dump()
        values.pop(missing)
        with pytest.raises(ValidationError):
            ComposeDraftRequest(**values)
    with pytest.raises(ValidationError, match="greater than 0"):
        _request(revision=0)


def test_draft_hash_ignores_mutation_and_revision_but_covers_bytes():
    attachment = {
        "filename": "generated.txt",
        "content_type": "text/plain",
        "data_base64": base64.b64encode(b"same bytes").decode(),
    }
    first = _request(attachments=[attachment])
    same = first.model_copy(update={"revision": 2, "mutation_id": uuid4()})
    changed = first.model_copy(update={
        "attachments": [first.attachments[0].model_copy(update={
            "data_base64": base64.b64encode(b"changed").decode(),
        })],
    })
    assert draft_request_hash(first) == draft_request_hash(same)
    assert draft_request_hash(first) != draft_request_hash(changed)
    assert draft_request_hash(first) != draft_request_hash(first.model_copy(update={
        "follow_up_reminder": "enabled",
        "follow_up_time_zone": "America/New_York",
    }))


def test_public_metadata_is_content_free_and_owned_detail_is_resumable():
    forbidden = {"payload", "to", "cc", "bcc", "subject", "body_html", "body_text", "attachments"}
    assert forbidden.isdisjoint(DraftSessionResponse.model_fields)
    assert {
        "to", "cc", "bcc", "subject", "body_html", "body_text", "attachments",
        "follow_up_reminder", "follow_up_time_zone",
    } <= DraftSessionDetailResponse.model_fields.keys()
    assert "provider_draft_id" not in DraftSessionDetailResponse.model_fields
    assert "provider_message_id" not in DraftSessionDetailResponse.model_fields


def test_draft_models_routes_migration_and_worker_are_complete():
    state_constraint = next(
        constraint
        for constraint in DraftSession.__table__.constraints
        if constraint.name == "ck_draft_sessions_state"
    )
    for state in DRAFT_SESSION_STATES:
        assert state in str(state_constraint.sqltext)
    assert DraftAttachment.__table__.c.content.type.__class__.__name__ == "LargeBinary"
    assert "payload" not in DraftMutation.__table__.c
    assert "draft_session_id" in OutboundMessage.__table__.c
    assert "client_draft_id" in OutboundMessage.__table__.c

    route_contract = {
        (route.path, method)
        for route in router.routes
        for method in route.methods
    }
    assert ("/api/compose/draft", "POST") in route_contract
    assert ("/api/compose/drafts/recent", "GET") in route_contract
    assert ("/api/compose/drafts/by-client-id/{client_draft_id}", "GET") in route_contract
    assert ("/api/compose/drafts/by-source-email/{source_email_id}", "GET") in route_contract
    assert ("/api/compose/drafts/by-email/{email_id}", "GET") in route_contract
    assert ("/api/compose/drafts/{client_draft_id}/discard", "POST") in route_contract
    assert ("/api/compose/drafts/{client_draft_id}/undo-discard", "POST") in route_contract
    save_route = next(route for route in router.routes if route.path == "/api/compose/draft")
    assert save_route.status_code == 202

    config = Config()
    config.set_main_option("script_location", "alembic")
    scripts = ScriptDirectory.from_config(config)
    revision = scripts.get_revision("e2f3a4b5c6d7")
    assert revision.down_revision == "d1e2f3a4b5c6"
    assert scripts.get_revision("f3a4b5c6d7e8").down_revision == "e2f3a4b5c6d7"
    assert scripts.get_revision("a4b5c6d7e8f9").down_revision == "f3a4b5c6d7e8"
    assert scripts.get_revision("b5c6d7e8f9a0").down_revision == "a4b5c6d7e8f9"
    assert scripts.get_revision("c6d7e8f9a0b1").down_revision == "b5c6d7e8f9a0"
    assert scripts.get_revision("f9a0b1c2d3e4").down_revision == "e8f9a0b1c2d3"
    assert scripts.get_heads() == ["a0b1c2d3e4f5"]

    assert drain_draft_sessions_task in CronWorkerSettings.functions
    assert any(job.coroutine is drain_draft_sessions_task for job in CronWorkerSettings.cron_jobs)


def test_discard_has_server_owned_ten_second_undo_window():
    draft = SimpleNamespace(
        state="discard_pending",
        linked_send_id=None,
        discard_undo_until=NOW + timedelta(seconds=DRAFT_DISCARD_UNDO_SECONDS),
    )
    assert DRAFT_DISCARD_UNDO_SECONDS == 10
    assert draft_can_undo_discard(draft, now=NOW + timedelta(seconds=9)) is True
    assert draft_can_undo_discard(draft, now=NOW + timedelta(seconds=11)) is False
    draft.linked_send_id = uuid4()
    assert draft_can_undo_discard(draft, now=NOW) is False


class _DraftApiCapture:
    def __init__(self):
        self.calls = []

    def users(self):
        return self

    def drafts(self):
        return self

    def create(self, **kwargs):
        self.calls.append(("create", kwargs))
        return SimpleNamespace(operation="create")

    def update(self, **kwargs):
        self.calls.append(("update", kwargs))
        return SimpleNamespace(operation="update")

    def get(self, **kwargs):
        self.calls.append(("get", kwargs))
        return SimpleNamespace(operation="get")

    def list(self, **kwargs):
        self.calls.append(("list", kwargs))
        return SimpleNamespace(operation="list")

    def delete(self, **kwargs):
        self.calls.append(("delete", kwargs))
        return SimpleNamespace(operation="delete")


@pytest.mark.asyncio
async def test_gmail_draft_resource_methods_preserve_stable_identity(monkeypatch):
    service = GmailService(SimpleNamespace(email="sender@example.test"))
    capture = _DraftApiCapture()
    client_draft_id = uuid4()

    async def execute(request, *, context, max_retries):
        assert max_retries == 1
        if context == "list_drafts":
            return {"drafts": []}
        if context == "delete_draft":
            return {}
        return {"id": "provider-draft", "message": {"id": "provider-message"}}

    monkeypatch.setattr(service, "_get_service", lambda: capture)
    monkeypatch.setattr(service, "_execute_with_retry", execute)
    kwargs = {
        "to": ["recipient@example.test"],
        "subject": "Generated",
        "body_text": "Generated",
        "message_id_header": f"<draft-{client_draft_id}@email.mcchord.net>",
        "draft_id_header": str(client_draft_id),
        "draft_revision": 3,
    }
    created = await service.create_draft_resource(**kwargs)
    updated = await service.update_draft_resource("provider-draft", **kwargs)
    await service.get_draft_resource("provider-draft")
    await service.list_draft_resources(query="rfc822msgid:generated")
    await service.delete_draft_resource("provider-draft")

    assert created["id"] == updated["id"] == "provider-draft"
    assert [call[0] for call in capture.calls] == ["create", "update", "get", "list", "delete"]
    raw = capture.calls[0][1]["body"]["message"]["raw"]
    message = BytesParser(policy=policy.default).parsebytes(base64.urlsafe_b64decode(raw))
    assert message["Message-ID"] == kwargs["message_id_header"]
    assert message["X-Mail-Client-Draft-ID"] == str(client_draft_id)
    assert message["X-Mail-Client-Draft-Revision"] == "3"


def test_provider_reconciliation_requires_all_stable_headers():
    draft = _draft()
    resource = {
        "id": "provider-draft",
        "message": {
            "id": "provider-message",
            "payload": {"headers": [
                {"name": "Message-ID", "value": draft.rfc_message_id},
                {"name": "X-Mail-Client-Draft-ID", "value": str(draft.client_draft_id)},
                {"name": "X-Mail-Client-Draft-Revision", "value": "3"},
            ]},
        },
    }
    assert _matched_provider_revision(draft, resource) == 3
    resource["message"]["payload"]["headers"][1]["value"] = str(uuid4())
    assert _matched_provider_revision(draft, resource) is None


@pytest.mark.asyncio
async def test_initial_create_is_single_attempt_and_missing_identity_reconciles(monkeypatch):
    draft = _draft()
    calls = []

    class Gmail:
        async def create_draft_resource(self, **kwargs):
            calls.append(kwargs)
            return {"id": "provider-draft", "message": {"id": "provider-message"}}

    async def marked(**_kwargs):
        return True

    async def no_token(*_args, **_kwargs):
        return None

    synced = []
    reconciled = []

    async def record_synced(**kwargs):
        synced.append(kwargs)

    async def record_reconciling(**kwargs):
        reconciled.append(kwargs)

    monkeypatch.setattr(draft_module, "_mark_create_attempt_started", marked)
    monkeypatch.setattr(draft_module, "_persist_refreshed_token", no_token)
    monkeypatch.setattr(draft_module, "_record_synced", record_synced)
    monkeypatch.setattr(draft_module, "_record_reconciling", record_reconciling)

    await _process_upsert(draft, gmail=Gmail())
    assert len(calls) == 1
    assert calls[0]["max_retries"] == 1
    assert synced and not reconciled

    class EmptyGmail(Gmail):
        async def create_draft_resource(self, **kwargs):
            calls.append(kwargs)
            return {"message": {}}

    await _process_upsert(_draft(), gmail=EmptyGmail())
    assert reconciled


@pytest.mark.asyncio
async def test_ambiguous_initial_create_reconciliation_is_lookup_only(monkeypatch):
    draft = _draft(
        lease_operation="reconcile",
        provider_create_attempted_at=NOW,
    )
    calls = []

    class Gmail:
        async def find_drafts_by_rfc_message_id(self, *_args, **_kwargs):
            calls.append("lookup")
            return []

        async def create_draft_resource(self, **_kwargs):
            pytest.fail("ambiguous initial create must never replay")

        def get_refreshed_token(self):
            return None

    async def no_token(*_args, **_kwargs):
        return None

    reconciled = []

    async def record_reconciling(**kwargs):
        reconciled.append(kwargs)

    monkeypatch.setattr(draft_module, "_persist_refreshed_token", no_token)
    monkeypatch.setattr(draft_module, "_record_reconciling", record_reconciling)
    await _process_reconciliation(draft, gmail=Gmail())
    assert calls == ["lookup"]
    assert reconciled


@pytest.mark.asyncio
async def test_discard_without_any_provider_attempt_scrubs_without_gmail(monkeypatch):
    draft = _draft(lease_operation="discard")
    finished = []

    class Gmail:
        async def delete_draft_resource(self, *_args, **_kwargs):
            pytest.fail("no provider draft exists")

    async def finish(**kwargs):
        finished.append(kwargs)

    monkeypatch.setattr(draft_module, "_finish_discarded", finish)
    await _process_discard(draft, gmail=Gmail())
    assert finished
