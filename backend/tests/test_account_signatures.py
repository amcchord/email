"""Focused contracts for account signatures and immutable message rendering."""

from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi import FastAPI
from pydantic import ValidationError

import backend.routers.compose as compose_router
import backend.routers.signatures as signature_router
import backend.services.drafts as draft_module
import backend.services.outbound_messages as outbound_module
import backend.services.follow_up_reminders as follow_up_module
from backend.models.account import GoogleAccount
from backend.models.draft import DraftMutation, DraftSession
from backend.models.outbound_message import OutboundMessage
from backend.database import get_db
from backend.models.signature import AccountSignature
from backend.routers.auth import get_current_user
from backend.schemas.email import ComposeDraftRequest, ComposeRequest, DraftSessionDetailResponse
from backend.schemas.signature import AccountSignatureReplace
from backend.services.drafts import DraftValidationError, draft_request_hash
from backend.services.drafts import _process_upsert, stage_draft_upsert
from backend.services.outbound_messages import (
    _process_claimed_outbound,
    outbound_payload_hash,
    stage_outbound_message,
)
from backend.services.signatures import (
    AccountSignatureView,
    SignatureConflict,
    SignatureNotFound,
    SignatureRenderedMessageTooLarge,
    SignatureValidationError,
    _snapshot,
    list_account_signatures,
    render_signature_bodies,
    replace_account_signature,
    sanitize_signature_html,
    valid_signature_snapshot,
    with_signature_snapshot_applied,
)


class _Result:
    def __init__(self, *, scalar=None, rows=None):
        self.scalar = scalar
        self.rows = rows or []

    def scalar_one_or_none(self):
        return self.scalar

    def all(self):
        return self.rows


class _SignatureSession:
    def __init__(self, *, account, signature=None, rows=None):
        self.account = account
        self.signature = signature
        self.rows = rows
        self.statements = []
        self.commit_count = 0

    async def execute(self, statement, _parameters=None):
        self.statements.append(statement)
        if self.rows is not None:
            return _Result(rows=self.rows)
        entity = statement.column_descriptions[0].get("entity")
        if entity is AccountSignature:
            return _Result(scalar=self.signature)
        return _Result(scalar=self.account)

    def add(self, signature):
        self.signature = signature

    async def commit(self):
        self.commit_count += 1

    async def refresh(self, _row):
        return None


class _AdmissionSession:
    def __init__(
        self,
        *,
        account,
        signature=None,
        existing_outbound=None,
        existing_draft=None,
    ):
        self.account = account
        self.signature = signature
        self.existing_outbound = existing_outbound
        self.existing_draft = existing_draft
        self.added = []
        self.statements = []
        self.commit_count = 0

    async def execute(self, statement, _parameters=None):
        self.statements.append(statement)
        descriptions = getattr(statement, "column_descriptions", [])
        entity = descriptions[0].get("entity") if descriptions else None
        if entity is GoogleAccount:
            return _Result(scalar=self.account)
        if entity is AccountSignature:
            return _Result(scalar=self.signature)
        if entity is OutboundMessage:
            return _Result(scalar=self.existing_outbound)
        if entity is DraftSession:
            return _Result(scalar=self.existing_draft)
        if entity is DraftMutation:
            return _Result(scalar=None)
        return _Result(scalar=None)

    def add(self, row):
        self.added.append(row)

    async def flush(self):
        for row in self.added:
            if isinstance(row, (DraftSession, OutboundMessage)) and row.id is None:
                row.id = 100 + self.added.index(row)

    async def commit(self):
        self.commit_count += 1

    async def rollback(self):
        return None


def _account(account_id=41, email="owner@example.test"):
    return SimpleNamespace(id=account_id, email=email, is_active=True)


def _request(**overrides):
    values = {
        "expected_revision": 0,
        "enabled": True,
        "include_on_new": True,
        "include_on_replies": False,
        "include_on_forwards": True,
        "body_html": '<p onclick="bad()">Generated <strong>signature</strong>'
        '<script>bad()</script><img src="https://tracker.example.test/pixel"></p>',
        "body_text": "Generated signature",
    }
    values.update(overrides)
    return AccountSignatureReplace(**values)


