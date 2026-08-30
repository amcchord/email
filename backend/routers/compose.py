import base64
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.models.draft import DraftSession
from backend.models.outbound_message import OutboundMessage
from backend.models.user import User
from backend.routers.auth import get_current_user
from backend.schemas.email import (
    ComposeDraftRequest,
    ComposeRequest,
    DraftAttachmentDetail,
    DraftMutationRequest,
    DraftSessionDetailResponse,
    DraftSessionResponse,
    OutboundSendResponse,
)
from backend.services.drafts import (
    DraftConflict,
    DraftNotFound,
    DraftPersistenceError,
    DraftQuotaExceeded,
    DraftSourceExists,
    DraftValidationError,
    discard_draft_session,
    draft_can_undo_discard,
    get_draft_session,
    get_draft_session_for_email,
    get_draft_session_for_source_email,
    recent_draft_sessions,
    stage_draft_upsert,
    try_enqueue_draft_drain,
    undo_discard_draft_session,
)
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
        client_draft_id=outbound.client_draft_id,
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


def _draft_response(draft: DraftSession) -> DraftSessionResponse:
    return DraftSessionResponse(
        client_draft_id=draft.client_draft_id,
        account_id=draft.account_id,
        source_email_id=draft.source_email_id_snapshot,
        revision=draft.revision,
        synced_revision=draft.synced_revision,
        state=draft.state,
        next_attempt_at=draft.next_attempt_at,
        attempt_count=draft.attempt_count,
        can_undo_discard=draft_can_undo_discard(draft),
        discard_at=draft.discard_at,
        discard_undo_until=draft.discard_undo_until,
        linked_send_id=draft.linked_send_id,
        error_code=draft.error_code,
        error_message=draft.error_message,
        attachment_count=draft.attachment_count,
        attachment_bytes=draft.attachment_bytes,
        created_at=draft.created_at,
        updated_at=draft.updated_at,
        synced_at=draft.synced_at,
        discarded_at=draft.discarded_at,
    )


def _draft_detail_response(draft: DraftSession) -> DraftSessionDetailResponse:
    metadata = _draft_response(draft).model_dump()
    payload = draft.payload if isinstance(draft.payload, dict) else {}
    attachments = [
        DraftAttachmentDetail(
            attachment_id=attachment.attachment_id,
            filename=attachment.filename,
            content_type=attachment.content_type,
            size_bytes=attachment.size_bytes,
            sha256=attachment.sha256,
            data_base64=base64.b64encode(attachment.content).decode("ascii"),
        )
        for attachment in sorted(draft.attachments, key=lambda item: item.sort_order)
    ]
    return DraftSessionDetailResponse(
        **metadata,
        to=list(payload.get("to") or []),
        cc=list(payload.get("cc") or []),
        bcc=list(payload.get("bcc") or []),
        subject=str(payload.get("subject") or ""),
        body_html=str(payload.get("body_html") or ""),
        body_text=str(payload.get("body_text") or ""),
        in_reply_to=payload.get("in_reply_to"),
        references=payload.get("references"),
        thread_id=payload.get("thread_id"),
        attachments=attachments,
    )


def _raise_draft_http_error(error: Exception) -> None:
    if isinstance(error, DraftQuotaExceeded):
        raise HTTPException(
            status_code=429,
            detail={"code": "draft_rate_limited", "message": str(error)},
            headers={"Retry-After": str(error.retry_after_seconds)},
        ) from error
    if isinstance(error, DraftNotFound):
        raise HTTPException(
            status_code=404,
            detail={"code": "draft_not_found", "message": str(error)},
        ) from error
    if isinstance(error, DraftConflict):
        code = "draft_source_exists" if isinstance(error, DraftSourceExists) else "draft_conflict"
        raise HTTPException(
            status_code=409,
            detail={"code": code, "message": str(error)},
        ) from error
    if isinstance(error, DraftValidationError):
        raise HTTPException(
            status_code=422,
            detail={"code": "draft_invalid", "message": str(error)},
        ) from error
    if isinstance(error, DraftPersistenceError):
        raise HTTPException(
            status_code=503,
            detail={
                "code": "draft_unavailable",
                "message": "Draft could not be accepted right now",
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
        if outbound.draft_session_id is not None:
            background_tasks.add_task(try_enqueue_draft_drain)
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


@router.post(
    "/draft",
    response_model=DraftSessionResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def save_draft(
    request: ComposeDraftRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        draft, created = await stage_draft_upsert(
            db,
            user_id=user.id,
            request=request,
        )
    except (
        DraftNotFound,
        DraftConflict,
        DraftQuotaExceeded,
        DraftValidationError,
        DraftPersistenceError,
    ) as error:
        _raise_draft_http_error(error)
    if created or draft.state in {"pending", "reconciling"}:
        background_tasks.add_task(try_enqueue_draft_drain)
    return _draft_response(draft)


@router.get("/drafts/recent", response_model=list[DraftSessionResponse])
async def recent_drafts(
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    drafts = await recent_draft_sessions(db, user_id=user.id, limit=limit)
    return [_draft_response(draft) for draft in drafts]


@router.get(
    "/drafts/by-client-id/{client_draft_id}",
    response_model=DraftSessionDetailResponse,
)
async def get_draft_by_client_id(
    client_draft_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        draft = await get_draft_session(
            db,
            user_id=user.id,
            client_draft_id=client_draft_id,
            include_attachments=True,
        )
    except DraftNotFound as error:
        _raise_draft_http_error(error)
    return _draft_detail_response(draft)


@router.get(
    "/drafts/by-source-email/{source_email_id}",
    response_model=DraftSessionDetailResponse,
)
async def get_draft_by_source_email(
    source_email_id: int,
    account_id: int = Query(..., gt=0),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        draft = await get_draft_session_for_source_email(
            db,
            user_id=user.id,
            account_id=account_id,
            source_email_id=source_email_id,
        )
    except (DraftNotFound, DraftConflict) as error:
        _raise_draft_http_error(error)
    return _draft_detail_response(draft)


@router.get(
    "/drafts/by-email/{email_id}",
    response_model=DraftSessionDetailResponse,
)
async def get_draft_by_email(
    email_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        draft = await get_draft_session_for_email(
            db,
            user_id=user.id,
            email_id=email_id,
        )
    except DraftNotFound as error:
        _raise_draft_http_error(error)
    return _draft_detail_response(draft)


@router.post(
    "/drafts/{client_draft_id}/discard",
    response_model=DraftSessionResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def discard_draft(
    client_draft_id: UUID,
    request: DraftMutationRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        draft = await discard_draft_session(
            db,
            user_id=user.id,
            client_draft_id=client_draft_id,
            mutation_id=request.mutation_id,
        )
    except (DraftNotFound, DraftConflict) as error:
        _raise_draft_http_error(error)
    background_tasks.add_task(try_enqueue_draft_drain)
    return _draft_response(draft)


@router.post(
    "/drafts/{client_draft_id}/undo-discard",
    response_model=DraftSessionResponse,
)
async def undo_discard_draft(
    client_draft_id: UUID,
    request: DraftMutationRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        draft = await undo_discard_draft_session(
            db,
            user_id=user.id,
            client_draft_id=client_draft_id,
            mutation_id=request.mutation_id,
        )
    except (DraftNotFound, DraftConflict) as error:
        _raise_draft_http_error(error)
    if draft.state in {"pending", "reconciling"}:
        background_tasks.add_task(try_enqueue_draft_drain)
    return _draft_response(draft)
