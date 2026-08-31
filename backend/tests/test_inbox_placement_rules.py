"""Focused contracts for private exact-account Inbox placement rules."""

from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi import FastAPI
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.dialects import postgresql

import backend.routers.inbox_placement_rules as rules_router
from backend.database import get_db
from backend.models.account import GoogleAccount
from backend.models.email import Email
from backend.models.inbox_placement_rule import InboxPlacementRule
from backend.routers.auth import get_current_user
from backend.schemas.inbox_placement_rule import (
    MAX_INBOX_PLACEMENT_RULES_PER_ACCOUNT,
    InboxPlacementRuleReplace,
    InboxPlacementRuleUpsert,
)
from backend.services.conversation_rows import conversation_split_page_statement
from backend.services.inbox_placement_rules import (
    InboxPlacementCandidate,
    InboxPlacementRuleCandidateUnavailable,
    InboxPlacementRuleConflict,
    InboxPlacementRuleNotFound,
    InboxPlacementRuleView,
    _owned_account_statement,
    _owned_rule_statement,
    _selector_values,
    _current_inbox_email_predicate,
    delete_inbox_placement_rule,
    get_inbox_placement_candidate,
    replace_inbox_placement_rule,
    upsert_inbox_placement_rule,
)
from backend.services.mailbox_identity import (
    MailboxIdentityError,
    mailbox_domain,
    normalize_mailbox,
    normalize_stored_mailbox,
)


NOW = datetime(2026, 8, 31, 16, 0, tzinfo=timezone.utc)


def _upsert_payload(**overrides):
    payload = {
        "create_id": str(uuid4()),
        "account_id": 7,
        "anchor_email_id": 31,
        "scope": "sender",
        "placement": "other",
        "enabled": True,
        "expected_revision": 0,
    }
    payload.update(overrides)
    return payload


