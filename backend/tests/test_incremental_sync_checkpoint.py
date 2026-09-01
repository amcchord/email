from contextlib import AbstractAsyncContextManager, asynccontextmanager
from types import SimpleNamespace

import pytest
from googleapiclient.errors import HttpError

import backend.services.gmail as gmail_module
import backend.services.sync as sync_module
from backend.services.gmail import GmailMessageNotFound, GmailService
from backend.services.sync import (
    EmailSyncService,
    FullSyncCheckpointConflict,
    FullSyncCheckpoint,
    IncrementalSyncCheckpointConflict,
    _decode_full_sync_checkpoint,
    _encode_full_sync_checkpoint,
)


def _message(message_id: str) -> dict:
    """Return deterministic generated Gmail data; no mailbox access is used."""
    return {"id": message_id}


def _history_result() -> dict:
    return {
        "history": [
            {
                "id": "101",
                "messagesAdded": [{"message": {"id": "message-a"}}],
            },
            {
                "id": "102",
                "messagesAdded": [{"message": {"id": "message-b"}}],
            },
        ],
        "new_history_id": "102",
    }


class _Result:
    def __init__(self, value=None, *, rows=None, rowcount=None):
        self.value = value
        self.rows = rows or []
        self.rowcount = rowcount

    def scalar_one_or_none(self):
        return self.value

    def scalar_one(self):
        return self.value

    def all(self):
        return self.rows


class _NestedTransaction(AbstractAsyncContextManager):
    async def __aexit__(self, exc_type, exc, traceback):
        return False


class _FakeSession:
    def __init__(self, state):
        self.state = state
        self.staged = {}
        self.staged_deletes = set()
        self.staged_status = {}

    async def execute(self, statement, *_args):
        if getattr(statement, "is_update", False):
            params = statement.compile().params
            is_checkpoint_commit = "last_history_id" in params
            if is_checkpoint_commit and self.state.cas_conflicts_remaining:
                self.state.cas_conflicts_remaining -= 1
                self.state.sync_status.last_history_id = (
                    self.state.cas_conflict_history_id
                )
                self.state.sync_status.status = "completed"
                return _Result(rowcount=0)
            is_full_checkpoint_update = "sync_page_token" in params
            if is_full_checkpoint_update and self.state.full_conflicts_remaining:
                self.state.full_conflicts_remaining -= 1
                self.state.sync_status.sync_page_token = (
                    self.state.full_conflict_checkpoint
                )
                if self.state.full_conflict_history_id is not None:
                    self.state.sync_status.last_history_id = (
                        self.state.full_conflict_history_id
                    )
                self.state.sync_status.status = "completed"
                return _Result(rowcount=0)
            self.staged_status.update(params)
            return _Result(rowcount=1)
        if "FROM emails" in str(statement):
            params = statement.compile().params
            message_id = next(
                (
                    value
                    for key, value in params.items()
                    if key.startswith("gmail_message_id_")
                ),
                None,
            )
            if message_id is not None:
                email_id = self.state.emails.get(message_id)
                value = (
                    SimpleNamespace(id=email_id, gmail_message_id=message_id)
                    if email_id is not None
                    else None
                )
                return _Result(value)
        return _Result(self.state.sync_status)

    def begin_nested(self):
        return _NestedTransaction()

    async def commit(self):
        for message_id in self.staged_deletes:
            self.state.emails.pop(message_id, None)
        self.staged_deletes.clear()
        self.state.emails.update(self.staged)
        self.staged.clear()
        for key in (
            "last_history_id",
            "last_incremental_sync",
            "status",
            "current_phase",
            "sync_page_token",
            "messages_synced",
            "total_messages",
            "last_full_sync",
            "completed_at",
        ):
            if key in self.staged_status:
                setattr(self.state.sync_status, key, self.staged_status[key])
        self.staged_status.clear()

    async def delete(self, email):
        self.staged_deletes.add(email.gmail_message_id)

    async def scalar(self, _statement):
        return len(self.state.emails) + len(self.staged) - len(self.staged_deletes)

    async def flush(self):
        return None


class _SessionContext(AbstractAsyncContextManager):
    def __init__(self, state):
        self.session = _FakeSession(state)

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, exc_type, exc, traceback):
        if exc_type is not None:
            self.session.staged.clear()
            self.session.staged_deletes.clear()
            self.session.staged_status.clear()
        return False


