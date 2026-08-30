from datetime import datetime, timedelta, timezone
import logging
from types import SimpleNamespace
from uuid import uuid4

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi import HTTPException
from googleapiclient.errors import HttpError
from pydantic import ValidationError

import backend.services.gmail as gmail_module
import backend.services.outbound_messages as outbound_module
from backend.database import engine
from backend.models.outbound_message import OUTBOUND_MESSAGE_STATES, OutboundMessage
from backend.routers.compose import _raise_outbound_http_error, router
from backend.schemas.email import ComposeRequest, OutboundSendResponse
from backend.services.gmail import GmailService
from backend.services.outbound_messages import (
    OUTBOUND_UNDO_SECONDS,
    OUTBOUND_RETRY_PAYLOAD_RETENTION_SECONDS,
    OutboundErrorDisposition,
    OutboundMessagePersistenceError,
    OutboundMessageQuotaExceeded,
    _fail_outbound,
    _process_claimed_outbound,
    _record_preflight_failure,
    _record_reconciling_locked,
    drain_due_outbound_messages,
    outbound_can_retry,
    outbound_can_cancel,
    outbound_scheduled_for,
    outbound_payload_hash,
    stage_outbound_message,
    undo_outbound_message,
)
from backend.workers.tasks import CronWorkerSettings, drain_outbound_messages_task


NOW = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)


def _request(**overrides):
    values = {
        "account_id": 7,
        "to": ["recipient@example.test"],
        "subject": "Generated message",
        "body_text": "Generated content",
        "idempotency_key": uuid4(),
    }
    values.update(overrides)
    return ComposeRequest(**values)


def _outbound(*, attempted=False, payload=None):
    send_id = uuid4()
    return SimpleNamespace(
        id=41,
        send_id=send_id,
        user_id=5,
        account_id=7,
        lease_token=uuid4(),
        rfc_message_id=f"<mail-{send_id}@email.mcchord.net>",
        provider_attempted_at=NOW if attempted else None,
        execute_after=NOW + timedelta(seconds=OUTBOUND_UNDO_SECONDS),
        undo_until=NOW + timedelta(seconds=OUTBOUND_UNDO_SECONDS),
        draft_session_id=None,
        retry_authorized=False,
        retry_expires_at=None,
        payload=payload if payload is not None else {
            "to": ["recipient@example.test"],
            "cc": [],
            "bcc": [],
            "subject": "Generated message",
            "body_html": "",
            "body_text": "Generated content",
            "in_reply_to": None,
            "references": None,
            "thread_id": None,
            "attachments": [],
        },
    )


def test_compose_request_normalizes_and_bounds_sensitive_payload():
    request = _request(to=['"Doe, Jane" <Jane@Example.test>'])
    assert request.to == ['"Doe, Jane" <jane@example.test>']

    with pytest.raises(ValidationError, match="unique across"):
        _request(to=["same@example.test"], cc=["Same <same@example.test>"])
    with pytest.raises(ValidationError, match="newlines"):
        _request(subject="safe\r\nBcc: injected@example.test")
    with pytest.raises(ValidationError, match="at least one To"):
        _request(to=[])
    with pytest.raises(ValidationError, match="valid base64"):
        _request(attachments=[{
            "filename": "generated.bin",
            "content_type": "application/octet-stream",
            "data_base64": "not base64!",
        }])


def test_compose_request_normalizes_an_absolute_schedule_and_requires_a_durable_draft():
    client_draft_id = uuid4()
    request = _request(
        client_draft_id=client_draft_id,
        draft_revision=3,
        scheduled_for="2026-08-31T09:00:00-04:00",
        schedule_timezone="America/New_York",
    )
    assert request.scheduled_for == datetime(2026, 8, 31, 13, 0, tzinfo=timezone.utc)

    with pytest.raises(ValidationError, match="timezone-aware"):
        _request(
            client_draft_id=client_draft_id,
            draft_revision=3,
            scheduled_for="2026-08-31T09:00:00",
        )
    with pytest.raises(ValidationError, match="safely saved draft"):
        _request(scheduled_for="2026-08-31T13:00:00Z")
    with pytest.raises(ValidationError, match="Schedule timezone requires"):
        _request(schedule_timezone="America/New_York")
    with pytest.raises(ValidationError, match="exact source email"):
        _request(archive_source_after_send=True)


