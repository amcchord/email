import importlib.util
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from backend.routers.todos import (
    MAX_TODO_TITLE_LENGTH,
    TODO_NOT_FOUND_DETAIL,
    TodoCreate,
    TodoUpdate,
    create_todo,
    create_todos_from_email,
)


class FakeResult:
    def __init__(self, *, scalar=None, rows=None):
        self.scalar = scalar
        self.rows = list(rows or [])

    def scalar_one_or_none(self):
        return self.scalar

    def all(self):
        return self.rows


class FakeSession:
    def __init__(self, *results):
        self.results = list(results)
        self.statements = []
        self.added = []
        self.commit_count = 0
        self.refresh_count = 0

    async def execute(self, statement):
        self.statements.append(statement)
        if not self.results:
            raise AssertionError("Unexpected database query")
        return self.results.pop(0)

    def add(self, item):
        self.added.append(item)

    async def commit(self):
        self.commit_count += 1

    async def refresh(self, item):
        self.refresh_count += 1
        if item.id is None:
            item.id = 9000 + self.refresh_count
        if item.created_at is None:
            item.created_at = datetime(2026, 8, 30, tzinfo=timezone.utc)


def _sql(statement) -> str:
    return " ".join(str(statement).split())


def test_todo_input_models_strip_and_bound_user_controlled_fields():
    create = TodoCreate(title="  Generated manual Todo  ", email_id=17)
    update = TodoUpdate(title="  Updated title  ", status="dismissed")

    assert create.title == "Generated manual Todo"
    assert create.source == "manual"
    assert update.title == "Updated title"

    invalid_create_payloads = [
        {"title": "   "},
        {"title": "x" * (MAX_TODO_TITLE_LENGTH + 1)},
        {"title": "Generated", "email_id": 0},
        {"title": "Generated", "email_id": True},
        {"title": "Generated", "source": "ai_action_item"},
        {"title": "Generated", "status": "done"},
    ]
    for payload in invalid_create_payloads:
        with pytest.raises(ValidationError):
            TodoCreate(**payload)

    with pytest.raises(ValidationError):
        TodoUpdate(title="   ")
    with pytest.raises(ValidationError):
        TodoUpdate(status="unknown")
    with pytest.raises(ValidationError):
        TodoUpdate(source="manual")


@pytest.mark.asyncio
async def test_manual_todo_accepts_an_owned_source_email():
    db = FakeSession(FakeResult(scalar=17))

    response = await create_todo(
        body=TodoCreate(title="Generated manual Todo", email_id=17),
        db=db,
        user=SimpleNamespace(id=23),
    )

    assert response["email_id"] == 17
    assert response["source"] == "manual"
    assert response["status"] == "pending"
    assert len(db.added) == 1
    assert db.commit_count == 1
    assert db.refresh_count == 1
    ownership_sql = _sql(db.statements[0])
    assert "JOIN google_accounts ON emails.account_id = google_accounts.id" in ownership_sql
    assert "emails.id" in ownership_sql
    assert "google_accounts.user_id" in ownership_sql
    assert db.results == []


@pytest.mark.asyncio
async def test_manual_todo_without_email_does_not_perform_an_ownership_lookup():
    db = FakeSession()

    response = await create_todo(
        body=TodoCreate(title="Generated standalone Todo"),
        db=db,
        user=SimpleNamespace(id=23),
    )

    assert response["email_id"] is None
    assert db.statements == []
    assert db.commit_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("unavailable_kind", ["foreign", "nonexistent"])
