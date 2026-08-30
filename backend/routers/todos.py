from datetime import datetime, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc, case

from backend.database import get_db
from backend.models.user import User
from backend.models.email import Email
from backend.models.account import GoogleAccount
from backend.models.ai import AIAnalysis
from backend.models.todo import TodoItem
from backend.routers.auth import get_current_user

router = APIRouter(prefix="/api/todos", tags=["todos"])

MAX_TODO_TITLE_LENGTH = 500
TODO_NOT_FOUND_DETAIL = "Email not found"
TodoStatus = Literal["pending", "done", "dismissed"]


def _normalized_title(value):
    if isinstance(value, str):
        return value.strip()
    return value


class TodoCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=MAX_TODO_TITLE_LENGTH)
    email_id: Optional[StrictInt] = Field(default=None, gt=0)
    # AI-derived Todos are created only by the ownership-scoped from-email
    # endpoint. The general create route is intentionally manual-only.
    source: Literal["manual"] = "manual"

    _strip_title = field_validator("title", mode="before")(_normalized_title)


class TodoUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: Optional[str] = Field(
        default=None,
        min_length=1,
        max_length=MAX_TODO_TITLE_LENGTH,
    )
    status: Optional[TodoStatus] = None

    _strip_title = field_validator("title", mode="before")(_normalized_title)


async def _owned_email_id(
    db: AsyncSession,
    *,
    user_id: int,
    email_id: int,
) -> Optional[int]:
    """Return an email id only when its account belongs to the user."""
    result = await db.execute(
        select(Email.id)
        .join(GoogleAccount, Email.account_id == GoogleAccount.id)
        .where(
            Email.id == email_id,
            GoogleAccount.user_id == user_id,
        )
    )
    return result.scalar_one_or_none()


def _action_item_title(item) -> Optional[str]:
    """Normalize stored analysis output before it becomes user-visible data."""
    if not isinstance(item, str):
        return None
    title = item.strip()
    if not title:
        return None
    return title[:MAX_TODO_TITLE_LENGTH]


def _todo_to_dict(todo: TodoItem) -> dict:
    return {
        "id": todo.id,
        "user_id": todo.user_id,
        "email_id": todo.email_id,
        "title": todo.title,
        "status": todo.status,
        "source": todo.source,
        "created_at": todo.created_at.isoformat() if todo.created_at else None,
        "completed_at": todo.completed_at.isoformat() if todo.completed_at else None,
        "ai_draft_status": todo.ai_draft_status,
        "ai_draft_body": todo.ai_draft_body,
        "ai_draft_to": todo.ai_draft_to,
    }


@router.get("/")
async def list_todos(
    status: Optional[TodoStatus] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """List todos for the current user."""
    base = select(TodoItem).where(TodoItem.user_id == user.id)
    if status:
        base = base.where(TodoItem.status == status)

    count = await db.scalar(select(func.count()).select_from(base.subquery()))

    result = await db.execute(
        base.order_by(
            # pending first, then done, then dismissed
            case(
                (TodoItem.status == "pending", 0),
                (TodoItem.status == "done", 1),
                else_=2,
            ),
            desc(TodoItem.created_at),
        )
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    items = result.scalars().all()

    return {
        "todos": [_todo_to_dict(t) for t in items],
        "total": count or 0,
    }


@router.post("/")
async def create_todo(
    body: TodoCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Create one manual Todo, optionally linked to an owned email."""
    if body.email_id is not None:
        owned_email_id = await _owned_email_id(
            db,
            user_id=user.id,
            email_id=body.email_id,
        )
        if owned_email_id is None:
            raise HTTPException(status_code=404, detail=TODO_NOT_FOUND_DETAIL)

    todo = TodoItem(
        user_id=user.id,
        email_id=body.email_id,
        title=body.title,
        source="manual",
        status="pending",
    )
    db.add(todo)
    await db.commit()
    await db.refresh(todo)
    return _todo_to_dict(todo)


@router.post("/from-email/{email_id}")
async def create_todos_from_email(
    email_id: int = Path(gt=0),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Bulk-create todos from all action items of an email's AI analysis."""
    # Scope the analysis itself through Email -> GoogleAccount ownership. A
    # foreign email, a missing email, and an email without analysis intentionally
    # share one response so the endpoint cannot disclose analysis existence.
    result = await db.execute(
        select(AIAnalysis)
        .join(Email, AIAnalysis.email_id == Email.id)
        .join(GoogleAccount, Email.account_id == GoogleAccount.id)
        .where(
            AIAnalysis.email_id == email_id,
            GoogleAccount.user_id == user.id,
        )
    )
    analysis = result.scalar_one_or_none()
    if not analysis:
        raise HTTPException(status_code=404, detail=TODO_NOT_FOUND_DETAIL)

    action_items = analysis.action_items
    if not isinstance(action_items, list):
        action_items = []
    if not action_items:
        return {"message": "No action items to add", "created": 0, "todos": []}

    # Check for duplicates -- don't re-add items already in the todo list for this email
    existing_result = await db.execute(
        select(TodoItem.title).where(
            TodoItem.user_id == user.id,
            TodoItem.email_id == email_id,
        )
    )
    existing_titles = {
        title
        for row in existing_result.all()
        if (title := _action_item_title(row[0]))
    }

    created = []
    for item in action_items:
        title = _action_item_title(item)
        if not title or title in existing_titles:
            continue
        todo = TodoItem(
            user_id=user.id,
            email_id=email_id,
            title=title,
            source="ai_action_item",
            status="pending",
        )
        db.add(todo)
        created.append(todo)
        existing_titles.add(title)

    await db.commit()
    for t in created:
        await db.refresh(t)

    return {
        "message": f"Added {len(created)} action items to todos",
        "created": len(created),
        "todos": [_todo_to_dict(t) for t in created],
    }


@router.patch("/{todo_id}")
async def update_todo(
    todo_id: int,
    body: TodoUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Update a todo (status, title)."""
    result = await db.execute(
        select(TodoItem).where(TodoItem.id == todo_id, TodoItem.user_id == user.id)
    )
    todo = result.scalar_one_or_none()
    if not todo:
        raise HTTPException(status_code=404, detail="Todo not found")

    if body.title is not None:
        todo.title = body.title
    if body.status is not None:
        todo.status = body.status
        if body.status == "done":
            todo.completed_at = datetime.now(timezone.utc)
        elif body.status == "pending":
            todo.completed_at = None

    await db.commit()
    await db.refresh(todo)
    return _todo_to_dict(todo)


@router.delete("/{todo_id}")
async def delete_todo(
    todo_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Delete a todo."""
    result = await db.execute(
        select(TodoItem).where(TodoItem.id == todo_id, TodoItem.user_id == user.id)
    )
    todo = result.scalar_one_or_none()
    if not todo:
        raise HTTPException(status_code=404, detail="Todo not found")

    await db.delete(todo)
    await db.commit()
    return {"message": "Todo deleted"}