class _State:
    def __init__(self):
        self.sync_status = SimpleNamespace(
            last_history_id="100",
            sync_page_token=None,
            rate_limit_count=0,
            status="completed",
            messages_synced=0,
            total_messages=0,
        )
        self.emails = {}
        self.next_email_id = 1
        self.cas_conflicts_remaining = 0
        self.cas_conflict_history_id = "200"
        self.full_conflicts_remaining = 0
        self.full_conflict_checkpoint = None
        self.full_conflict_history_id = None
        self.upsert_calls = []


class _FakeGmail:
    def __init__(self, batch_results, history_result=None):
        self.batch_results = list(batch_results)
        self.history_result = history_result or _history_result()
        self.requested_batches = []

    async def get_history(self, start_history_id, max_retries):
        assert start_history_id == "100"
        assert max_retries == 1
        return self.history_result

    async def batch_get_messages(self, message_ids):
        self.requested_batches.append(list(message_ids))
        return self.batch_results.pop(0)

    def get_refreshed_token(self):
        return None


class _FakeFullSyncGmail:
    def __init__(self, batch_result):
        self.batch_result = batch_result
        self.list_page_tokens = []
        self.requested_batches = []

    async def list_message_ids(self, page_token=None):
        self.list_page_tokens.append(page_token)
        return (
            [{"id": "message-a"}, {"id": "message-b"}],
            "next-page",
            2,
        )

    async def batch_get_messages(self, message_ids):
        self.requested_batches.append(list(message_ids))
        return self.batch_result

    def get_refreshed_token(self):
        return None


class _ResumableFullSyncGmail:
    def __init__(self):
        self.page_ids = [f"message-{index:03d}" for index in range(101)]
        self.requested_batches = []
        self.tail_attempts = 0

    async def list_message_ids(self, page_token=None):
        if page_token == "next-page":
            raise RuntimeError("generated stop after page checkpoint")
        assert page_token == "current-page"
        return ([{"id": message_id} for message_id in self.page_ids], "next-page", 101)

    async def batch_get_messages(self, message_ids):
        self.requested_batches.append(list(message_ids))
        if len(message_ids) == 1:
            self.tail_attempts += 1
            if self.tail_attempts == 1:
                return []
        return [_message(message_id) for message_id in message_ids]

    def get_refreshed_token(self):
        return None


class _FullFlowGmail:
    def __init__(
        self,
        *,
        pages=None,
        history_results=None,
        profile_history_ids=None,
        batch_results=None,
        list_error=None,
    ):
        self.pages = pages or {None: ([], None, 0)}
        self.history_results = list(history_results or [])
        self.profile_history_ids = list(profile_history_ids or [])
        self.batch_results = list(batch_results or [])
        self.list_error = list_error
        self.list_page_tokens = []
        self.history_baselines = []
        self.requested_batches = []
        self.profile_calls = 0

    async def get_profile_history_id(self):
        self.profile_calls += 1
        return self.profile_history_ids.pop(0)

    async def list_message_ids(self, page_token=None):
        self.list_page_tokens.append(page_token)
        if self.list_error:
            raise RuntimeError(self.list_error)
        message_ids, next_page, estimate = self.pages[page_token]
        return ([{"id": message_id} for message_id in message_ids], next_page, estimate)

    async def batch_get_messages(self, message_ids):
        self.requested_batches.append(list(message_ids))
        if self.batch_results:
            return self.batch_results.pop(0)
        return [_message(message_id) for message_id in message_ids]

    async def get_history(self, baseline, max_retries):
        self.history_baselines.append(baseline)
        assert max_retries == 1
        return self.history_results.pop(0)

    def get_refreshed_token(self):
        return None


