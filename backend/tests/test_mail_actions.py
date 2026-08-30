import asyncio
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

import backend.services.mail_actions as action_module
import backend.services.gmail as gmail_module
import backend.services.sync as sync_module
from backend.models.email import Email
from backend.models.mail_action import MailAction
from backend.schemas.email import EmailActionRequest
from backend.services.mail_actions import (
    ACTION_LABEL_DELTAS,
    ErrorDisposition,
    MailActionConflict,
    MailActionNotFound,
    _claim_due_actions,
    _record_action_failure,
    _record_action_success,
    action_payload_hash,
    apply_mail_state,
    canonical_mail_state,
    classify_mail_action_error,
    drain_due_mail_actions,
    get_mail_action_operation_by_idempotency,
    recent_mail_action_operations,
    retry_delay,
    retry_mail_action_operation,
    stage_mail_actions,
    state_after_action,
    undo_mail_action_operation,
)
from backend.services.sync import EmailSyncService
from backend.services.gmail import GmailService
from backend.workers.tasks import CronWorkerSettings, drain_mail_actions_task


NOW = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)


class _Scalars:
    def __init__(self, values):
        self.values = values

    def all(self):
        return list(self.values)


class _Result:
    def __init__(self, *, values=None, value=None, rows=None):
        self.values = values or []
        self.value = value
        self.rows = rows or []

    def scalars(self):
        return _Scalars(self.values)

    def scalar_one_or_none(self):
        return self.value

    def scalar_one(self):
        return self.value

    def all(self):
        return list(self.rows)


class _StageSession:
    def __init__(self, emails):
        self.emails = emails
        self.added = []
        self.statements = []
        self.commit_count = 0

    async def execute(self, statement, *_args):
        self.statements.append(statement)
        return _Result(values=self.emails)

    def add(self, value):
        self.added.append(value)

    async def flush(self):
        for index, action in enumerate(self.added, start=1):
            action.id = index

    async def commit(self):
        self.commit_count += 1


def _email(
    email_id: int,
    *,
    account_id: int = 1,
    labels=None,
    is_read: bool = False,
    is_starred: bool = False,
    is_trash: bool = False,
    is_spam: bool = False,
) -> Email:
    return Email(
        id=email_id,
        account_id=account_id,
        gmail_message_id=f"generated-{account_id}-{email_id}",
        gmail_thread_id=f"thread-{email_id}",
        labels=list(labels or ["INBOX", "UNREAD"]),
        is_read=is_read,
        is_starred=is_starred,
        is_trash=is_trash,
        is_spam=is_spam,
        mail_action_version=0,
    )


def _action(
    email: Email,
    *,
    request_id=None,
    idempotency_key=None,
    state="staged",
    sequence=1,
    action="archive",
    before_state=None,
    after_state=None,
) -> MailAction:
    before = before_state or canonical_mail_state(["INBOX", "UNREAD"])
    after = after_state or canonical_mail_state(["UNREAD"])
    return MailAction(
        id=(email.id * 100) + sequence,
        request_id=request_id or uuid4(),
        idempotency_key=idempotency_key or uuid4(),
        payload_hash=action_payload_hash([email.id], action),
        user_id=9,
        account_id=email.account_id,
        email_id=email.id,
        gmail_message_id=email.gmail_message_id,
        sequence=sequence,
        chain_start_sequence=1,
        action=action,
        base_state=before,
        before_state=before,
        after_state=after,
        add_labels=list(ACTION_LABEL_DELTAS[action][0]),
        remove_labels=list(ACTION_LABEL_DELTAS[action][1]),
        state=state,
        execute_after=NOW + timedelta(seconds=10),
        undo_until=NOW + timedelta(seconds=10),
        next_attempt_at=NOW + timedelta(seconds=10),
        attempt_count=0,
        max_attempts=8,
        created_at=NOW,
        updated_at=NOW,
    )