def _app(*, authenticated):
    app = FastAPI()
    app.include_router(signature_router.router)

    async def fake_db():
        yield SimpleNamespace()

    app.dependency_overrides[get_db] = fake_db
    if authenticated:
        async def fake_user():
            return SimpleNamespace(id=17)

        app.dependency_overrides[get_current_user] = fake_user
    return app


def test_schema_model_and_direct_e8_migration_contract():
    request = _request()
    assert request.include_on_replies is False
    with pytest.raises(ValidationError):
        AccountSignatureReplace.model_validate({**request.model_dump(), "private": True})
    with pytest.raises(ValidationError):
        _request(expected_revision=-1)

    constraints = {constraint.name for constraint in AccountSignature.__table__.constraints}
    assert {
        "ck_account_signatures_revision",
        "ck_account_signatures_sanitizer_version",
        "ck_account_signatures_body_bounds",
        "ck_account_signatures_enabled_body",
    } <= constraints

    config = Config()
    config.set_main_option("script_location", "alembic")
    scripts = ScriptDirectory.from_config(config)
    assert scripts.get_revision("f9a0b1c2d3e4").down_revision == "e8f9a0b1c2d3"
    assert scripts.get_heads() == ["a0b1c2d3e4f5"]


def test_allowlist_sanitizer_removes_active_and_remote_content():
    cleaned = sanitize_signature_html(_request().body_html)
    assert cleaned == "<p>Generated <strong>signature</strong></p>"
    assert "script" not in cleaned
    assert "onclick" not in cleaned
    assert "tracker" not in cleaned
    assert "img" not in cleaned
    assert "javascript:" not in sanitize_signature_html(
        '<a href="javascript:alert(1)">unsafe</a>'
    )


@pytest.mark.asyncio
async def test_defaults_create_replay_update_and_owner_scope():
    empty = _SignatureSession(
        account=None,
        rows=[(_account(), None)],
    )
    listed = await list_account_signatures(empty, user_id=17)
    assert listed == [
        AccountSignatureView(
            account_id=41,
            account_email="owner@example.test",
            enabled=False,
            include_on_new=True,
            include_on_replies=True,
            include_on_forwards=True,
            body_html="",
            body_text="",
            revision=0,
            sanitizer_version=1,
        )
    ]
    query = str(empty.statements[0])
    assert "google_accounts.user_id" in query
    assert "LEFT OUTER JOIN account_signatures" in query

    db = _SignatureSession(account=_account())
    created = await replace_account_signature(
        db, user_id=17, account_id=41, request=_request()
    )
    assert created.revision == 1
    assert created.body_html == "<p>Generated <strong>signature</strong></p>"
    assert db.commit_count == 1

    replayed = await replace_account_signature(
        db, user_id=17, account_id=41, request=_request()
    )
    assert replayed == created
    assert db.commit_count == 2

    update = _request(expected_revision=1, body_text="Changed")
    updated = await replace_account_signature(
        db, user_id=17, account_id=41, request=update
    )
    assert updated.revision == 2
    assert updated.body_text == "Changed"
    with pytest.raises(SignatureConflict, match="another device"):
        await replace_account_signature(
            db,
            user_id=17,
            account_id=41,
            request=_request(expected_revision=1, body_text="Other"),
        )

    foreign = _SignatureSession(account=None)
    with pytest.raises(SignatureNotFound):
        await replace_account_signature(
            foreign, user_id=17, account_id=99, request=_request()
        )
    assert "google_accounts.user_id" in str(foreign.statements[0])


