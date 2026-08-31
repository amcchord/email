"""Focused contracts for private deterministic Saved Views."""

from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import UUID, uuid4

import httpx
import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi import FastAPI
from pydantic import ValidationError
from sqlalchemy.dialects import postgresql

import backend.routers.saved_views as saved_views_router
from backend.database import get_db
from backend.models.saved_view import SavedView
from backend.routers.auth import get_current_user
from backend.schemas.saved_view import (
    MAX_SAVED_VIEWS,
    SavedViewCreate,
    SavedViewReorder,
    SavedViewReplace,
)
from backend.services.saved_views import (
    SavedViewConflict,
    SavedViewNotFound,
    _owned_account_statement,
    _owned_view_statement,
    create_saved_view,
    saved_view_matches,
    validate_reorder,
)


NOW = datetime(2026, 8, 31, tzinfo=timezone.utc)


def _payload(**overrides):
    values = {
        "create_id": str(uuid4()),
        "name": "  VIP   Launch ",
        "account_id": 7,
        "query": 'from:vip@example.test subject:"Launch plan"',
    }
    values.update(overrides)
    return values


def _row(request=None, **overrides):
    request = request or SavedViewCreate(**_payload())
    values = {
        "row_id": 1,
        "id": uuid4(),
        "create_id": request.create_id,
        "user_id": 17,
        "name": request.name,
        "account_id": request.account_id,
        "query": request.query,
        "position": 0,
        "revision": 1,
        "created_at": NOW,
        "updated_at": NOW,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _app(*, authenticated: bool):
    app = FastAPI()
    app.include_router(saved_views_router.router)

    async def fake_db():
        yield SimpleNamespace()

    app.dependency_overrides[get_db] = fake_db
    if authenticated:
        async def fake_user():
            return SimpleNamespace(id=17)

        app.dependency_overrides[get_current_user] = fake_user
    return app


class _ScalarResult:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class _ScriptedSession:
    def __init__(self, execute_values, *, scalar_value=0):
        self.execute_values = list(execute_values)
        self.scalar_value = scalar_value
        self.added = []

    async def execute(self, _statement):
        return _ScalarResult(self.execute_values.pop(0))

    async def scalar(self, _statement):
        return self.scalar_value

    def add(self, value):
        self.added.append(value)


def test_schema_normalizes_name_and_reuses_bounded_search_parser():
    request = SavedViewCreate(**_payload())
    assert request.name == "VIP Launch"
    assert request.query == 'from:vip@example.test subject:"Launch plan"'

    with pytest.raises(ValidationError, match="cannot be empty"):
        SavedViewCreate(**_payload(query="   "))
    with pytest.raises(ValidationError, match="unterminated quote"):
        SavedViewCreate(**_payload(query='subject:"unfinished'))
    with pytest.raises(ValidationError, match="512 characters"):
        SavedViewCreate(**_payload(query="x" * 513))
    with pytest.raises(ValidationError):
        SavedViewCreate(**_payload(name="x" * 81))
    with pytest.raises(ValidationError):
        SavedViewCreate(**_payload(account_id=True))


def test_frozen_payload_names_and_strict_update_reorder_contracts():
    create = SavedViewCreate(**_payload())
    replacement = SavedViewReplace(
        name=create.name,
        query=create.query,
        account_id=create.account_id,
        revision=3,
    )
    assert set(create.model_dump()) == {"create_id", "name", "account_id", "query"}
    assert set(replacement.model_dump()) == {
        "name", "account_id", "query", "revision"
    }

    first, second = uuid4(), uuid4()
    reorder = SavedViewReorder(
        expected_order=[first, second],
        view_ids=[second, first],
    )
    assert set(reorder.model_dump()) == {"expected_order", "view_ids"}
    with pytest.raises(ValidationError, match="duplicate"):
        SavedViewReorder(expected_order=[first], view_ids=[first, first])


def test_model_and_reserved_migration_are_content_free_owner_scoped_head():
    assert [column.name for column in SavedView.__table__.columns] == [
        "row_id", "id", "create_id", "user_id", "account_id", "name",
        "query", "position", "revision", "created_at", "updated_at",
    ]
    constraints = {constraint.name for constraint in SavedView.__table__.constraints}
    assert {
        "ck_saved_views_revision",
        "ck_saved_views_position",
        "ck_saved_views_name",
        "ck_saved_views_query",
        "uq_saved_views_user_public_id",
        "uq_saved_views_user_client_create_id",
        "uq_saved_views_user_position",
    } <= constraints
    assert {index.name for index in SavedView.__table__.indexes} == {
        "uq_saved_views_user_name_ci",
        "ix_saved_views_user_order",
    }
    account_fk = next(
        foreign_key
        for foreign_key in SavedView.__table__.foreign_key_constraints
        if list(foreign_key.columns)[0].name == "account_id"
    )
    assert account_fk.ondelete == "CASCADE"

    config = Config()
    config.set_main_option("script_location", "alembic")
    scripts = ScriptDirectory.from_config(config)
    assert scripts.get_revision("a0b1c2d3e4f5").down_revision == "f9a0b1c2d3e4"
    assert scripts.get_heads() == ["c1d2e3f4a5b6"]


def test_owner_predicates_bind_both_user_and_exact_resource_ids():
    view_id = uuid4()
    view_statement = _owned_view_statement(user_id=17, view_id=view_id).compile(
        dialect=postgresql.dialect()
    )
    account_statement = _owned_account_statement(user_id=17, account_id=7).compile(
        dialect=postgresql.dialect()
    )
    view_sql = str(view_statement)
    account_sql = str(account_statement)
    assert "saved_views.user_id" in view_sql and "saved_views.id" in view_sql
    assert 17 in view_statement.params.values() and view_id in view_statement.params.values()
    assert "google_accounts.user_id" in account_sql and "google_accounts.id" in account_sql
    assert 17 in account_statement.params.values() and 7 in account_statement.params.values()


def test_idempotency_matches_all_mutable_content_and_is_per_owner():
    request = SavedViewCreate(**_payload())
    row = _row(request)
    assert saved_view_matches(row, request) is True
    changed = SavedViewCreate(**_payload(
        create_id=str(request.create_id),
        query="from:other@example.test",
    ))
    assert saved_view_matches(row, changed) is False


@pytest.mark.asyncio
async def test_create_replay_returns_existing_without_consuming_quota():
    request = SavedViewCreate(**_payload())
    row = _row(request)
    db = _ScriptedSession([None, row])
    replay, created = await create_saved_view(db, user_id=17, request=request)
    assert replay is row
    assert created is False
    assert db.execute_values == []
    assert db.added == []


@pytest.mark.asyncio
async def test_create_rejects_foreign_account_and_collection_limit():
    account_request = SavedViewCreate(**_payload())
    foreign_account_db = _ScriptedSession([None, None, None])
    with pytest.raises(SavedViewNotFound, match="Saved view not found"):
        await create_saved_view(
            foreign_account_db,
            user_id=17,
            request=account_request,
        )
    assert foreign_account_db.added == []

    unscoped = SavedViewCreate(**_payload(account_id=None))
    full_db = _ScriptedSession([None, None], scalar_value=MAX_SAVED_VIEWS)
    with pytest.raises(SavedViewConflict, match=str(MAX_SAVED_VIEWS)):
        await create_saved_view(full_db, user_id=17, request=unscoped)
    assert full_db.added == []


def test_reorder_requires_current_order_and_exact_membership():
    first, second, foreign = uuid4(), uuid4(), uuid4()
    validate_reorder(
        [first, second],
        expected_order=[first, second],
        view_ids=[second, first],
    )
    with pytest.raises(SavedViewConflict, match="changed elsewhere"):
        validate_reorder(
            [first, second],
            expected_order=[second, first],
            view_ids=[second, first],
        )
    with pytest.raises(SavedViewConflict, match="exact collection"):
        validate_reorder(
            [first, second],
            expected_order=[first, second],
            view_ids=[first, foreign],
        )


@pytest.mark.asyncio
async def test_routes_are_authenticated_no_store_and_use_frozen_shapes(monkeypatch):
    unauthenticated = _app(authenticated=False)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=unauthenticated), base_url="https://test"
    ) as client:
        response = await client.get("/api/saved-views")
    assert response.status_code == 401
    assert response.headers["cache-control"] == "private, no-store"

    request = SavedViewCreate(**_payload())
    row = _row(request)

    async def create(_db, *, user_id, request):
        assert user_id == 17 and request.create_id == row.create_id
        return row, True

    async def list_views(_db, *, user_id):
        assert user_id == 17
        return [row]

    monkeypatch.setattr(saved_views_router, "create_saved_view", create)
    monkeypatch.setattr(saved_views_router, "list_saved_views", list_views)
    app = _app(authenticated=True)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://test"
    ) as client:
        collection = await client.get("/api/saved-views")
        created = await client.post("/api/saved-views", json=_payload(
            create_id=str(request.create_id),
        ))
        invalid = await client.post("/api/saved-views", json={
            **_payload(), "unexpected": "message content"
        })
    assert collection.status_code == 200
    assert set(collection.json()) == {"items", "max_views"}
    assert collection.json()["max_views"] == MAX_SAVED_VIEWS
    assert created.status_code == 201
    assert created.headers["cache-control"] == "private, no-store"
    assert set(created.json()) == {
        "id", "create_id", "name", "account_id", "query", "revision",
        "position", "created_at", "updated_at",
    }
    assert invalid.status_code == 422
    assert invalid.headers["cache-control"] == "private, no-store"