@pytest.mark.parametrize("action", sorted(ACTION_LABEL_DELTAS))
def test_every_supported_action_produces_consistent_labels_and_flags(action):
    before = canonical_mail_state(
        ["INBOX", "UNREAD", "STARRED", "custom"],
        is_read=False,
        is_starred=True,
        is_trash=False,
        is_spam=False,
    )
    after, add_labels, remove_labels = state_after_action(before, action)

    assert set(add_labels).isdisjoint(remove_labels)
    assert after["is_read"] == ("UNREAD" not in after["labels"])
    assert after["is_starred"] == ("STARRED" in after["labels"])
    assert after["is_trash"] == ("TRASH" in after["labels"])
    assert after["is_spam"] == ("SPAM" in after["labels"])
    assert "custom" in after["labels"]


def test_action_request_requires_positive_unique_strict_ids_and_known_action():
    with pytest.raises(ValidationError):
        EmailActionRequest(email_ids=[1, 1], action="archive")
    with pytest.raises(ValidationError):
        EmailActionRequest(email_ids=[0], action="archive")
    with pytest.raises(ValidationError):
        EmailActionRequest(email_ids=[True], action="archive")
    with pytest.raises(ValidationError):
        EmailActionRequest(email_ids=[1], action="move")


def test_gmail_service_builds_finite_httplib2_transport_for_mutations(monkeypatch):
    credentials = object()
    raw_transport = object()
    authorized_transport = object()
    built_service = object()
    captured = {}

    def make_transport(*, timeout):
        captured["timeout"] = timeout
        return raw_transport

    def authorize(received_credentials, *, http):
        captured["credentials"] = received_credentials
        captured["raw_transport"] = http
        return authorized_transport

    def build_service(api, version, **kwargs):
        captured["build"] = (api, version, kwargs)
        return built_service

    monkeypatch.setattr(gmail_module.httplib2, "Http", make_transport)
    monkeypatch.setattr(gmail_module, "AuthorizedHttp", authorize)
    monkeypatch.setattr(gmail_module, "build", build_service)

    gmail = GmailService(
        SimpleNamespace(email="generated@example.test"),
        transport_timeout=17.5,
    )
    monkeypatch.setattr(gmail, "_get_credentials", lambda: credentials)

    assert gmail._get_service() is built_service
    assert captured["timeout"] == 17.5
    assert captured["credentials"] is credentials
    assert captured["raw_transport"] is raw_transport
    assert captured["build"] == (
        "gmail",
        "v1",
        {"http": authorized_transport, "cache_discovery": False},
    )
    assert gmail._get_service() is built_service


def test_gmail_service_rejects_nonpositive_transport_timeout():
    with pytest.raises(ValueError, match="transport timeout"):
        GmailService(SimpleNamespace(email="generated@example.test"), transport_timeout=0)


@pytest.mark.asyncio
async def test_stage_bulk_is_atomic_cross_account_and_applies_optimistic_state(monkeypatch):
    emails = [_email(11, account_id=2), _email(10, account_id=1)]
    db = _StageSession(emails)

    async def no_lock(*_args, **_kwargs):
        return None

    async def no_existing(*_args, **_kwargs):
        return []

    async def no_publish(*_args, **_kwargs):
        return None

    monkeypatch.setattr(action_module, "_lock_idempotency_key", no_lock)
    monkeypatch.setattr(action_module, "_actions_for_idempotency", no_existing)
    monkeypatch.setattr(action_module, "_publish_action_event", no_publish)

    idempotency_key = uuid4()
    actions, created = await stage_mail_actions(
        db,
        user_id=9,
        email_ids=[11, 10],
        action="archive",
        idempotency_key=idempotency_key,
        now=NOW,
    )

    assert created is True
    assert db.commit_count == 1
    assert len(actions) == 2
    assert {action.account_id for action in actions} == {1, 2}
    assert len({action.request_id for action in actions}) == 1
    assert all(action.idempotency_key == idempotency_key for action in actions)
    assert all(action.state == "staged" for action in actions)
    assert all(action.execute_after == NOW + timedelta(seconds=10) for action in actions)
    assert all("INBOX" not in email.labels for email in emails)
    assert all(email.mail_action_version == 1 for email in emails)
    compiled = str(db.statements[0])
    assert "ORDER BY emails.id" in compiled
    assert "FOR UPDATE" in compiled