@pytest.mark.asyncio
async def test_routes_are_authenticated_wrapped_and_no_store(monkeypatch):
    anonymous = _app(authenticated=False)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=anonymous), base_url="https://test"
    ) as client:
        assert (await client.get("/api/compose/signatures")).status_code == 401
        assert (
            await client.put("/api/compose/signatures/41", json=_request().model_dump())
        ).status_code == 401

    async def list_views(_db, *, user_id):
        assert user_id == 17
        return [
            AccountSignatureView(
                account_id=41,
                account_email="owner@example.test",
                enabled=False,
                include_on_new=True,
                include_on_replies=True,
                include_on_forwards=True,
                body_html="",
                body_text="",
                revision=0,
                sanitizer_version=1,
            )
        ]

    monkeypatch.setattr(signature_router, "list_account_signatures", list_views)
    authenticated = _app(authenticated=True)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=authenticated), base_url="https://test"
    ) as client:
        response = await client.get("/api/compose/signatures")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["total"] == 1
    assert response.json()["accounts"][0]["revision"] == 0

    async def replace_view(_db, *, user_id, account_id, request):
        assert (user_id, account_id, request.expected_revision) == (17, 41, 0)
        return AccountSignatureView(
            account_id=41,
            account_email="owner@example.test",
            enabled=request.enabled,
            include_on_new=request.include_on_new,
            include_on_replies=request.include_on_replies,
            include_on_forwards=request.include_on_forwards,
            body_html="<p>Saved</p>",
            body_text="Saved",
            revision=1,
            sanitizer_version=1,
        )

    monkeypatch.setattr(signature_router, "replace_account_signature", replace_view)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=authenticated), base_url="https://test"
    ) as client:
        replaced = await client.put(
            "/api/compose/signatures/41",
            json=_request(body_html="<p>Saved</p>", body_text="Saved").model_dump(),
        )
    assert replaced.status_code == 200
    assert replaced.headers["cache-control"] == "no-store"
    assert replaced.json()["sanitizer_version"] == 1

    async def conflict(*_args, **_kwargs):
        raise SignatureConflict("This signature changed on another device; refresh it")

    monkeypatch.setattr(signature_router, "replace_account_signature", conflict)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=authenticated), base_url="https://test"
    ) as client:
        conflicted = await client.put(
            "/api/compose/signatures/41", json=_request().model_dump()
        )
    assert conflicted.status_code == 409
    assert conflicted.json()["detail"]["code"] == "signature_conflict"


def test_snapshot_is_tamper_evident_and_renderer_preserves_authored_parts():
    signature = AccountSignature(
        account_id=41,
        enabled=True,
        include_on_new=True,
        include_on_replies=True,
        include_on_forwards=True,
        body_html="<p>Signature</p>",
        body_text="Signature",
        revision=7,
        sanitizer_version=1,
    )
    snapshot = _snapshot(account_id=41, signature=signature, applied=True)
    assert valid_signature_snapshot(snapshot, account_id=41) == snapshot
    tampered = {**snapshot, "body_text": "Changed"}
    assert valid_signature_snapshot(tampered, account_id=41) is None
    assert valid_signature_snapshot(snapshot, account_id=42) is None
    with pytest.raises(SignatureValidationError, match="snapshot is invalid"):
        render_signature_bodies(
            account_id=41,
            body_html="Authored",
            body_text="Authored",
            quoted_html="",
            quoted_text="",
            signature_snapshot=tampered,
        )

    html, text = render_signature_bodies(
        account_id=41,
        body_html="<p>Authored</p>",
        body_text="Authored",
        quoted_html="<blockquote>Quote</blockquote>",
        quoted_text="> Quote",
        signature_snapshot=snapshot,
    )
    assert html == (
        "<p>Authored</p><br><br><p>Signature</p><br><br>"
        "<blockquote>Quote</blockquote>"
    )
    assert text == "Authored\n\nSignature\n\n> Quote"
    assert html.count("Authored") == html.count("Signature") == html.count("Quote") == 1

    suppressed = _snapshot(account_id=41, signature=signature, applied=False)
    assert suppressed["body_html"] == "<p>Signature</p>"
    assert suppressed["body_text"] == "Signature"
    assert valid_signature_snapshot(suppressed, account_id=41) == suppressed
    assert render_signature_bodies(
        account_id=41,
        body_html="Authored",
        body_text="Authored",
        quoted_html="Quote",
        quoted_text="Quote",
        signature_snapshot=suppressed,
    ) == ("Authored<br><br>Quote", "Authored\n\nQuote")

    restored = with_signature_snapshot_applied(
        suppressed,
        account_id=41,
        applied=True,
    )
    assert restored["policy_revision"] == suppressed["policy_revision"]
    assert restored["body_html"] == suppressed["body_html"]
    assert restored["content_hash"] != suppressed["content_hash"]
    assert valid_signature_snapshot(restored, account_id=41) == restored
    with pytest.raises(SignatureValidationError, match="usable frozen signature"):
        with_signature_snapshot_applied(
            _snapshot(account_id=41, signature=None, applied=False),
            account_id=41,
            applied=True,
        )


