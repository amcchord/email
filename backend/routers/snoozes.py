from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.models.user import User
from backend.routers.auth import get_current_user
from backend.schemas.snooze import (
    SnoozeCreateRequest,
    SnoozeListResponse,
    SnoozeRescheduleRequest,
    SnoozeResponse,
    SnoozeStateFilter,
)
from backend.services.snoozes import (
    SnoozeConflict,
    SnoozeNotFound,
    SnoozeValidationError,
    cancel_snooze,
    create_snooze,
    get_snooze,
    get_snooze_by_idempotency,
    list_snoozes,
    reschedule_snooze,
    return_snooze_now,
    try_enqueue_snooze_drain,
)


router = APIRouter(prefix="/api/snoozes", tags=["snoozes"])


def _raise_http(error: Exception):
    if isinstance(error, SnoozeNotFound):
        raise HTTPException(status_code=404, detail=str(error)) from error
    if isinstance(error, SnoozeConflict):
        raise HTTPException(status_code=409, detail=str(error)) from error
    if isinstance(error, SnoozeValidationError):
        raise HTTPException(status_code=422, detail=str(error)) from error
    raise error


@router.post("", response_model=SnoozeResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_email_snooze(
    request: SnoozeCreateRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        response, created = await create_snooze(
            db, user_id=user.id, request=request
        )
    except (SnoozeNotFound, SnoozeConflict, SnoozeValidationError) as error:
        _raise_http(error)
    if created:
        background_tasks.add_task(try_enqueue_snooze_drain)
    return response


@router.get("", response_model=SnoozeListResponse)
async def list_email_snoozes(
    state: SnoozeStateFilter = "active",
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return await list_snoozes(
        db, user_id=user.id, state=state, limit=limit, offset=offset
    )


@router.get("/by-idempotency/{idempotency_key}", response_model=SnoozeResponse)
async def get_email_snooze_by_idempotency(
    idempotency_key: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        return await get_snooze_by_idempotency(
            db, user_id=user.id, idempotency_key=idempotency_key
        )
    except SnoozeNotFound as error:
        _raise_http(error)


@router.get("/{snooze_id}", response_model=SnoozeResponse)
async def get_email_snooze(
    snooze_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        return await get_snooze(db, user_id=user.id, public_id=snooze_id)
    except SnoozeNotFound as error:
        _raise_http(error)


@router.patch("/{snooze_id}/reschedule", response_model=SnoozeResponse)
async def reschedule_email_snooze(
    snooze_id: UUID,
    request: SnoozeRescheduleRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        return await reschedule_snooze(
            db,
            user_id=user.id,
            public_id=snooze_id,
            wake_at=request.wake_at,
            time_zone=request.time_zone,
        )
    except (SnoozeNotFound, SnoozeConflict, SnoozeValidationError) as error:
        _raise_http(error)


@router.post("/{snooze_id}/cancel", response_model=SnoozeResponse)
async def cancel_email_snooze(
    snooze_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        return await cancel_snooze(db, user_id=user.id, public_id=snooze_id)
    except SnoozeNotFound as error:
        _raise_http(error)


@router.post("/{snooze_id}/return-now", response_model=SnoozeResponse)
async def return_email_snooze_now(
    snooze_id: UUID,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        response = await return_snooze_now(
            db, user_id=user.id, public_id=snooze_id
        )
    except (SnoozeNotFound, SnoozeConflict) as error:
        _raise_http(error)
    background_tasks.add_task(try_enqueue_snooze_drain)
    return response