def test_payload_hash_ignores_idempotency_key_but_covers_content():
    first = _request(idempotency_key=uuid4())
    same = _request(idempotency_key=uuid4())
    changed = _request(idempotency_key=uuid4(), subject="Changed")

    assert outbound_payload_hash(first) == outbound_payload_hash(same)
    assert outbound_payload_hash(first) != outbound_payload_hash(changed)
    scheduled = _request(
        client_draft_id=uuid4(),
        draft_revision=1,
        scheduled_for="2026-08-31T13:00:00Z",
        schedule_timezone="America/New_York",
    )
    rescheduled = scheduled.model_copy(update={
        "idempotency_key": uuid4(),
        "scheduled_for": datetime(2026, 9, 1, 13, 0, tzinfo=timezone.utc),
    })
    assert outbound_payload_hash(scheduled) != outbound_payload_hash(rescheduled)


def test_outbound_model_and_routes_expose_complete_state_contract():
    state_constraint = next(
        constraint
        for constraint in OutboundMessage.__table__.constraints
        if constraint.name == "ck_outbound_messages_state"
    )
    for state in OUTBOUND_MESSAGE_STATES:
        assert state in str(state_constraint.sqltext)

    route_contract = {
        (route.path, method)
        for route in router.routes
        for method in route.methods
    }
    assert ("/api/compose/send", "POST") in route_contract
    assert ("/api/compose/sends/recent", "GET") in route_contract
    assert ("/api/compose/sends/scheduled", "GET") in route_contract
    assert ("/api/compose/sends/by-idempotency/{idempotency_key}", "GET") in route_contract
    assert ("/api/compose/sends/{send_id}", "GET") in route_contract
    assert ("/api/compose/sends/{send_id}/undo", "POST") in route_contract
    assert ("/api/compose/sends/{send_id}/cancel", "POST") in route_contract
    assert ("/api/compose/sends/{send_id}/send-now", "POST") in route_contract
    assert ("/api/compose/sends/{send_id}/retry", "POST") in route_contract
    send_route = next(route for route in router.routes if route.path == "/api/compose/send")
    assert send_route.status_code == 202
    assert "payload" not in OutboundSendResponse.model_fields


def test_scheduled_send_metadata_and_actionability_are_deadline_bound():
    outbound = _outbound()
    outbound.state = "staged"
    outbound.created_at = NOW
    outbound.undo_until = NOW + timedelta(seconds=OUTBOUND_UNDO_SECONDS)
    outbound.execute_after = NOW + timedelta(hours=2)
    outbound.payload["scheduled_for"] = outbound.execute_after.isoformat()
    outbound.payload["schedule_timezone"] = "America/New_York"

    assert outbound_scheduled_for(outbound) == outbound.execute_after
    assert outbound_can_cancel(outbound, now=NOW + timedelta(hours=1)) is True
    assert outbound_can_cancel(outbound, now=outbound.execute_after) is False
    assert "retry_authorized" not in OutboundSendResponse.model_fields
    index_names = {index.name for index in OutboundMessage.__table__.indexes}
    assert {
        "ix_outbound_messages_account_created",
        "ix_outbound_messages_user_capacity",
        "ix_outbound_messages_account_capacity",
        "ix_outbound_messages_retry_expiry",
    } <= index_names
    constraint_names = {
        constraint.name for constraint in OutboundMessage.__table__.constraints
    }
    assert "ck_outbound_messages_retry_authorized" in constraint_names
    assert "ck_outbound_messages_failed_payload" in constraint_names
    assert "ck_outbound_messages_retry_expiry" in constraint_names


def test_outbound_migration_is_immediate_post_c0_head():
    config = Config()
    config.set_main_option("script_location", "alembic")
    scripts = ScriptDirectory.from_config(config)
    revision = scripts.get_revision("d1e2f3a4b5c6")
    assert revision.down_revision == "c0d1e2f3a4b5"
    assert scripts.get_revision("f3a4b5c6d7e8").down_revision == "e2f3a4b5c6d7"
    assert scripts.get_heads() == ["f3a4b5c6d7e8"]