def _build_service(monkeypatch, state, gmail, *, fail_once_on=None):
    service = EmailSyncService(account_id=7)

    monkeypatch.setattr(sync_module, "async_session", lambda: _SessionContext(state))
    monkeypatch.setattr(
        GmailService,
        "parse_message",
        staticmethod(lambda message: {"gmail_message_id": message["id"]}),
    )

    async def get_account(_db):
        return SimpleNamespace(id=7)

    async def create_gmail_service(_db, _account):
        return gmail

    async def update_sync_status(db, **kwargs):
        for key, value in kwargs.items():
            setattr(state.sync_status, key, value)
        await db.commit()

    failures_remaining = {fail_once_on} if fail_once_on else set()

    async def upsert_email(db, parsed):
        message_id = parsed["gmail_message_id"]
        state.upsert_calls.append(message_id)
        if message_id in failures_remaining:
            failures_remaining.remove(message_id)
            raise ValueError("generated processing failure")

        existing_id = db.staged.get(message_id) or state.emails.get(message_id)
        if existing_id:
            return existing_id, False

        email_id = state.next_email_id
        state.next_email_id += 1
        db.staged[message_id] = email_id
        return email_id, True

    async def skip_unsubscribe_tracking(_db):
        return None

    async def skip_sync_labels():
        return None

    @asynccontextmanager
    async def acquired_lock():
        yield True

    monkeypatch.setattr(service, "_account_sync_lock", acquired_lock)
    monkeypatch.setattr(service, "_get_account", get_account)
    monkeypatch.setattr(service, "_create_gmail_service", create_gmail_service)
    monkeypatch.setattr(service, "_update_sync_status", update_sync_status)
    monkeypatch.setattr(service, "_upsert_email", upsert_email)
    monkeypatch.setattr(service, "_update_unsubscribe_tracking", skip_unsubscribe_tracking)
    monkeypatch.setattr(service, "sync_labels", skip_sync_labels)
    return service


def _scan_checkpoint(page_token: str | None) -> str:
    return _encode_full_sync_checkpoint(FullSyncCheckpoint(
        baseline_history_id="100",
        phase="scan",
        page_token=page_token,
    ))


def _replay_checkpoint(baseline: str = "100") -> str:
    return _encode_full_sync_checkpoint(FullSyncCheckpoint(
        baseline_history_id=baseline,
        phase="replay",
    ))


class _GeneratedBatchRequest:
    def __init__(self, outcomes):
        self.outcomes = outcomes
        self.requests = []

    def add(self, request, *, request_id, callback):
        self.requests.append((request, request_id, callback))

    def execute(self):
        for request, request_id, callback in self.requests:
            outcome = self.outcomes[request["id"]]
            if isinstance(outcome, Exception):
                callback(request_id, None, outcome)
            else:
                callback(request_id, outcome, None)


class _GeneratedBatchApi:
    def __init__(self, outcomes):
        self.outcomes = outcomes
        self.batch = None

    def users(self):
        return self

    def messages(self):
        return self

    def get(self, **kwargs):
        return kwargs

    def new_batch_http_request(self):
        self.batch = _GeneratedBatchRequest(self.outcomes)
        return self.batch


def _generated_http_error(status: int) -> HttpError:
    response = SimpleNamespace(status=status, reason="Generated")
    return HttpError(response, b'{"error":{"message":"generated"}}')


@pytest.mark.asyncio
async def test_batch_get_resolves_404_as_tombstone_but_omits_retryable_errors(
    monkeypatch,
):
    gmail = GmailService(SimpleNamespace(email="generated@example.test"))
    api = _GeneratedBatchApi({
        "message-live": _message("message-live"),
        "message-gone": _generated_http_error(404),
        "message-retry": _generated_http_error(503),
    })

    async def acquire(_cost):
        return None

    monkeypatch.setattr(gmail, "_get_service", lambda: api)
    monkeypatch.setattr(gmail_module.gmail_rate_limiter, "acquire", acquire)
    monkeypatch.setattr(gmail_module, "BATCH_PAUSE", 0)

    result = await gmail.batch_get_messages([
        "message-live",
        "message-gone",
        "message-retry",
    ])

    assert result == [
        _message("message-live"),
        GmailMessageNotFound("message-gone"),
    ]


@pytest.mark.asyncio
async def test_partial_batch_does_not_advance_checkpoint_and_retry_converges(monkeypatch):
    state = _State()
    gmail = _FakeGmail([
        [_message("message-a")],
        [_message("message-b"), _message("message-a")],
    ])
    service = _build_service(monkeypatch, state, gmail)

    with pytest.raises(RuntimeError, match="missing 1"):
        await service.incremental_sync()

    assert state.sync_status.last_history_id == "100"
    assert state.emails == {}
    assert state.sync_status.status == "error"

    new_email_ids = await service.incremental_sync()

    assert new_email_ids == [1, 2]
    assert state.sync_status.last_history_id == "102"
    assert state.sync_status.status == "completed"
    assert set(state.emails) == {"message-a", "message-b"}
    assert gmail.requested_batches == [
        ["message-a", "message-b"],
        ["message-a", "message-b"],
    ]


