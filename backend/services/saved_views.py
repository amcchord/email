"""Durable owner-scoped operations for deterministic Saved Views."""

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.account import GoogleAccount
from backend.models.saved_view import SavedView
from backend.models.user import User
from backend.schemas.saved_view import (
    MAX_SAVED_VIEWS,
    SavedViewCreate,
    SavedViewReplace,
)


class SavedViewError(Exception):
    """Base class for stable Saved View API failures."""


class SavedViewNotFound(SavedViewError):
    pass


class SavedViewConflict(SavedViewError):
    pass


def saved_view_matches(
    view: SavedView,
    body: SavedViewCreate | SavedViewReplace,
) -> bool:
    return (
        view.name == body.name
        and view.query == body.query
        and view.account_id == body.account_id
    )


def _owned_account_statement(*, user_id: int, account_id: int):
    return select(GoogleAccount.id).where(
        GoogleAccount.id == account_id,
        GoogleAccount.user_id == user_id,
    )


def _owned_view_statement(*, user_id: int, view_id: UUID):
    return select(SavedView).where(
        SavedView.user_id == user_id,
        SavedView.id == view_id,
    )


async def _lock_owner(db: AsyncSession, *, user_id: int) -> None:
    await db.execute(select(User.id).where(User.id == user_id).with_for_update())


async def _require_owned_account(
    db: AsyncSession,
    *,
    user_id: int,
    account_id: int | None,
) -> None:
    if account_id is None:
        return
    result = await db.execute(
        _owned_account_statement(user_id=user_id, account_id=account_id)
    )
    if result.scalar_one_or_none() is None:
        # Foreign and missing accounts share the view-not-found response. Never
        # coerce an invalid account to NULL, which would broaden the view.
        raise SavedViewNotFound("Saved view not found")


async def _view_by_create_id(
    db: AsyncSession,
    *,
    user_id: int,
    create_id: UUID,
) -> SavedView | None:
    result = await db.execute(
        select(SavedView).where(
            SavedView.user_id == user_id,
            SavedView.create_id == create_id,
        )
    )
    return result.scalar_one_or_none()


async def list_saved_views(
    db: AsyncSession,
    *,
    user_id: int,
) -> list[SavedView]:
    result = await db.execute(
        select(SavedView)
        .where(SavedView.user_id == user_id)
        .order_by(SavedView.position, SavedView.row_id)
    )
    return list(result.scalars().all())


async def create_saved_view(
    db: AsyncSession,
    *,
    user_id: int,
    request: SavedViewCreate,
) -> tuple[SavedView, bool]:
    # One owner lock serializes quota, position, name, and idempotency checks
    # without blocking another user's independent collection.
    await _lock_owner(db, user_id=user_id)
    existing = await _view_by_create_id(
        db,
        user_id=user_id,
        create_id=request.create_id,
    )
    if existing is not None:
        if saved_view_matches(existing, request):
            return existing, False
        raise SavedViewConflict("That Saved View request ID is already used")

    await _require_owned_account(
        db,
        user_id=user_id,
        account_id=request.account_id,
    )
    count = int(
        await db.scalar(
            select(func.count(SavedView.row_id)).where(SavedView.user_id == user_id)
        )
        or 0
    )
    if count >= MAX_SAVED_VIEWS:
        raise SavedViewConflict(
            f"A user can keep at most {MAX_SAVED_VIEWS} Saved Views"
        )

    view = SavedView(
        user_id=user_id,
        create_id=request.create_id,
        name=request.name,
        query=request.query,
        account_id=request.account_id,
        position=count,
        revision=1,
    )
    db.add(view)
    try:
        await db.commit()
    except IntegrityError as error:
        await db.rollback()
        replay = await _view_by_create_id(
            db,
            user_id=user_id,
            create_id=request.create_id,
        )
        if replay is not None and saved_view_matches(replay, request):
            return replay, False
        raise SavedViewConflict("That Saved View name is already in use") from error
    await db.refresh(view)
    return view, True