def test_ten_second_undo_and_cron_worker_recovery_contract():
    assert OUTBOUND_UNDO_SECONDS == 10
    assert drain_outbound_messages_task in CronWorkerSettings.functions
    assert any(job.coroutine is drain_outbound_messages_task for job in CronWorkerSettings.cron_jobs)


def test_database_engine_hides_bound_parameters():
    assert engine.sync_engine.hide_parameters is True


def test_quota_and_persistence_errors_map_to_safe_retryable_http_responses():
    with pytest.raises(HTTPException) as quota_info:
        _raise_outbound_http_error(
            OutboundMessageQuotaExceeded(
                "Too many sends were accepted recently. Try again shortly.",
                retry_after_seconds=17,
            )
        )
    assert quota_info.value.status_code == 429
    assert quota_info.value.headers == {"Retry-After": "17"}
    assert quota_info.value.detail["code"] == "outbound_rate_limited"

    with pytest.raises(HTTPException) as persistence_info:
        _raise_outbound_http_error(
            OutboundMessagePersistenceError("sensitive database detail")
        )
    assert persistence_info.value.status_code == 503
    assert persistence_info.value.headers == {"Retry-After": "5"}
    assert "sensitive" not in str(persistence_info.value.detail)


@pytest.mark.asyncio
async def test_staging_failure_rolls_back_without_logging_payload_or_parameters(caplog):
    secret = "generated-sensitive-body-never-log"

    class Db:
        rollback_count = 0

        async def execute(self, *_args, **_kwargs):
            raise RuntimeError(f"driver parameters included {secret}")

        async def rollback(self):
            self.rollback_count += 1

    db = Db()
    caplog.set_level(logging.ERROR, logger=outbound_module.__name__)

    with pytest.raises(OutboundMessagePersistenceError) as error_info:
        await stage_outbound_message(
            db,
            user_id=5,
            request=_request(body_text=secret),
            now=NOW,
        )

    assert db.rollback_count == 1
    assert str(error_info.value) == "Send could not be accepted right now"
    assert secret not in caplog.text
    assert "driver parameters" not in caplog.text


def test_terminal_failure_scrubs_unless_server_authorizes_safe_preflight_retry():
    non_retryable = _outbound()
    non_retryable.state = "processing"
    non_retryable.next_attempt_at = NOW
    non_retryable.failed_at = None
    _fail_outbound(non_retryable, now=NOW, retry_authorized=False)
    assert non_retryable.state == "failed"
    assert non_retryable.payload is None
    assert non_retryable.retry_authorized is False
    assert non_retryable.retry_expires_at is None
    assert outbound_can_retry(non_retryable, now=NOW) is False

    retryable = _outbound()
    retryable.state = "processing"
    retryable.next_attempt_at = NOW
    retryable.failed_at = None
    _fail_outbound(retryable, now=NOW, retry_authorized=True)
    assert retryable.payload is not None
    assert retryable.retry_authorized is True
    assert retryable.retry_expires_at == NOW + timedelta(
        seconds=OUTBOUND_RETRY_PAYLOAD_RETENTION_SECONDS
    )
    assert outbound_can_retry(retryable, now=NOW) is True
    assert outbound_can_retry(retryable, now=retryable.retry_expires_at) is False

    attempted = _outbound(attempted=True)
    attempted.state = "processing"
    attempted.next_attempt_at = NOW
    attempted.failed_at = None
    _fail_outbound(attempted, now=NOW, retry_authorized=True)
    assert attempted.payload is None
    assert attempted.retry_authorized is False
    assert attempted.retry_expires_at is None
    assert outbound_can_retry(attempted, now=NOW) is False


