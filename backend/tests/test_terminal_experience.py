"""Focused contract tests for the first-class At a Glance read API."""
from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import backend.routers.terminal_admin as terminal_admin
from backend.database import get_db
from backend.main import app as main_app
from backend.models.terminal import TerminalSettings
from backend.routers.auth import get_current_user
from backend.services.terminal.web_display import WebFrame


@pytest.fixture
def app():
    application = FastAPI()
    application.include_router(terminal_admin.router)

    async def fake_db():
        yield SimpleNamespace()

    async def fake_user():
        return SimpleNamespace(id=7)

    application.dependency_overrides[get_db] = fake_db
    application.dependency_overrides[get_current_user] = fake_user
    return application


def test_experience_routes_require_session_authentication():
    for path in (
        "/api/terminal/experience",
        "/api/terminal/experience/preview.png",
    ):
        response = TestClient(main_app).get(path)
        assert response.status_code == 401
        assert response.json() == {"detail": "Not authenticated"}


@pytest.mark.asyncio
async def test_experience_returns_only_catalog_metadata_and_owned_summaries(
    app,
    monkeypatch,
):
    calls = []

    async def owned_summaries(_db, *, user_id):
        calls.append(user_id)
        return []

    monkeypatch.setattr(
        terminal_admin,
        "_list_owned_device_summaries",
        owned_summaries,
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="https://test",
    ) as client:
        response = await client.get("/api/terminal/experience")

    assert response.status_code == 200
    assert calls == [7]
    assert response.headers["cache-control"] == "private, no-store"
    body = response.json()
    assert set(body) == {
        "views",
        "designs",
        "display_profiles",
        "combinations",
        "devices",
    }
    assert body["devices"] == []
    assert {
        (item["view"], item["design"], item["profile"])
        for item in body["combinations"]
    } == {
        ("home", "editorial", "landscape_16_9"),
        ("home", "swiss", "landscape_16_9"),
        ("day_ahead", "editorial", "portrait_9_16"),
        ("clock", None, "landscape_16_9"),
        ("clock", None, "portrait_9_16"),
    }
    serialized = response.text.lower()
    for forbidden in (
        '"code"',
        '"token"',
        '"url"',
        "home_assistant",
        "schedule_url",
        "image_url",
        "display_url",
    ):
        assert forbidden not in serialized


@pytest.mark.asyncio
async def test_preview_resolves_and_renders_exact_catalog_combination(app, monkeypatch):
    settings = TerminalSettings(user_id=7, code="", timezone="UTC")
    resolved = {}

    async def read_settings(_db, *, user_id):
        assert user_id == 7
        return settings

    async def render(*, settings, view, design, profile):
        resolved.update(
            settings=settings,
            view=view.key,
            design=design.key if design else None,
            profile=profile.key,
        )
        return WebFrame(
            body=b"\x89PNG\r\n\x1a\npreview",
            etag='"web-generated"',
            width=720,
            height=1280,
        )

    monkeypatch.setattr(terminal_admin, "_read_experience_settings", read_settings)
    monkeypatch.setattr(terminal_admin, "render_web_frame", render)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="https://test",
    ) as client:
        response = await client.get(
            "/api/terminal/experience/preview.png",
            params={
                "view": "day_ahead",
                "design": "editorial",
                "profile": "portrait_9_16",
            },
        )

    assert response.status_code == 200
    assert response.content == b"\x89PNG\r\n\x1a\npreview"
    assert response.headers["content-type"] == "image/png"
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["etag"] == '"web-generated"'
    assert resolved == {
        "settings": settings,
        "view": "day_ahead",
        "design": "editorial",
        "profile": "portrait_9_16",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "params",
    [
        {"profile": "square"},
        {"view": "mailbox", "profile": "landscape"},
        {"view": "home", "profile": "portrait"},
        {"view": "day_ahead", "design": "swiss", "profile": "portrait"},
        {"view": "clock", "design": "editorial", "profile": "landscape"},
    ],
)
async def test_preview_rejects_unknown_or_incompatible_combinations(app, params):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="https://test",
    ) as client:
        response = await client.get(
            "/api/terminal/experience/preview.png",
            params=params,
        )

    assert response.status_code == 400
    assert isinstance(response.json()["detail"], str)


@pytest.mark.asyncio
async def test_missing_settings_use_transient_defaults_without_database_writes():
    class Result:
        @staticmethod
        def scalar_one_or_none():
            return None

    class ReadOnlyDB:
        writes = 0

        async def execute(self, _statement):
            return Result()

        def add(self, _value):
            self.writes += 1

        async def commit(self):
            self.writes += 1

    db = ReadOnlyDB()
    settings = await terminal_admin._read_experience_settings(db, user_id=23)

    assert settings.user_id == 23
    assert settings.code == ""
    assert settings.timezone == "UTC"
    assert settings.home_assistant_url is None
    assert settings.home_assistant_token_encrypted is None
    assert db.writes == 0