@pytest.mark.asyncio
async def test_incremental_404_tombstone_deletes_local_row_and_advances_checkpoint(
    monkeypatch,
):
    state = _State()
    state.emails = {"message-a": 1}
    state.next_email_id = 2
    gmail = _FakeGmail([[
        GmailMessageNotFound("message-a"),
        _message("message-b"),
    ]])
    service = _build_service(monkeypatch, state, gmail)

    new_email_ids = await service.incremental_sync()

    assert new_email_ids == [2]
    assert state.emails == {"message-b": 2}
    assert state.upsert_calls == ["message-b"]
    assert state.sync_status.last_history_id == "102"
    assert state.sync_status.status == "completed"


@pytest.mark.asyncio
async def test_404_tombstone_waits_for_complete_incremental_batch(monkeypatch):
    state = _State()
    state.emails = {"message-a": 1}
    state.next_email_id = 2
    gmail = _FakeGmail([[
        GmailMessageNotFound("message-a"),
    ]])
    service = _build_service(monkeypatch, state, gmail)

    with pytest.raises(RuntimeError, match="missing 1"):
        await service.incremental_sync()

    assert state.emails == {"message-a": 1}
    assert state.upsert_calls == []
    assert state.sync_status.last_history_id == "100"
    assert state.sync_status.status == "error"


@pytest.mark.asyncio
async def test_message_processing_failure_rolls_back_and_retries_without_duplicates(monkeypatch):
    state = _State()
    gmail = _FakeGmail([
        [_message("message-a"), _message("message-b")],
        [_message("message-a"), _message("message-b")],
    ])
    service = _build_service(
        monkeypatch,
        state,
        gmail,
        fail_once_on="message-b",
    )

    with pytest.raises(RuntimeError, match="changed message could not be processed"):
        await service.incremental_sync()

    assert state.sync_status.last_history_id == "100"
    assert state.emails == {}

    new_email_ids = await service.incremental_sync()

    assert new_email_ids == [2, 3]
    assert state.sync_status.last_history_id == "102"
    assert set(state.emails) == {"message-a", "message-b"}
    assert len(state.emails) == 2


@pytest.mark.asyncio
async def test_incremental_checkpoint_compare_and_swap_conflict_rolls_back(monkeypatch):
    state = _State()
    state.cas_conflicts_remaining = 1
    gmail = _FakeGmail([
        [_message("message-a"), _message("message-b")],
    ])
    service = _build_service(monkeypatch, state, gmail)

    with pytest.raises(IncrementalSyncCheckpointConflict):
        await service.incremental_sync()

    assert state.sync_status.last_history_id == "200"
    assert state.emails == {}
    assert state.sync_status.status == "completed"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "candidate, error_pattern",
    [
        ("99", "cannot move backwards"),
        ("not-a-history-id", "must be numeric"),
    ],
)
async def test_incremental_rejects_invalid_checkpoint_candidates(
    monkeypatch,
    candidate,
    error_pattern,
):
    state = _State()
    history_result = _history_result()
    history_result["new_history_id"] = candidate
    gmail = _FakeGmail(
        [[_message("message-a"), _message("message-b")]],
        history_result=history_result,
    )
    service = _build_service(monkeypatch, state, gmail)

    with pytest.raises(RuntimeError, match=error_pattern):
        await service.incremental_sync()

    assert state.sync_status.last_history_id == "100"
    assert state.emails == {}


@pytest.mark.asyncio
async def test_empty_history_advances_authoritative_high_water_without_mail_fetch(monkeypatch):
    state = _State()
    gmail = _FakeGmail(
        [],
        history_result={"history": [], "new_history_id": "150"},
    )
    service = _build_service(monkeypatch, state, gmail)

    assert await service.incremental_sync() == []

    assert state.sync_status.last_history_id == "150"
    assert gmail.requested_batches == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "batch_result, error_pattern",
    [
        ([_message("message-a")], "missing 1"),
        ([_message("message-a"), {}], "duplicate or malformed 1"),
    ],
)
async def test_full_sync_does_not_save_next_page_for_incomplete_batch(
    monkeypatch,
    batch_result,
    error_pattern,
):
    state = _State()
    state.sync_status.sync_page_token = _scan_checkpoint("current-page")
    gmail = _FakeFullSyncGmail(batch_result)
    service = _build_service(monkeypatch, state, gmail)

    with pytest.raises(RuntimeError, match=error_pattern):
        await service.full_sync()

    assert state.sync_status.sync_page_token == _scan_checkpoint("current-page")
    assert state.emails == {}
    assert gmail.list_page_tokens == ["current-page"]
    assert gmail.requested_batches == [["message-a", "message-b"]]


