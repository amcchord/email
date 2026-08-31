"""Web-session-only contact projections over synchronized mail metadata."""

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import get_settings
from backend.database import get_db
from backend.models.user import User
from backend.routers.auth import get_current_user
from backend.schemas.contact import (
    ContactProfileRequest,
    ContactProfileResponse,
    ContactQueryRequest,
    ContactQueryResponse,
)
from backend.services.contact_profiles import (
    ContactNotFound,
    get_contact_profile,
    query_contact_profiles,
)


router = APIRouter(prefix="/api/contacts", tags=["contacts"])
settings = get_settings()
PRIVATE_NO_STORE_HEADERS = {"Cache-Control": "private, no-store"}


def _private_no_store(response: Response) -> None:
    response.headers.update(PRIVATE_NO_STORE_HEADERS)


@router.post("/query", response_model=ContactQueryResponse)
async def query_contacts(
    request: ContactQueryRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _private_no_store(response)
    try:
        return await query_contact_profiles(
            db,
            user_id=user.id,
            account_id=request.account_id,
            secret_key=settings.secret_key,
            query=request.query,
            relationship=request.relationship,
            page=request.page,
            page_size=request.page_size,
        )
    except ContactNotFound as error:
        raise HTTPException(
            status_code=404,
            detail="Contact not found",
            headers=PRIVATE_NO_STORE_HEADERS,
        ) from error


@router.post("/profile", response_model=ContactProfileResponse)
async def contact_profile(
    request: ContactProfileRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _private_no_store(response)
    try:
        return await get_contact_profile(
            db,
            user_id=user.id,
            account_id=request.account_id,
            contact_key=request.contact_key,
            secret_key=settings.secret_key,
            recent_limit=request.recent_limit,
        )
    except ContactNotFound as error:
        raise HTTPException(
            status_code=404,
            detail="Contact not found",
            headers=PRIVATE_NO_STORE_HEADERS,
        ) from error