def test_renderer_enforces_combined_utf8_ceiling(monkeypatch):
    import backend.services.signatures as signatures_module

    monkeypatch.setattr(signatures_module, "MAX_RENDERED_MESSAGE_BYTES", 7)
    with pytest.raises(SignatureRenderedMessageTooLarge, match="10 MiB"):
        render_signature_bodies(
            account_id=41,
            body_html="four",
            body_text="four",
            quoted_html="",
            quoted_text="",
            signature_snapshot=None,
        )


def test_compose_contract_hashes_new_fields_and_preserves_legacy_hash_shape():
    common = {
        "account_id": 41,
        "to": ["recipient@example.test"],
        "body_html": "<p>Authored</p>",
        "body_text": "Authored",
    }
    legacy_draft = ComposeDraftRequest(
        **common,
        client_draft_id="00000000-0000-4000-8000-000000000001",
        revision=1,
        mutation_id="00000000-0000-4000-8000-000000000002",
    )
    signed_draft = ComposeDraftRequest(
        **common,
        client_draft_id=legacy_draft.client_draft_id,
        revision=1,
        mutation_id=legacy_draft.mutation_id,
        signature_mode="default",
        composition_kind="forward",
        quoted_html="<blockquote>Quote</blockquote>",
        quoted_text="> Quote",
    )
    assert draft_request_hash(legacy_draft) != draft_request_hash(signed_draft)

    legacy_send = ComposeRequest(
        **common,
        idempotency_key="00000000-0000-4000-8000-000000000003",
    )
    signed_send = ComposeRequest(
        **common,
        idempotency_key=legacy_send.idempotency_key,
        signature_mode="default",
        composition_kind="forward",
        quoted_html="<blockquote>Quote</blockquote>",
        quoted_text="> Quote",
    )
    assert outbound_payload_hash(legacy_send) != outbound_payload_hash(signed_send)
    assert "signature_snapshot" in DraftSessionDetailResponse.model_fields


def test_explicit_enabled_requires_usable_signature():
    from backend.services.signatures import _policy_applies

    with pytest.raises(SignatureValidationError, match="usable signature"):
        _policy_applies(None, composition_kind="new", signature_mode="enabled")


@pytest.mark.asyncio
async def test_provider_draft_render_is_transient_and_ordered(monkeypatch):
    snapshot = _snapshot(
        account_id=41,
        signature=AccountSignature(
            account_id=41,
            enabled=True,
            include_on_new=True,
            include_on_replies=True,
            include_on_forwards=True,
            body_html="<p>Signature</p>",
            body_text="Signature",
            revision=1,
            sanitizer_version=1,
        ),
        applied=True,
    )
    persisted_payload = {
        "to": ["recipient@example.test"],
        "cc": [],
        "bcc": [],
        "subject": "Generated",
        "body_html": "<p>Authored</p>",
        "body_text": "Authored",
        "quoted_html": "<blockquote>Quote</blockquote>",
        "quoted_text": "> Quote",
        "thread_id": None,
        "in_reply_to": None,
        "references": None,
        "signature_snapshot": snapshot,
    }
    draft = SimpleNamespace(
        id=1,
        account_id=41,
        payload=persisted_payload,
        attachments=[],
        provider_draft_id="provider-draft",
        client_draft_id=uuid4(),
        revision=3,
        rfc_message_id="<draft-generated@example.test>",
        lease_token=uuid4(),
    )
    calls = []

    class Gmail:
        async def update_draft_resource(self, _draft_id, **kwargs):
            calls.append(kwargs)
            return {"id": "provider-draft", "message": {"id": "provider-message"}}

        def get_refreshed_token(self):
            return None

    async def no_token(*_args, **_kwargs):
        return None

    async def synced(**_kwargs):
        return True

    monkeypatch.setattr(draft_module, "_persist_refreshed_token", no_token)
    monkeypatch.setattr(draft_module, "_record_synced", synced)
    await _process_upsert(draft, gmail=Gmail())

    assert calls[0]["body_html"] == (
        "<p>Authored</p><br><br><p>Signature</p><br><br>"
        "<blockquote>Quote</blockquote>"
    )
    assert calls[0]["body_text"] == "Authored\n\nSignature\n\n> Quote"
    assert persisted_payload["body_html"] == "<p>Authored</p>"
    assert persisted_payload["body_text"] == "Authored"


