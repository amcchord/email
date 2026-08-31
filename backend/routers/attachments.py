"""Authenticated metadata-only attachment workspace API."""

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.exceptions import HTTPException as StarletteHTTPException

from backend.config import get_settings
from backend.database import get_db
from backend.models.user import User
from backend.routers.auth import get_current_user
from backend.schemas.attachment_workspace import (
    AttachmentWorkspaceQueryRequest,
    AttachmentWorkspaceQueryResponse,
)
from backend.services.attachment_workspace import (
    AttachmentWorkspaceInvalidCursor,
    AttachmentWorkspaceNotFound,
    query_attachment_workspace,
)


PRIVATE_NO_STORE_HEADERS = {"Cache-Control": "private, no-store"}


class PrivateNoStoreRoute(APIRoute):
    """Apply private/no-store to successes, auth failures, and validation errors."""

    def get_route_handler(self):
        original = super().get_route_handler()

        async def no_store_handler(request):
            try:
                response = await original(request)
            except RequestValidationError as error:
                return JSONResponse(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    content={"detail": jsonable_encoder(error.errors())},
                    headers=PRIVATE_NO_STORE_HEADERS,
                )
            except StarletteHTTPException as error:
                headers = dict(error.headers or {})
                headers.update(PRIVATE_NO_STORE_HEADERS)
                raise StarletteHTTPException(
                    status_code=error.status_code,
                    detail=error.detail,
                    headers=headers,
                ) from error
            response.headers.update(PRIVATE_NO_STORE_HEADERS)
            return response

        return no_store_handler


router = APIRouter(
    prefix="/api/attachments",
    tags=["attachments"],
    route_class=PrivateNoStoreRoute,
)
settings = get_settings()


@router.post("/query", response_model=AttachmentWorkspaceQueryResponse)
async def query_attachments(
    request: AttachmentWorkspaceQueryRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        return await query_attachment_workspace(
            db,
            user_id=user.id,
            account_id=request.account_id,
            secret_key=settings.secret_key,
            query=request.query,
            kind=request.kind,
            direction=request.direction,
            cursor=request.cursor,
            page_size=request.page_size,
        )
    except AttachmentWorkspaceNotFound as error:
        raise HTTPException(status_code=404, detail="Attachment workspace not found") from error
    except AttachmentWorkspaceInvalidCursor as error:
        raise HTTPException(status_code=422, detail="Attachment cursor is invalid") from error