@pytest.mark.asyncio
async def test_stage_rejects_mixed_owned_or_missing_ids_without_mutation(monkeypatch):
    db = _StageSession([_email(10)])

    async def no_lock(*_args, **_kwargs):
        return None

    async def no_existing(*_args, **_kwargs):
        return []

    monkeypatch.setattr(action_module, "_lock_idempotency_key", no_lock)
    monkeypatch.setattr(action_module, "_actions_for_idempotency", no_existing)

    with pytest.raises(MailActionNotFound, match="One or more emails"):
        await stage_mail_actions(
            db,
            user_id=9,
            email_ids=[10, 99],
            action="trash",
            idempotency_key=uuid4(),
            now=NOW,
        )

    assert db.added == []
    assert db.commit_count == 0
    assert db.emails[0].is_trash is False


@pytest.mark.asyncio
async def test_repeated_idempotency_returns_exact_operation_and_mismatch_conflicts(monkeypatch):
    email = _email(10)
    key = uuid4()
    existing = _action(email, idempotency_key=key)
    db = _StageSession([])

    async def no_lock(*_args, **_kwargs):
        return None

    async def existing_actions(*_args, **_kwargs):
        return [existing]

    monkeypatch.setattr(action_module, "_lock_idempotency_key", no_lock)
    monkeypatch.setattr(action_module, "_actions_for_idempotency", existing_actions)

    actions, created = await stage_mail_actions(
        db,
        user_id=9,
        email_ids=[10],
        action="archive",
        idempotency_key=key,
        now=NOW,
    )
    assert actions == [existing]
    assert created is False
    assert db.commit_count == 0

    with pytest.raises(MailActionConflict, match="another payload"):
        await stage_mail_actions(
            db,
            user_id=9,
            email_ids=[10],
            action="trash",
            idempotency_key=key,
            now=NOW,
        )


@pytest.mark.asyncio
async def test_owned_idempotency_lookup_returns_exact_operation_or_404():
    email = _email(10)
    key = uuid4()
    action = _action(email, idempotency_key=key)
    found_db = _SequenceSession([_Result(values=[action])])

    result = await get_mail_action_operation_by_idempotency(
        found_db,
        user_id=action.user_id,
        idempotency_key=key,
    )

    assert result == [action]
    statement = str(found_db.statements[0])
    assert "mail_actions.user_id" in statement
    assert "mail_actions.idempotency_key" in statement

    missing_db = _SequenceSession([_Result()])
    with pytest.raises(MailActionNotFound, match="Mail action not found"):
        await get_mail_action_operation_by_idempotency(
            missing_db,
            user_id=action.user_id + 1,
            idempotency_key=key,
        )


@pytest.mark.asyncio
async def test_recent_operations_prioritize_bounded_unresolved_failures():
    recent_email = _email(10)
    failed_email = _email(11)
    recent = _action(recent_email, state="applied")
    failed = _action(failed_email, state="failed")
    recent.created_at = NOW
    failed.created_at = NOW - timedelta(days=30)
    db = _SequenceSession([
        _Result(rows=[
            SimpleNamespace(request_id=failed.request_id),
            SimpleNamespace(request_id=recent.request_id),
        ]),
        _Result(values=[recent, failed]),
    ])

    operations = await recent_mail_action_operations(db, user_id=9, limit=20)

    assert operations == [[failed], [recent]]
    visible_query = str(db.statements[0])
    assert "CASE WHEN (mail_actions.state" in visible_query
    assert "ORDER BY" in visible_query
    assert "DESC" in visible_query
    assert "LIMIT" in visible_query


class _SequenceSession:
    def __init__(self, results):
        self.results = list(results)
        self.statements = []
        self.commit_count = 0

    async def execute(self, statement, *_args):
        self.statements.append(statement)
        return self.results.pop(0)

    async def commit(self):
        self.commit_count += 1


