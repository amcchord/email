"""Focused checks for the private metadata-only attachment workspace."""

from datetime import datetime, timedelta, timezone
import importlib
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
import httpx
import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy.dialects import postgresql

import backend.routers.attachments as attachment_router
from backend.database import get_db
from backend.models.email import Attachment
from backend.routers.auth import get_current_user
from backend.schemas.attachment_workspace import (
    AttachmentWorkspaceQueryRequest,
    AttachmentWorkspaceQueryResponse,
)
from backend.services.attachment_workspace import (
    AttachmentWorkspaceInvalidCursor,
    AttachmentWorkspaceNotFound,
    _attachment_query_statement,
    _decode_cursor,
    _encode_cursor,
    _safe_sender_address,
    query_attachment_workspace,
)


NOW = datetime(2026, 8, 31, 18, 0, tzinfo=timezone.utc)
SECRET = "generated-attachment-workspace-secret"


class _ScalarResult:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class _RowsResult:
    def __init__(self, rows):
        self.rows = rows

    def all(self):
        return self.rows


class _Session:
    def __init__(self, rows=(), *, account=17):
        self.rows = list(rows)
        self.account = account
        self.statements = []

    async def execute(self, statement):
        self.statements.append(statement)
        if len(self.statements) == 1:
            return _ScalarResult(self.account)
        return _RowsResult(self.rows)


def _row(row_id: int, *, account_id: int = 17, days: int = 0, **values):
    defaults = {
        "account_id": account_id,
        "attachment_id": row_id,
        "email_id": 100 + row_id,
        "filename": f"generated-{row_id}.pdf",
        "content_type": "application/pdf",
        "size_bytes": row_id * 100,
        "message_date": NOW - timedelta(days=days),
        "sender_name": "Generated Sender",
        "sender_address": "sender@example.test",
        "subject": "Generated private subject",
        "is_sent": False,
        # Fields that the response must never serialize.
        "gmail_attachment_id": "private-provider-id",
        "storage_path": "/private/generated/path",
        "content_id": "private-content-id",
        "snippet": "private generated snippet",
        "body_text": "private generated body",
        "to_addresses": [{"address": "private@example.test"}],
        "bcc_addresses": [{"address": "hidden@example.test"}],
    }
    defaults.update(values)
    return SimpleNamespace(**defaults)


def _compile(statement) -> str:
    return str(statement.compile(
        dialect=postgresql.dialect(),
        compile_kwargs={"literal_binds": True},
    ))


def test_request_contract_is_exact_and_bounded():
    request = AttachmentWorkspaceQueryRequest(
        account_id=17,
        query="  generated   report  ",
        kind="document",
        direction="received",
        page_size=50,
    )
    assert request.query == "generated report"

    invalid_payloads = [
        {"account_id": 0},
        {"account_id": True},
        {"account_id": 17, "query": "x" * 257},
        {"account_id": 17, "query": "bad\u0000query"},
        {"account_id": 17, "kind": "executable"},
        {"account_id": 17, "direction": "both"},
        {"account_id": 17, "page_size": 51},
        {"account_id": 17, "unknown": "field"},
    ]
    for payload in invalid_payloads:
        with pytest.raises(ValueError):
            AttachmentWorkspaceQueryRequest.model_validate(payload)


