"""Focused contract tests for private swipe-triage preferences."""

import httpx
import pytest
from fastapi import FastAPI

import backend.routers.auth as auth_router
from backend.database import get_db
from backend.models.user import User
from backend.routers.auth import get_current_user


class PreferenceSession:
    def __init__(self):
        self.commit_count = 0
        self.refresh_count = 0

    async def commit(self):
        self.commit_count += 1

    async def refresh(self, _value):
        self.refresh_count += 1


def _app(*, user=None, session=None):
    app = FastAPI()
    app.include_router(auth_router.router)
    session = session or PreferenceSession()

    async def fake_db():
        yield session

    app.dependency_overrides[get_db] = fake_db
    if user is not None:
        async def fake_user():
            return user

        app.dependency_overrides[get_current_user] = fake_user
    return app, session


@pytest.mark.asyncio
async def test_swipe_preferences_return_safe_defaults_without_persisting_them():
    user = User(id=17, email="generated@example.test", ui_preferences=None)
    app, session = _app(user=user)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://test"
    ) as client:
        response = await client.get("/api/auth/ui-preferences")

    assert response.status_code == 200
    assert response.json()["swipe_left_action"] == "archive"
    assert response.json()["swipe_right_action"] == "snooze"
    assert session.commit_count == 0
    assert user.ui_preferences is None


@pytest.mark.asyncio
async def test_valid_swipe_preferences_update_both_directions():
    user = User(id=17, email="generated@example.test", ui_preferences={})
    app, session = _app(user=user)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://test"
    ) as client:
        response = await client.put(
            "/api/auth/ui-preferences",
            json={
                "swipe_left_action": "toggle_read",
                "swipe_right_action": "toggle_star",
            },
        )

    assert response.status_code == 200
    assert response.json()["swipe_left_action"] == "toggle_read"
    assert response.json()["swipe_right_action"] == "toggle_star"
    assert user.ui_preferences == {
        "swipe_left_action": "toggle_read",
        "swipe_right_action": "toggle_star",
    }
    assert session.commit_count == 1
    assert session.refresh_count == 1


@pytest.mark.asyncio
async def test_partial_swipe_update_preserves_other_direction_and_unrelated_preferences():
    user = User(
        id=17,
        email="generated@example.test",
        ui_preferences={
            "thread_order": "oldest_first",
            "theme": "blue",
            "private_future_preference": {"preserve": True},
            "swipe_left_action": "archive",
            "swipe_right_action": "toggle_star",
        },
    )
    app, session = _app(user=user)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://test"
    ) as client:
        response = await client.put(
            "/api/auth/ui-preferences",
            json={"swipe_left_action": "none"},
        )

    assert response.status_code == 200
    assert response.json()["swipe_left_action"] == "none"
    assert response.json()["swipe_right_action"] == "toggle_star"
    assert user.ui_preferences == {
        "thread_order": "oldest_first",
        "theme": "blue",
        "private_future_preference": {"preserve": True},
        "swipe_left_action": "none",
        "swipe_right_action": "toggle_star",
    }
    assert session.commit_count == 1
    assert session.refresh_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["swipe_left_action", "swipe_right_action"])
async def test_invalid_swipe_preference_returns_422_without_writing(field):
    initial = {
        "thread_order": "newest_first",
        "swipe_left_action": "archive",
        "swipe_right_action": "snooze",
    }
    user = User(id=17, email="generated@example.test", ui_preferences=dict(initial))
    app, session = _app(user=user)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://test"
    ) as client:
        response = await client.put(
            "/api/auth/ui-preferences",
            json={field: "delete"},
        )

    assert response.status_code == 422
    assert user.ui_preferences == initial
    assert session.commit_count == 0
    assert session.refresh_count == 0


@pytest.mark.asyncio
async def test_swipe_preferences_remain_private_to_authenticated_sessions():
    app, session = _app()

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://test"
    ) as client:
        get_response = await client.get("/api/auth/ui-preferences")
        put_response = await client.put(
            "/api/auth/ui-preferences",
            json={"swipe_left_action": "none"},
        )

    assert [get_response.status_code, put_response.status_code] == [401, 401]
    assert session.commit_count == 0