@pytest.mark.asyncio
async def test_staged_bulk_undo_restores_exact_snapshots_all_or_none(monkeypatch):
    request_id = uuid4()
    first = _email(10, labels=["INBOX", "UNREAD", "custom"])
    second = _email(11, labels=["INBOX", "STARRED"], is_read=True, is_starred=True)
    first.mail_action_version = second.mail_action_version = 1
    first_before = canonical_mail_state(["INBOX", "UNREAD", "custom"])
    second_before = canonical_mail_state(["INBOX", "STARRED"])
    actions = [
        _action(first, request_id=request_id, before_state=first_before),
        _action(second, request_id=request_id, before_state=second_before),
    ]
    apply_mail_state(first, actions[0].after_state)
    apply_mail_state(second, actions[1].after_state)
    db = _SequenceSession([
        _Result(values=[first, second]),
        _Result(value=False),
        _Result(values=[actions[0]]),
        _Result(value=False),
        _Result(values=[actions[1]]),
    ])

    async def get_actions(*_args, **_kwargs):
        return actions

    async def no_publish(*_args, **_kwargs):
        return None

    monkeypatch.setattr(action_module, "get_mail_action_operation", get_actions)
    monkeypatch.setattr(action_module, "_publish_action_event", no_publish)

    result = await undo_mail_action_operation(
        db,
        user_id=9,
        request_id=request_id,
        now=NOW,
    )

    assert result == actions
    assert all(action.state == "cancelled" for action in actions)
    assert first.labels == ["INBOX", "UNREAD", "custom"]
    assert second.labels == ["INBOX", "STARRED"]
    assert db.commit_count == 1
    assert "FROM emails" in str(db.statements[0])
    assert "FOR UPDATE" in str(db.statements[0])


@pytest.mark.asyncio
async def test_bulk_undo_rejects_if_any_item_started_without_restoring(monkeypatch):
    first = _email(10)
    second = _email(11)
    actions = [_action(first), _action(second, state="processing")]
    db = _SequenceSession([_Result(values=[first, second])])

    async def get_actions(*_args, **_kwargs):
        return actions

    monkeypatch.setattr(action_module, "get_mail_action_operation", get_actions)
    with pytest.raises(MailActionConflict, match="already started"):
        await undo_mail_action_operation(
            db,
            user_id=9,
            request_id=actions[0].request_id,
            now=NOW,
        )
    assert actions[0].state == "staged"
    assert db.commit_count == 0


@pytest.mark.asyncio
async def test_retry_only_failed_subset_reapplies_intent_and_resets_attempts(monkeypatch):
    request_id = uuid4()
    applied_email = _email(10)
    failed_email = _email(11)
    failed_email.mail_action_version = 1
    applied = _action(applied_email, request_id=request_id, state="applied")
    failed = _action(failed_email, request_id=request_id, state="failed")
    failed.attempt_count = 8
    apply_mail_state(failed_email, failed.before_state)
    db = _SequenceSession([
        _Result(value=False),
        _Result(values=[failed_email]),
        _Result(value=False),
        _Result(values=[failed]),
    ])

    async def get_actions(*_args, **_kwargs):
        return [applied, failed]

    async def no_publish(*_args, **_kwargs):
        return None

    monkeypatch.setattr(action_module, "get_mail_action_operation", get_actions)
    monkeypatch.setattr(action_module, "_publish_action_event", no_publish)

    actions = await retry_mail_action_operation(
        db,
        user_id=9,
        request_id=request_id,
        now=NOW,
    )
    assert actions == [applied, failed]
    assert applied.state == "applied"
    assert failed.state == "retry_wait"
    assert failed.attempt_count == 0
    assert failed.next_attempt_at == NOW
    assert failed_email.labels == failed.after_state["labels"]
    assert db.commit_count == 1
    assert "FROM email_snoozes" in str(db.statements[0])
    assert "FROM emails" in str(db.statements[1])
    assert "FOR UPDATE" in str(db.statements[1])


@pytest.mark.asyncio
async def test_claim_uses_lease_and_skip_locked_oldest_per_email():
    email = _email(10)
    action = _action(email)
    db = _SequenceSession([_Result(), _Result(), _Result(values=[action])])

    actions = await _claim_due_actions(
        db,
        account_id=1,
        now=NOW + timedelta(seconds=20),
        limit=50,
    )

    assert actions == [action]
    assert action.state == "processing"
    assert action.attempt_count == 1
    assert action.lease_token is not None
    assert action.lease_expires_at == NOW + timedelta(seconds=140)
    assert db.commit_count == 1