async def test_manual_todo_hides_foreign_and_nonexistent_source_emails(unavailable_kind):
    db = FakeSession(FakeResult(scalar=None))

    with pytest.raises(HTTPException) as exc_info:
        await create_todo(
            body=TodoCreate(title=f"Generated {unavailable_kind}", email_id=404),
            db=db,
            user=SimpleNamespace(id=23),
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == TODO_NOT_FOUND_DETAIL
    assert db.added == []
    assert db.commit_count == 0
    assert db.results == []


@pytest.mark.asyncio
async def test_from_email_scopes_analysis_and_deduplicates_normalized_action_items():
    oversized = "z" * (MAX_TODO_TITLE_LENGTH + 25)
    analysis = SimpleNamespace(action_items=[
        "Existing action",
        "  New generated action  ",
        "New generated action",
        "   ",
        None,
        17,
        oversized,
    ])
    db = FakeSession(
        FakeResult(scalar=analysis),
        FakeResult(rows=[("  Existing action  ",)]),
    )

    response = await create_todos_from_email(
        email_id=71,
        db=db,
        user=SimpleNamespace(id=23),
    )

    assert response["created"] == 2
    assert [todo["title"] for todo in response["todos"]] == [
        "New generated action",
        oversized[:MAX_TODO_TITLE_LENGTH],
    ]
    assert all(todo["source"] == "ai_action_item" for todo in response["todos"])
    assert all(todo["email_id"] == 71 for todo in response["todos"])
    assert db.commit_count == 1
    assert db.refresh_count == 2
    analysis_sql = _sql(db.statements[0])
    assert "JOIN emails ON ai_analyses.email_id = emails.id" in analysis_sql
    assert "JOIN google_accounts ON emails.account_id = google_accounts.id" in analysis_sql
    assert "google_accounts.user_id" in analysis_sql
    duplicate_sql = _sql(db.statements[1])
    assert "todo_items.user_id" in duplicate_sql
    assert "todo_items.email_id" in duplicate_sql
    assert db.results == []


@pytest.mark.asyncio
@pytest.mark.parametrize("action_items", [[], {}, "not-a-list"])
async def test_from_email_with_no_action_items_is_a_noop(action_items):
    db = FakeSession(FakeResult(scalar=SimpleNamespace(action_items=action_items)))

    response = await create_todos_from_email(
        email_id=71,
        db=db,
        user=SimpleNamespace(id=23),
    )

    assert response == {
        "message": "No action items to add",
        "created": 0,
        "todos": [],
    }
    assert db.added == []
    assert db.commit_count == 0
    assert db.results == []


@pytest.mark.asyncio
@pytest.mark.parametrize("unavailable_kind", ["foreign", "nonexistent"])
async def test_from_email_hides_foreign_and_nonexistent_analysis(unavailable_kind):
    db = FakeSession(FakeResult(scalar=None))

    with pytest.raises(HTTPException) as exc_info:
        await create_todos_from_email(
            email_id=404,
            db=db,
            user=SimpleNamespace(id=23),
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == TODO_NOT_FOUND_DETAIL
    assert db.added == []
    assert db.commit_count == 0
    assert len(db.statements) == 1
    assert db.results == []


def _load_migration():
    migration_path = (
        Path(__file__).parents[2]
        / "alembic"
        / "versions"
        / "c0d1e2f3a4b5_sanitize_todo_email_ownership.py"
    )
    spec = importlib.util.spec_from_file_location("todo_ownership_migration", migration_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_todo_ownership_migration_enforces_and_sanitizes_the_boundary(monkeypatch):
    migration = _load_migration()
    statements = []
    monkeypatch.setattr(migration.op, "execute", lambda statement: statements.append(_sql(statement)))

    migration.upgrade()

    assert migration.down_revision == "b9c0d1e2f3a4"
    assert len(statements) == 4
    assert "CREATE FUNCTION enforce_todo_email_ownership()" in statements[0]
    assert "account.user_id = NEW.user_id" in statements[0]
    assert "CREATE TRIGGER trg_todo_items_email_ownership" in statements[1]
    assert "DELETE FROM todo_items AS todo" in statements[2]
    assert "todo.source = 'ai_action_item'" in statements[2]
    assert "account.user_id = todo.user_id" in statements[2]
    assert "UPDATE todo_items AS todo" in statements[3]
    for field in ("email_id", "ai_draft_status", "ai_draft_body", "ai_draft_to"):
        assert f"{field} = NULL" in statements[3]

    statements.clear()
    migration.downgrade()
    assert statements == [
        "DROP TRIGGER IF EXISTS trg_todo_items_email_ownership ON todo_items",
        "DROP FUNCTION IF EXISTS enforce_todo_email_ownership()",
    ]
