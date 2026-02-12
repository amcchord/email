from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc, case

from backend.database import get_db
from backend.models.user import User
from backend.models.email import Email
from backend.models.ai import AIAnalysis
from backend.models.todo import TodoItem
from backend.routers.auth import get_current_user

router = APIRouter(prefix="/api/todos", tags=["todos"])


class TodoCreate(BaseModel):
    title: str
    email_id: Optional[int] = None
    source: str = "manual"


class TodoUpdate(BaseModel):
    title: Optional[str] = None
    status: Optional[str] = None  # pending, done, dismissed


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
    status: Optional[str] = None,
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
    """Create a single todo."""
    todo = TodoItem(
        user_id=user.id,
        email_id=body.email_id,
        title=body.title,
        source=body.source,
        status="pending",
    )
    db.add(todo)
    await db.commit()
    await db.refresh(todo)
    return _todo_to_dict(todo)


@router.post("/from-email/{email_id}")
async def create_todos_from_email(
    email_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Bulk-create todos from all action items of an email's AI analysis."""
    # Get the AI analysis for this email
    result = await db.execute(
        select(AIAnalysis).where(AIAnalysis.email_id == email_id)
    )
    analysis = result.scalar_one_or_none()
    if not analysis:
        raise HTTPException(status_code=404, detail="No AI analysis found for this email")

    action_items = analysis.action_items or []
    if not action_items:
        return {"message": "No action items to add", "created": 0, "todos": []}

    # Check for duplicates -- don't re-add items already in the todo list for this email
    existing_result = await db.execute(
        select(TodoItem.title).where(
            TodoItem.user_id == user.id,
            TodoItem.email_id == email_id,
        )
    )
    existing_titles = set(r[0] for r in existing_result.all())

    created = []
    for item in action_items:
        if not item or item in existing_titles:
            continue
        todo = TodoItem(
            user_id=user.id,
            email_id=email_id,
            title=item,
            source="ai_action_item",
            status="pending",
        )
        db.add(todo)
        created.append(todo)

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