@pytest.mark.asyncio
async def test_outbound_worker_reuses_frozen_snapshot_without_live_lookup(monkeypatch):
    snapshot = _snapshot(
        account_id=41,
        signature=AccountSignature(
            account_id=41,
            enabled=True,
            include_on_new=True,
            include_on_replies=True,
            include_on_forwards=True,
            body_html="<p>Frozen signature</p>",
            body_text="Frozen signature",
            revision=4,
            sanitizer_version=1,
        ),
        applied=True,
    )
    payload = {
        "to": ["recipient@example.test"],
        "cc": [],
        "bcc": [],
        "subject": "Generated",
        "body_html": "<p>Authored</p>",
        "body_text": "Authored",
        "quoted_html": "<blockquote>Quote</blockquote>",
        "quoted_text": "> Quote",
        "thread_id": None,
        "in_reply_to": None,
        "references": None,
        "attachments": [],
        "signature_snapshot": snapshot,
    }
    outbound = SimpleNamespace(
        id=7,
        send_id=uuid4(),
        user_id=17,
        account_id=41,
        source_email_id=None,
        lease_token=uuid4(),
        rfc_message_id="<mail-generated@example.test>",
        provider_attempted_at=None,
        payload=payload,
    )
    sent = []

    class Gmail:
        async def find_sent_message_by_rfc_message_id(self, *_args, **_kwargs):
            return None

        async def send_email(self, **kwargs):
            sent.append(kwargs)
            return "provider-message"

        def get_refreshed_token(self):
            return None

    async def marked(**_kwargs):
        return True

    async def recorded(**_kwargs):
        return True

    async def no_token(*_args, **_kwargs):
        return None

    monkeypatch.setattr(outbound_module, "_mark_provider_attempt_started", marked)
    monkeypatch.setattr(outbound_module, "_record_outbound_sent", recorded)
    monkeypatch.setattr(outbound_module, "_persist_refreshed_token", no_token)
    await _process_claimed_outbound(outbound, gmail=Gmail())

    assert sent[0]["body_html"].count("Authored") == 1
    assert sent[0]["body_html"].count("Frozen signature") == 1
    assert sent[0]["body_html"].count("Quote") == 1
    assert payload["body_html"] == "<p>Authored</p>"
    assert payload["signature_snapshot"]["policy_revision"] == 4


@pytest.mark.asyncio
async def test_rendered_size_fails_before_draft_or_send_provider_contact(monkeypatch):
    import backend.services.signatures as signatures_module

    monkeypatch.setattr(signatures_module, "MAX_RENDERED_MESSAGE_BYTES", 7)
    provider_calls = []
    failures = []

    class Gmail:
        async def find_sent_message_by_rfc_message_id(self, *_args, **_kwargs):
            provider_calls.append("find")
            return None

        async def send_email(self, **_kwargs):
            provider_calls.append("send")
            return "provider-message"

        async def create_draft_resource(self, **_kwargs):
            provider_calls.append("draft")
            return {"id": "provider-draft"}

        def get_refreshed_token(self):
            return None

    async def outbound_failed(**kwargs):
        failures.append(("outbound", kwargs["disposition"].code))
        return True

    async def draft_failed(**kwargs):
        failures.append(("draft", kwargs["disposition"].code))
        return True

    monkeypatch.setattr(outbound_module, "_record_preflight_failure", outbound_failed)
    monkeypatch.setattr(draft_module, "_record_retry_or_failure", draft_failed)
    payload = {
        "to": ["recipient@example.test"],
        "cc": [],
        "bcc": [],
        "subject": "",
        "body_html": "four",
        "body_text": "four",
        "quoted_html": "",
        "quoted_text": "",
        "attachments": [],
    }
    outbound = SimpleNamespace(
        id=7,
        account_id=41,
        lease_token=uuid4(),
        rfc_message_id="<mail-too-large@example.test>",
        provider_attempted_at=None,
        payload=payload,
    )
    draft = SimpleNamespace(
        account_id=41,
        payload=payload,
    )

    await _process_claimed_outbound(outbound, gmail=Gmail())
    await _process_upsert(draft, gmail=Gmail())

    assert provider_calls == []
    assert failures == [
        ("outbound", "rendered_message_too_large"),
        ("draft", "rendered_message_too_large"),
    ]