@pytest.mark.asyncio
async def test_orphaned_active_actions_fail_and_emit_operation_update():
    request_id = uuid4()
    db = _SequenceSession([
        _Result(rows=[SimpleNamespace(user_id=9, request_id=request_id)]),
    ])

    notifications = await action_module._terminalize_orphaned_actions(
        db,
        account_id=1,
        now=NOW,
    )

    assert notifications == {(9, request_id)}
    statement = str(db.statements[0])
    assert "UPDATE mail_actions" in statement
    assert "mail_actions.email_id IS NULL" in statement
    assert "RETURNING mail_actions.user_id, mail_actions.request_id" in statement


@pytest.mark.asyncio
async def test_gmail_success_persists_canonical_state_without_erasing_newer_intent(monkeypatch):
    email = _email(10, labels=["INBOX", "UNREAD"])
    action = _action(email, state="processing")
    action.lease_token = uuid4()
    email.mail_action_version = 2
    newer = _action(
        email,
        state="staged",
        sequence=2,
        action="star",
        before_state=action.after_state,
    )
    newer.base_state = action.base_state
    newer.chain_start_sequence = action.chain_start_sequence
    newer_state = canonical_mail_state(["UNREAD", "STARRED"])
    apply_mail_state(email, newer_state)
    db = _SequenceSession([
        _Result(value=action),
        _Result(value=email),
        _Result(value=action),
        _Result(values=[action, newer]),
    ])

    async def no_publish(*_args, **_kwargs):
        return None

    monkeypatch.setattr(action_module, "async_session", lambda: _Context(db))
    monkeypatch.setattr(action_module, "_publish_action_event", no_publish)

    assert await _record_action_success(
        action_id=action.id,
        lease_token=action.lease_token,
        gmail_result={"labelIds": ["UNREAD"], "historyId": "123"},
        now=NOW,
    ) is True
    assert action.state == "applied"
    assert action.after_state == canonical_mail_state(["UNREAD"])
    assert action.gmail_history_id == "123"
    assert email.labels == newer_state["labels"]
    assert db.commit_count == 1
    assert "FROM emails" in str(db.statements[1])
    assert "FOR UPDATE" in str(db.statements[1])
    assert "FROM mail_actions" in str(db.statements[2])
    assert "FOR UPDATE" in str(db.statements[2])


@pytest.mark.asyncio
async def test_terminal_failure_restores_exact_state_only_for_current_sequence(monkeypatch):
    email = _email(10, labels=["UNREAD"])
    email.mail_action_version = 1
    before = canonical_mail_state(["INBOX", "UNREAD", "custom"])
    action = _action(email, state="processing", before_state=before)
    action.lease_token = uuid4()
    action.attempt_count = action.max_attempts
    db = _SequenceSession([
        _Result(value=action),
        _Result(value=email),
        _Result(value=action),
        _Result(values=[action]),
    ])

    async def no_publish(*_args, **_kwargs):
        return None

    monkeypatch.setattr(action_module, "async_session", lambda: _Context(db))
    monkeypatch.setattr(action_module, "_publish_action_event", no_publish)

    assert await _record_action_failure(
        action_id=action.id,
        lease_token=action.lease_token,
        disposition=ErrorDisposition(False, "gmail_400", "Gmail rejected the mail action"),
        now=NOW,
    ) is True
    assert action.state == "failed"
    assert action.error_code == "gmail_400"
    assert email.labels == ["INBOX", "UNREAD", "custom"]
    assert db.commit_count == 1


@pytest.mark.asyncio
async def test_terminal_failure_does_not_resurrect_later_cancelled_intent(monkeypatch):
    base = canonical_mail_state(["INBOX", "UNREAD", "generated-external"])
    email = _email(10, labels=["UNREAD", "STARRED"])
    action = _action(email, state="processing", before_state=base)
    action.lease_token = uuid4()
    action.attempt_count = action.max_attempts
    cancelled = _action(
        email,
        state="cancelled",
        sequence=2,
        action="star",
        before_state=action.after_state,
    )
    cancelled.base_state = base
    cancelled.chain_start_sequence = 1
    db = _SequenceSession([
        _Result(value=action),
        _Result(value=email),
        _Result(value=action),
        _Result(values=[action, cancelled]),
    ])

    async def no_publish(*_args, **_kwargs):
        return None

    monkeypatch.setattr(action_module, "async_session", lambda: _Context(db))
    monkeypatch.setattr(action_module, "_publish_action_event", no_publish)

    assert await _record_action_failure(
        action_id=action.id,
        lease_token=action.lease_token,
        disposition=ErrorDisposition(False, "gmail_400", "Gmail rejected the mail action"),
        now=NOW,
    ) is True
    assert action.state == "failed"
    assert cancelled.state == "cancelled"
    assert email.labels == ["INBOX", "UNREAD", "generated-external"]