def test_query_sql_keeps_ownership_filters_and_order_inside_one_boundary():
    compiled = _compile(_attachment_query_statement(
        user_id=9,
        account_id=17,
        query="100%_literal",
        kind="document",
        direction="received",
        page_size=7,
    ))

    assert "JOIN emails ON emails.id = attachments.email_id" in compiled
    assert "JOIN google_accounts ON google_accounts.id = emails.account_id" in compiled
    assert "google_accounts.user_id = 9" in compiled
    assert "google_accounts.id = 17" in compiled
    assert "google_accounts.is_active IS true" in compiled
    assert "emails.account_id = 17" in compiled
    assert "emails.is_draft IS NOT true" in compiled
    assert "emails.is_spam IS NOT true" in compiled
    assert "emails.is_trash IS NOT true" in compiled
    assert "attachments.is_inline IS NOT true" in compiled
    assert "emails.is_sent IS NOT true" in compiled
    assert compiled.count(r"100\\%%\\_literal") == 4
    assert "lower(coalesce(attachments.filename" in compiled
    assert "lower(coalesce(emails.subject" in compiled
    assert "lower(coalesce(emails.from_name" in compiled
    assert "lower(coalesce(emails.from_address" in compiled
    assert "ORDER BY emails.date DESC NULLS LAST, emails.id DESC, attachments.id DESC" in compiled
    assert "LIMIT 8" in compiled


def test_kind_and_direction_filters_are_local_metadata_predicates():
    compiled_by_kind = {
        kind: _compile(_attachment_query_statement(
            user_id=9,
            account_id=17,
            query="",
            kind=kind,
            direction="sent" if kind == "archive" else "all",
            page_size=10,
        ))
        for kind in ("document", "image", "archive", "other")
    }
    assert "application/pdf" in compiled_by_kind["document"]
    assert "image/%" in compiled_by_kind["image"]
    assert "application/zip" in compiled_by_kind["archive"]
    assert "emails.is_sent IS true" in compiled_by_kind["archive"]
    assert "NOT" in compiled_by_kind["other"]


def test_sender_address_is_canonical_or_omitted_without_breaking_the_page():
    assert _safe_sender_address("Generated Sender <Sender@Example.Test>") == "sender@example.test"
    assert _safe_sender_address("MAILER-DAEMON") is None
    assert _safe_sender_address("first@example.test, second@example.test") is None
    assert _safe_sender_address("sender@example.test\r\nBcc: hidden@example.test") is None


@pytest.mark.asyncio
async def test_query_returns_sanitized_allowlisted_items_and_signed_next_cursor():
    rows = [
        _row(
            1,
            filename='../../R\u00e9sum\u00e9\r\n".pdf',
            content_type="text/html\r\nX-Injected: true",
            size_bytes=-1,
            sender_name="Generated\u0000 Sender",
            sender_address="sender@example.test\r\n",
            subject="Private\u0000 generated\nsubject",
        ),
        _row(2, days=1),
    ]
    session = _Session(rows)
    page = await query_attachment_workspace(
        session,
        user_id=9,
        account_id=17,
        secret_key=SECRET,
        query="report",
        kind="document",
        direction="all",
        page_size=1,
    )

    assert page.account_id == 17
    assert page.has_more is True
    assert page.next_cursor
    assert len(page.items) == 1
    item = page.items[0]
    assert item.filename == 'Résumé".pdf'
    assert item.content_type == "application/octet-stream"
    assert item.size_bytes is None
    assert item.sender_name == "Generated Sender"
    assert item.sender_address == "sender@example.test"
    assert item.subject == "Private generatedsubject"
    assert _decode_cursor(
        page.next_cursor,
        secret_key=SECRET,
        user_id=9,
        account_id=17,
        query="report",
        kind="document",
        direction="all",
    ) == (NOW, 101, 1)

    payload = page.model_dump(mode="json")
    assert set(payload) == {"account_id", "items", "next_cursor", "has_more"}
    assert set(payload["items"][0]) == {
        "account_id", "attachment_id", "email_id", "filename", "content_type",
        "size_bytes", "message_date", "sender_name", "sender_address", "subject",
        "is_sent",
    }
    serialized = str(payload)
    for forbidden in (
        "gmail_attachment_id", "storage_path", "content_id", "snippet", "body_text",
        "to_addresses", "bcc_addresses", "private-provider-id", "/private/generated/path",
    ):
        assert forbidden not in serialized


