"""Authenticated private Saved Views / Custom Splits API."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.exceptions import HTTPException as StarletteHTTPException

from backend.database import get_db
from backend.models.saved_view import SavedView
from backend.models.user import User
from backend.routers.auth import get_current_user
from backend.schemas.saved_view import (
    MAX_SAVED_VIEWS,
    SavedViewCreate,
    SavedViewListResponse,
    SavedViewReorder,
    SavedViewReplace,
    SavedViewResponse,
)
from backend.services.saved_views import (
    SavedViewConflict,
    SavedViewNotFound,
    create_saved_view,
    delete_saved_view,
    list_saved_views,
    reorder_saved_views,
    replace_saved_view,
)


NO_STORE_HEADERS = {"Cache-Control": "private, no-store"}


class PrivateNoStoreRoute(APIRoute):
    """Apply private/no-store to successes and route-level error responses."""

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
    prefix="/api/saved-views",
    tags=["saved-views"],
    route_class=PrivateNoStoreRoute,
)


def _response(view: SavedView) -> SavedViewResponse:
    return SavedViewResponse(
        id=view.id,
        create_id=view.create_id,
        name=view.name,
        query=view.query,
        account_id=view.account_id,
        position=view.position,
        revision=view.revision,
        created_at=view.created_at,
        updated_at=view.updated_at,
    )


def _raise_saved_view_http_error(error: Exception) -> None:
    if isinstance(error, SavedViewNotFound):
        raise HTTPException(
            status_code=404,
            detail={
                "code": "saved_view_not_found",
                "message": "Saved view not found",
            },
        ) from error
    if isinstance(error, SavedViewConflict):
        raise HTTPException(
            status_code=409,
            detail={"code": "saved_view_conflict", "message": str(error)},
        ) from error
    raise error


def _list_response(views: list[SavedView]) -> SavedViewListResponse:
    ordered = sorted(views, key=lambda view: (view.position, view.row_id))
    return SavedViewListResponse(
        items=[_response(view) for view in ordered],
        max_views=MAX_SAVED_VIEWS,
    )


@router.get("", response_model=SavedViewListResponse)
async def get_saved_views(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return _list_response(await list_saved_views(db, user_id=user.id))


@router.post("", response_model=SavedViewResponse)
async def post_saved_view(
    request: SavedViewCreate,
    response: Response,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        view, created = await create_saved_view(db, user_id=user.id, request=request)
    except (SavedViewNotFound, SavedViewConflict) as error:
        _raise_saved_view_http_error(error)
    response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    return _response(view)


@router.post("/reorder", response_model=SavedViewListResponse)
async def post_saved_view_reorder(
    request: SavedViewReorder,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        views = await reorder_saved_views(
            db,
            user_id=user.id,
            expected_order=request.expected_order,
            view_ids=request.view_ids,
        )
    except SavedViewConflict as error:
        _raise_saved_view_http_error(error)
    return _list_response(views)


@router.put("/{view_id}", response_model=SavedViewResponse)
async def put_saved_view(
    view_id: UUID,
    request: SavedViewReplace,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        view = await replace_saved_view(
            db,
            user_id=user.id,
            view_id=view_id,
            request=request,
        )
    except (SavedViewNotFound, SavedViewConflict) as error:
        _raise_saved_view_http_error(error)
    return _response(view)


@router.delete("/{view_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_saved_view(
    view_id: UUID,
    revision: int = Query(gt=0),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        await delete_saved_view(
            db,
            user_id=user.id,
            view_id=view_id,
            revision=revision,
        )
    except (SavedViewNotFound, SavedViewConflict) as error:
        _raise_saved_view_http_error(error)
    return Response(status_code=status.HTTP_204_NO_CONTENT, headers=NO_STORE_HEADERS)
