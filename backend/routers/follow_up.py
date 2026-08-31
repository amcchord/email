"""Authenticated automatic follow-up policy API."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.models.user import User
from backend.routers.auth import get_current_user
from backend.schemas.follow_up import (
    FollowUpPolicyListResponse,
    FollowUpPolicyReplace,
    FollowUpPolicyResponse,
)
from backend.services.follow_up_policies import (
    FollowUpPolicyConflict,
    FollowUpPolicyNotFound,
    list_follow_up_policies,
    replace_follow_up_policy,
)


router = APIRouter(prefix="/api/follow-up", tags=["follow-up"])


def _raise_policy_http_error(error: Exception) -> None:
    if isinstance(error, FollowUpPolicyNotFound):
        raise HTTPException(
            status_code=404,
            detail={"code": "follow_up_policy_not_found", "message": str(error)},
        ) from error
    if isinstance(error, FollowUpPolicyConflict):
        raise HTTPException(
            status_code=409,
            detail={"code": "follow_up_policy_conflict", "message": str(error)},
        ) from error
    raise error


@router.get("/policies", response_model=FollowUpPolicyListResponse)
async def get_follow_up_policies(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    policies = await list_follow_up_policies(db, user_id=user.id)
    return FollowUpPolicyListResponse(accounts=policies, total=len(policies))


@router.put(
    "/policies/{account_id}",
    response_model=FollowUpPolicyResponse,
)
async def put_follow_up_policy(
    account_id: int,
    request: FollowUpPolicyReplace,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        return await replace_follow_up_policy(
            db,
            user_id=user.id,
            account_id=account_id,
            request=request,
        )
    except (FollowUpPolicyNotFound, FollowUpPolicyConflict) as error:
        _raise_policy_http_error(error)
