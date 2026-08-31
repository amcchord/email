"""Focused provider-free checks for private contact projections."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.dialects import postgresql

import backend.routers.contacts as contacts_router
from backend.database import get_db
from backend.routers.auth import get_current_user
from backend.services.contact_profiles import (
    CONTACT_CORPUS_ROW_LIMIT,
    ContactCoverage,
    ContactNotFound,
    ContactProfile,
    ContactQueryPage,
    ContactSummary,
    RecentContactConversation,
    _corpus_statement,
    build_contact_profile,
    build_contact_query_page,
    contact_key_for_address,
    query_contact_profiles,
)


NOW = datetime(2026, 8, 31, 16, 0, tzinfo=timezone.utc)
SECRET = "generated-contact-test-secret"


def _row(row_id: int, days: int = 0, **values):
    defaults = {
        "id": row_id,
        "gmail_thread_id": f"generated-thread-{row_id}",
        "from_address": "incoming@example.test",
        "from_name": "Incoming Person",
        "to_addresses": [],
        "cc_addresses": [],
        "bcc_addresses": [],
        "date": NOW + timedelta(days=days),
        "is_sent": False,
        "is_draft": False,
        "is_spam": False,
        "is_trash": False,
        # Deliberately sensitive-looking fields prove they are not serialized.
        "subject": "Private generated subject",
        "snippet": "Private generated snippet",
        "body_text": "Private generated body",
        "labels": ["Private_generated_label"],
    }
    defaults.update(values)
    return SimpleNamespace(**defaults)


def _summary(*, account_id: int = 17) -> ContactSummary:
    return ContactSummary(
        account_id=account_id,
        contact_key="a" * 64,
        name="Generated Contact",
        address="contact@example.test",
        formatted="Generated Contact <contact@example.test>",
        relationship="bidirectional",
        observed_message_count=3,
        observed_received_count=2,
        observed_sent_count=1,
        observed_conversation_count=2,
        observed_first_at=NOW - timedelta(days=2),
        observed_last_at=NOW,
        observed_last_received_at=NOW,
        observed_last_sent_at=NOW - timedelta(days=1),
    )


def test_projection_is_account_keyed_content_free_and_excludes_bcc_self_invalid_and_status_rows():
    rows = [
        _row(
            1,
            0,
            gmail_thread_id="generated-shared-thread",
            from_address="Person@Example.Test",
            from_name="Person\x00 Name",
        ),
        _row(
            2,
            1,
            gmail_thread_id="generated-shared-thread",
            is_sent=True,
            from_address="owner@example.test",
            from_name="Owner",
            to_addresses=[
                {"name": "New Person Name", "address": "person@example.test"},
                {"name": "New Person Name", "address": "PERSON@example.test"},
            ],
            cc_addresses=[{"name": "Copied", "address": "copy@example.test"}],
        ),
        _row(
            3,
            2,
            is_sent=True,
            from_address="owner@example.test",
            bcc_addresses=[{"name": "Hidden", "address": "hidden@example.test"}],
        ),
        _row(4, 3, from_address="owner@example.test"),
        _row(5, 4, from_address="invalid"),
        _row(6, 5, from_address="draft@example.test", is_draft=True),
        _row(7, 6, from_address="spam@example.test", is_spam=True),
        _row(8, 7, from_address="trash@example.test", is_trash=True),
    ]

    page = build_contact_query_page(
        corpus_rows=rows,
        owned_addresses=["owner@example.test", "alias@example.test"],
        user_id=9,
        account_id=17,
        secret_key=SECRET,
        page_size=50,
    )

    assert [contact.address for contact in page.contacts] == [
        "person@example.test",
        "copy@example.test",
    ]
    person = page.contacts[0]
    assert person.account_id == 17
    assert person.name == "New Person Name"
    assert person.relationship == "bidirectional"
    assert person.observed_message_count == 2
    assert person.observed_received_count == 1
    assert person.observed_sent_count == 1
    assert person.observed_conversation_count == 1
    assert person.contact_key == contact_key_for_address(
        user_id=9,
        account_id=17,
        address="person@example.test",
        secret_key=SECRET,
    )
    assert len(person.contact_key) == 64
    assert "hidden@example.test" not in {contact.address for contact in page.contacts}
    assert "owner@example.test" not in {contact.address for contact in page.contacts}
    assert page.coverage.rows_scanned == 5
    assert page.coverage.history_may_be_truncated is False
    assert not hasattr(person, "subject")
    assert not hasattr(person, "snippet")
    assert not hasattr(person, "body_text")

    other_account_key = contact_key_for_address(
        user_id=9,
        account_id=18,
        address="person@example.test",
        secret_key=SECRET,
    )
    other_user_key = contact_key_for_address(
        user_id=10,
        account_id=17,
        address="person@example.test",
        secret_key=SECRET,
    )
    assert person.contact_key not in {other_account_key, other_user_key}


def test_query_ranking_relationship_filter_and_pagination_are_deterministic():
    rows = [
        _row(1, from_name="Zulu", from_address="zulu@example.test"),
        _row(2, from_name="Alpha", from_address="alpha@example.test"),
        _row(
            3,
            is_sent=True,
            from_address="owner@example.test",
            to_addresses=[{"name": "Outbound", "address": "outbound@example.test"}],
        ),
    ]
    first = build_contact_query_page(
        corpus_rows=rows,
        owned_addresses=["owner@example.test"],
        user_id=9,
        account_id=17,
        secret_key=SECRET,
        relationship="inbound_only",
        page=1,
        page_size=1,
    )
    second = build_contact_query_page(
        corpus_rows=rows,
        owned_addresses=["owner@example.test"],
        user_id=9,
        account_id=17,
        secret_key=SECRET,
        relationship="inbound_only",
        page=2,
        page_size=1,
    )
    outbound = build_contact_query_page(
        corpus_rows=rows,
        owned_addresses=["owner@example.test"],
        user_id=9,
        account_id=17,
        secret_key=SECRET,
        query="out",
        relationship="outbound_only",
    )

    assert first.total == 2
    assert first.total_pages == 2
    assert [item.address for item in first.contacts] == ["alpha@example.test"]
    assert [item.address for item in second.contacts] == ["zulu@example.test"]
    assert [item.address for item in outbound.contacts] == ["outbound@example.test"]


def test_profile_uses_opaque_key_and_returns_only_content_free_recent_pointers():
    rows = [
        _row(
            1,
            0,
            gmail_thread_id="generated-thread",
            from_address="person@example.test",
        ),
        _row(
            2,
            1,
            gmail_thread_id="generated-thread",
            is_sent=True,
            from_address="owner@example.test",
            to_addresses=["Person <person@example.test>"],
        ),
        _row(
            3,
            2,
            gmail_thread_id=" ",
            from_address="person@example.test",
        ),
    ]
    key = contact_key_for_address(
        user_id=9,
        account_id=17,
        address="person@example.test",
        secret_key=SECRET,
    )
    profile = build_contact_profile(
        corpus_rows=rows,
        owned_addresses=["owner@example.test"],
        user_id=9,
        account_id=17,
        contact_key=key,
        secret_key=SECRET,
        recent_limit=8,
    )

    assert profile.account_id == profile.contact.account_id == 17
    assert [item.thread_id for item in profile.recent_conversations] == [
        None,
        "generated-thread",
    ]
    assert profile.recent_conversations[0].anchor_email_id == 3
    assert profile.recent_conversations[0].direction == "inbound_only"
    assert profile.recent_conversations[1].anchor_email_id == 2
    assert profile.recent_conversations[1].observed_message_count == 2
    assert profile.recent_conversations[1].direction == "bidirectional"
    assert not hasattr(profile.recent_conversations[0], "subject")

    with pytest.raises(ContactNotFound, match="Contact not found"):
        build_contact_profile(
            corpus_rows=rows,
            owned_addresses=["owner@example.test"],
            user_id=9,
            account_id=17,
            contact_key="f" * 64,
            secret_key=SECRET,
        )


def test_corpus_statement_filters_before_limit_and_selects_no_sensitive_content_or_bcc():
    compiled = str(_corpus_statement(17).compile(
        dialect=postgresql.dialect(),
        compile_kwargs={"literal_binds": True},
    )).lower()

    assert "emails.account_id = 17" in compiled
    assert "emails.date is not null" in compiled
    assert "emails.is_draft is not true" in compiled
    assert "emails.is_spam is not true" in compiled
    assert "emails.is_trash is not true" in compiled
    assert "order by emails.date desc, emails.id desc" in compiled
    assert f"limit {CONTACT_CORPUS_ROW_LIMIT}" in compiled
    selected = compiled.split("\nfrom emails", 1)[0]
    for forbidden in (
        "bcc_addresses",
        "subject",
        "snippet",
        "body_text",
        "body_html",
        "raw_headers",
        "labels",
    ):
        assert forbidden not in selected


class _Result:
    def __init__(self, rows):
        self.rows = list(rows)

    def all(self):
        return list(self.rows)


class _Session:
    def __init__(self, *results):
        self.results = list(results)
        self.statements = []

    async def execute(self, statement):
        self.statements.append(statement)
        if not self.results:
            raise AssertionError("Unexpected database query")
        return _Result(self.results.pop(0))


@pytest.mark.asyncio
async def test_service_requires_active_owned_account_before_reading_corpus_and_excludes_all_self_addresses():
    accounts = [
        SimpleNamespace(id=17, email="owner@example.test", is_active=True),
        SimpleNamespace(id=18, email="alias@example.test", is_active=True),
    ]
    session = _Session(accounts, [
        _row(1, from_address="alias@example.test"),
        _row(2, from_address="external@example.test"),
    ])
    result = await query_contact_profiles(
        session,
        user_id=9,
        account_id=17,
        secret_key=SECRET,
    )
    assert [item.address for item in result.contacts] == ["external@example.test"]
    assert len(session.statements) == 2

    for account_rows in (
        [SimpleNamespace(id=17, email="owner@example.test", is_active=False)],
        [SimpleNamespace(id=99, email="foreign@example.test", is_active=True)],
        [],
    ):
        missing = _Session(account_rows)
        with pytest.raises(ContactNotFound, match="Contact not found"):
            await query_contact_profiles(
                missing,
                user_id=9,
                account_id=17,
                secret_key=SECRET,
            )
        assert len(missing.statements) == 1


def _app(*, authenticated: bool):
    app = FastAPI()
    app.include_router(contacts_router.router)

    async def fake_db():
        yield SimpleNamespace()

    app.dependency_overrides[get_db] = fake_db
    if authenticated:
        async def fake_user():
            return SimpleNamespace(id=9)

        app.dependency_overrides[get_current_user] = fake_user
    return app


@pytest.mark.asyncio
async def test_routes_are_session_only_post_no_store_and_return_allowlisted_fields(monkeypatch):
    anonymous = _app(authenticated=False)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=anonymous), base_url="https://test"
    ) as client:
        unauthorized = await client.post("/api/contacts/query", json={"account_id": 17})
    assert unauthorized.status_code == 401

    captured = {}

    async def fake_query(_db, **kwargs):
        captured.update(kwargs)
        return ContactQueryPage(
            account_id=17,
            page=1,
            page_size=50,
            total=1,
            total_pages=1,
            coverage=ContactCoverage(
                rows_scanned=3,
                row_limit=CONTACT_CORPUS_ROW_LIMIT,
                history_may_be_truncated=False,
                observed_oldest_at=NOW - timedelta(days=2),
                observed_newest_at=NOW,
            ),
            contacts=[_summary()],
        )

    async def fake_profile(_db, **kwargs):
        return ContactProfile(
            account_id=17,
            contact=_summary(),
            recent_conversations=[RecentContactConversation(
                account_id=17,
                anchor_email_id=41,
                thread_id="generated-thread",
                observed_last_at=NOW,
                observed_message_count=2,
                direction="bidirectional",
            )],
        )

    monkeypatch.setattr(contacts_router, "query_contact_profiles", fake_query)
    monkeypatch.setattr(contacts_router, "get_contact_profile", fake_profile)
    app = _app(authenticated=True)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://test"
    ) as client:
        query_response = await client.post("/api/contacts/query", json={
            "account_id": 17,
            "query": " generated contact ",
            "relationship": "all",
            "page": 1,
            "page_size": 50,
        })
        profile_response = await client.post("/api/contacts/profile", json={
            "account_id": 17,
            "contact_key": "a" * 64,
            "recent_limit": 8,
        })
        get_response = await client.get("/api/contacts/query")

    assert query_response.status_code == profile_response.status_code == 200
    assert query_response.headers["cache-control"] == "private, no-store"
    assert profile_response.headers["cache-control"] == "private, no-store"
    assert get_response.status_code == 405
    assert captured == {
        "user_id": 9,
        "account_id": 17,
        "secret_key": contacts_router.settings.secret_key,
        "query": "generated contact",
        "relationship": "all",
        "page": 1,
        "page_size": 50,
    }
    payload = query_response.json()
    assert set(payload) == {
        "account_id", "page", "page_size", "total", "total_pages", "coverage", "contacts",
    }
    assert set(payload["coverage"]) == {
        "rows_scanned", "row_limit", "history_may_be_truncated",
        "observed_oldest_at", "observed_newest_at",
    }
    assert set(payload["contacts"][0]) == {
        "account_id", "contact_key", "name", "address", "formatted", "relationship",
        "observed_message_count", "observed_received_count", "observed_sent_count",
        "observed_conversation_count", "observed_first_at", "observed_last_at",
        "observed_last_received_at", "observed_last_sent_at",
    }
    assert "subject" not in str(payload)
    assert set(profile_response.json()) == {
        "account_id", "contact", "recent_conversations",
    }
    assert set(profile_response.json()["recent_conversations"][0]) == {
        "account_id", "anchor_email_id", "thread_id", "observed_last_at",
        "observed_message_count", "direction",
    }


@pytest.mark.asyncio
async def test_foreign_inactive_missing_and_key_mismatch_share_non_disclosing_404(monkeypatch):
    async def missing(*_args, **_kwargs):
        raise ContactNotFound("Contact not found")

    monkeypatch.setattr(contacts_router, "query_contact_profiles", missing)
    monkeypatch.setattr(contacts_router, "get_contact_profile", missing)
    app = _app(authenticated=True)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://test"
    ) as client:
        responses = [
            await client.post("/api/contacts/query", json={"account_id": 999}),
            await client.post("/api/contacts/profile", json={
                "account_id": 17,
                "contact_key": "f" * 64,
            }),
        ]

    for response in responses:
        assert response.status_code == 404
        assert response.json() == {"detail": "Contact not found"}
        assert response.headers["cache-control"] == "private, no-store"