@pytest.mark.asyncio
async def test_non_retryable_preflight_and_exhausted_reconciliation_scrub_payload(monkeypatch):
    async def no_publish(*_args, **_kwargs):
        return None

    monkeypatch.setattr(outbound_module, "_publish_outbound_event", no_publish)

    preflight = _outbound()
    preflight.state = "processing"
    preflight.attempt_count = 1
    preflight.max_attempts = 8
    preflight.next_attempt_at = None
    preflight.failed_at = None
    preflight.error_code = None
    preflight.error_message = None
    preflight.updated_at = NOW
    preflight.lease_expires_at = NOW

    class Result:
        def scalar_one_or_none(self):
            return preflight

    class Db:
        commit_count = 0

        async def execute(self, *_args, **_kwargs):
            return Result()

        async def commit(self):
            self.commit_count += 1

    db = Db()

    class SessionContext:
        async def __aenter__(self):
            return db

        async def __aexit__(self, *_args):
            return False

    monkeypatch.setattr(outbound_module, "async_session", lambda: SessionContext())

    await _record_preflight_failure(
        outbound_id=preflight.id,
        lease_token=preflight.lease_token,
        disposition=OutboundErrorDisposition(
            False,
            "gmail_authorization",
            "The sending account needs attention",
        ),
        now=NOW,
    )
    assert preflight.state == "failed"
    assert preflight.payload is None
    assert preflight.retry_authorized is False

    restored_draft = SimpleNamespace(user_id=5, client_draft_id=uuid4())
    restore_calls = []

    async def restore_scheduled_draft(*_args, **kwargs):
        restore_calls.append(kwargs)
        return restored_draft

    async def no_draft_publish(*_args, **_kwargs):
        return None

    import backend.services.drafts as drafts_module

    monkeypatch.setattr(
        drafts_module,
        "restore_linked_draft_after_outbound_cancel",
        restore_scheduled_draft,
    )
    monkeypatch.setattr(drafts_module, "publish_draft_session_event", no_draft_publish)
    monkeypatch.setattr(drafts_module, "try_enqueue_draft_drain", no_draft_publish)

    scheduled = _outbound()
    scheduled.state = "processing"
    scheduled.attempt_count = 1
    scheduled.max_attempts = 8
    scheduled.next_attempt_at = None
    scheduled.failed_at = None
    scheduled.error_code = None
    scheduled.error_message = None
    scheduled.updated_at = NOW
    scheduled.lease_expires_at = NOW
    scheduled.draft_session_id = 81
    scheduled.execute_after = NOW
    scheduled.undo_until = NOW + timedelta(seconds=OUTBOUND_UNDO_SECONDS)
    scheduled.payload["scheduled_for"] = (NOW + timedelta(hours=1)).isoformat()
    scheduled.payload["schedule_timezone"] = "America/New_York"
    preflight = scheduled

    await _record_preflight_failure(
        outbound_id=scheduled.id,
        lease_token=scheduled.lease_token,
        disposition=OutboundErrorDisposition(
            False,
            "gmail_authorization",
            "The sending account needs attention",
        ),
        now=NOW,
    )
    assert scheduled.state == "failed"
    assert scheduled.payload is None
    assert scheduled.draft_session_id is None
    assert restore_calls == [{
        "user_id": scheduled.user_id,
        "draft_session_id": 81,
        "send_id": scheduled.send_id,
        "now": NOW,
    }]

    reconciling = _outbound(attempted=True)
    reconciling.state = "processing"
    reconciling.reconcile_count = outbound_module.OUTBOUND_RECONCILE_MAX_CHECKS - 1
    reconciling.next_attempt_at = None
    reconciling.failed_at = None
    reconciling.error_code = None
    reconciling.error_message = None
    reconciling.updated_at = NOW
    reconciling.lease_expires_at = NOW
    await _record_reconciling_locked(
        db,
        outbound=reconciling,
        now=NOW,
        provider_confirmed_absent=True,
    )
    assert reconciling.state == "failed"
    assert reconciling.payload is None
    assert reconciling.retry_authorized is False
    assert reconciling.retry_expires_at is None


@pytest.mark.asyncio
async def test_cron_drain_scrubs_retry_payloads_before_claiming_due_work(monkeypatch):
    events = []

    async def scrub():
        events.append("scrub")
        return 1

    async def due(_now):
        events.append("due")
        return []

    monkeypatch.setattr(outbound_module, "scrub_expired_retry_payloads", scrub)
    monkeypatch.setattr(outbound_module, "_due_account_ids", due)

    assert await drain_due_outbound_messages() == 0
    assert events == ["scrub", "due"]