@pytest.mark.asyncio
async def test_draft_admission_freezes_snapshot_without_materializing_authored_body(monkeypatch):
    signature = AccountSignature(
        account_id=41,
        enabled=True,
        include_on_new=True,
        include_on_replies=True,
        include_on_forwards=True,
        body_html="<p>Signature</p>",
        body_text="Signature",
        revision=3,
        sanitizer_version=1,
    )
    db = _AdmissionSession(account=_account(), signature=signature)

    async def no_quotas(*_args, **_kwargs):
        return None

    async def no_trim(*_args, **_kwargs):
        return None

    async def no_publish(*_args, **_kwargs):
        return None

    monkeypatch.setattr(draft_module, "_enforce_quotas", no_quotas)
    monkeypatch.setattr(draft_module, "_trim_mutation_receipts", no_trim)
    monkeypatch.setattr(draft_module, "_publish_draft_event", no_publish)
    request = ComposeDraftRequest(
        account_id=41,
        to=["recipient@example.test"],
        body_html="<p>Authored</p>",
        body_text="Authored",
        quoted_html="<blockquote>Quote</blockquote>",
        quoted_text="> Quote",
        composition_kind="forward",
        signature_mode="default",
        client_draft_id=uuid4(),
        revision=1,
        mutation_id=uuid4(),
    )

    draft, created = await stage_draft_upsert(
        db,
        user_id=17,
        request=request,
        now=datetime(2026, 8, 31, 12, 0, tzinfo=timezone.utc),
    )

    assert created is True
    assert draft.payload["body_html"] == "<p>Authored</p>"
    assert draft.payload["body_text"] == "Authored"
    assert draft.payload["quoted_html"] == "<blockquote>Quote</blockquote>"
    assert draft.payload["signature_snapshot"]["policy_revision"] == 3
    assert draft.payload["signature_snapshot"]["applied"] is True
    acknowledgement = compose_router._draft_response(draft, include_signature=True)
    assert acknowledgement.signature_snapshot is not None
    assert acknowledgement.signature_snapshot.policy_revision == 3
    assert compose_router._draft_response(draft).signature_snapshot is None


