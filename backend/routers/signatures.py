"""Authenticated, account-owned signature settings API."""

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.models.user import User
from backend.routers.auth import get_current_user
from backend.schemas.signature import (
    AccountSignatureListResponse,
    AccountSignatureReplace,
    AccountSignatureResponse,
)
from backend.services.signatures import (
    AccountSignatureView,
    SignatureConflict,
    SignatureNotFound,
    SignatureValidationError,
    list_account_signatures,
    replace_account_signature,
)


router = APIRouter(prefix="/api/compose/signatures", tags=["compose", "signatures"])


def _response(view: AccountSignatureView) -> AccountSignatureResponse:
    return AccountSignatureResponse(
        account_id=view.account_id,
        account_email=view.account_email,
        enabled=view.enabled,
        include_on_new=view.include_on_new,
        include_on_replies=view.include_on_replies,
        include_on_forwards=view.include_on_forwards,
        body_html=view.body_html,
        body_text=view.body_text,
        revision=view.revision,
        sanitizer_version=view.sanitizer_version,
    )


def _raise_signature_http_error(error: Exception) -> None:
    if isinstance(error, SignatureNotFound):
        raise HTTPException(
            status_code=404,
            detail={"code": "signature_not_found", "message": str(error)},
        ) from error
    if isinstance(error, SignatureConflict):
        raise HTTPException(
            status_code=409,
            detail={"code": "signature_conflict", "message": str(error)},
        ) from error
    if isinstance(error, SignatureValidationError):
        raise HTTPException(
            status_code=422,
            detail={"code": "signature_invalid", "message": str(error)},
        ) from error
    raise error


@router.get("", response_model=AccountSignatureListResponse)
async def list_signatures(
    response: Response,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    response.headers["Cache-Control"] = "no-store"
    signatures = await list_account_signatures(db, user_id=user.id)
    return AccountSignatureListResponse(
        accounts=[_response(signature) for signature in signatures],
        total=len(signatures),
    )


@router.put("/{account_id}", response_model=AccountSignatureResponse)
async def replace_signature(
    account_id: int,
    request: AccountSignatureReplace,
    response: Response,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    response.headers["Cache-Control"] = "no-store"
    try:
        signature = await replace_account_signature(
            db,
            user_id=user.id,
            account_id=account_id,
            request=request,
        )
    except (SignatureNotFound, SignatureConflict, SignatureValidationError) as error:
        _raise_signature_http_error(error)
    return _response(signature)
