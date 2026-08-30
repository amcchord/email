from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.models.account import GoogleAccount
from backend.models.outbound_message import OutboundMessage
from backend.models.user import User
from backend.routers.auth import get_current_user
from backend.schemas.email import ComposeDraftRequest, ComposeRequest, OutboundSendResponse
from backend.services.credentials import get_google_credentials
from backend.services.gmail import GmailService
from backend.services.outbound_messages import (
    OutboundMessageConflict,
    OutboundMessageNotFound,
    OutboundMessagePersistenceError,
    OutboundMessageQuotaExceeded,
    OutboundMessageValidationError,
    get_outbound_message,
    get_outbound_message_by_idempotency,
    outbound_can_retry,
    outbound_can_undo,
    recent_outbound_messages,
    retry_outbound_message,
    stage_outbound_message,
    try_enqueue_outbound_drain,
    undo_outbound_message,
)


router = APIRouter(prefix="/api/compose", tags=["compose"])


def _outbound_response(outbound: OutboundMessage) -> OutboundSendResponse:
    return OutboundSendResponse(
        send_id=outbound.send_id,
        idempotency_key=outbound.idempotency_key,
        account_id=outbound.account_id,
        source_email_id=outbound.source_email_id,
        state=outbound.state,
        execute_after=outbound.execute_after,
        undo_until=outbound.undo_until,
        next_attempt_at=outbound.next_attempt_at,
        attempt_count=outbound.attempt_count,
        max_attempts=outbound.max_attempts,
        can_undo=outbound_can_undo(outbound),
        can_retry=outbound_can_retry(outbound),
        provider_message_id=outbound.provider_message_id,
        error_code=outbound.error_code,
        error_message=outbound.error_message,
        created_at=outbound.created_at,
        updated_at=outbound.updated_at,
        sent_at=outbound.sent_at,
        failed_at=outbound.failed_at,
        cancelled_at=outbound.cancelled_at,
    )


def _raise_outbound_http_error(error: Exception) -> None:
    if isinstance(error, OutboundMessageQuotaExceeded):
        raise HTTPException(
            status_code=429,
            detail={"code": "outbound_rate_limited", "message": str(error)},
            headers={"Retry-After": str(error.retry_after_seconds)},
        ) from error
    if isinstance(error, OutboundMessageNotFound):
        raise HTTPException(
            status_code=404,
            detail={"code": "outbound_not_found", "message": str(error)},
        ) from error
    if isinstance(error, OutboundMessageConflict):
        raise HTTPException(
            status_code=409,
            detail={"code": "outbound_conflict", "message": str(error)},
        ) from error
    if isinstance(error, OutboundMessageValidationError):
        raise HTTPException(
            status_code=422,
            detail={"code": "outbound_invalid", "message": str(error)},
        ) from error
    if isinstance(error, OutboundMessagePersistenceError):
        raise HTTPException(
            status_code=503,
            detail={
                "code": "outbound_unavailable",
                "message": "Send could not be accepted right now",
            },
            headers={"Retry-After": "5"},
        ) from error
    raise error


@router.post(
    "/send",
    response_model=OutboundSendResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def send_email(
    request: ComposeRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        outbound, created = await stage_outbound_message(
            db,
            user_id=user.id,
            request=request,
        )
    except (
        OutboundMessageNotFound,
        OutboundMessageConflict,
        OutboundMessageQuotaExceeded,
        OutboundMessageValidationError,
        OutboundMessagePersistenceError,
    ) as error:
        _raise_outbound_http_error(error)
    if created:
        background_tasks.add_task(try_enqueue_outbound_drain)
    return _outbound_response(outbound)


@router.get("/sends/recent", response_model=list[OutboundSendResponse])
async def recent_sends(
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    sends = await recent_outbound_messages(db, user_id=user.id, limit=limit)
    return [_outbound_response(outbound) for outbound in sends]


@router.get(
    "/sends/by-idempotency/{idempotency_key}",
    response_model=OutboundSendResponse,
)
async def get_send_by_idempotency(
    idempotency_key: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        outbound = await get_outbound_message_by_idempotency(
            db,
            user_id=user.id,
            idempotency_key=idempotency_key,
        )
    except OutboundMessageNotFound as error:
        _raise_outbound_http_error(error)
    return _outbound_response(outbound)


@router.get("/sends/{send_id}", response_model=OutboundSendResponse)
async def get_send(
    send_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        outbound = await get_outbound_message(db, user_id=user.id, send_id=send_id)
    except OutboundMessageNotFound as error:
        _raise_outbound_http_error(error)
    return _outbound_response(outbound)


@router.post("/sends/{send_id}/undo", response_model=OutboundSendResponse)
async def undo_send(
    send_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        outbound = await undo_outbound_message(db, user_id=user.id, send_id=send_id)
    except (OutboundMessageNotFound, OutboundMessageConflict) as error:
        _raise_outbound_http_error(error)
    return _outbound_response(outbound)


@router.post("/sends/{send_id}/retry", response_model=OutboundSendResponse)
async def retry_send(
    send_id: UUID,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        outbound = await retry_outbound_message(db, user_id=user.id, send_id=send_id)
    except (OutboundMessageNotFound, OutboundMessageConflict) as error:
        _raise_outbound_http_error(error)
    background_tasks.add_task(try_enqueue_outbound_drain)
    return _outbound_response(outbound)


@router.post("/draft")
async def save_draft(
    request: ComposeDraftRequest,
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
    if getattr(account, "is_active", True) is False:
        raise HTTPException(status_code=422, detail="Account is inactive")

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
            in_reply_to=request.in_reply_to,
            references=request.references,
            thread_id=request.thread_id,
            attachments=request.attachments,
        )
        return {"message": "Draft saved", "draft_id": draft_id}
    except ValueError as error:
        raise HTTPException(status_code=400, detail="Draft content is invalid") from error
    except Exception as error:
        raise HTTPException(status_code=503, detail="Gmail is temporarily unavailable") from error
