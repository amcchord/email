"""Durable owner-scoped operations for reusable personal snippets."""

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.snippet import PersonalSnippet
from backend.models.user import User
from backend.schemas.snippet import (
    MAX_PERSONAL_SNIPPETS,
    PersonalSnippetCreate,
    PersonalSnippetReplace,
)


class SnippetError(Exception):
    """Base class for stable snippet API failures."""


class SnippetNotFound(SnippetError):
    pass


class SnippetConflict(SnippetError):
    pass


class SnippetQuotaExceeded(SnippetError):
    pass


def snippet_matches(
    snippet: PersonalSnippet,
    body: PersonalSnippetCreate | PersonalSnippetReplace,
) -> bool:
    return (
        snippet.name == body.name
        and snippet.shortcut == body.shortcut
        and snippet.body_html == body.body_html
        and snippet.body_text == body.body_text
    )


async def list_personal_snippets(
    db: AsyncSession,
    *,
    user_id: int,
) -> list[PersonalSnippet]:
    result = await db.execute(
        select(PersonalSnippet)
        .where(PersonalSnippet.user_id == user_id)
        .order_by(func.lower(PersonalSnippet.name), PersonalSnippet.id)
    )
    return list(result.scalars().all())


async def _snippet_by_public_id(
    db: AsyncSession,
    *,
    user_id: int,
    snippet_id,
) -> PersonalSnippet | None:
    result = await db.execute(
        select(PersonalSnippet).where(
            PersonalSnippet.user_id == user_id,
            PersonalSnippet.snippet_id == snippet_id,
        )
    )
    return result.scalar_one_or_none()


async def create_personal_snippet(
    db: AsyncSession,
    *,
    user_id: int,
    request: PersonalSnippetCreate,
) -> tuple[PersonalSnippet, bool]:
    # Lock the owner row so quota checks and client-id replays serialize for
    # this user without blocking other users' independent collections.
    await db.execute(select(User.id).where(User.id == user_id).with_for_update())

    existing = await _snippet_by_public_id(
        db,
        user_id=user_id,
        snippet_id=request.snippet_id,
    )
    if existing is not None:
        if snippet_matches(existing, request):
            return existing, False
        raise SnippetConflict("That snippet request ID is already used")

    count = await db.scalar(
        select(func.count(PersonalSnippet.id)).where(PersonalSnippet.user_id == user_id)
    )
    if int(count or 0) >= MAX_PERSONAL_SNIPPETS:
        raise SnippetQuotaExceeded(
            f"A user can keep at most {MAX_PERSONAL_SNIPPETS} personal snippets"
        )

    snippet = PersonalSnippet(
        snippet_id=request.snippet_id,
        user_id=user_id,
        name=request.name,
        shortcut=request.shortcut,
        body_html=request.body_html,
        body_text=request.body_text,
        revision=1,
    )
    db.add(snippet)
    try:
        await db.commit()
    except IntegrityError as error:
        await db.rollback()
        existing = await _snippet_by_public_id(
            db,
            user_id=user_id,
            snippet_id=request.snippet_id,
        )
        if existing is not None and snippet_matches(existing, request):
            return existing, False
        raise SnippetConflict("That snippet shortcut is already in use") from error
    await db.refresh(snippet)
    return snippet, True


async def replace_personal_snippet(
    db: AsyncSession,
    *,
    user_id: int,
    snippet_id,
    request: PersonalSnippetReplace,
) -> PersonalSnippet:
    result = await db.execute(
        select(PersonalSnippet)
        .where(
            PersonalSnippet.user_id == user_id,
            PersonalSnippet.snippet_id == snippet_id,
        )
        .with_for_update()
    )
    snippet = result.scalar_one_or_none()
    if snippet is None:
        raise SnippetNotFound("Snippet not found")

    if snippet.revision == request.expected_revision + 1 and snippet_matches(
        snippet, request
    ):
        # Exact replay after a lost successful response.
        return snippet
    if snippet.revision != request.expected_revision:
        raise SnippetConflict("This snippet changed on another device; refresh it")

    snippet.name = request.name
    snippet.shortcut = request.shortcut
    snippet.body_html = request.body_html
    snippet.body_text = request.body_text
    snippet.revision += 1
    try:
        await db.commit()
    except IntegrityError as error:
        await db.rollback()
        raise SnippetConflict("That snippet shortcut is already in use") from error
    await db.refresh(snippet)
    return snippet


async def delete_personal_snippet(
    db: AsyncSession,
    *,
    user_id: int,
    snippet_id,
    expected_revision: int,
) -> bool:
    result = await db.execute(
        select(PersonalSnippet)
        .where(
            PersonalSnippet.user_id == user_id,
            PersonalSnippet.snippet_id == snippet_id,
        )
        .with_for_update()
    )
    snippet = result.scalar_one_or_none()
    if snippet is None:
        # Missing and foreign IDs are deliberately indistinguishable; repeated
        # deletion is safe after a lost 204 response.
        return False
    if snippet.revision != expected_revision:
        raise SnippetConflict("This snippet changed on another device; refresh it")
    await db.delete(snippet)
    await db.commit()
    return True
