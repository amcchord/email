"""Authenticated private Share Availability API."""

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.exceptions import HTTPException as StarletteHTTPException

from backend.database import get_db
from backend.models.user import User
from backend.routers.auth import get_current_user
from backend.schemas.calendar_availability import (
    CalendarAvailabilityRequest,
    CalendarAvailabilityResponse,
)
from backend.services.calendar_availability import (
    CalendarAvailabilityInvalidRequest,
    CalendarAvailabilityNotFound,
    get_calendar_availability,
)


NO_STORE_HEADERS = {"Cache-Control": "private, no-store"}


class PrivateNoStoreRoute(APIRoute):
    """Apply private/no-store to successes and route-level errors."""

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
    prefix="/api/calendar",
    tags=["calendar"],
    route_class=PrivateNoStoreRoute,
)


@router.post("/availability", response_model=CalendarAvailabilityResponse)
async def post_calendar_availability(
    request: CalendarAvailabilityRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        return await get_calendar_availability(
            db,
            user_id=user.id,
            request=request,
        )
    except CalendarAvailabilityNotFound as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "account_not_found", "message": "Account not found"},
        ) from error
    except CalendarAvailabilityInvalidRequest as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": "invalid_date_range", "message": str(error)},
        ) from error