@pytest.mark.asyncio
async def test_expired_lease_retries_only_below_attempt_limit():
    email = _email(10, labels=["UNREAD"])
    action = _action(email, state="processing")
    action.attempt_count = action.max_attempts - 1
    action.lease_token = uuid4()
    action.lease_expires_at = NOW - timedelta(seconds=1)
    db = _SequenceSession([
        _Result(values=[action]),
        _Result(values=[email]),
        _Result(values=[action]),
    ])

    notifications = await action_module._reclaim_expired_leases(
        db,
        account_id=email.account_id,
        now=NOW,
    )

    assert notifications == {(action.user_id, action.request_id)}
    assert action.state == "retry_wait"
    assert action.next_attempt_at == NOW
    assert action.lease_token is None
    assert action.lease_expires_at is None
    assert action.error_code == "lease_expired"
    assert "FROM emails" in str(db.statements[1])
    assert "FOR UPDATE" in str(db.statements[1])
    assert "FROM mail_actions" in str(db.statements[2])
    assert "FOR UPDATE" in str(db.statements[2])


@pytest.mark.asyncio
async def test_expired_lease_at_attempt_limit_fails_and_reconciles_projection():
    before = canonical_mail_state(["INBOX", "UNREAD", "generated-external"])
    email = _email(10, labels=["UNREAD"])
    action = _action(
        email,
        state="processing",
        before_state=before,
    )
    action.attempt_count = action.max_attempts
    action.lease_token = uuid4()
    action.lease_expires_at = NOW - timedelta(seconds=1)
    db = _SequenceSession([
        _Result(values=[action]),
        _Result(values=[email]),
        _Result(values=[action]),
        _Result(values=[action]),
    ])

    notifications = await action_module._reclaim_expired_leases(
        db,
        account_id=email.account_id,
        now=NOW,
    )

    assert notifications == {(action.user_id, action.request_id)}
    assert action.state == "failed"
    assert action.next_attempt_at is None
    assert action.lease_token is None
    assert action.lease_expires_at is None
    assert action.error_code == "lease_attempts_exhausted"
    assert action.failed_at == NOW
    assert email.labels == ["INBOX", "UNREAD", "generated-external"]


class _HttpError(Exception):
    def __init__(self, status, message="generated private upstream detail"):
        super().__init__(message)
        self.resp = SimpleNamespace(status=status)


@pytest.mark.parametrize(
    "error,retryable,code",
    [
        (_HttpError(400), False, "gmail_400"),
        (_HttpError(401), False, "gmail_401"),
        (_HttpError(404), False, "gmail_404"),
        (_HttpError(403, "generated quota limit"), True, "gmail_403_rate_limit"),
        (_HttpError(429), True, "gmail_429"),
        (_HttpError(503), True, "gmail_503"),
        (TimeoutError("generated private upstream detail"), True, "gmail_transport"),
        (RuntimeError("generated private upstream detail"), True, "gmail_unknown"),
    ],
)
def test_error_classification_is_bounded_and_never_stores_upstream_text(error, retryable, code):
    disposition = classify_mail_action_error(error)
    assert disposition.retryable is retryable
    assert disposition.code == code
    assert str(error) not in disposition.message
    assert retry_delay(1) == timedelta(seconds=15)
    assert retry_delay(100) == timedelta(minutes=15)


class _Context(AbstractAsyncContextManager):
    def __init__(self, value):
        self.value = value

    async def __aenter__(self):
        return self.value

    async def __aexit__(self, exc_type, exc, traceback):
        return False