@pytest.mark.asyncio
async def test_name_and_revision_conflicts_are_409_no_store(monkeypatch):
    async def conflict(*_args, **_kwargs):
        raise SavedViewConflict("That Saved View name is already in use")

    monkeypatch.setattr(saved_views_router, "create_saved_view", conflict)
    app = _app(authenticated=True)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://test"
    ) as client:
        response = await client.post("/api/saved-views", json=_payload())
    assert response.status_code == 409
    assert response.headers["cache-control"] == "private, no-store"
    assert response.json()["detail"]["code"] == "saved_view_conflict"


@pytest.mark.asyncio
async def test_foreign_view_and_account_share_non_disclosing_404(monkeypatch):
    async def missing(*_args, **_kwargs):
        raise SavedViewNotFound("Saved view not found")

    monkeypatch.setattr(saved_views_router, "replace_saved_view", missing)
    app = _app(authenticated=True)
    payload = {
        "name": "Generated",
        "account_id": 999,
        "query": "from:generated@example.test",
        "revision": 1,
    }
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://test"
    ) as client:
        response = await client.put(f"/api/saved-views/{uuid4()}", json=payload)
    assert response.status_code == 404
    assert response.headers["cache-control"] == "private, no-store"
    assert response.json()["detail"] == {
        "code": "saved_view_not_found",
        "message": "Saved view not found",
    }


def test_static_reorder_route_precedes_uuid_resource_routes():
    contract = [
        (route.path, next(iter(route.methods)))
        for route in saved_views_router.router.routes
    ]
    assert contract == [
        ("/api/saved-views", "GET"),
        ("/api/saved-views", "POST"),
        ("/api/saved-views/reorder", "POST"),
        ("/api/saved-views/{view_id}", "PUT"),
        ("/api/saved-views/{view_id}", "DELETE"),
    ]
