from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi import Response
from pydantic import ValidationError

import backend.routers.snippets as snippets_router
from backend.middleware.compose_body_limit import (
    MAX_COMPOSE_SEND_BODY_BYTES,
    MAX_SNIPPET_BODY_BYTES,
    ComposeSendBodyLimitMiddleware,
)
from backend.models.snippet import PersonalSnippet
from backend.schemas.snippet import PersonalSnippetCreate, PersonalSnippetReplace
from backend.services.snippets import snippet_matches


def _create(**overrides):
    values = {
        "snippet_id": uuid4(),
        "name": "  Friendly   follow-up ",
        "shortcut": ";Follow_Up",
        "body_html": "<p>Generated follow-up</p>",
        "body_text": "Generated follow-up",
    }
    values.update(overrides)
    return PersonalSnippetCreate(**values)


def _row(request, **overrides):
    values = {
        "snippet_id": request.snippet_id,
        "user_id": 7,
        "name": request.name,
        "shortcut": request.shortcut,
        "body_html": request.body_html,
        "body_text": request.body_text,
        "revision": 1,
        "created_at": datetime(2026, 8, 30, tzinfo=timezone.utc),
        "updated_at": datetime(2026, 8, 30, tzinfo=timezone.utc),
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_snippet_schema_normalizes_and_bounds_private_content():
    request = _create()
    assert request.name == "Friendly follow-up"
    assert request.shortcut == "follow_up"

    with pytest.raises(ValidationError, match="Shortcut must start"):
        _create(shortcut="bad shortcut")
    with pytest.raises(ValidationError, match="unsupported control"):
        _create(body_text="unsafe\x00content")
    with pytest.raises(ValidationError):
        _create(body_text="")
    with pytest.raises(ValidationError):
        _create(body_html="x" * 50_001)


def test_snippet_replace_requires_positive_revision_and_full_content():
    request = _create()
    replacement = PersonalSnippetReplace(
        expected_revision=3,
        name=request.name,
        shortcut=request.shortcut,
        body_html=request.body_html,
        body_text=request.body_text,
    )
    assert replacement.expected_revision == 3
    with pytest.raises(ValidationError):
        replacement.model_copy(update={"expected_revision": 0}).model_validate(
            {**replacement.model_dump(), "expected_revision": 0}
        )


def test_snippet_model_and_migration_are_one_owner_scoped_head():
    constraint_names = {
        constraint.name for constraint in PersonalSnippet.__table__.constraints
    }
    assert {
        "ck_personal_snippets_revision",
        "ck_personal_snippets_shortcut",
        "ck_personal_snippets_name",
        "ck_personal_snippets_body",
        "uq_personal_snippets_user_public_id",
        "uq_personal_snippets_user_shortcut",
    } <= constraint_names
    assert {index.name for index in PersonalSnippet.__table__.indexes} == {
        "ix_personal_snippets_user_name"
    }

    config = Config()
    config.set_main_option("script_location", "alembic")
    scripts = ScriptDirectory.from_config(config)
    assert scripts.get_revision("d7e8f9a0b1c2").down_revision == "c6d7e8f9a0b1"
    assert scripts.get_heads() == ["c1d2e3f4a5b6"]


def test_snippet_routes_stay_session_only_under_compose():
    contract = {
        (route.path, method)
        for route in snippets_router.router.routes
        for method in route.methods
    }
    assert contract == {
        ("/api/compose/snippets", "GET"),
        ("/api/compose/snippets", "POST"),
        ("/api/compose/snippets/{snippet_id}", "PUT"),
        ("/api/compose/snippets/{snippet_id}", "DELETE"),
    }


def test_snippet_body_limiter_covers_create_and_dynamic_replace_paths():
    async def app(_scope, _receive, _send):
        return None

    middleware = ComposeSendBodyLimitMiddleware(app)
    base = {"type": "http", "headers": []}
    assert middleware._request_limit({**base, "method": "POST", "path": "/api/compose/send"}) == MAX_COMPOSE_SEND_BODY_BYTES
    assert middleware._request_limit({**base, "method": "POST", "path": "/api/compose/snippets"}) == MAX_SNIPPET_BODY_BYTES
    assert middleware._request_limit({**base, "method": "PUT", "path": f"/api/compose/snippets/{uuid4()}"}) == MAX_SNIPPET_BODY_BYTES
    assert middleware._request_limit({**base, "method": "GET", "path": "/api/compose/snippets"}) is None


def test_exact_snippet_replay_matches_all_mutable_content():
    request = _create()
    row = _row(request)
    assert snippet_matches(row, request) is True
    assert snippet_matches(row, _create(snippet_id=request.snippet_id, body_text="Changed")) is False


@pytest.mark.asyncio
async def test_create_route_returns_201_then_200_for_exact_replay(monkeypatch):
    request = _create()
    row = _row(request)
    created = True

    async def create(_db, *, user_id, request):
        assert user_id == 9
        assert request.snippet_id == row.snippet_id
        return row, created

    monkeypatch.setattr(snippets_router, "create_personal_snippet", create)
    response = Response()
    result = await snippets_router.create_snippet(
        request,
        response,
        db=object(),
        user=SimpleNamespace(id=9),
    )
    assert response.status_code == 201
    assert result.shortcut == "follow_up"

    created = False
    replay_response = Response()
    replay = await snippets_router.create_snippet(
        request,
        replay_response,
        db=object(),
        user=SimpleNamespace(id=9),
    )
    assert replay_response.status_code == 200
    assert replay.snippet_id == request.snippet_id