@pytest.mark.asyncio
async def test_existing_draft_mode_toggles_only_the_frozen_revision(monkeypatch):
    frozen_signature = AccountSignature(
        account_id=41,
        enabled=True,
        include_on_new=True,
        include_on_replies=True,
        include_on_forwards=True,
        body_html="<p>Frozen revision four</p>",
        body_text="Frozen revision four",
        revision=4,
        sanitizer_version=1,
    )
    frozen = _snapshot(account_id=41, signature=frozen_signature, applied=True)
    draft = DraftSession(
        id=81,
        client_draft_id=uuid4(),
        user_id=17,
        account_id=41,
        source_email_id=None,
        source_email_id_snapshot=None,
        source_gmail_thread_id=None,
        source_message_id_header=None,
        source_references_header=None,
        revision=1,
        synced_revision=1,
        payload_hash="a" * 64,
        payload={
            "account_id": 41,
            "to": ["recipient@example.test"],
            "cc": [],
            "bcc": [],
            "subject": "",
            "body_html": "<p>Authored</p>",
            "body_text": "Authored",
            "quoted_html": "",
            "quoted_text": "",
            "composition_kind": "new",
            "signature_mode": "default",
            "signature_snapshot": frozen,
        },
        attachment_count=0,
        attachment_bytes=0,
        rfc_message_id="<draft-frozen@example.test>",
        provider_draft_id="provider-draft",
        provider_message_id="provider-message",
        provider_create_attempted_at=None,
        state="synced",
        next_attempt_at=None,
        attempt_count=0,
        max_attempts=8,
        reconcile_count=0,
    )
    live_signature = AccountSignature(
        account_id=41,
        enabled=True,
        include_on_new=True,
        include_on_replies=True,
        include_on_forwards=True,
        body_html="<p>Live revision five</p>",
        body_text="Live revision five",
        revision=5,
        sanitizer_version=1,
    )
    db = _AdmissionSession(
        account=_account(),
        signature=live_signature,
        existing_draft=draft,
    )

    async def no_op(*_args, **_kwargs):
        return None

    monkeypatch.setattr(draft_module, "_enforce_quotas", no_op)
    monkeypatch.setattr(draft_module, "_trim_mutation_receipts", no_op)
    monkeypatch.setattr(draft_module, "_publish_draft_event", no_op)

    def request(*, revision, mode, kind="new"):
        return ComposeDraftRequest(
            account_id=41,
            to=["recipient@example.test"],
            body_html="<p>Authored</p>",
            body_text="Authored",
            composition_kind=kind,
            signature_mode=mode,
            client_draft_id=draft.client_draft_id,
            revision=revision,
            mutation_id=uuid4(),
        )

    disabled, _created = await stage_draft_upsert(
        db,
        user_id=17,
        request=request(revision=2, mode="disabled"),
    )
    assert disabled.payload["signature_snapshot"]["applied"] is False
    assert disabled.payload["signature_snapshot"]["policy_revision"] == 4
    assert disabled.payload["signature_snapshot"]["body_text"] == "Frozen revision four"

    restored, _created = await stage_draft_upsert(
        db,
        user_id=17,
        request=request(revision=3, mode="enabled"),
    )
    assert restored.payload["signature_snapshot"] == frozen
    assert restored.payload["signature_snapshot"]["policy_revision"] == 4
    assert not any(
        getattr(statement, "column_descriptions", [{}])[0].get("entity") is AccountSignature
        for statement in db.statements
        if getattr(statement, "column_descriptions", None)
    )

    with pytest.raises(DraftValidationError, match="cannot change composition kind"):
        await stage_draft_upsert(
            db,
            user_id=17,
            request=request(revision=4, mode="enabled", kind="forward"),
        )


@pytest.mark.asyncio
async def test_legacy_draft_admission_remains_unsigned(monkeypatch):
    signature = AccountSignature(
        account_id=41,
        enabled=True,
        include_on_new=True,
        include_on_replies=True,
        include_on_forwards=True,
        body_html="<p>Signature</p>",
        body_text="Signature",
        revision=3,
        sanitizer_version=1,
    )
    db = _AdmissionSession(account=_account(), signature=signature)

    async def no_op(*_args, **_kwargs):
        return None

    monkeypatch.setattr(draft_module, "_enforce_quotas", no_op)
    monkeypatch.setattr(draft_module, "_trim_mutation_receipts", no_op)
    monkeypatch.setattr(draft_module, "_publish_draft_event", no_op)
    request = ComposeDraftRequest(
        account_id=41,
        to=["recipient@example.test"],
        body_text="Legacy authored",
        client_draft_id=uuid4(),
        revision=1,
        mutation_id=uuid4(),
    )
    draft, _created = await stage_draft_upsert(db, user_id=17, request=request)
    assert "signature_snapshot" not in draft.payload
    assert not any(
        getattr(statement, "column_descriptions", [{}])[0].get("entity") is AccountSignature
        for statement in db.statements
        if getattr(statement, "column_descriptions", None)
    )