@pytest.mark.asyncio
async def test_undo_scrubs_sensitive_payload(monkeypatch):
    outbound = _outbound()
    outbound.state = "staged"
    outbound.undo_until = NOW + timedelta(seconds=10)
    outbound.next_attempt_at = outbound.undo_until
    outbound.cancelled_at = None
    outbound.updated_at = NOW
    outbound.error_code = "old"
    outbound.error_message = "old"

    class Db:
        commit_count = 0

        async def commit(self):
            self.commit_count += 1

    db = Db()

    async def get_owned(*_args, **_kwargs):
        return outbound

    async def no_publish(*_args, **_kwargs):
        return None

    monkeypatch.setattr(outbound_module, "get_outbound_message", get_owned)
    monkeypatch.setattr(outbound_module, "_publish_outbound_event", no_publish)

    result = await undo_outbound_message(
        db,
        user_id=outbound.user_id,
        send_id=outbound.send_id,
        now=NOW,
    )

    assert result.state == "cancelled"
    assert result.payload is None
    assert result.next_attempt_at is None
    assert result.error_code is None
    assert result.error_message is None
    assert db.commit_count == 1


def test_gmail_message_contains_stable_rfc_message_id():
    service = GmailService(SimpleNamespace(email="sender@example.test"))
    message_id = "<mail-generated@example.test>"
    message = service._build_compose_message(
        to=["recipient@example.test"],
        body_text="Generated",
        message_id_header=message_id,
    )
    assert message["Message-ID"] == message_id

    with pytest.raises(ValueError, match="Message-ID"):
        service._build_compose_message(
            to=["recipient@example.test"],
            message_id_header="bad\r\nBcc: injected@example.test",
        )