async def replace_saved_view(
    db: AsyncSession,
    *,
    user_id: int,
    view_id: UUID,
    request: SavedViewReplace,
) -> SavedView:
    await _lock_owner(db, user_id=user_id)
    result = await db.execute(
        _owned_view_statement(user_id=user_id, view_id=view_id).with_for_update()
    )
    view = result.scalar_one_or_none()
    if view is None:
        raise SavedViewNotFound("Saved view not found")

    # Exact PUT replay after a lost successful response is safe.
    if view.revision == request.revision + 1 and saved_view_matches(
        view, request
    ):
        return view
    if view.revision != request.revision:
        raise SavedViewConflict("This Saved View changed elsewhere; refresh it")

    await _require_owned_account(
        db,
        user_id=user_id,
        account_id=request.account_id,
    )
    view.name = request.name
    view.query = request.query
    view.account_id = request.account_id
    view.revision += 1
    try:
        await db.commit()
    except IntegrityError as error:
        await db.rollback()
        raise SavedViewConflict("That Saved View name is already in use") from error
    await db.refresh(view)
    return view


async def _move_positions(
    db: AsyncSession,
    *,
    rows: Sequence[SavedView],
    new_positions: dict[UUID, int],
) -> None:
    moved = [row for row in rows if row.position != new_positions[row.id]]
    if not moved:
        return

    # Move affected rows outside the bounded live range before assigning final
    # positions so the per-owner unique constraint cannot fail during swaps.
    temporary_offset = MAX_SAVED_VIEWS + len(rows)
    for row in moved:
        row.position += temporary_offset
    await db.flush()
    for row in moved:
        row.position = new_positions[row.id]
        row.revision += 1


async def delete_saved_view(
    db: AsyncSession,
    *,
    user_id: int,
    view_id: UUID,
    revision: int,
) -> None:
    await _lock_owner(db, user_id=user_id)
    result = await db.execute(
        _owned_view_statement(user_id=user_id, view_id=view_id).with_for_update()
    )
    view = result.scalar_one_or_none()
    if view is None:
        raise SavedViewNotFound("Saved view not found")
    if view.revision != revision:
        raise SavedViewConflict("This Saved View changed elsewhere; refresh it")

    rows = await list_saved_views(db, user_id=user_id)
    remaining = [row for row in rows if row.id != view_id]
    await db.delete(view)
    await db.flush()
    await _move_positions(
        db,
        rows=remaining,
        new_positions={row.id: index for index, row in enumerate(remaining)},
    )
    await db.commit()


def validate_reorder(
    current_order: Sequence[UUID],
    *,
    expected_order: Sequence[UUID],
    view_ids: Sequence[UUID],
) -> None:
    if list(expected_order) != list(current_order):
        raise SavedViewConflict("Saved View order changed elsewhere; refresh it")
    if len(view_ids) != len(current_order) or set(view_ids) != set(current_order):
        raise SavedViewConflict("Saved View reorder must contain the exact collection")


async def reorder_saved_views(
    db: AsyncSession,
    *,
    user_id: int,
    expected_order: Sequence[UUID],
    view_ids: Sequence[UUID],
) -> list[SavedView]:
    await _lock_owner(db, user_id=user_id)
    result = await db.execute(
        select(SavedView)
        .where(SavedView.user_id == user_id)
        .order_by(SavedView.position, SavedView.row_id)
        .with_for_update()
    )
    rows = list(result.scalars().all())
    current_order = [row.id for row in rows]
    validate_reorder(
        current_order,
        expected_order=expected_order,
        view_ids=view_ids,
    )
    if list(view_ids) == current_order:
        return rows

    positions = {view_id: index for index, view_id in enumerate(view_ids)}
    await _move_positions(db, rows=rows, new_positions=positions)
    await db.commit()
    for row in rows:
        await db.refresh(row)
    return sorted(rows, key=lambda row: (row.position, row.row_id))
