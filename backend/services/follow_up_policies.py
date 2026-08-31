"""Owner-scoped, revision-safe automatic follow-up policy operations."""

from dataclasses import dataclass

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.account import GoogleAccount
from backend.models.follow_up import AccountFollowUpPolicy
from backend.schemas.follow_up import FollowUpPolicyReplace


class FollowUpPolicyError(Exception):
    """Base class for stable policy API failures."""


class FollowUpPolicyNotFound(FollowUpPolicyError):
    pass


class FollowUpPolicyConflict(FollowUpPolicyError):
    pass


@dataclass(frozen=True, slots=True)
class FollowUpPolicyView:
    account_id: int
    account_email: str
    enabled: bool
    delay_days: int
    wake_local_time: str
    time_zone: str
    weekdays_only: bool
    revision: int


def _view(account: GoogleAccount, policy: AccountFollowUpPolicy | None) -> FollowUpPolicyView:
    if policy is None:
        return FollowUpPolicyView(
            account_id=account.id,
            account_email=account.email,
            enabled=False,
            delay_days=3,
            wake_local_time="09:00",
            time_zone="UTC",
            weekdays_only=True,
            revision=0,
        )
    return FollowUpPolicyView(
        account_id=account.id,
        account_email=account.email,
        enabled=policy.enabled,
        delay_days=policy.delay_days,
        wake_local_time=policy.wake_local_time,
        time_zone=policy.time_zone,
        weekdays_only=policy.weekdays_only,
        revision=policy.revision,
    )


def policy_matches(policy: AccountFollowUpPolicy, request: FollowUpPolicyReplace) -> bool:
    return (
        policy.enabled == request.enabled
        and policy.delay_days == request.delay_days
        and policy.wake_local_time == request.wake_local_time
        and policy.time_zone == request.time_zone
        and policy.weekdays_only == request.weekdays_only
    )


async def list_follow_up_policies(
    db: AsyncSession,
    *,
    user_id: int,
) -> list[FollowUpPolicyView]:
    result = await db.execute(
        select(GoogleAccount, AccountFollowUpPolicy)
        .outerjoin(
            AccountFollowUpPolicy,
            and_(
                AccountFollowUpPolicy.account_id == GoogleAccount.id,
                AccountFollowUpPolicy.user_id == GoogleAccount.user_id,
            ),
        )
        .where(
            GoogleAccount.user_id == user_id,
            GoogleAccount.is_active.is_(True),
            GoogleAccount.encrypted_refresh_token.is_not(None),
            GoogleAccount.encrypted_refresh_token != "",
        )
        .order_by(func.lower(GoogleAccount.email), GoogleAccount.id)
    )
    return [_view(account, policy) for account, policy in result.all()]


async def replace_follow_up_policy(
    db: AsyncSession,
    *,
    user_id: int,
    account_id: int,
    request: FollowUpPolicyReplace,
) -> FollowUpPolicyView:
    # The account lock serializes the row's first create with later revisions.
    account_result = await db.execute(
        select(GoogleAccount)
        .where(
            GoogleAccount.id == account_id,
            GoogleAccount.user_id == user_id,
        )
        .with_for_update()
    )
    account = account_result.scalar_one_or_none()
    if account is None:
        raise FollowUpPolicyNotFound("Follow-up policy account not found")

    policy_result = await db.execute(
        select(AccountFollowUpPolicy).where(
            AccountFollowUpPolicy.account_id == account_id,
            AccountFollowUpPolicy.user_id == user_id,
        )
    )
    policy = policy_result.scalar_one_or_none()

    if policy is not None:
        if policy.revision == request.expected_revision + 1 and policy_matches(
            policy, request
        ):
            # Exact replay after a successful response was lost.
            return _view(account, policy)
        if policy.revision != request.expected_revision:
            raise FollowUpPolicyConflict(
                "This follow-up policy changed on another device; refresh it"
            )
        policy.enabled = request.enabled
        policy.delay_days = request.delay_days
        policy.wake_local_time = request.wake_local_time
        policy.time_zone = request.time_zone
        policy.weekdays_only = request.weekdays_only
        policy.revision += 1
    else:
        if request.expected_revision != 0:
            raise FollowUpPolicyConflict(
                "This follow-up policy changed on another device; refresh it"
            )
        policy = AccountFollowUpPolicy(
            account_id=account.id,
            user_id=user_id,
            enabled=request.enabled,
            delay_days=request.delay_days,
            wake_local_time=request.wake_local_time,
            time_zone=request.time_zone,
            weekdays_only=request.weekdays_only,
            revision=1,
        )
        db.add(policy)

    await db.commit()
    await db.refresh(policy)
    return _view(account, policy)