@pytest.mark.asyncio
async def test_full_sync_processing_failure_does_not_save_next_page(monkeypatch):
    state = _State()
    state.sync_status.sync_page_token = _scan_checkpoint("current-page")
    gmail = _FakeFullSyncGmail([
        _message("message-a"),
        _message("message-b"),
    ])
    service = _build_service(
        monkeypatch,
        state,
        gmail,
        fail_once_on="message-b",
    )

    with pytest.raises(RuntimeError, match="requested message could not be processed"):
        await service.full_sync()

    assert state.sync_status.sync_page_token == _scan_checkpoint("current-page")
    assert state.emails == {}


@pytest.mark.asyncio
async def test_full_sync_404_tombstone_deletes_stale_row_and_completes(monkeypatch):
    state = _State()
    state.sync_status.sync_page_token = _scan_checkpoint(None)
    state.emails = {"message-a": 1, "message-b": 2}
    state.next_email_id = 3
    gmail = _FullFlowGmail(
        pages={None: (["message-a", "message-b"], None, 2)},
        batch_results=[[
            GmailMessageNotFound("message-a"),
            _message("message-b"),
        ]],
        history_results=[{"history": [], "new_history_id": "120"}],
    )
    service = _build_service(monkeypatch, state, gmail)

    async def no_sleep(_seconds):
        return None

    monkeypatch.setattr(sync_module.asyncio, "sleep", no_sleep)

    assert await service.full_sync() == []

    assert state.emails == {"message-b": 2}
    assert state.upsert_calls == ["message-b"]
    assert state.sync_status.last_history_id == "120"
    assert state.sync_status.sync_page_token is None
    assert state.sync_status.status == "completed"


@pytest.mark.asyncio
async def test_full_sync_retry_reuses_committed_batches_without_duplicates(monkeypatch):
    state = _State()
    state.sync_status.sync_page_token = _scan_checkpoint("current-page")
    gmail = _ResumableFullSyncGmail()
    service = _build_service(monkeypatch, state, gmail)

    async def no_sleep(_seconds):
        return None

    monkeypatch.setattr(sync_module.asyncio, "sleep", no_sleep)

    with pytest.raises(RuntimeError, match="missing 1"):
        await service.full_sync()

    assert state.sync_status.sync_page_token == _scan_checkpoint("current-page")
    assert len(state.emails) == 100

    with pytest.raises(RuntimeError, match="stop after page checkpoint"):
        await service.full_sync()

    assert state.sync_status.sync_page_token == _scan_checkpoint("next-page")
    assert len(state.emails) == 101
    assert gmail.requested_batches[-1] == ["message-100"]


class _BusyLockSession(AbstractAsyncContextManager):
    def __init__(self, queries):
        self.queries = queries

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    async def execute(self, statement, _params=None):
        self.queries.append(str(statement))
        return _Result(False)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "public_method, locked_method",
    [
        ("full_sync", "_full_sync_locked"),
        ("incremental_sync", "_incremental_sync_locked"),
    ],
)
async def test_busy_account_lock_is_benign_and_does_not_enter_sync(
    monkeypatch,
    public_method,
    locked_method,
):
    queries = []
    service = EmailSyncService(account_id=7)
    entered = False

    async def forbidden_sync():
        nonlocal entered
        entered = True
        raise AssertionError("busy lock must not enter sync state")

    monkeypatch.setattr(
        sync_module,
        "async_session",
        lambda: _BusyLockSession(queries),
    )
    monkeypatch.setattr(service, locked_method, forbidden_sync)

    assert await getattr(service, public_method)() == []

    assert entered is False
    assert len(queries) == 1
    assert "pg_try_advisory_xact_lock" in queries[0]
    assert "pg_advisory_unlock" not in queries[0]


class _AvailableLockSession(_BusyLockSession):
    def __init__(self, queries):
        super().__init__(queries)
        self.rolled_back = False
        self.exited = False

    async def __aexit__(self, exc_type, exc, traceback):
        self.exited = True
        return False

    async def execute(self, statement, _params=None):
        self.queries.append(str(statement))
        return _Result(True)

    async def rollback(self):
        self.rolled_back = True