@pytest.mark.asyncio
async def test_linked_outbound_copies_the_draft_snapshot_without_live_resolution(monkeypatch):
    accepted_signature = AccountSignature(
        account_id=41,
        enabled=True,
        include_on_new=True,
        include_on_replies=True,
        include_on_forwards=True,
        body_html="<p>Accepted signature</p>",
        body_text="Accepted signature",
        revision=4,
        sanitizer_version=1,
    )
    frozen = _snapshot(account_id=41, signature=accepted_signature, applied=True)
    newer_signature = AccountSignature(
        account_id=41,
        enabled=True,
        include_on_new=True,
        include_on_replies=True,
        include_on_forwards=True,
        body_html="<p>Newer settings</p>",
        body_text="Newer settings",
        revision=5,
        sanitizer_version=1,
    )
    db = _AdmissionSession(account=_account(), signature=newer_signature)
    client_draft_id = uuid4()
    linked = SimpleNamespace(
        id=71,
        rfc_message_id="<draft-frozen@example.test>",
        payload={"signature_snapshot": frozen},
    )

    async def return_linked(*_args, **_kwargs):
        return linked

    async def return_none(*_args, **_kwargs):
        return None

    async def return_empty(*_args, **_kwargs):
        return []

    monkeypatch.setattr(draft_module, "link_draft_for_outbound_send", return_linked)
    monkeypatch.setattr(outbound_module, "_scrub_expired_retry_payloads", return_empty)
    monkeypatch.setattr(outbound_module, "_enforce_acceptance_quotas", return_none)
    monkeypatch.setattr(outbound_module, "_publish_outbound_event", return_none)
    monkeypatch.setattr(follow_up_module, "resolve_effective_follow_up", return_none)
    monkeypatch.setattr(follow_up_module, "stage_follow_up_intent", return_none)
    request = ComposeRequest(
        account_id=41,
        to=["recipient@example.test"],
        body_text="Authored",
        composition_kind="new",
        signature_mode="default",
        client_draft_id=client_draft_id,
        draft_revision=2,
        idempotency_key=uuid4(),
    )

    outbound, created = await stage_outbound_message(db, user_id=17, request=request)

    assert created is True
    assert outbound.payload["signature_snapshot"] == frozen
    assert outbound.payload["signature_snapshot"]["policy_revision"] == 4
    assert not any(
        getattr(statement, "column_descriptions", [{}])[0].get("entity") is AccountSignature
        for statement in db.statements
        if getattr(statement, "column_descriptions", None)
    )


@pytest.mark.asyncio
async def test_unlinked_outbound_admission_resolves_once_and_replay_keeps_snapshot(monkeypatch):
    signature = AccountSignature(
        account_id=41,
        enabled=True,
        include_on_new=True,
        include_on_replies=True,
        include_on_forwards=True,
        body_html="<p>Accepted signature</p>",
        body_text="Accepted signature",
        revision=5,
        sanitizer_version=1,
    )
    db = _AdmissionSession(account=_account(), signature=signature)

    async def no_scrub(*_args, **_kwargs):
        return []

    async def no_quotas(*_args, **_kwargs):
        return None

    async def no_follow_up(*_args, **_kwargs):
        return None

    async def no_publish(*_args, **_kwargs):
        return None

    monkeypatch.setattr(outbound_module, "_scrub_expired_retry_payloads", no_scrub)
    monkeypatch.setattr(outbound_module, "_enforce_acceptance_quotas", no_quotas)
    monkeypatch.setattr(outbound_module, "_publish_outbound_event", no_publish)
    monkeypatch.setattr(follow_up_module, "resolve_effective_follow_up", no_follow_up)
    monkeypatch.setattr(follow_up_module, "stage_follow_up_intent", no_follow_up)
    request = ComposeRequest(
        account_id=41,
        to=["recipient@example.test"],
        body_html="<p>Authored</p>",
        body_text="Authored",
        composition_kind="new",
        signature_mode="default",
        idempotency_key=uuid4(),
    )
    outbound, created = await stage_outbound_message(db, user_id=17, request=request)
    assert created is True
    assert outbound.payload["body_html"] == "<p>Authored</p>"
    assert outbound.payload["signature_snapshot"]["policy_revision"] == 5

    db.existing_outbound = outbound
    db.account = None
    db.signature = None
    replayed, replay_created = await stage_outbound_message(
        db, user_id=17, request=request
    )
    assert replay_created is False
    assert replayed.payload["signature_snapshot"]["policy_revision"] == 5