@pytest.mark.asyncio
async def test_action_status_publication_returns_after_redis_deadline(monkeypatch):
    cancelled = asyncio.Event()

    async def stalled_publish(*_args, **_kwargs):
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    import backend.services.notifications as notifications_module

    monkeypatch.setattr(notifications_module, "publish_event", stalled_publish)
    monkeypatch.setattr(action_module, "MAIL_ACTION_REDIS_IO_TIMEOUT_SECONDS", 0.01)

    await asyncio.wait_for(
        action_module._publish_action_event(9, uuid4()),
        timeout=0.2,
    )
    await asyncio.wait_for(cancelled.wait(), timeout=0.2)


@pytest.mark.asyncio
async def test_mail_action_enqueue_returns_after_redis_connect_deadline(monkeypatch):
    cancelled = asyncio.Event()

    async def stalled_create_pool(*_args, **_kwargs):
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    monkeypatch.setattr(action_module, "create_pool", stalled_create_pool)
    monkeypatch.setattr(action_module, "MAIL_ACTION_REDIS_IO_TIMEOUT_SECONDS", 0.01)

    await asyncio.wait_for(action_module.try_enqueue_mail_action_drain(), timeout=0.2)
    await asyncio.wait_for(cancelled.wait(), timeout=0.2)


@pytest.mark.asyncio
async def test_drainer_uses_one_gmail_attempt_and_shared_account_lock(monkeypatch):
    email = _email(10)
    action = _action(email)
    action.lease_token = uuid4()
    calls = []
    claim_batches = [[action]]

    class Gmail:
        async def modify_labels(self, message_id, add_labels, remove_labels, *, max_retries):
            calls.append((message_id, add_labels, remove_labels, max_retries))
            return {"id": message_id, "labelIds": ["UNREAD"]}

        def get_refreshed_token(self):
            return None

    account_session = SimpleNamespace(
        execute=lambda *_args, **_kwargs: None,
    )

    async def execute_account(_statement):
        return _Result(value=SimpleNamespace(id=1))

    account_session.execute = execute_account

    @asynccontextmanager
    async def acquired_lock(account_id):
        assert account_id == 1
        yield True

    async def due_accounts(_now):
        # The global job budget must stop before visiting the second account.
        return [1, 2]

    async def credentials(_db):
        return ("generated-client", "generated-secret")

    async def claim(_db, **_kwargs):
        assert _kwargs["limit"] == 1
        return claim_batches.pop(0)

    async def record_success(**kwargs):
        calls.append(("success", kwargs["action_id"], kwargs["lease_token"]))
        return True

    monkeypatch.setattr(action_module, "_due_account_ids", due_accounts)
    monkeypatch.setattr(action_module, "MAIL_ACTION_DRAIN_MAX_ACTIONS", 1)
    monkeypatch.setattr(action_module, "account_advisory_lock", acquired_lock)
    monkeypatch.setattr(action_module, "async_session", lambda: _Context(account_session))
    monkeypatch.setattr(action_module, "get_google_credentials", credentials)
    def gmail_factory(*_args, **kwargs):
        assert kwargs["transport_timeout"] == (
            action_module.MAIL_ACTION_GMAIL_TRANSPORT_TIMEOUT_SECONDS
        )
        return Gmail()

    monkeypatch.setattr(action_module, "GmailService", gmail_factory)
    monkeypatch.setattr(action_module, "_claim_due_actions", claim)
    monkeypatch.setattr(action_module, "_record_action_success", record_success)

    assert await drain_due_mail_actions() == 1
    assert calls[0] == (email.gmail_message_id, [], ["INBOX"], 1)
    assert calls[1] == ("success", action.id, action.lease_token)


@pytest.mark.asyncio
async def test_cancelled_notification_publication_closes_redis_client(monkeypatch):
    import backend.services.notifications as notifications_module

    publishing = asyncio.Event()
    closed = asyncio.Event()

    class Redis:
        async def publish(self, *_args, **_kwargs):
            publishing.set()
            await asyncio.Event().wait()

        async def aclose(self):
            closed.set()

    def redis_factory(*_args, **kwargs):
        assert kwargs["socket_connect_timeout"] == 1
        assert kwargs["socket_timeout"] == 1
        return Redis()

    monkeypatch.setattr(notifications_module.aioredis, "from_url", redis_factory)
    task = asyncio.create_task(notifications_module.publish_event(9, "generated"))
    await publishing.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert closed.is_set()