@pytest.mark.asyncio
async def test_acquired_account_lock_ends_dedicated_transaction(monkeypatch):
    queries = []
    lock_session = _AvailableLockSession(queries)
    service = EmailSyncService(account_id=7)

    async def completed_sync():
        return [42]

    monkeypatch.setattr(sync_module, "async_session", lambda: lock_session)
    monkeypatch.setattr(service, "_full_sync_locked", completed_sync)

    assert await service.full_sync() == [42]

    assert lock_session.rolled_back is True
    assert lock_session.exited is True
    assert len(queries) == 1
    assert "pg_try_advisory_xact_lock" in queries[0]


@pytest.mark.asyncio
async def test_legacy_full_checkpoint_restarts_with_fresh_profile_baseline(monkeypatch):
    state = _State()
    state.sync_status.sync_page_token = "legacy-page-token"
    gmail = _FullFlowGmail(
        profile_history_ids=["300"],
        list_error="generated stop after legacy reset",
    )
    service = _build_service(monkeypatch, state, gmail)

    with pytest.raises(RuntimeError, match="stop after legacy reset"):
        await service.full_sync()

    checkpoint = _decode_full_sync_checkpoint(state.sync_status.sync_page_token)
    assert checkpoint == FullSyncCheckpoint(
        baseline_history_id="300",
        phase="scan",
    )
    assert state.sync_status.last_history_id == "300"
    assert state.sync_status.status == "error"
    assert gmail.profile_calls == 1
    assert gmail.list_page_tokens == [None]


@pytest.mark.asyncio
async def test_stale_full_page_checkpoint_cannot_overwrite_new_owner(monkeypatch):
    state = _State()
    state.sync_status.sync_page_token = _scan_checkpoint(None)
    state.full_conflicts_remaining = 1
    state.full_conflict_checkpoint = _scan_checkpoint("winner-page")
    gmail = _FullFlowGmail(
        pages={None: (["message-a"], "stale-page", 1)},
    )
    service = _build_service(monkeypatch, state, gmail)

    with pytest.raises(FullSyncCheckpointConflict):
        await service.full_sync()

    assert state.sync_status.sync_page_token == _scan_checkpoint("winner-page")
    assert state.sync_status.status == "completed"
    assert state.emails == {"message-a": 1}


@pytest.mark.asyncio
async def test_full_scan_refreshes_existing_messages_before_completion(monkeypatch):
    state = _State()
    state.emails["message-a"] = 1
    state.next_email_id = 2
    gmail = _FullFlowGmail(
        pages={None: (["message-a"], None, 1)},
        history_results=[{"history": [], "new_history_id": "120"}],
    )
    service = _build_service(monkeypatch, state, gmail)

    assert await service.full_sync() == []

    assert gmail.requested_batches == [["message-a"]]
    assert state.upsert_calls == ["message-a"]
    assert state.emails == {"message-a": 1}
    assert state.sync_status.last_history_id == "120"
    assert state.sync_status.sync_page_token is None
    assert state.sync_status.status == "completed"


@pytest.mark.asyncio
async def test_full_replay_applies_update_and_delete_before_high_water_commit(monkeypatch):
    state = _State()
    state.sync_status.sync_page_token = _replay_checkpoint()
    state.emails = {"delete-me": 1, "update-me": 2}
    state.next_email_id = 3
    gmail = _FullFlowGmail(history_results=[{
        "history": [
            {
                "id": "125",
                "messagesDeleted": [{"message": {"id": "delete-me"}}],
            },
            {
                "id": "129",
                "labelsAdded": [{"message": {"id": "update-me"}}],
            },
        ],
        "new_history_id": "130",
    }])
    service = _build_service(monkeypatch, state, gmail)

    assert await service.full_sync() == []

    assert state.emails == {"update-me": 2}
    assert state.upsert_calls == ["update-me"]
    assert gmail.requested_batches == [["update-me"]]
    assert state.sync_status.last_history_id == "130"
    assert state.sync_status.sync_page_token is None
    assert state.sync_status.status == "completed"


