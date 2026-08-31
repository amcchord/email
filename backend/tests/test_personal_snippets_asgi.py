"""ASGI contract checks for the private Personal Snippets API."""

from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI

import backend.routers.snippets as snippets_router
from backend.database import get_db
from backend.routers.auth import get_current_user
from backend.services.snippets import SnippetConflict, SnippetNotFound


def _app(*, authenticated):
    app = FastAPI()
    app.include_router(snippets_router.router)

    async def fake_db():
        yield SimpleNamespace()

    app.dependency_overrides[get_db] = fake_db
    if authenticated:
        async def fake_user():
            return SimpleNamespace(id=17)

        app.dependency_overrides[get_current_user] = fake_user
    return app


def _payload(**overrides):
    values = {
        "snippet_id": str(uuid4()),
        "name": "Generated follow-up",
        "shortcut": "followup",
        "body_html": "<p>Generated follow-up</p>",
        "body_text": "Generated follow-up",
    }
    values.update(overrides)
    return values


@pytest.mark.asyncio
async def test_all_snippet_routes_require_an_authenticated_session():
    app = _app(authenticated=False)
    snippet_id = uuid4()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://test"
    ) as client:
        responses = [
            await client.get("/api/compose/snippets"),
            await client.post("/api/compose/snippets", json=_payload()),
            await client.put(f"/api/compose/snippets/{snippet_id}", json={
                **{key: value for key, value in _payload().items() if key != "snippet_id"},
                "expected_revision": 1,
            }),
            await client.delete(
                f"/api/compose/snippets/{snippet_id}?expected_revision=1"
            ),
        ]
    assert [response.status_code for response in responses] == [401, 401, 401, 401]


@pytest.mark.asyncio
async def test_create_contract_is_strict_and_maps_duplicate_conflicts(monkeypatch):
    app = _app(authenticated=True)
    payload = _payload()

    async def duplicate(*_args, **_kwargs):
        raise SnippetConflict("That snippet shortcut is already in use")

    monkeypatch.setattr(snippets_router, "create_personal_snippet", duplicate)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://test"
    ) as client:
        conflict = await client.post("/api/compose/snippets", json=payload)
        invalid = await client.post(
            "/api/compose/snippets", json={**payload, "unexpected": "private"}
        )

    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == "snippet_conflict"
    assert invalid.status_code == 422


@pytest.mark.asyncio
async def test_foreign_update_is_non_disclosing_404(monkeypatch):
    app = _app(authenticated=True)

    async def missing(*_args, **_kwargs):
        raise SnippetNotFound("Snippet not found")

    monkeypatch.setattr(snippets_router, "replace_personal_snippet", missing)
    snippet_id = uuid4()
    request = _payload()
    request.pop("snippet_id")
    request["expected_revision"] = 1
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://test"
    ) as client:
        response = await client.put(
            f"/api/compose/snippets/{snippet_id}", json=request
        )

    assert response.status_code == 404
    assert response.json()["detail"] == {
        "code": "snippet_not_found",
        "message": "Snippet not found",
    }
