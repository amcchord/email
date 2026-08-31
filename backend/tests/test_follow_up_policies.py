"""Focused contracts for automatic follow-up policy persistence and API."""

from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi import FastAPI
from pydantic import ValidationError

import backend.routers.follow_up as follow_up_router
from backend.database import get_db
from backend.models.follow_up import AccountFollowUpPolicy, OutboundFollowUpIntent
from backend.routers.auth import get_current_user
from backend.schemas.follow_up import FollowUpPolicyReplace
from backend.services.follow_up_policies import (
    FollowUpPolicyConflict,
    FollowUpPolicyNotFound,
    FollowUpPolicyView,
    list_follow_up_policies,
    replace_follow_up_policy,
)


class _Result:
    def __init__(self, *, scalar=None, rows=None):
        self.scalar = scalar
        self.rows = rows or []

    def scalar_one_or_none(self):
        return self.scalar

    def all(self):
        return self.rows


class _ListSession:
    def __init__(self, rows):
        self.rows = rows
        self.statements = []
        self.added = []

    async def execute(self, statement):
        self.statements.append(statement)
        return _Result(rows=self.rows)

    def add(self, row):
        self.added.append(row)


class _PolicySession:
    def __init__(self, *, account, policy=None):
        self.account = account
        self.policy = policy
        self.statements = []
        self.commit_count = 0
        self.refresh_count = 0

    async def execute(self, statement):
        self.statements.append(statement)
        entity = statement.column_descriptions[0].get("entity")
        if entity is AccountFollowUpPolicy:
            return _Result(scalar=self.policy)
        return _Result(scalar=self.account)

    def add(self, policy):
        self.policy = policy

    async def commit(self):
        self.commit_count += 1

    async def refresh(self, _row):
        self.refresh_count += 1


def _account(*, account_id=41, email="owner@example.test"):
    return SimpleNamespace(id=account_id, email=email)


def _request(**overrides):
    values = {
        "expected_revision": 0,
        "enabled": True,
        "delay_days": 3,
        "wake_local_time": "09:00",
        "time_zone": "America/New_York",
        "weekdays_only": True,
    }
    values.update(overrides)
    return FollowUpPolicyReplace(**values)


def _app(*, authenticated):
    app = FastAPI()
    app.include_router(follow_up_router.router)

    async def fake_db():
        yield SimpleNamespace()

    app.dependency_overrides[get_db] = fake_db
    if authenticated:

        async def fake_user():
            return SimpleNamespace(id=17)

        app.dependency_overrides[get_current_user] = fake_user
    return app


def test_policy_schema_is_strict_and_validates_time_and_iana_zone():
    request = _request()
    assert request.expected_revision == 0
    assert request.wake_local_time == "09:00"
    assert request.time_zone == "America/New_York"

    for invalid in ("9:00", "24:00", "12:60", "09:00:00"):
        with pytest.raises(ValidationError, match="24-hour HH:MM"):
            _request(wake_local_time=invalid)
    with pytest.raises(ValidationError, match="valid IANA"):
        _request(time_zone="Generated/Nowhere")
    with pytest.raises(ValidationError):
        _request(delay_days=0)
    with pytest.raises(ValidationError):
        _request(delay_days=31)
    with pytest.raises(ValidationError):
        _request(expected_revision=-1)
    with pytest.raises(ValidationError):
        FollowUpPolicyReplace.model_validate(
            {**_request().model_dump(), "unexpected": "private"}
        )


@pytest.mark.asyncio
async def test_get_synthesizes_revision_zero_defaults_without_writing_rows():
    stored = AccountFollowUpPolicy(
        account_id=42,
        user_id=17,
        enabled=True,
        delay_days=7,
        wake_local_time="10:30",
        time_zone="UTC",
        weekdays_only=False,
        revision=4,
    )
    db = _ListSession(
        [
            (_account(), None),
            (_account(account_id=42, email="stored@example.test"), stored),
        ]
    )

    policies = await list_follow_up_policies(db, user_id=17)

    assert policies == [
        FollowUpPolicyView(
            account_id=41,
            account_email="owner@example.test",
            enabled=False,
            delay_days=3,
            wake_local_time="09:00",
            time_zone="UTC",
            weekdays_only=True,
            revision=0,
        ),
        FollowUpPolicyView(
            account_id=42,
            account_email="stored@example.test",
            enabled=True,
            delay_days=7,
            wake_local_time="10:30",
            time_zone="UTC",
            weekdays_only=False,
            revision=4,
        ),
    ]
    assert db.added == []
    query = str(db.statements[0])
    assert "google_accounts.user_id" in query
    assert "google_accounts.is_active IS true" in query
    assert "google_accounts.encrypted_refresh_token IS NOT NULL" in query
    assert "LEFT OUTER JOIN account_follow_up_policies" in query


@pytest.mark.asyncio
async def test_policy_create_update_exact_replay_and_stale_conflict():
    db = _PolicySession(account=_account())

    created = await replace_follow_up_policy(
        db,
        user_id=17,
        account_id=41,
        request=_request(),
    )
    assert created.revision == 1
    assert db.policy.user_id == 17
    assert db.commit_count == 1

    create_replay = await replace_follow_up_policy(
        db,
        user_id=17,
        account_id=41,
        request=_request(),
    )
    assert create_replay == created
    assert db.commit_count == 1

    update = _request(
        expected_revision=1,
        delay_days=5,
        wake_local_time="08:15",
        weekdays_only=False,
    )
    updated = await replace_follow_up_policy(
        db,
        user_id=17,
        account_id=41,
        request=update,
    )
    assert updated.revision == 2
    assert updated.delay_days == 5
    assert db.commit_count == 2

    update_replay = await replace_follow_up_policy(
        db,
        user_id=17,
        account_id=41,
        request=update,
    )
    assert update_replay == updated
    assert db.commit_count == 2

    with pytest.raises(FollowUpPolicyConflict, match="another device"):
        await replace_follow_up_policy(
            db,
            user_id=17,
            account_id=41,
            request=_request(expected_revision=1, delay_days=6),
        )
    assert db.commit_count == 2