@pytest.mark.asyncio
async def test_foreign_missing_inactive_and_mixed_account_rows_fail_closed():
    for _unavailable_kind in ("foreign", "missing", "inactive"):
        with pytest.raises(AttachmentWorkspaceNotFound):
            await query_attachment_workspace(
                _Session(account=None),
                user_id=9,
                account_id=17,
                secret_key=SECRET,
            )

    with pytest.raises(AttachmentWorkspaceNotFound):
        await query_attachment_workspace(
            _Session([_row(1, account_id=18)]),
            user_id=9,
            account_id=17,
            secret_key=SECRET,
        )


def test_cursor_is_bound_to_user_account_and_every_filter():
    cursor = _encode_cursor(
        secret_key=SECRET,
        user_id=9,
        account_id=17,
        query="generated report",
        kind="document",
        direction="received",
        message_date=NOW,
        email_id=101,
        attachment_id=1,
    )
    valid = {
        "secret_key": SECRET,
        "user_id": 9,
        "account_id": 17,
        "query": "generated report",
        "kind": "document",
        "direction": "received",
    }
    assert _decode_cursor(cursor, **valid) == (NOW, 101, 1)

    mutations = (
        {"secret_key": "other-secret"},
        {"user_id": 10},
        {"account_id": 18},
        {"query": "other report"},
        {"kind": "image"},
        {"direction": "sent"},
    )
    for mutation in mutations:
        with pytest.raises(AttachmentWorkspaceInvalidCursor):
            _decode_cursor(cursor, **(valid | mutation))
    with pytest.raises(AttachmentWorkspaceInvalidCursor):
        _decode_cursor(f"{cursor[:-1]}x", **valid)

    null_date_cursor = _encode_cursor(
        secret_key=SECRET,
        user_id=9,
        account_id=17,
        query="generated report",
        kind="document",
        direction="received",
        message_date=None,
        email_id=80,
        attachment_id=3,
    )
    assert _decode_cursor(null_date_cursor, **valid) == (None, 80, 3)
    null_page_sql = _compile(_attachment_query_statement(
        user_id=9,
        account_id=17,
        query="generated report",
        kind="document",
        direction="received",
        page_size=10,
        cursor_position=(None, 80, 3),
    ))
    assert "emails.date IS NULL" in null_page_sql
    assert "emails.id < 80" in null_page_sql
    assert "attachments.id < 3" in null_page_sql


@pytest.mark.asyncio
async def test_metadata_query_never_calls_cache_bytes_or_provider(monkeypatch):
    from backend.services import attachments as bytes_service
    from backend.services.gmail import GmailService

    async def forbidden(*_args, **_kwargs):
        raise AssertionError("Metadata queries must never load attachment bytes")

    monkeypatch.setattr(bytes_service, "load_attachment_bytes", forbidden)
    monkeypatch.setattr(GmailService, "get_attachment", forbidden)
    page = await query_attachment_workspace(
        _Session([_row(1)]),
        user_id=9,
        account_id=17,
        secret_key=SECRET,
    )
    assert [item.attachment_id for item in page.items] == [1]


def _app(*, authenticated: bool):
    app = FastAPI()
    app.include_router(attachment_router.router)

    async def fake_db():
        yield SimpleNamespace()

    app.dependency_overrides[get_db] = fake_db
    if authenticated:
        async def fake_user():
            return SimpleNamespace(id=9)

        app.dependency_overrides[get_current_user] = fake_user
    return app


