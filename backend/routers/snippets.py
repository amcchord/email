"""Authenticated private Personal Snippets API."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.models.snippet import PersonalSnippet
from backend.models.user import User
from backend.routers.auth import get_current_user
from backend.schemas.snippet import (
    MAX_PERSONAL_SNIPPETS,
    PersonalSnippetCreate,
    PersonalSnippetListResponse,
    PersonalSnippetReplace,
    PersonalSnippetResponse,
)
from backend.services.snippets import (
    SnippetConflict,
    SnippetNotFound,
    SnippetQuotaExceeded,
    create_personal_snippet,
    delete_personal_snippet,
    list_personal_snippets,
    replace_personal_snippet,
)


router = APIRouter(prefix="/api/compose/snippets", tags=["compose", "snippets"])


def _response(snippet: PersonalSnippet) -> PersonalSnippetResponse:
    return PersonalSnippetResponse(
        snippet_id=snippet.snippet_id,
        name=snippet.name,
        shortcut=snippet.shortcut,
        body_html=snippet.body_html,
        body_text=snippet.body_text,
        revision=snippet.revision,
        created_at=snippet.created_at,
        updated_at=snippet.updated_at,
    )


def _raise_snippet_http_error(error: Exception) -> None:
    if isinstance(error, SnippetNotFound):
        raise HTTPException(
            status_code=404,
            detail={"code": "snippet_not_found", "message": str(error)},
        ) from error
    if isinstance(error, SnippetConflict):
        raise HTTPException(
            status_code=409,
            detail={"code": "snippet_conflict", "message": str(error)},
        ) from error
    if isinstance(error, SnippetQuotaExceeded):
        raise HTTPException(
            status_code=429,
            detail={"code": "snippet_quota_exceeded", "message": str(error)},
        ) from error
    raise error


@router.get("", response_model=PersonalSnippetListResponse)
async def list_snippets(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    snippets = await list_personal_snippets(db, user_id=user.id)
    return PersonalSnippetListResponse(
        snippets=[_response(snippet) for snippet in snippets],
        total=len(snippets),
        limit=MAX_PERSONAL_SNIPPETS,
    )


@router.post("", response_model=PersonalSnippetResponse)
async def create_snippet(
    request: PersonalSnippetCreate,
    response: Response,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        snippet, created = await create_personal_snippet(
            db,
            user_id=user.id,
            request=request,
        )
    except (SnippetConflict, SnippetQuotaExceeded) as error:
        _raise_snippet_http_error(error)
    response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    return _response(snippet)


@router.put("/{snippet_id}", response_model=PersonalSnippetResponse)
async def replace_snippet(
    snippet_id: UUID,
    request: PersonalSnippetReplace,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        snippet = await replace_personal_snippet(
            db,
            user_id=user.id,
            snippet_id=snippet_id,
            request=request,
        )
    except (SnippetNotFound, SnippetConflict) as error:
        _raise_snippet_http_error(error)
    return _response(snippet)


@router.delete("/{snippet_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_snippet(
    snippet_id: UUID,
    expected_revision: int = Query(gt=0),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        await delete_personal_snippet(
            db,
            user_id=user.id,
            snippet_id=snippet_id,
            expected_revision=expected_revision,
        )
    except SnippetConflict as error:
        _raise_snippet_http_error(error)
