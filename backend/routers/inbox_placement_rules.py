"""Authenticated private API for local user-trainable Inbox placement rules."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.exceptions import HTTPException as StarletteHTTPException

from backend.database import get_db
from backend.models.user import User
from backend.routers.auth import get_current_user
from backend.schemas.inbox_placement_rule import (
    MAX_INBOX_PLACEMENT_RULES_PER_ACCOUNT,
    InboxPlacementRuleCandidateResponse,
    InboxPlacementRuleListResponse,
    InboxPlacementRuleReplace,
    InboxPlacementRuleResponse,
    InboxPlacementRuleUpsert,
)
from backend.services.inbox_placement_rules import (
    InboxPlacementCandidate,
    InboxPlacementRuleCandidateUnavailable,
    InboxPlacementRuleConflict,
    InboxPlacementRuleNotFound,
    InboxPlacementRuleView,
    delete_inbox_placement_rule,
    get_inbox_placement_candidate,
    list_inbox_placement_rules,
    replace_inbox_placement_rule,
    upsert_inbox_placement_rule,
)


NO_STORE_HEADERS = {"Cache-Control": "private, no-store"}


class PrivateNoStoreRoute(APIRoute):
    def get_route_handler(self):
        original = super().get_route_handler()

        async def no_store_handler(request):
            try:
                response = await original(request)
            except RequestValidationError as error:
                return JSONResponse(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    content={"detail": jsonable_encoder(error.errors())},
                    headers=NO_STORE_HEADERS,
                )
            except StarletteHTTPException as error:
                headers = dict(error.headers or {})
                headers.update(NO_STORE_HEADERS)
                raise StarletteHTTPException(
                    status_code=error.status_code,
                    detail=error.detail,
                    headers=headers,
                ) from error
            response.headers.update(NO_STORE_HEADERS)
            return response

        return no_store_handler


router = APIRouter(
    prefix="/api/inbox-placement-rules",
    tags=["inbox-placement-rules"],
    route_class=PrivateNoStoreRoute,
)


def _response(view: InboxPlacementRuleView) -> InboxPlacementRuleResponse:
    rule = view.rule
    return InboxPlacementRuleResponse(
        id=rule.id,
        account_id=rule.account_id,
        account_email=view.account_email,
        scope=rule.scope,
        display_value=view.display_value,
        placement=rule.placement,
        enabled=rule.enabled,
        revision=rule.revision,
        created_at=rule.created_at,
        updated_at=rule.updated_at,
    )


def _candidate_response(
    candidate: InboxPlacementCandidate,
) -> InboxPlacementRuleCandidateResponse:
    return InboxPlacementRuleCandidateResponse(
        account_id=candidate.account_id,
        account_email=candidate.account_email,
        anchor_email_id=candidate.anchor_email_id,
        conversation_label=candidate.conversation_label,
        sender_address=candidate.sender_address,
        sender_domain=candidate.sender_domain,
        rules=[_response(view) for view in candidate.rules],
    )


def _raise_rule_http_error(error: Exception) -> None:
    if isinstance(error, InboxPlacementRuleNotFound):
        raise HTTPException(
            status_code=404,
            detail={
                "code": "inbox_placement_rule_not_found",
                "message": "Inbox placement rule not found",
            },
        ) from error
    if isinstance(error, InboxPlacementRuleCandidateUnavailable):
        raise HTTPException(
            status_code=422,
            detail={
                "code": "inbox_placement_rule_candidate_unavailable",
                "message": str(error),
            },
        ) from error
    if isinstance(error, InboxPlacementRuleConflict):
        raise HTTPException(
            status_code=409,
            detail={
                "code": "inbox_placement_rule_conflict",
                "message": str(error),
            },
        ) from error
    raise error


@router.get("", response_model=InboxPlacementRuleListResponse)
async def get_inbox_placement_rules(
    account_id: int | None = Query(default=None, gt=0),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        views = await list_inbox_placement_rules(
            db,
            user_id=user.id,
            account_id=account_id,
        )
    except InboxPlacementRuleNotFound as error:
        _raise_rule_http_error(error)
    return InboxPlacementRuleListResponse(
        items=[_response(view) for view in views],
        max_rules_per_account=MAX_INBOX_PLACEMENT_RULES_PER_ACCOUNT,
    )


@router.get("/candidate", response_model=InboxPlacementRuleCandidateResponse)
async def get_inbox_placement_rule_candidate(
    account_id: int = Query(gt=0),
    anchor_email_id: int = Query(gt=0),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        candidate = await get_inbox_placement_candidate(
            db,
            user_id=user.id,
            account_id=account_id,
            anchor_email_id=anchor_email_id,
        )
    except (InboxPlacementRuleNotFound, InboxPlacementRuleCandidateUnavailable) as error:
        _raise_rule_http_error(error)
    return _candidate_response(candidate)


@router.post("", response_model=InboxPlacementRuleResponse)
async def post_inbox_placement_rule(
    request: InboxPlacementRuleUpsert,
    response: Response,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        view, created = await upsert_inbox_placement_rule(
            db,
            user_id=user.id,
            request=request,
        )
    except (
        InboxPlacementRuleNotFound,
        InboxPlacementRuleCandidateUnavailable,
        InboxPlacementRuleConflict,
    ) as error:
        _raise_rule_http_error(error)
    response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    return _response(view)


@router.put("/{rule_id}", response_model=InboxPlacementRuleResponse)
async def put_inbox_placement_rule(
    rule_id: UUID,
    request: InboxPlacementRuleReplace,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        view = await replace_inbox_placement_rule(
            db,
            user_id=user.id,
            rule_id=rule_id,
            request=request,
        )
    except (InboxPlacementRuleNotFound, InboxPlacementRuleConflict) as error:
        _raise_rule_http_error(error)
    return _response(view)


@router.delete("/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_inbox_placement_rule(
    rule_id: UUID,
    revision: int = Query(gt=0),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        await delete_inbox_placement_rule(
            db,
            user_id=user.id,
            rule_id=rule_id,
            revision=revision,
        )
    except (InboxPlacementRuleNotFound, InboxPlacementRuleConflict) as error:
        _raise_rule_http_error(error)
    return Response(status_code=status.HTTP_204_NO_CONTENT, headers=NO_STORE_HEADERS)
