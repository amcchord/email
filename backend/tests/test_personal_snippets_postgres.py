"""Disposable-PostgreSQL invariants for owner-scoped personal snippets."""

import os
from uuid import uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.models.snippet import PersonalSnippet
from backend.models.user import User
from backend.schemas.snippet import PersonalSnippetCreate, PersonalSnippetReplace
from backend.services.snippets import (
    SnippetConflict,
    SnippetNotFound,
    create_personal_snippet,
    delete_personal_snippet,
    list_personal_snippets,
    replace_personal_snippet,
)


DATABASE_URL = os.getenv("PERSONAL_SNIPPETS_POSTGRES_TEST_URL")
pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(
        not DATABASE_URL,
        reason="requires PERSONAL_SNIPPETS_POSTGRES_TEST_URL for disposable PostgreSQL",
    ),
]


def _session_factory():
    engine = create_async_engine(DATABASE_URL, pool_pre_ping=True, hide_parameters=True)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


async def _reset(engine):
    async with engine.begin() as connection:
        await connection.execute(text("TRUNCATE TABLE users RESTART IDENTITY CASCADE"))


async def _seed_users(sessions):
    async with sessions() as db:
        first = User(username="generated-snippets-a", is_active=True, is_admin=False)
        second = User(username="generated-snippets-b", is_active=True, is_admin=False)
        db.add_all([first, second])
        await db.commit()
        return first.id, second.id


def _create(*, snippet_id=None, name="Generated follow-up", shortcut="followup"):
    return PersonalSnippetCreate(
        snippet_id=snippet_id or uuid4(),
        name=name,
        shortcut=shortcut,
        body_html=f"<p>{name}</p>",
        body_text=name,
    )


def _replace(source, *, expected_revision, name=None, shortcut=None):
    next_name = name or source.name
    return PersonalSnippetReplace(
        expected_revision=expected_revision,
        name=next_name,
        shortcut=shortcut or source.shortcut,
        body_html=f"<p>{next_name}</p>",
        body_text=next_name,
    )


async def test_snippet_lifecycle_is_private_revisioned_and_replay_safe():
    engine, sessions = _session_factory()
    try:
        await _reset(engine)
        first_user, second_user = await _seed_users(sessions)
        request = _create()

        async with sessions() as db:
            created, was_created = await create_personal_snippet(
                db, user_id=first_user, request=request
            )
        assert was_created is True
        assert created.revision == 1

        async with sessions() as db:
            replay, replay_created = await create_personal_snippet(
                db, user_id=first_user, request=request
            )
        assert replay_created is False
        assert replay.snippet_id == created.snippet_id

        async with sessions() as db:
            with pytest.raises(SnippetConflict, match="request ID"):
                await create_personal_snippet(
                    db,
                    user_id=first_user,
                    request=_create(snippet_id=request.snippet_id, name="Divergent replay"),
                )

        # The same shortcut is valid in another owner's private collection.
        async with sessions() as db:
            foreign, foreign_created = await create_personal_snippet(
                db,
                user_id=second_user,
                request=_create(name="Other owner's follow-up"),
            )
        assert foreign_created is True

        async with sessions() as db:
            first_rows = await list_personal_snippets(db, user_id=first_user)
            second_rows = await list_personal_snippets(db, user_id=second_user)
        assert [row.snippet_id for row in first_rows] == [created.snippet_id]
        assert [row.snippet_id for row in second_rows] == [foreign.snippet_id]

        replacement = _replace(created, expected_revision=1, name="Generated check-in")
        async with sessions() as db:
            updated = await replace_personal_snippet(
                db,
                user_id=first_user,
                snippet_id=created.snippet_id,
                request=replacement,
            )
        assert updated.revision == 2
        assert updated.name == "Generated check-in"

        # A lost successful response may be replayed, while divergent stale data loses.
        async with sessions() as db:
            replayed_update = await replace_personal_snippet(
                db,
                user_id=first_user,
                snippet_id=created.snippet_id,
                request=replacement,
            )
        assert replayed_update.revision == 2
        async with sessions() as db:
            with pytest.raises(SnippetConflict, match="another device"):
                await replace_personal_snippet(
                    db,
                    user_id=first_user,
                    snippet_id=created.snippet_id,
                    request=_replace(created, expected_revision=1, name="Stale overwrite"),
                )

        # Foreign IDs disclose no row and cannot be updated or deleted.
        async with sessions() as db:
            with pytest.raises(SnippetNotFound):
                await replace_personal_snippet(
                    db,
                    user_id=second_user,
                    snippet_id=created.snippet_id,
                    request=_replace(updated, expected_revision=2),
                )
            assert await delete_personal_snippet(
                db,
                user_id=second_user,
                snippet_id=created.snippet_id,
                expected_revision=2,
            ) is False

        async with sessions() as db:
            assert await delete_personal_snippet(
                db,
                user_id=first_user,
                snippet_id=created.snippet_id,
                expected_revision=2,
            ) is True
        async with sessions() as db:
            assert await delete_personal_snippet(
                db,
                user_id=first_user,
                snippet_id=created.snippet_id,
                expected_revision=2,
            ) is False

        async with sessions() as db:
            count = len((await db.execute(select(PersonalSnippet))).scalars().all())
        assert count == 1
    finally:
        await engine.dispose()