@pytest.mark.asyncio
async def test_full_completion_conflict_rolls_back_replay_mail_changes(monkeypatch):
    state = _State()
    state.sync_status.sync_page_token = _replay_checkpoint()
    state.emails = {"delete-me": 1}
    state.full_conflicts_remaining = 1
    state.full_conflict_checkpoint = None
    state.full_conflict_history_id = "200"
    gmail = _FullFlowGmail(history_results=[{
        "history": [{
            "id": "125",
            "messagesDeleted": [{"message": {"id": "delete-me"}}],
        }],
        "new_history_id": "130",
    }])
    service = _build_service(monkeypatch, state, gmail)

    with pytest.raises(FullSyncCheckpointConflict):
        await service.full_sync()

    assert state.emails == {"delete-me": 1}
    assert state.sync_status.last_history_id == "200"
    assert state.sync_status.sync_page_token is None
    assert state.sync_status.status == "completed"


@pytest.mark.asyncio
async def test_expired_full_baseline_keeps_ownership_and_restarts_scan(monkeypatch):
    state = _State()
    state.sync_status.sync_page_token = _replay_checkpoint()
    gmail = _FullFlowGmail(
        pages={None: ([], None, 0)},
        history_results=[
            None,
            {"history": [], "new_history_id": "350"},
        ],
        profile_history_ids=["300"],
    )
    service = _build_service(monkeypatch, state, gmail)

    assert await service.full_sync() == []

    assert gmail.history_baselines == ["100", "300"]
    assert gmail.profile_calls == 1
    assert gmail.list_page_tokens == [None]
    assert state.sync_status.last_history_id == "350"
    assert state.sync_status.sync_page_token is None
    assert state.sync_status.status == "completed"


class _HistoryResource:
    def __init__(self):
        self.requests = []

    def list(self, **kwargs):
        self.requests.append(kwargs)
        return kwargs


class _GeneratedGmailApi:
    def __init__(self):
        self.history_resource = _HistoryResource()

    def users(self):
        return self

    def history(self):
        return self.history_resource


@pytest.mark.asyncio
async def test_get_history_uses_response_high_water_across_pages(monkeypatch):
    gmail = GmailService(SimpleNamespace(email="generated@example.test"))
    api = _GeneratedGmailApi()
    responses = [
        {
            "history": [{"id": "118"}, {"id": "105"}],
            "historyId": "120",
            "nextPageToken": "page-2",
        },
        {
            "history": [{"id": "119"}],
            "historyId": "125",
        },
    ]

    async def execute(_request, **_kwargs):
        return responses.pop(0)

    monkeypatch.setattr(gmail, "_get_service", lambda: api)
    monkeypatch.setattr(gmail, "_execute_with_retry", execute)
    monkeypatch.setattr(gmail_module, "PAGE_PAUSE", 0)

    result = await gmail.get_history("100")

    assert result["new_history_id"] == "125"
    assert [entry["id"] for entry in result["history"]] == ["118", "105", "119"]
    assert api.history_resource.requests[1]["pageToken"] == "page-2"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response, expected_history_id",
    [
        ({"history": [], "historyId": "150"}, "150"),
        (
            {"history": [{"id": "145"}, {"id": "130"}, {"id": "140"}]},
            "145",
        ),
    ],
)
async def test_get_history_high_water_handles_empty_and_unordered_responses(
    monkeypatch,
    response,
    expected_history_id,
):
    gmail = GmailService(SimpleNamespace(email="generated@example.test"))
    api = _GeneratedGmailApi()

    async def execute(_request, **_kwargs):
        return response

    monkeypatch.setattr(gmail, "_get_service", lambda: api)
    monkeypatch.setattr(gmail, "_execute_with_retry", execute)

    result = await gmail.get_history("100")

    assert result["new_history_id"] == expected_history_id


@pytest.mark.asyncio
async def test_get_history_page_failure_never_returns_partial_history(monkeypatch):
    gmail = GmailService(SimpleNamespace(email="generated@example.test"))
    api = _GeneratedGmailApi()
    calls = 0

    async def execute(_request, **_kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            return {
                "history": [{"id": "110"}],
                "historyId": "120",
                "nextPageToken": "page-2",
            }
        raise RuntimeError("generated second-page failure")

    monkeypatch.setattr(gmail, "_get_service", lambda: api)
    monkeypatch.setattr(gmail, "_execute_with_retry", execute)
    monkeypatch.setattr(gmail_module, "PAGE_PAUSE", 0)

    with pytest.raises(RuntimeError, match="generated second-page failure"):
        await gmail.get_history("100")

    assert calls == 2