@pytest.mark.asyncio
async def test_drainer_durably_records_credential_setup_failure(monkeypatch):
    email = _email(10)
    action = _action(email, state="processing")
    action.lease_token = uuid4()
    claim_batches = [[action]]
    recorded = []

    class Session:
        async def execute(self, _statement):
            return _Result(value=SimpleNamespace(id=email.account_id))

    @asynccontextmanager
    async def acquired_lock(account_id):
        assert account_id == email.account_id
        yield True

    async def claim(_db, **_kwargs):
        return claim_batches.pop(0)

    async def credentials(_db):
        raise RuntimeError("generated credential setup failure")

    async def record_failure(**kwargs):
        recorded.append(kwargs)
        return True

    monkeypatch.setattr(action_module, "account_advisory_lock", acquired_lock)
    monkeypatch.setattr(action_module, "async_session", lambda: _Context(Session()))
    monkeypatch.setattr(action_module, "_claim_due_actions", claim)
    monkeypatch.setattr(action_module, "get_google_credentials", credentials)
    monkeypatch.setattr(action_module, "_record_action_failure", record_failure)

    assert await action_module._drain_account_mail_actions(email.account_id) == 1
    assert len(recorded) == 1
    assert recorded[0]["action_id"] == action.id
    assert recorded[0]["lease_token"] == action.lease_token
    assert recorded[0]["disposition"].retryable is True
    assert recorded[0]["disposition"].code == "gmail_unknown"


@pytest.mark.asyncio
async def test_sync_overlay_rebases_pending_chain_on_fresh_gmail_state():
    email = _email(10, labels=["INBOX", "UNREAD", "generated-external"])
    first = _action(
        email,
        state="staged",
        before_state=canonical_mail_state(["INBOX", "UNREAD"]),
    )
    second = _action(
        email,
        state="retry_wait",
        sequence=2,
        action="star",
        before_state=first.after_state,
    )
    db = _SequenceSession([_Result(values=[first, second])])

    assert await action_module.overlay_active_mail_actions(db, email=email) is True
    fresh_base = canonical_mail_state(["INBOX", "UNREAD", "generated-external"])
    assert first.base_state == fresh_base
    assert first.before_state == fresh_base
    assert first.after_state == canonical_mail_state(["UNREAD", "generated-external"])
    assert second.base_state == fresh_base
    assert second.before_state == first.after_state
    assert second.after_state == canonical_mail_state(
        ["UNREAD", "STARRED", "generated-external"]
    )
    assert email.labels == ["STARRED", "UNREAD", "generated-external"]


@pytest.mark.asyncio
async def test_sync_upsert_overlays_newest_active_action(monkeypatch):
    service = EmailSyncService(account_id=1)
    email = _email(10, labels=["INBOX", "UNREAD"])

    class Session:
        def __init__(self):
            self.statements = []

        async def execute(self, statement):
            self.statements.append(statement)
            return _Result(value=email)

    async def overlay(_db, *, email):
        apply_mail_state(email, canonical_mail_state(["UNREAD", "STARRED"]))
        return True

    monkeypatch.setattr(sync_module, "overlay_active_mail_actions", overlay)
    db = Session()
    email_id, is_new = await service._upsert_email(
        db,
        {
            "gmail_message_id": email.gmail_message_id,
            "gmail_thread_id": email.gmail_thread_id,
            "labels": ["INBOX", "UNREAD"],
            "is_read": False,
            "is_starred": False,
            "is_trash": False,
            "is_spam": False,
            "attachments": [],
        },
    )
    assert (email_id, is_new) == (10, False)
    assert email.labels == ["STARRED", "UNREAD"]
    assert email.is_starred is True
    assert "INBOX" not in email.labels
    assert "FOR UPDATE" in str(db.statements[0])


def test_worker_registers_database_sweeper_on_cron_queue():
    assert drain_mail_actions_task in CronWorkerSettings.functions
    assert any(job.coroutine is drain_mail_actions_task for job in CronWorkerSettings.cron_jobs)
