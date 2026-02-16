from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from backend.database import get_db
from backend.models.user import User
from backend.models.account import GoogleAccount
from backend.schemas.email import ComposeRequest
from backend.routers.auth import get_current_user
from backend.services.gmail import GmailService
from backend.services.credentials import get_google_credentials

router = APIRouter(prefix="/api/compose", tags=["compose"])


@router.post("/send")
async def send_email(
    request: ComposeRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(GoogleAccount).where(
            GoogleAccount.id == request.account_id,
            GoogleAccount.user_id == user.id,
        )
    )
    account = result.scalar_one_or_none()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    client_id, client_secret = await get_google_credentials(db)
    gmail = GmailService(account, client_id=client_id, client_secret=client_secret)
    try:
        message_id = await gmail.send_email(
            to=request.to,
            cc=request.cc,
            bcc=request.bcc,
            subject=request.subject,
            body_html=request.body_html,
            body_text=request.body_text,
            in_reply_to=request.in_reply_to,
            references=request.references,
            thread_id=request.thread_id,
        )
        return {"message": "Email sent", "gmail_message_id": message_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to send: {str(e)}")


@router.post("/draft")
async def save_draft(
    request: ComposeRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(GoogleAccount).where(
            GoogleAccount.id == request.account_id,
            GoogleAccount.user_id == user.id,
        )
    )
    account = result.scalar_one_or_none()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    client_id, client_secret = await get_google_credentials(db)
    gmail = GmailService(account, client_id=client_id, client_secret=client_secret)
    try:
        draft_id = await gmail.create_draft(
            to=request.to,
            cc=request.cc,
            bcc=request.bcc,
            subject=request.subject,
            body_html=request.body_html,
            body_text=request.body_text,
            thread_id=request.thread_id,
        )
        return {"message": "Draft saved", "draft_id": draft_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save draft: {str(e)}")