@pytest.mark.asyncio
async def test_missing_or_foreign_account_is_non_disclosing_and_never_writes():
    db = _PolicySession(account=None)
    with pytest.raises(
        FollowUpPolicyNotFound,
        match="Follow-up policy account not found",
    ):
        await replace_follow_up_policy(
            db,
            user_id=17,
            account_id=99,
            request=_request(),
        )
    assert len(db.statements) == 1
    assert db.policy is None
    assert db.commit_count == 0
    query = str(db.statements[0])
    assert "google_accounts.id" in query
    assert "google_accounts.user_id" in query


@pytest.mark.asyncio
async def test_policy_routes_require_auth_and_get_returns_accounts_wrapper(monkeypatch):
    anonymous = _app(authenticated=False)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=anonymous), base_url="https://test"
    ) as client:
        responses = [
            await client.get("/api/follow-up/policies"),
            await client.put(
                "/api/follow-up/policies/41",
                json=_request().model_dump(),
            ),
        ]
    assert [response.status_code for response in responses] == [401, 401]

    async def list_policies(_db, *, user_id):
        assert user_id == 17
        return [
            FollowUpPolicyView(
                account_id=41,
                account_email="owner@example.test",
                enabled=False,
                delay_days=3,
                wake_local_time="09:00",
                time_zone="UTC",
                weekdays_only=True,
                revision=0,
            )
        ]

    monkeypatch.setattr(follow_up_router, "list_follow_up_policies", list_policies)
    authenticated = _app(authenticated=True)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=authenticated), base_url="https://test"
    ) as client:
        response = await client.get("/api/follow-up/policies")
    assert response.status_code == 200
    assert response.json() == {
        "accounts": [
            {
                "account_id": 41,
                "account_email": "owner@example.test",
                "enabled": False,
                "delay_days": 3,
                "wake_local_time": "09:00",
                "time_zone": "UTC",
                "weekdays_only": True,
                "revision": 0,
            }
        ],
        "total": 1,
    }


@pytest.mark.asyncio
async def test_policy_route_maps_foreign_and_stale_writes(monkeypatch):
    app = _app(authenticated=True)

    async def missing(*_args, **_kwargs):
        raise FollowUpPolicyNotFound("Follow-up policy account not found")

    monkeypatch.setattr(follow_up_router, "replace_follow_up_policy", missing)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://test"
    ) as client:
        missing_response = await client.put(
            "/api/follow-up/policies/99", json=_request().model_dump()
        )
    assert missing_response.status_code == 404
    assert missing_response.json()["detail"]["code"] == "follow_up_policy_not_found"

    async def stale(*_args, **_kwargs):
        raise FollowUpPolicyConflict("This follow-up policy changed; refresh it")

    monkeypatch.setattr(follow_up_router, "replace_follow_up_policy", stale)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://test"
    ) as client:
        stale_response = await client.put(
            "/api/follow-up/policies/41", json=_request().model_dump()
        )
    assert stale_response.status_code == 409
    assert stale_response.json()["detail"]["code"] == "follow_up_policy_conflict"


def test_follow_up_models_and_migration_are_the_direct_d7_child():
    policy_constraints = {
        constraint.name for constraint in AccountFollowUpPolicy.__table__.constraints
    }
    assert {
        "ck_account_follow_up_policies_delay_days",
        "ck_account_follow_up_policies_wake_local_time",
        "ck_account_follow_up_policies_time_zone",
        "ck_account_follow_up_policies_revision",
    } <= policy_constraints
    assert AccountFollowUpPolicy.__table__.c.account_id.primary_key is True

    intent_constraints = {
        constraint.name for constraint in OutboundFollowUpIntent.__table__.constraints
    }
    assert {
        "ck_outbound_follow_up_intents_state",
        "ck_outbound_follow_up_intents_requested_via",
        "ck_outbound_follow_up_intents_delay_days",
        "ck_outbound_follow_up_intents_lease_shape",
        "ck_outbound_follow_up_intents_scheduled_shape",
        "uq_outbound_follow_up_intents_public_id",
        "uq_outbound_follow_up_intents_outbound_message",
    } <= intent_constraints
    assert {column.name for column in OutboundFollowUpIntent.__table__.c} >= {
        "outbound_message_id",
        "snooze_id",
        "post_send_archive",
        "delivered_at",
        "wake_at",
        "next_attempt_at",
        "lease_token",
        "lease_expires_at",
        "scheduled_at",
        "cancelled_at",
        "failed_at",
    }

    config = Config("alembic.ini")
    config.set_main_option("script_location", "alembic")
    scripts = ScriptDirectory.from_config(config)
    revision = scripts.get_revision("e8f9a0b1c2d3")
    assert revision.down_revision == "d7e8f9a0b1c2"
    assert scripts.get_revision("f9a0b1c2d3e4").down_revision == "e8f9a0b1c2d3"
    assert scripts.get_heads() == ["a0b1c2d3e4f5"]

    migration_source = Path(revision.path).read_text()
    assert '"follow_up_requested"' in migration_source
    assert '"origin_outbound_id"' in migration_source
    assert "automatic_follow_up" in migration_source
    assert "data-lossy" in migration_source