def _rule(**overrides):
    values = {
        "row_id": 1,
        "id": uuid4(),
        "create_id": uuid4(),
        "account_id": 7,
        "scope": "sender",
        "match_value": "sender@example.test",
        "placement": "other",
        "enabled": True,
        "revision": 1,
        "created_at": NOW,
        "updated_at": NOW,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class _Result:
    def __init__(self, value=None, *, rows=None):
        self.value = value
        self.rows = rows

    def scalar_one_or_none(self):
        return self.value

    def one_or_none(self):
        return self.value

    def scalars(self):
        return self

    def all(self):
        if self.rows is not None:
            return list(self.rows)
        if isinstance(self.value, list):
            return list(self.value)
        return []


class _ScriptedSession:
    def __init__(self, execute_values, *, scalar_values=()):
        self.execute_values = list(execute_values)
        self.scalar_values = list(scalar_values)
        self.added = []
        self.deleted = []
        self.commits = 0
        self.rollbacks = 0

    async def execute(self, _statement):
        return _Result(self.execute_values.pop(0))

    async def scalar(self, _statement):
        return self.scalar_values.pop(0)

    def add(self, value):
        self.added.append(value)

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        self.rollbacks += 1

    async def refresh(self, _value):
        pass

    async def delete(self, value):
        self.deleted.append(value)


def _app(*, authenticated: bool):
    app = FastAPI()
    app.include_router(rules_router.router)

    async def fake_db():
        yield SimpleNamespace()

    app.dependency_overrides[get_db] = fake_db
    if authenticated:
        async def fake_user():
            return SimpleNamespace(id=17)

        app.dependency_overrides[get_current_user] = fake_user
    return app


def test_strict_mailbox_and_idna_normalization_is_sql_compatible_or_fails_closed():
    assert normalize_mailbox(" Sender@BÜCHER.example. ") == "sender@xn--bcher-kva.example"
    assert mailbox_domain("Sender@Example.TEST") == "example.test"
    assert normalize_stored_mailbox("Sender@Example.TEST.") == "sender@example.test"

    with pytest.raises(MailboxIdentityError, match="matched safely"):
        normalize_stored_mailbox("sender@bücher.example")
    for invalid in (
        "first@example.test, second@example.test",
        "sender@example.test\r\nBcc: victim@example.test",
        "missing-at-sign",
        "sender@[127.0.0.1]",
    ):
        with pytest.raises(MailboxIdentityError):
            normalize_mailbox(invalid)

    assert _selector_values(SimpleNamespace(
        gmail_thread_id="provider-thread",
        gmail_message_id="provider-message",
        from_address="sender@bücher.example",
    )) == {"conversation": "thread:provider-thread"}


def test_training_requires_a_literal_incoming_inbox_anchor():
    compiled = _current_inbox_email_predicate().compile(
        dialect=postgresql.dialect()
    )
    sql = str(compiled)
    assert "emails.labels @>" in sql
    assert "emails.is_trash IS false" in sql
    assert "emails.is_spam IS false" in sql
    assert "emails.is_draft IS false" in sql
    assert "emails.is_sent IS false" in sql


@pytest.mark.asyncio
async def test_malformed_sender_preserves_conversation_scope_and_fails_other_scopes_closed():
    account = SimpleNamespace(id=7, email="owner@example.test", is_active=True)
    email = SimpleNamespace(
        id=31,
        gmail_thread_id="",
        gmail_message_id="provider-message-id",
        from_address="sender@example.test@attacker.example",
        subject="Generated conversation",
    )
    candidate = await get_inbox_placement_candidate(
        _ScriptedSession([account, email, []]),
        user_id=17,
        account_id=7,
        anchor_email_id=31,
    )
    assert candidate.sender_address == ""
    assert candidate.sender_domain == ""
    assert candidate.rules == []

    conversation_request = InboxPlacementRuleUpsert(
        **_upsert_payload(scope="conversation")
    )
    create_db = _ScriptedSession(
        [account, email, None, None],
        scalar_values=[0],
    )
    created, was_created = await upsert_inbox_placement_rule(
        create_db,
        user_id=17,
        request=conversation_request,
    )
    assert was_created is True
    assert created.rule.scope == "conversation"
    assert created.rule.match_value == "message:provider-message-id"
    assert create_db.commits == 1

    for scope in ("sender", "domain"):
        with pytest.raises(
            InboxPlacementRuleCandidateUnavailable,
            match="valid sender",
        ):
            await upsert_inbox_placement_rule(
                _ScriptedSession([account, email]),
                user_id=17,
                request=InboxPlacementRuleUpsert(
                    **_upsert_payload(scope=scope)
                ),
            )


def test_frozen_schema_is_strict_and_bounded():
    request = InboxPlacementRuleUpsert(**_upsert_payload())
    assert set(request.model_dump()) == {
        "create_id",
        "account_id",
        "anchor_email_id",
        "scope",
        "placement",
        "enabled",
        "expected_revision",
    }
    assert InboxPlacementRuleReplace(
        placement="focused", enabled=False, revision=2
    ).revision == 2

    for field, value in (
        ("account_id", True),
        ("anchor_email_id", False),
        ("expected_revision", True),
        ("enabled", 1),
        ("scope", "subdomain"),
        ("placement", "priority"),
    ):
        with pytest.raises(ValidationError):
            InboxPlacementRuleUpsert(**_upsert_payload(**{field: value}))
    with pytest.raises(ValidationError):
        InboxPlacementRuleUpsert(**_upsert_payload(unexpected="value"))


def test_model_and_migration_are_one_additive_account_scoped_head():
    assert [column.name for column in InboxPlacementRule.__table__.columns] == [
        "row_id",
        "id",
        "create_id",
        "account_id",
        "scope",
        "match_value",
        "placement",
        "enabled",
        "revision",
        "created_at",
        "updated_at",
    ]
    constraints = {
        constraint.name for constraint in InboxPlacementRule.__table__.constraints
    }
    assert {
        "ck_inbox_placement_rules_scope",
        "ck_inbox_placement_rules_placement",
        "ck_inbox_placement_rules_match_value",
        "ck_inbox_placement_rules_revision",
        "uq_inbox_placement_rules_account_public_id",
        "uq_inbox_placement_rules_account_create_id",
        "uq_inbox_placement_rules_account_match",
    } <= constraints
    account_fk = next(iter(InboxPlacementRule.__table__.foreign_key_constraints))
    assert account_fk.ondelete == "CASCADE"

    config = Config("alembic.ini")
    config.set_main_option("script_location", "alembic")
    scripts = ScriptDirectory.from_config(config)
    assert scripts.get_heads() == ["c1d2e3f4a5b6"]
    assert scripts.get_revision("c1d2e3f4a5b6").down_revision == "b1c2d3e4f5a6"


def test_owner_predicates_never_widen_account_or_rule_lookup():
    account = _owned_account_statement(
        user_id=17, account_id=7, active_only=True
    ).compile(dialect=postgresql.dialect())
    rule_id = uuid4()
    rule = _owned_rule_statement(user_id=17, rule_id=rule_id).compile(
        dialect=postgresql.dialect()
    )
    assert "google_accounts.id" in str(account)
    assert "google_accounts.user_id" in str(account)
    assert "google_accounts.is_active IS true" in str(account)
    assert {17, 7} <= set(account.params.values())
    assert "inbox_placement_rules.id" in str(rule)
    assert "google_accounts.user_id" in str(rule)
    assert rule_id in rule.params.values()


def test_rules_join_at_authoritative_anchor_before_counts_windows_and_pages():
    compiled = conversation_split_page_statement(
        select(Email).where(Email.account_id.in_([7, 8])),
        page=2,
        page_size=20,
        sort_by="date",
        sort_order="desc",
    ).compile(dialect=postgresql.dialect())
    sql = str(compiled)
    params = list(compiled.params.values())

    assert "inbox_placement_rules AS conversation_rule" in sql
    assert "inbox_placement_rules AS sender_rule" in sql
    assert "inbox_placement_rules AS domain_rule" in sql
    assert sql.index("inbox_placement_rules AS conversation_rule") < sql.index(
        "placed_conversation_anchors AS"
    )
    assert sql.index("placed_conversation_anchors AS") < sql.index(
        "sectioned_conversation_rows AS"
    )
    assert "conversation_rule.account_id = emails.account_id" in sql
    assert "sender_rule.account_id = emails.account_id" in sql
    assert "domain_rule.account_id = emails.account_id" in sql
    assert "conversation_rule.enabled IS true" in sql
    assert "inbox_placement_rule_id" in sql
    assert "inbox_placement_rule_scope" in sql
    assert "inbox_placement_rule_revision" in sql
    assert "user_rule_focused" in params
    assert "user_rule_other" in params
    assert "conversation" in params and "sender" in params and "domain" in params


@pytest.mark.asyncio
async def test_upsert_create_and_update_replays_do_not_mutate_again():
    account = SimpleNamespace(id=7, email="owner@example.test", is_active=True)
    email = SimpleNamespace(
        id=31,
        gmail_thread_id="",
        gmail_message_id="provider-message-id",
        from_address="Sender@Example.TEST",
        subject="Generated conversation",
    )
    request = InboxPlacementRuleUpsert(**_upsert_payload())
    existing = _rule(create_id=request.create_id)
    replay_db = _ScriptedSession([account, email, existing, existing])

    replay, created = await upsert_inbox_placement_rule(
        replay_db, user_id=17, request=request
    )
    assert replay.rule is existing
    assert created is False
    assert replay_db.commits == 0
    assert replay_db.added == []

    update_request = InboxPlacementRuleUpsert(
        **_upsert_payload(
            create_id=str(uuid4()),
            placement="focused",
            expected_revision=1,
        )
    )
    updated = _rule(placement="focused", revision=2)
    update_db = _ScriptedSession([account, email, None, updated])
    update_replay, created = await upsert_inbox_placement_rule(
        update_db, user_id=17, request=update_request
    )
    assert update_replay.rule is updated
    assert created is False
    assert update_db.commits == 0


@pytest.mark.asyncio
async def test_upsert_rejects_missing_foreign_and_stale_without_widening():
    request = InboxPlacementRuleUpsert(**_upsert_payload())
    with pytest.raises(InboxPlacementRuleNotFound, match="not found"):
        await upsert_inbox_placement_rule(
            _ScriptedSession([None]), user_id=17, request=request
        )

    account = SimpleNamespace(id=7, email="owner@example.test", is_active=True)
    email = SimpleNamespace(
        id=31,
        gmail_thread_id="",
        gmail_message_id="provider-message-id",
        from_address="sender@example.test",
        subject="Generated conversation",
    )
    stale = _rule(revision=4)
    stale_request = InboxPlacementRuleUpsert(
        **_upsert_payload(expected_revision=2)
    )
    with pytest.raises(InboxPlacementRuleConflict, match="changed elsewhere"):
        await upsert_inbox_placement_rule(
            _ScriptedSession([account, email, None, stale]),
            user_id=17,
            request=stale_request,
        )


@pytest.mark.asyncio
async def test_create_enforces_per_account_quota_before_mutation():
    account = SimpleNamespace(id=7, email="owner@example.test", is_active=True)
    email = SimpleNamespace(
        id=31,
        gmail_thread_id="",
        gmail_message_id="provider-message-id",
        from_address="sender@example.test",
        subject="Generated conversation",
    )
    db = _ScriptedSession(
        [account, email, None, None],
        scalar_values=[MAX_INBOX_PLACEMENT_RULES_PER_ACCOUNT],
    )
    with pytest.raises(InboxPlacementRuleConflict, match="at most 500"):
        await upsert_inbox_placement_rule(
            db,
            user_id=17,
            request=InboxPlacementRuleUpsert(**_upsert_payload()),
        )
    assert db.added == []
    assert db.commits == 0


@pytest.mark.asyncio
async def test_replace_and_delete_are_revisioned_and_owner_scoped():
    rule = _rule(placement="other", enabled=True, revision=3)
    update_db = _ScriptedSession([(rule, "owner@example.test")])
    updated = await replace_inbox_placement_rule(
        update_db,
        user_id=17,
        rule_id=rule.id,
        request=InboxPlacementRuleReplace(
            placement="focused",
            enabled=False,
            revision=3,
        ),
    )
    assert updated.rule.placement == "focused"
    assert updated.rule.enabled is False
    assert updated.rule.revision == 4
    assert update_db.commits == 1

    replay_db = _ScriptedSession([(rule, "owner@example.test")])
    replay = await replace_inbox_placement_rule(
        replay_db,
        user_id=17,
        rule_id=rule.id,
        request=InboxPlacementRuleReplace(
            placement="focused",
            enabled=False,
            revision=3,
        ),
    )
    assert replay.rule is rule
    assert replay_db.commits == 0

    stale_db = _ScriptedSession([(rule, "owner@example.test")])
    with pytest.raises(InboxPlacementRuleConflict, match="changed elsewhere"):
        await replace_inbox_placement_rule(
            stale_db,
            user_id=17,
            rule_id=rule.id,
            request=InboxPlacementRuleReplace(
                placement="other",
                enabled=True,
                revision=2,
            ),
        )

    delete_db = _ScriptedSession([(rule, "owner@example.test")])
    await delete_inbox_placement_rule(
        delete_db,
        user_id=17,
        rule_id=rule.id,
        revision=4,
    )
    assert delete_db.deleted == [rule]
    assert delete_db.commits == 1

    missing_db = _ScriptedSession([None])
    with pytest.raises(InboxPlacementRuleNotFound, match="not found"):
        await delete_inbox_placement_rule(
            missing_db,
            user_id=17,
            rule_id=uuid4(),
            revision=1,
        )


@pytest.mark.asyncio
async def test_private_candidate_never_returns_provider_ids(monkeypatch):
    conversation_rule = _rule(
        scope="conversation",
        match_value="thread:raw-provider-thread-id",
    )
    candidate = InboxPlacementCandidate(
        account_id=7,
        account_email="owner@example.test",
        anchor_email_id=31,
        conversation_label="A safe subject",
        sender_address="sender@example.test",
        sender_domain="example.test",
        rules=[
            InboxPlacementRuleView(
                rule=conversation_rule,
                account_email="owner@example.test",
                display_value="A safe subject",
            )
        ],
    )

    async def fake_candidate(*_args, **_kwargs):
        return candidate

    monkeypatch.setattr(
        rules_router, "get_inbox_placement_candidate", fake_candidate
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app(authenticated=True)),
        base_url="http://test",
    ) as client:
        response = await client.get(
            "/api/inbox-placement-rules/candidate",
            params={"account_id": 7, "anchor_email_id": 31},
        )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    payload = response.json()
    assert payload["rules"][0]["display_value"] == "A safe subject"
    assert "raw-provider-thread-id" not in response.text
    assert "match_value" not in response.text


@pytest.mark.asyncio
async def test_router_auth_validation_and_conflicts_are_private_no_store(monkeypatch):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app(authenticated=True)),
        base_url="http://test",
    ) as client:
        validation = await client.post("/api/inbox-placement-rules", json={})
    assert validation.status_code == 422
    assert validation.headers["cache-control"] == "private, no-store"

    async def conflict(*_args, **_kwargs):
        raise InboxPlacementRuleConflict("changed elsewhere")

    monkeypatch.setattr(rules_router, "upsert_inbox_placement_rule", conflict)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app(authenticated=True)),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/api/inbox-placement-rules",
            json=_upsert_payload(),
        )
    assert response.status_code == 409
    assert response.headers["cache-control"] == "private, no-store"
    assert response.json()["detail"]["code"] == "inbox_placement_rule_conflict"

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app(authenticated=False)),
        base_url="http://test",
    ) as client:
        unauthenticated = await client.get("/api/inbox-placement-rules")
    assert unauthenticated.status_code == 401
    assert unauthenticated.headers["cache-control"] == "private, no-store"
    assert MAX_INBOX_PLACEMENT_RULES_PER_ACCOUNT == 500
