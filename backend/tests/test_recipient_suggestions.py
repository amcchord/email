"""Focused, provider-free tests for Compose correspondent suggestions."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.dialects import postgresql

import backend.routers.compose as compose_router
from backend.database import get_db
from backend.routers.auth import get_current_user
from backend.services.recipient_suggestions import (
    RECIPIENT_CORPUS_ROW_LIMIT,
    RecipientAccountNotFound,
    RecipientSuggestion,
    _corpus_statement,
    build_recipient_suggestions,
    suggest_recipients,
)


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


def _at(days):
    return datetime(2026, 8, 1, tzinfo=timezone.utc) + timedelta(days=days)


def test_normalizes_legacy_and_object_rows_without_splitting_quoted_names():
    suggestions = build_recipient_suggestions(
        corpus_rows=[
            SimpleNamespace(
                from_name="Doe,\tJane",
                from_address="Jane.Doe@Example.Test",
                date=_at(3),
                is_sent=False,
                is_draft=False,
                is_spam=False,
                is_trash=False,
            ),
            SimpleNamespace(
                to_addresses=['"Doe, Jane" <jane.doe@example.test>'],
                cc_addresses=[{"display_name": "Team Contact", "address": "team@example.test"}],
                bcc_addresses=["bad, second@example.test", "self@example.test"],
                date=_at(4),
                is_sent=True,
                is_draft=False,
                is_spam=False,
                is_trash=False,
            ),
        ],
        owned_addresses=["self@example.test"],
        query="",
        limit=10,
    )

    assert suggestions == [
        RecipientSuggestion(
            name="Doe, Jane",
            address="jane.doe@example.test",
            formatted='"Doe, Jane" <jane.doe@example.test>',
        ),
        RecipientSuggestion(
            name="Team Contact",
            address="team@example.test",
            formatted="Team Contact <team@example.test>",
        ),
    ]


def test_ranking_prefers_match_tier_then_outgoing_recency_frequency_and_address():
    incoming = [
        SimpleNamespace(from_name="Jane Exact", from_address="jane@example.test", date=_at(5), is_sent=False),
        SimpleNamespace(from_name="Janice Recent", from_address="janice@example.test", date=_at(9), is_sent=False),
        SimpleNamespace(from_name="Janet Frequent", from_address="janet@example.test", date=_at(2), is_sent=False),
        SimpleNamespace(from_name="Janet Frequent", from_address="JANET@example.test", date=_at(1), is_sent=False),
    ]
    outgoing = [
        SimpleNamespace(
            to_addresses=[{"name": "Janet Frequent", "address": "janet@example.test"}],
            cc_addresses=[],
            bcc_addresses=[],
            date=_at(3),
            is_sent=True,
        ),
    ]

    prefix = build_recipient_suggestions(
        corpus_rows=[*incoming, *outgoing],
        owned_addresses=[],
        query="jan",
        limit=10,
    )
    assert [item.address for item in prefix] == [
        "janet@example.test",
        "janice@example.test",
        "jane@example.test",
    ]

    exact = build_recipient_suggestions(
        corpus_rows=[*incoming, *outgoing],
        owned_addresses=[],
        query="jane@example.test",
        limit=10,
    )
    assert [item.address for item in exact] == ["jane@example.test"]


def test_corpus_statement_is_account_date_index_compatible_and_hard_bounded():
    corpus_sql = str(_corpus_statement(17).compile(
        dialect=postgresql.dialect(),
        compile_kwargs={"literal_binds": True},
    )).lower()

    assert "emails.account_id = 17" in corpus_sql
    assert "emails.date is not null" in corpus_sql
    assert "order by emails.date desc" in corpus_sql
    assert f"limit {RECIPIENT_CORPUS_ROW_LIMIT}" in corpus_sql
    where_clause = corpus_sql.split("\nwhere ", 1)[1].split(" order by ", 1)[0]
    assert "is_sent" not in where_clause
    assert "is_draft" not in where_clause
    assert "is_spam" not in where_clause
    assert "is_trash" not in where_clause


def test_status_classification_happens_after_the_bounded_corpus_read():
    corpus = [
        SimpleNamespace(
            from_name="Incoming",
            from_address="incoming@example.test",
            date=_at(8),
            is_sent=False,
            is_draft=False,
            is_spam=False,
            is_trash=False,
        ),
        SimpleNamespace(
            to_addresses=["outgoing@example.test"],
            cc_addresses=[],
            bcc_addresses=[],
            date=_at(7),
            is_sent=True,
            is_draft=False,
            is_spam=False,
            is_trash=False,
        ),
        SimpleNamespace(
            from_address="draft@example.test",
            date=_at(9),
            is_sent=False,
            is_draft=True,
            is_spam=False,
            is_trash=False,
        ),
        SimpleNamespace(
            from_address="spam@example.test",
            date=_at(9),
            is_sent=False,
            is_draft=False,
            is_spam=True,
            is_trash=False,
        ),
        SimpleNamespace(
            to_addresses=["trash@example.test"],
            date=_at(9),
            is_sent=True,
            is_draft=False,
            is_spam=False,
            is_trash=True,
        ),
    ]

    suggestions = build_recipient_suggestions(
        corpus_rows=corpus,
        owned_addresses=[],
        limit=10,
    )
    assert [item.address for item in suggestions] == [
        "outgoing@example.test",
        "incoming@example.test",
    ]


@pytest.mark.asyncio
async def test_service_requires_an_active_owned_account_and_excludes_all_owned_addresses():
    accounts = [
        SimpleNamespace(id=17, email="owner@example.test", is_active=True),
        SimpleNamespace(id=18, email="alias@example.test", is_active=True),
    ]
    corpus = [
        SimpleNamespace(from_name="Owner", from_address="alias@example.test", date=_at(8), is_sent=False),
        SimpleNamespace(from_name="External", from_address="external@example.test", date=_at(7), is_sent=False),
        SimpleNamespace(
            to_addresses=["owner@example.test", "friend@example.test"],
            cc_addresses=[],
            bcc_addresses=[],
            date=_at(6),
            is_sent=True,
        ),
    ]
    session = _Session(accounts, corpus)

    result = await suggest_recipients(
        session,
        user_id=9,
        account_id=17,
        query="",
        limit=8,
    )

    assert [item.address for item in result] == [
        "friend@example.test",
        "external@example.test",
    ]
    assert len(session.statements) == 2

    missing_session = _Session([
        SimpleNamespace(id=17, email="owner@example.test", is_active=False),
    ])
    with pytest.raises(RecipientAccountNotFound, match="Account not found"):
        await suggest_recipients(
            missing_session,
            user_id=9,
            account_id=17,
        )
    assert len(missing_session.statements) == 1


def _app(*, authenticated):
    app = FastAPI()
    app.include_router(compose_router.router)

    async def fake_db():
        yield SimpleNamespace()

    app.dependency_overrides[get_db] = fake_db
    if authenticated:
        async def fake_user():
            return SimpleNamespace(id=9)

        app.dependency_overrides[get_current_user] = fake_user
    return app


@pytest.mark.asyncio
async def test_endpoint_is_session_only_and_returns_only_public_recipient_fields(monkeypatch):
    anonymous = _app(authenticated=False)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=anonymous), base_url="https://test"
    ) as client:
        unauthorized = await client.get(
            "/api/compose/recipients?account_id=17&q=jan&limit=8"
        )
    assert unauthorized.status_code == 401

    captured = {}

    async def fake_suggestions(_db, **kwargs):
        captured.update(kwargs)
        return [RecipientSuggestion(
            name="Doe, Jane",
            address="jane@example.test",
            formatted='"Doe, Jane" <jane@example.test>',
        )]

    monkeypatch.setattr(compose_router, "suggest_recipients", fake_suggestions)
    authenticated = _app(authenticated=True)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=authenticated), base_url="https://test"
    ) as client:
        response = await client.get(
            "/api/compose/recipients?account_id=17&q=jan&limit=8"
        )

    assert response.status_code == 200
    assert response.json() == {"suggestions": [{
        "name": "Doe, Jane",
        "address": "jane@example.test",
        "formatted": '"Doe, Jane" <jane@example.test>',
    }]}
    assert captured == {"user_id": 9, "account_id": 17, "query": "jan", "limit": 8}


@pytest.mark.asyncio
async def test_endpoint_maps_foreign_or_inactive_account_to_same_404(monkeypatch):
    async def missing(*_args, **_kwargs):
        raise RecipientAccountNotFound("Account not found")

    monkeypatch.setattr(compose_router, "suggest_recipients", missing)
    app = _app(authenticated=True)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://test"
    ) as client:
        missing_response = await client.get(
            "/api/compose/recipients?account_id=999&q=x&limit=8"
        )
        invalid_limit = await client.get(
            "/api/compose/recipients?account_id=17&q=x&limit=21"
        )

    assert missing_response.status_code == 404
    assert missing_response.json() == {"detail": "Account not found"}
    assert invalid_limit.status_code == 422