@pytest.mark.asyncio
async def test_route_is_session_only_post_no_store_and_allowlisted(monkeypatch):
    anonymous = _app(authenticated=False)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=anonymous), base_url="https://test"
    ) as client:
        unauthorized = await client.post("/api/attachments/query", json={"account_id": 17})
    assert unauthorized.status_code == 401
    assert unauthorized.headers["cache-control"] == "private, no-store"

    captured = {}

    async def fake_query(_db, **kwargs):
        captured.update(kwargs)
        return AttachmentWorkspaceQueryResponse(
            account_id=17,
            items=[{
                "account_id": 17,
                "attachment_id": 1,
                "email_id": 101,
                "filename": "generated.pdf",
                "content_type": "application/pdf",
                "size_bytes": 123,
                "message_date": NOW,
                "sender_name": "Generated Sender",
                "sender_address": "sender@example.test",
                "subject": "Generated subject",
                "is_sent": False,
            }],
            next_cursor=None,
            has_more=False,
        )

    monkeypatch.setattr(attachment_router, "query_attachment_workspace", fake_query)
    app = _app(authenticated=True)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://test"
    ) as client:
        response = await client.post("/api/attachments/query", json={
            "account_id": 17,
            "query": " generated   report ",
            "kind": "document",
            "direction": "received",
            "page_size": 25,
        })
        wrong_method = await client.get("/api/attachments/query")
        invalid = await client.post("/api/attachments/query", json={
            "account_id": 17,
            "extra": "forbidden",
        })

    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    assert wrong_method.status_code == 405
    assert invalid.status_code == 422
    assert invalid.headers["cache-control"] == "private, no-store"
    assert captured == {
        "user_id": 9,
        "account_id": 17,
        "secret_key": attachment_router.settings.secret_key,
        "query": "generated report",
        "kind": "document",
        "direction": "received",
        "cursor": None,
        "page_size": 25,
    }
    assert set(response.json()["items"][0]) == {
        "account_id", "attachment_id", "email_id", "filename", "content_type",
        "size_bytes", "message_date", "sender_name", "sender_address", "subject",
        "is_sent",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "expected_status", "expected_detail"),
    [
        (AttachmentWorkspaceNotFound("hidden"), 404, "Attachment workspace not found"),
        (AttachmentWorkspaceInvalidCursor("hidden"), 422, "Attachment cursor is invalid"),
    ],
)
async def test_route_errors_are_non_disclosing_and_no_store(
    monkeypatch,
    error,
    expected_status,
    expected_detail,
):
    async def fail(*_args, **_kwargs):
        raise error

    monkeypatch.setattr(attachment_router, "query_attachment_workspace", fail)
    app = _app(authenticated=True)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://test"
    ) as client:
        response = await client.post("/api/attachments/query", json={"account_id": 17})
    assert response.status_code == expected_status
    assert response.json() == {"detail": expected_detail}
    assert response.headers["cache-control"] == "private, no-store"


def test_attachment_email_index_model_and_migration_upgrade_downgrade(monkeypatch):
    assert "ix_attachments_email_id" in {index.name for index in Attachment.__table__.indexes}
    migration_path = (
        Path(__file__).parents[2]
        / "alembic/versions/b1c2d3e4f5a6_add_attachment_email_index.py"
    )
    spec = importlib.util.spec_from_file_location("attachment_index_migration", migration_path)
    assert spec and spec.loader
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    assert migration.revision == "b1c2d3e4f5a6"
    assert migration.down_revision == "a0b1c2d3e4f5"
    config = Config()
    config.set_main_option("script_location", str(Path(__file__).parents[2] / "alembic"))
    script = ScriptDirectory.from_config(config)
    assert script.get_heads() == ["c1d2e3f4a5b6"]
    assert script.get_revision("b1c2d3e4f5a6").down_revision == "a0b1c2d3e4f5"

    calls = []
    monkeypatch.setattr(
        migration.op,
        "create_index",
        lambda name, table, columns, unique=False: calls.append(
            ("create", name, table, columns, unique)
        ),
    )
    monkeypatch.setattr(
        migration.op,
        "drop_index",
        lambda name, table_name: calls.append(("drop", name, table_name)),
    )
    migration.upgrade()
    migration.downgrade()
    assert calls == [
        ("create", "ix_attachments_email_id", "attachments", ["email_id"], False),
        ("drop", "ix_attachments_email_id", "attachments"),
    ]
