"""AI reply drafting and approval endpoints.

Split out of `backend/routers/ai.py` to keep individual files reviewable. All
endpoints register on the same `router` instance defined in
`backend.routers.ai`, so URL paths are unchanged.
"""
import logging
from datetime import datetime, timezone

from fastapi import Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.models.account import GoogleAccount
from backend.models.email import Email
from backend.models.todo import TodoItem
from backend.models.user import User
from backend.routers.ai import router, _get_user_account_ids
from backend.routers.auth import get_current_user
from backend.services.ai import (
    AIService,
    get_custom_prompt_model_for_user,
    get_model_for_user,
)
from backend.services.credentials import get_google_credentials
from backend.services.gmail import GmailService

logger = logging.getLogger(__name__)


@router.post("/draft-action")
async def draft_action(
    body: dict,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Have AI draft a reply for a todo item's action item."""
    todo_id = body.get("todo_id")
    if not todo_id:
        raise HTTPException(status_code=400, detail="todo_id is required")

    result = await db.execute(
        select(TodoItem).where(TodoItem.id == todo_id, TodoItem.user_id == user.id)
    )
    todo = result.scalar_one_or_none()
    if not todo:
        raise HTTPException(status_code=404, detail="Todo not found")
    if not todo.email_id:
        raise HTTPException(status_code=400, detail="Todo has no source email to draft against")

    todo.ai_draft_status = "drafting"
    await db.commit()

    try:
        model = await get_model_for_user(user.id)
        ai = AIService(model=model)
        result = await ai.draft_action_reply(todo_id, user_context=user.about_me)
        return result
    except Exception as e:
        logger.error(f"Draft action error: {e}")
        todo.ai_draft_status = None
        await db.commit()
        raise HTTPException(status_code=500, detail=f"Failed to draft: {str(e)}")


@router.post("/generate-reply")
async def generate_reply(
    body: dict,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Generate a custom AI reply based on a user-provided prompt."""
    email_id = body.get("email_id")
    prompt = body.get("prompt", "").strip()
    if not email_id:
        raise HTTPException(status_code=400, detail="email_id is required")
    if not prompt:
        raise HTTPException(status_code=400, detail="prompt is required")

    result = await db.execute(select(Email).where(Email.id == email_id))
    email = result.scalar_one_or_none()
    if not email:
        raise HTTPException(status_code=404, detail="Email not found")

    account_ids = await _get_user_account_ids(db, user)
    if email.account_id not in account_ids:
        raise HTTPException(status_code=404, detail="Email not found")

    acct_result = await db.execute(
        select(GoogleAccount.description, GoogleAccount.email).where(
            GoogleAccount.id == email.account_id
        )
    )
    acct_row = acct_result.first()
    acct_desc = acct_row[0] if acct_row else None
    acct_email = acct_row[1] if acct_row else None

    try:
        model = await get_custom_prompt_model_for_user(user.id)
        ai = AIService(model=model)
        result = await ai.generate_custom_reply(
            email_id,
            user_prompt=prompt,
            user_context=user.about_me,
            account_description=acct_desc,
            account_email=acct_email,
        )
        return result
    except Exception as e:
        logger.error(f"Generate reply error: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to generate reply: {str(e)}")


@router.post("/approve-action/{todo_id}")
async def approve_action(
    todo_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Approve and send an AI-drafted reply for a todo item."""
    result = await db.execute(
        select(TodoItem).where(TodoItem.id == todo_id, TodoItem.user_id == user.id)
    )
    todo = result.scalar_one_or_none()
    if not todo:
        raise HTTPException(status_code=404, detail="Todo not found")

    if not todo.ai_draft_body:
        raise HTTPException(status_code=400, detail="No draft to send")
    if not todo.ai_draft_to:
        raise HTTPException(status_code=400, detail="No recipient for draft")

    email = None
    if todo.email_id:
        email_result = await db.execute(select(Email).where(Email.id == todo.email_id))
        email = email_result.scalar_one_or_none()

    account_ids = await _get_user_account_ids(db, user)
    if not account_ids:
        raise HTTPException(status_code=400, detail="No email account available")

    acct_result = await db.execute(
        select(GoogleAccount).where(GoogleAccount.id == account_ids[0])
    )
    account = acct_result.scalar_one_or_none()
    if not account:
        raise HTTPException(status_code=400, detail="Account not found")

    subject = ""
    thread_id = None
    in_reply_to = None
    if email:
        subject = email.subject or ""
        if not subject.startswith("Re:"):
            subject = f"Re: {subject}"
        thread_id = email.gmail_thread_id
        in_reply_to = email.message_id_header

    client_id, client_secret = await get_google_credentials(db)
    gmail = GmailService(account, client_id=client_id, client_secret=client_secret)

    try:
        body_html = f"<p>{todo.ai_draft_body.replace(chr(10), '<br>')}</p>"
        await gmail.send_email(
            to=[todo.ai_draft_to],
            subject=subject,
            body_text=todo.ai_draft_body,
            body_html=body_html,
            in_reply_to=in_reply_to,
            references=in_reply_to,
            thread_id=thread_id,
        )

        todo.ai_draft_status = "sent"
        todo.status = "done"
        todo.completed_at = datetime.now(timezone.utc)
        await db.commit()

        return {
            "id": todo.id,
            "ai_draft_status": "sent",
            "status": "done",
            "message": f"Reply sent to {todo.ai_draft_to}",
        }

    except Exception as e:
        logger.error(f"Send draft error for todo {todo_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to send: {str(e)}")
