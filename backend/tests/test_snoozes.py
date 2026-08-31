from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from pydantic import ValidationError

from backend.models.mail_action import MAIL_ACTION_TYPES, MailAction
from backend.models.snooze import EmailSnooze, SNOOZE_ACTIVE_STATES
from backend.schemas.email import EmailActionRequest
from backend.schemas.snooze import SnoozeCreateRequest, SnoozeRescheduleRequest
from backend.services.mail_actions import ACTION_LABEL_DELTAS, state_after_action
from backend.services.snoozes import _action_key, _payload_hash
from backend.workers.tasks import CronWorkerSettings, drain_snoozes_task


NOW = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)


def test_snooze_schema_normalizes_utc_and_preserves_iana_zone():
    request = SnoozeCreateRequest(
        email_id=42,
        wake_at="2026-11-01T01:30:00-04:00",
        time_zone="America/New_York",
        condition="if_no_reply",
    )

    assert request.wake_at == datetime(2026, 11, 1, 5, 30, tzinfo=timezone.utc)
    assert request.time_zone == "America/New_York"
    assert request.condition == "if_no_reply"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("wake_at", "2026-08-31T09:00:00"),
        ("time_zone", "Not/A_Time_Zone"),
    ],
)
def test_snooze_schema_rejects_ambiguous_time_metadata(field, value):
    payload = {
        "email_id": 42,
        "wake_at": "2026-08-31T09:00:00-04:00",
        "time_zone": "America/New_York",
    }
    payload[field] = value
    with pytest.raises(ValidationError):
        SnoozeCreateRequest(**payload)


def test_reschedule_schema_uses_same_dst_safe_contract():
    request = SnoozeRescheduleRequest(
        wake_at="2026-11-01T01:30:00-05:00",
        time_zone="America/New_York",
    )
    assert request.wake_at == datetime(2026, 11, 1, 6, 30, tzinfo=timezone.utc)


def test_create_payload_and_internal_action_keys_are_deterministic():
    key = uuid4()
    request = SnoozeCreateRequest(
        email_id=42,
        wake_at=NOW + timedelta(days=1),
        time_zone="UTC",
        idempotency_key=key,
    )
    same = request.model_copy()

    assert _payload_hash(request) == _payload_hash(same)
    public_id = uuid4()
    assert _action_key(public_id, "archive") == _action_key(public_id, "archive")
    assert _action_key(public_id, "archive") != _action_key(public_id, "return")


def test_unarchive_is_a_first_class_inverse_mail_action():
    before = {
        "labels": ["SENT", "STARRED"],
        "is_read": True,
        "is_starred": True,
        "is_trash": False,
        "is_spam": False,
    }
    after, added, removed = state_after_action(before, "unarchive")

    assert "unarchive" in MAIL_ACTION_TYPES
    assert ACTION_LABEL_DELTAS["unarchive"] == (("INBOX",), ())
    assert added == ["INBOX"]
    assert removed == []
    assert set(after["labels"]) == {"INBOX", "SENT", "STARRED"}
    assert EmailActionRequest(email_ids=[1], action="unarchive").action == "unarchive"
    action_check = next(
        item for item in MailAction.__table__.constraints if item.name == "ck_mail_actions_action"
    )
    assert "unarchive" in str(action_check.sqltext)


def test_snooze_model_has_one_active_email_guard_and_lease_shape():
    active_index = next(
        item for item in EmailSnooze.__table__.indexes
        if item.name == "uq_email_snoozes_active_conversation"
    )
    assert active_index.unique is True
    assert [column.name for column in active_index.columns] == [
        "user_id", "account_id", "gmail_thread_id"
    ]
    assert set(SNOOZE_ACTIVE_STATES) == {
        "pending_archive", "scheduled", "pending_return"
    }
    where = str(active_index.dialect_options["postgresql"]["where"])
    assert "pending_archive" in where
    assert "scheduled" in where
    assert "pending_return" in where


def test_snooze_migration_is_single_head_directly_after_terminal_head():
    config = Config("alembic.ini")
    config.set_main_option("script_location", "alembic")
    scripts = ScriptDirectory.from_config(config)
    assert scripts.get_heads() == ["b1c2d3e4f5a6"]
    revision = scripts.get_revision("a4b5c6d7e8f9")
    assert revision.down_revision == "f3a4b5c6d7e8"
    assert scripts.get_revision("b5c6d7e8f9a0").down_revision == "a4b5c6d7e8f9"
    assert scripts.get_revision("c6d7e8f9a0b1").down_revision == "b5c6d7e8f9a0"


@pytest.mark.asyncio
async def test_snooze_worker_is_registered_and_delegates(monkeypatch):
    import backend.workers.tasks as tasks

    async def generated_drain():
        return 7

    monkeypatch.setattr(tasks, "drain_due_snoozes", generated_drain)
    assert await drain_snoozes_task({}) == 7
    assert drain_snoozes_task in CronWorkerSettings.functions
    assert any(job.coroutine is drain_snoozes_task for job in CronWorkerSettings.cron_jobs)