class _GmailSearchCapture:
    def __init__(self):
        self.kwargs = None

    def users(self):
        return self

    def messages(self):
        return self

    def list(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace()


@pytest.mark.asyncio
async def test_gmail_reconciliation_uses_sent_rfc822_message_id_search(monkeypatch):
    service = GmailService(SimpleNamespace(email="sender@example.test"))
    capture = _GmailSearchCapture()

    async def execute(_request, **kwargs):
        assert kwargs["context"] == "find_sent_message_by_rfc_message_id"
        assert kwargs["max_retries"] == 1
        return {"messages": [{"id": "provider-generated"}]}

    monkeypatch.setattr(service, "_get_service", lambda: capture)
    monkeypatch.setattr(service, "_execute_with_retry", execute)

    found = await service.find_sent_message_by_rfc_message_id(
        "<mail-generated@example.test>",
        max_retries=1,
    )
    assert found == "provider-generated"
    assert capture.kwargs == {
        "userId": "me",
        "labelIds": ["SENT"],
        "q": "rfc822msgid:mail-generated@example.test",
        "maxResults": 10,
    }


class _GmailSendCapture:
    def __init__(self):
        self.send_calls = 0
        self.execute_calls = 0

    def users(self):
        return self

    def messages(self):
        return self

    def send(self, **_kwargs):
        self.send_calls += 1
        return self

    def execute(self):
        self.execute_calls += 1
        response = SimpleNamespace(status=404, reason="Not Found")
        raise HttpError(response, b'{"error":{"message":"generated"}}')


@pytest.mark.asyncio
async def test_durable_max_retries_one_never_executes_thread_fallback(monkeypatch):
    service = GmailService(SimpleNamespace(email="sender@example.test"))
    capture = _GmailSendCapture()

    async def acquire(_cost):
        return None

    monkeypatch.setattr(service, "_get_service", lambda: capture)
    monkeypatch.setattr(gmail_module.gmail_rate_limiter, "acquire", acquire)

    with pytest.raises(HttpError):
        await service.send_email(
            to=["recipient@example.test"],
            thread_id="generated-thread",
            max_retries=1,
        )

    assert capture.send_calls == 1
    assert capture.execute_calls == 1


@pytest.mark.asyncio
async def test_first_send_marks_provider_attempt_before_call(monkeypatch):
    outbound = _outbound()
    order = []
    sent = {}

    class Gmail:
        async def find_sent_message_by_rfc_message_id(self, *_args, **_kwargs):
            order.append("lookup")
            return None

        async def send_email(self, **kwargs):
            order.append("send")
            sent.update(kwargs)
            return "provider-generated"

        def get_refreshed_token(self):
            return None

    async def mark(**_kwargs):
        order.append("mark")
        return True

    async def record_sent(**kwargs):
        order.append("record")
        assert kwargs["provider_message_id"] == "provider-generated"
        return True

    async def no_token(*_args, **_kwargs):
        return None

    monkeypatch.setattr(outbound_module, "_mark_provider_attempt_started", mark)
    monkeypatch.setattr(outbound_module, "_record_outbound_sent", record_sent)
    monkeypatch.setattr(outbound_module, "_persist_refreshed_token", no_token)

    await _process_claimed_outbound(outbound, gmail=Gmail())

    assert order == ["lookup", "mark", "send", "record"]
    assert sent["message_id_header"] == outbound.rfc_message_id
    assert sent["max_retries"] == 1


@pytest.mark.asyncio
async def test_ambiguous_provider_failure_enters_reconciliation_without_replay(monkeypatch):
    outbound = _outbound()
    reconciliations = []

    class Gmail:
        async def find_sent_message_by_rfc_message_id(self, *_args, **_kwargs):
            return None

        async def send_email(self, **_kwargs):
            raise TimeoutError("sensitive provider detail")

        def get_refreshed_token(self):
            return None

    async def mark(**_kwargs):
        return True

    async def reconcile(**kwargs):
        reconciliations.append(kwargs)
        return True

    async def no_token(*_args, **_kwargs):
        return None

    monkeypatch.setattr(outbound_module, "_mark_provider_attempt_started", mark)
    monkeypatch.setattr(outbound_module, "_record_reconciling", reconcile)
    monkeypatch.setattr(outbound_module, "_persist_refreshed_token", no_token)

    await _process_claimed_outbound(outbound, gmail=Gmail())

    assert len(reconciliations) == 1
    assert "sensitive provider detail" not in str(reconciliations)


@pytest.mark.asyncio
async def test_previously_attempted_absence_never_calls_send(monkeypatch):
    outbound = _outbound(attempted=True)
    reconciliations = []

    class Gmail:
        async def find_sent_message_by_rfc_message_id(self, *_args, **_kwargs):
            return None

        async def send_email(self, **_kwargs):
            raise AssertionError("an attempted send must never be replayed")

        def get_refreshed_token(self):
            return None

    async def reconcile(**kwargs):
        reconciliations.append(kwargs)
        return True

    async def no_token(*_args, **_kwargs):
        return None

    monkeypatch.setattr(outbound_module, "_record_reconciling", reconcile)
    monkeypatch.setattr(outbound_module, "_persist_refreshed_token", no_token)

    await _process_claimed_outbound(outbound, gmail=Gmail())

    assert len(reconciliations) == 1
    assert reconciliations[0]["provider_confirmed_absent"] is True


@pytest.mark.asyncio
async def test_empty_provider_id_is_ambiguous_not_sent(monkeypatch):
    outbound = _outbound()
    events = []

    class Gmail:
        async def find_sent_message_by_rfc_message_id(self, *_args, **_kwargs):
            return None

        async def send_email(self, **_kwargs):
            return ""

        def get_refreshed_token(self):
            return None

    async def mark(**_kwargs):
        return True

    async def reconcile(**_kwargs):
        events.append("reconcile")
        return True

    async def sent(**_kwargs):
        events.append("sent")
        return True

    async def no_token(*_args, **_kwargs):
        return None

    monkeypatch.setattr(outbound_module, "_mark_provider_attempt_started", mark)
    monkeypatch.setattr(outbound_module, "_record_reconciling", reconcile)
    monkeypatch.setattr(outbound_module, "_record_outbound_sent", sent)
    monkeypatch.setattr(outbound_module, "_persist_refreshed_token", no_token)

    await _process_claimed_outbound(outbound, gmail=Gmail())

    assert events == ["reconcile"]
