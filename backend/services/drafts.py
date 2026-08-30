"""Durable Gmail draft sessions.

PostgreSQL owns the writing intent, bytes, revision order, and recovery state.
Redis only wakes the drainer. An initial Gmail create is attempted at most once;
after an ambiguous result the worker performs lookup-only reconciliation by the
stable RFC Message-ID and client draft headers.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4, uuid5

from arq import create_pool
from arq.connections import RedisSettings
from googleapiclient.errors import HttpError
from sqlalchemy import and_, delete, func, or_, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import load_only, selectinload

from backend.config import get_settings
from backend.database import async_session
from backend.models.account import GoogleAccount
from backend.models.draft import DraftAttachment, DraftMutation, DraftSession
from backend.models.email import Email
from backend.schemas.email import ComposeDraftRequest, ComposeRequest
from backend.services.account_lock import account_advisory_lock
from backend.services.credentials import get_google_credentials
from backend.services.gmail import GmailService
from backend.utils.security import encrypt_value


logger = logging.getLogger(__name__)

DRAFT_QUEUE_NAME = "arq:cron"
DRAFT_DISCARD_UNDO_SECONDS = 10
DRAFT_LEASE_SECONDS = 120
DRAFT_MAX_ATTEMPTS = 8
DRAFT_DRAIN_MAX_SESSIONS = 12
DRAFT_GMAIL_TRANSPORT_TIMEOUT_SECONDS = 30.0
DRAFT_REDIS_IO_TIMEOUT_SECONDS = 1.0
DRAFT_RFC_MESSAGE_ID_DOMAIN = "email.mcchord.net"
DRAFT_MUTATION_WINDOW_SECONDS = 60
DRAFT_USER_RECENT_LIMIT = 120
DRAFT_ACCOUNT_RECENT_LIMIT = 90
DRAFT_USER_ACTIVE_LIMIT = 100
DRAFT_ACCOUNT_ACTIVE_LIMIT = 60
DRAFT_USER_STORAGE_LIMIT = 500 * 1024 * 1024
DRAFT_ACCOUNT_STORAGE_LIMIT = 250 * 1024 * 1024
DRAFT_MUTATION_RECEIPTS_PER_SESSION = 100
DRAFT_ACTIVE_STATES = (
    "pending",
    "syncing",
    "reconciling",
    "synced",
    "failed",
    "discard_pending",
    "sending",
)


class DraftError(RuntimeError):
    """Base class for safe API-facing draft errors."""


class DraftNotFound(DraftError):
    pass


class DraftConflict(DraftError):
    pass


class DraftSourceExists(DraftConflict):
    """A different active draft already owns this exact reply source."""


class DraftValidationError(DraftError):
    pass


class DraftQuotaExceeded(DraftError):
    def __init__(self, message: str, *, retry_after_seconds: int):
        super().__init__(message)
        self.retry_after_seconds = max(1, retry_after_seconds)


class DraftPersistenceError(DraftError):
    pass


@dataclass(frozen=True)
class DraftErrorDisposition:
    retryable: bool
    code: str
    message: str


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def draft_can_undo_discard(draft: DraftSession, *, now: datetime | None = None) -> bool:
    current = now or utcnow()
    return bool(
        draft.state == "discard_pending"
        and draft.linked_send_id is None
        and draft.discard_undo_until is not None
        and current <= draft.discard_undo_until
    )


def _expected_reply_references(source: Email) -> str:
    existing = (source.references_header or "").strip()
    parts = existing.split() if existing else []
    message_id = (source.message_id_header or "").strip()
    if message_id and message_id not in parts:
        parts.append(message_id)
    return " ".join(parts)


async def _validate_new_reply_provenance(
    db: AsyncSession,
    *,
    account_id: int,
    request: ComposeDraftRequest,
) -> Email | None:
    has_reply_metadata = any((request.thread_id, request.in_reply_to, request.references))
    if has_reply_metadata and request.source_email_id is None:
        raise DraftValidationError("Reply source is required")
    if request.source_email_id is None:
        return None
    source = (
        await db.execute(
            select(Email).where(
                Email.id == request.source_email_id,
                Email.account_id == account_id,
            )
        )
    ).scalar_one_or_none()
    if source is None:
        raise DraftNotFound("Reply source not found")
    expected_message_id = (source.message_id_header or "").strip() or None
    expected_references = _expected_reply_references(source) or None
    if (
        not has_reply_metadata
        or request.thread_id != source.gmail_thread_id
        or request.in_reply_to != expected_message_id
        or request.references != expected_references
    ):
        raise DraftNotFound("Reply source not found")
    return source


def _validate_existing_reply_provenance(
    draft: DraftSession,
    request: ComposeDraftRequest,
) -> None:
    if request.source_email_id != draft.source_email_id_snapshot:
        raise DraftNotFound("Reply source not found")
    if draft.source_email_id_snapshot is None:
        if any((request.thread_id, request.in_reply_to, request.references)):
            raise DraftNotFound("Reply source not found")
        return
    if (
        request.thread_id != draft.source_gmail_thread_id
        or request.in_reply_to != draft.source_message_id_header
        or request.references != draft.source_references_header
    ):
        raise DraftNotFound("Reply source not found")


def _attachment_material(
    request: ComposeDraftRequest,
) -> tuple[list[dict], list[dict], int]:
    stored = []
    manifest = []
    total = 0
    for index, attachment in enumerate(request.attachments):
        try:
            content = base64.b64decode(attachment.data_base64, validate=True)
        except (TypeError, ValueError) as error:
            raise DraftValidationError("Attachment data is invalid") from error
        digest = hashlib.sha256(content).hexdigest()
        attachment_id = attachment.attachment_id or uuid5(
            request.client_draft_id,
            f"{index}:{attachment.filename}:{attachment.content_type}:{digest}",
        )
        size = len(content)
        total += size
        stored.append({
            "attachment_id": attachment_id,
            "filename": attachment.filename,
            "content_type": attachment.content_type,
            "size_bytes": size,
            "sha256": digest,
            "content": content,
            "sort_order": index,
        })
        manifest.append({
            "filename": attachment.filename,
            "content_type": attachment.content_type,
            "size_bytes": size,
            "sha256": digest,
            "sort_order": index,
        })
    return stored, manifest, total


def _message_payload(request: ComposeDraftRequest | ComposeRequest) -> dict:
    return {
        "account_id": request.account_id,
        "to": list(request.to),
        "cc": list(request.cc),
        "bcc": list(request.bcc),
        "subject": request.subject,
        "body_html": request.body_html,
        "body_text": request.body_text,
        "in_reply_to": request.in_reply_to,
        "references": request.references,
        "thread_id": request.thread_id,
        "source_email_id": request.source_email_id,
    }


def _payload_hash(payload: dict, attachment_manifest: list[dict]) -> str:
    serialized = json.dumps(
        {"message": payload, "attachments": attachment_manifest},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def draft_request_hash(request: ComposeDraftRequest) -> str:
    _stored, manifest, _total = _attachment_material(request)
    return _payload_hash(_message_payload(request), manifest)


def _draft_lock_key(user_id: int, client_draft_id: UUID) -> int:
    digest = hashlib.sha256(f"draft:{user_id}:{client_draft_id}".encode("ascii")).digest()
    return int.from_bytes(digest[:8], byteorder="big", signed=True)


def _draft_acceptance_lock_key(user_id: int) -> int:
    digest = hashlib.sha256(f"draft-acceptance:{user_id}".encode("ascii")).digest()
    return int.from_bytes(digest[:8], byteorder="big", signed=True)


async def _lock_draft(db: AsyncSession, *, user_id: int, client_draft_id: UUID) -> None:
    await db.execute(
        text("SELECT pg_advisory_xact_lock(:lock_key)"),
        {"lock_key": _draft_lock_key(user_id, client_draft_id)},
    )


async def _lock_draft_acceptance(db: AsyncSession, *, user_id: int) -> None:
    await db.execute(
        text("SELECT pg_advisory_xact_lock(:lock_key)"),
        {"lock_key": _draft_acceptance_lock_key(user_id)},
    )


async def _owned_draft(
    db: AsyncSession,
    *,
    user_id: int,
    client_draft_id: UUID,
    for_update: bool = False,
    include_attachments: bool = False,
) -> DraftSession | None:
    statement = select(DraftSession).where(
        DraftSession.user_id == user_id,
        DraftSession.client_draft_id == client_draft_id,
    )
    if include_attachments:
        statement = statement.options(selectinload(DraftSession.attachments))
    if for_update:
        statement = statement.with_for_update()
    return (await db.execute(statement)).scalar_one_or_none()


async def _existing_mutation(
    db: AsyncSession,
    *,
    draft_session_id: int,
    mutation_id: UUID,
) -> DraftMutation | None:
    return (
        await db.execute(
            select(DraftMutation).where(
                DraftMutation.draft_session_id == draft_session_id,
                DraftMutation.mutation_id == mutation_id,
            )
        )
    ).scalar_one_or_none()


async def _recent_mutation_retry_after(
    db: AsyncSession,
    *,
    now: datetime,
    limit: int,
    user_id: int | None = None,
    account_id: int | None = None,
) -> int | None:
    cutoff = now - timedelta(seconds=DRAFT_MUTATION_WINDOW_SECONDS)
    statement = (
        select(DraftMutation.created_at)
        .join(DraftSession, DraftSession.id == DraftMutation.draft_session_id)
        .where(DraftMutation.created_at >= cutoff)
    )
    if user_id is not None:
        statement = statement.where(DraftSession.user_id == user_id)
    if account_id is not None:
        statement = statement.where(DraftSession.account_id == account_id)
    threshold = (
        await db.execute(
            statement.order_by(DraftMutation.created_at.desc(), DraftMutation.id.desc())
            .offset(limit - 1)
            .limit(1)
        )
    ).scalar_one_or_none()
    if threshold is None:
        return None
    return max(
        1,
        math.ceil(
            (threshold + timedelta(seconds=DRAFT_MUTATION_WINDOW_SECONDS) - now).total_seconds()
        ),
    )


async def _enforce_quotas(
    db: AsyncSession,
    *,
    user_id: int,
    account_id: int,
    existing: DraftSession | None,
    replacement_bytes: int,
    now: datetime,
) -> None:
    if existing is None:
        user_active = await db.scalar(
            select(func.count()).select_from(DraftSession).where(
                DraftSession.user_id == user_id,
                DraftSession.state.in_(DRAFT_ACTIVE_STATES),
            )
        )
        account_active = await db.scalar(
            select(func.count()).select_from(DraftSession).where(
                DraftSession.account_id == account_id,
                DraftSession.state.in_(DRAFT_ACTIVE_STATES),
            )
        )
        if int(user_active or 0) >= DRAFT_USER_ACTIVE_LIMIT:
            raise DraftQuotaExceeded("Too many active drafts", retry_after_seconds=60)
        if int(account_active or 0) >= DRAFT_ACCOUNT_ACTIVE_LIMIT:
            raise DraftQuotaExceeded("Too many active drafts", retry_after_seconds=60)

    account_retry = await _recent_mutation_retry_after(
        db,
        now=now,
        limit=DRAFT_ACCOUNT_RECENT_LIMIT,
        account_id=account_id,
    )
    user_retry = await _recent_mutation_retry_after(
        db,
        now=now,
        limit=DRAFT_USER_RECENT_LIMIT,
        user_id=user_id,
    )
    retry_after = max(account_retry or 0, user_retry or 0)
    if retry_after:
        raise DraftQuotaExceeded("Drafts are being saved too quickly", retry_after_seconds=retry_after)

    current_bytes = existing.attachment_bytes if existing is not None else 0
    user_bytes = await db.scalar(
        select(func.coalesce(func.sum(DraftSession.attachment_bytes), 0)).where(
            DraftSession.user_id == user_id,
            DraftSession.state != "discarded",
        )
    )
    account_bytes = await db.scalar(
        select(func.coalesce(func.sum(DraftSession.attachment_bytes), 0)).where(
            DraftSession.account_id == account_id,
            DraftSession.state != "discarded",
        )
    )
    if int(user_bytes or 0) - current_bytes + replacement_bytes > DRAFT_USER_STORAGE_LIMIT:
        raise DraftQuotaExceeded("Draft attachment storage is full", retry_after_seconds=300)
    if int(account_bytes or 0) - current_bytes + replacement_bytes > DRAFT_ACCOUNT_STORAGE_LIMIT:
        raise DraftQuotaExceeded("Draft attachment storage is full", retry_after_seconds=300)


async def _trim_mutation_receipts(db: AsyncSession, *, draft_session_id: int) -> None:
    retained = (
        select(DraftMutation.id)
        .where(DraftMutation.draft_session_id == draft_session_id)
        .order_by(DraftMutation.created_at.desc(), DraftMutation.id.desc())
        .limit(DRAFT_MUTATION_RECEIPTS_PER_SESSION)
    )
    await db.execute(
        delete(DraftMutation).where(
            DraftMutation.draft_session_id == draft_session_id,
            DraftMutation.id.not_in(retained),
        )
    )


async def stage_draft_upsert(
    db: AsyncSession,
    *,
    user_id: int,
    request: ComposeDraftRequest,
    now: datetime | None = None,
) -> tuple[DraftSession, bool]:
    try:
        return await _stage_draft_upsert(db, user_id=user_id, request=request, now=now)
    except DraftError:
        await db.rollback()
        raise
    except Exception as error:
        await db.rollback()
        logger.error("Draft staging failed safely; exception_type=%s", type(error).__name__)
        raise DraftPersistenceError("Draft could not be accepted right now") from None


async def _stage_draft_upsert(
    db: AsyncSession,
    *,
    user_id: int,
    request: ComposeDraftRequest,
    now: datetime | None,
) -> tuple[DraftSession, bool]:
    accepted_at = now or utcnow()
    stored_attachments, manifest, attachment_bytes = _attachment_material(request)
    payload = _message_payload(request)
    payload_hash = _payload_hash(payload, manifest)

    # Draft upserts and outbound Send both acquire the account row before the
    # per-draft advisory/row locks. Keeping that global order prevents an
    # autosave racing Send from deadlocking with the account acceptance path.
    await _lock_draft_acceptance(db, user_id=user_id)
    account = (
        await db.execute(
            select(GoogleAccount)
            .where(
                GoogleAccount.id == request.account_id,
                GoogleAccount.user_id == user_id,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if account is None:
        raise DraftNotFound("Account not found")
    if not account.is_active:
        raise DraftValidationError("Account is inactive")

    await _lock_draft(db, user_id=user_id, client_draft_id=request.client_draft_id)
    draft = await _owned_draft(
        db,
        user_id=user_id,
        client_draft_id=request.client_draft_id,
        for_update=True,
    )
    if draft is not None:
        mutation = await _existing_mutation(
            db,
            draft_session_id=draft.id,
            mutation_id=request.mutation_id,
        )
        if mutation is not None:
            if (
                mutation.operation != "upsert"
                or mutation.revision != request.revision
                or mutation.payload_hash != payload_hash
            ):
                raise DraftConflict("Mutation ID was already used for another draft change")
            await db.commit()
            return draft, False
        if draft.state in {"discard_pending", "discarded", "sending"}:
            raise DraftConflict("Draft is no longer editable")
        if request.revision <= draft.revision:
            raise DraftConflict("Draft revision is stale")
        if request.account_id != draft.account_id:
            raise DraftNotFound("Draft not found")
        _validate_existing_reply_provenance(draft, request)

    source = None
    if draft is None:
        source = await _validate_new_reply_provenance(
            db,
            account_id=account.id,
            request=request,
        )
        if source is not None:
            occupied = (
                await db.execute(
                    select(DraftSession.id).where(
                        DraftSession.user_id == user_id,
                        DraftSession.account_id == account.id,
                        DraftSession.source_email_id_snapshot == source.id,
                        DraftSession.client_draft_id != request.client_draft_id,
                        DraftSession.state != "discarded",
                    ).limit(1)
                )
            ).scalar_one_or_none()
            if occupied is not None:
                # _lock_draft_acceptance serializes competing first saves for
                # different client UUIDs. The loser discovers the winner via
                # the exact owned-source lookup instead of creating another
                # provider draft.
                raise DraftSourceExists("A reply draft already exists for this message")

    await _enforce_quotas(
        db,
        user_id=user_id,
        account_id=account.id,
        existing=draft,
        replacement_bytes=attachment_bytes,
        now=accepted_at,
    )

    created = draft is None
    if draft is None:
        draft = DraftSession(
            client_draft_id=request.client_draft_id,
            user_id=user_id,
            account_id=account.id,
            source_email_id=request.source_email_id,
            source_email_id_snapshot=request.source_email_id,
            source_gmail_thread_id=source.gmail_thread_id if source else None,
            source_message_id_header=(source.message_id_header or "").strip() or None if source else None,
            source_references_header=_expected_reply_references(source) or None if source else None,
            revision=request.revision,
            synced_revision=None,
            payload_hash=payload_hash,
            payload=payload,
            attachment_count=len(stored_attachments),
            attachment_bytes=attachment_bytes,
            rfc_message_id=(
                f"<draft-{request.client_draft_id}@{DRAFT_RFC_MESSAGE_ID_DOMAIN}>"
            ),
            state="pending",
            next_attempt_at=accepted_at,
            attempt_count=0,
            max_attempts=DRAFT_MAX_ATTEMPTS,
            reconcile_count=0,
            created_at=accepted_at,
            updated_at=accepted_at,
        )
        db.add(draft)
        await db.flush()
    else:
        draft.revision = request.revision
        draft.payload_hash = payload_hash
        draft.payload = payload
        draft.attachment_count = len(stored_attachments)
        draft.attachment_bytes = attachment_bytes
        draft.error_code = None
        draft.error_message = None
        draft.updated_at = accepted_at
        if draft.state != "syncing":
            if draft.provider_create_attempted_at is not None and draft.provider_draft_id is None:
                draft.state = "reconciling"
            else:
                draft.state = "pending"
            draft.next_attempt_at = accepted_at
        await db.execute(
            delete(DraftAttachment).where(DraftAttachment.draft_session_id == draft.id)
        )

    for item in stored_attachments:
        db.add(DraftAttachment(draft_session_id=draft.id, created_at=accepted_at, **item))
    db.add(DraftMutation(
        draft_session_id=draft.id,
        mutation_id=request.mutation_id,
        operation="upsert",
        revision=request.revision,
        payload_hash=payload_hash,
        created_at=accepted_at,
    ))
    await db.flush()
    await _trim_mutation_receipts(db, draft_session_id=draft.id)
    await db.commit()
    await _publish_draft_event(draft.user_id, draft.client_draft_id)
    return draft, created


async def get_draft_session(
    db: AsyncSession,
    *,
    user_id: int,
    client_draft_id: UUID,
    include_attachments: bool = False,
) -> DraftSession:
    draft = await _owned_draft(
        db,
        user_id=user_id,
        client_draft_id=client_draft_id,
        include_attachments=include_attachments,
    )
    if draft is None:
        raise DraftNotFound("Draft not found")
    return draft


async def get_draft_session_for_source_email(
    db: AsyncSession,
    *,
    user_id: int,
    account_id: int,
    source_email_id: int,
) -> DraftSession:
    """Resolve one active app draft for an exact owned reply source.

    This lookup is intentionally distinct from ``by-email``: that endpoint
    maps a Gmail Draft mailbox row back to an app-managed draft, while this
    endpoint resumes a reply from its original received message.
    """
    source = (
        await db.execute(
            select(Email.id)
            .join(GoogleAccount, GoogleAccount.id == Email.account_id)
            .where(
                Email.id == source_email_id,
                Email.account_id == account_id,
                GoogleAccount.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if source is None:
        raise DraftNotFound("Draft not found")

    matches = list((await db.execute(
        select(DraftSession)
        .options(selectinload(DraftSession.attachments))
        .where(
            DraftSession.user_id == user_id,
            DraftSession.account_id == account_id,
            DraftSession.source_email_id_snapshot == source_email_id,
            DraftSession.state != "discarded",
        )
        .order_by(DraftSession.updated_at.desc(), DraftSession.id.desc())
        .limit(2)
    )).scalars().all())
    if not matches:
        raise DraftNotFound("Draft not found")
    if len(matches) > 1:
        # Do not silently choose between legacy duplicates. That could reopen
        # or send content from a different writing session.
        raise DraftConflict("Multiple reply drafts require review")
    return matches[0]


async def recent_draft_sessions(
    db: AsyncSession,
    *,
    user_id: int,
    limit: int = 20,
) -> list[DraftSession]:
    result = await db.execute(
        select(DraftSession)
        .options(load_only(
            DraftSession.id,
            DraftSession.client_draft_id,
            DraftSession.account_id,
            DraftSession.source_email_id_snapshot,
            DraftSession.revision,
            DraftSession.synced_revision,
            DraftSession.state,
            DraftSession.next_attempt_at,
            DraftSession.attempt_count,
            DraftSession.discard_at,
            DraftSession.discard_undo_until,
            DraftSession.linked_send_id,
            DraftSession.error_code,
            DraftSession.error_message,
            DraftSession.attachment_count,
            DraftSession.attachment_bytes,
            DraftSession.created_at,
            DraftSession.updated_at,
            DraftSession.synced_at,
            DraftSession.discarded_at,
        ))
        .where(
            DraftSession.user_id == user_id,
            DraftSession.state != "discarded",
        )
        .order_by(DraftSession.updated_at.desc(), DraftSession.id.desc())
        .limit(limit)
    )
    return list(result.scalars().all())


async def get_draft_session_for_email(
    db: AsyncSession,
    *,
    user_id: int,
    email_id: int,
) -> DraftSession:
    email = (
        await db.execute(
            select(Email)
            .join(GoogleAccount, GoogleAccount.id == Email.account_id)
            .where(
                Email.id == email_id,
                Email.is_draft.is_(True),
                GoogleAccount.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if email is None:
        raise DraftNotFound("Draft not found")
    draft = (
        await db.execute(
            select(DraftSession)
            .options(selectinload(DraftSession.attachments))
            .where(
                DraftSession.user_id == user_id,
                DraftSession.account_id == email.account_id,
                DraftSession.provider_message_id == email.gmail_message_id,
                DraftSession.state.not_in(("discarded", "sending")),
            )
        )
    ).scalar_one_or_none()
    if draft is None:
        # Unknown external drafts remain read-only; this lookup never imports
        # or creates a second provider draft.
        raise DraftNotFound("Draft is not managed by this app")
    return draft


def _action_hash(operation: str, mutation_id: UUID) -> str:
    return hashlib.sha256(f"{operation}:{mutation_id}".encode("ascii")).hexdigest()


async def discard_draft_session(
    db: AsyncSession,
    *,
    user_id: int,
    client_draft_id: UUID,
    mutation_id: UUID,
    now: datetime | None = None,
) -> DraftSession:
    current = now or utcnow()
    await _lock_draft(db, user_id=user_id, client_draft_id=client_draft_id)
    draft = await _owned_draft(
        db,
        user_id=user_id,
        client_draft_id=client_draft_id,
        for_update=True,
    )
    if draft is None:
        raise DraftNotFound("Draft not found")
    receipt = await _existing_mutation(
        db,
        draft_session_id=draft.id,
        mutation_id=mutation_id,
    )
    action_hash = _action_hash("discard", mutation_id)
    if receipt is not None:
        if receipt.operation != "discard" or receipt.payload_hash != action_hash:
            raise DraftConflict("Mutation ID was already used for another draft change")
        await db.commit()
        return draft
    if draft.state in {"discarded", "sending"}:
        raise DraftConflict("Draft is no longer editable")
    if draft.state == "syncing":
        raise DraftConflict("Draft is currently syncing; try again shortly")
    deadline = current + timedelta(seconds=DRAFT_DISCARD_UNDO_SECONDS)
    draft.state = "discard_pending"
    draft.discard_at = deadline
    draft.discard_undo_until = deadline
    draft.next_attempt_at = deadline
    draft.error_code = None
    draft.error_message = None
    draft.updated_at = current
    db.add(DraftMutation(
        draft_session_id=draft.id,
        mutation_id=mutation_id,
        operation="discard",
        revision=draft.revision,
        payload_hash=action_hash,
        created_at=current,
    ))
    await db.commit()
    await _publish_draft_event(draft.user_id, draft.client_draft_id)
    return draft


async def undo_discard_draft_session(
    db: AsyncSession,
    *,
    user_id: int,
    client_draft_id: UUID,
    mutation_id: UUID,
    now: datetime | None = None,
) -> DraftSession:
    current = now or utcnow()
    await _lock_draft(db, user_id=user_id, client_draft_id=client_draft_id)
    draft = await _owned_draft(
        db,
        user_id=user_id,
        client_draft_id=client_draft_id,
        for_update=True,
    )
    if draft is None:
        raise DraftNotFound("Draft not found")
    receipt = await _existing_mutation(
        db,
        draft_session_id=draft.id,
        mutation_id=mutation_id,
    )
    action_hash = _action_hash("undo_discard", mutation_id)
    if receipt is not None:
        if receipt.operation != "undo_discard" or receipt.payload_hash != action_hash:
            raise DraftConflict("Mutation ID was already used for another draft change")
        await db.commit()
        return draft
    if not draft_can_undo_discard(draft, now=current):
        raise DraftConflict("Draft can no longer be restored")
    draft.discard_at = None
    draft.discard_undo_until = None
    draft.error_code = None
    draft.error_message = None
    draft.updated_at = current
    if draft.provider_draft_id is not None and draft.synced_revision == draft.revision:
        draft.state = "synced"
        draft.next_attempt_at = None
    elif draft.provider_create_attempted_at is not None and draft.provider_draft_id is None:
        draft.state = "reconciling"
        draft.next_attempt_at = current
    else:
        draft.state = "pending"
        draft.next_attempt_at = current
    db.add(DraftMutation(
        draft_session_id=draft.id,
        mutation_id=mutation_id,
        operation="undo_discard",
        revision=draft.revision,
        payload_hash=action_hash,
        created_at=current,
    ))
    await db.commit()
    await _publish_draft_event(draft.user_id, draft.client_draft_id)
    return draft


def _send_attachment_manifest(request: ComposeRequest) -> tuple[list[dict], int]:
    manifest = []
    total = 0
    for index, attachment in enumerate(request.attachments):
        try:
            content = base64.b64decode(attachment.data_base64, validate=True)
        except (TypeError, ValueError) as error:
            raise DraftValidationError("Attachment data is invalid") from error
        size = len(content)
        total += size
        manifest.append({
            "filename": attachment.filename,
            "content_type": attachment.content_type,
            "size_bytes": size,
            "sha256": hashlib.sha256(content).hexdigest(),
            "sort_order": index,
        })
    return manifest, total


async def link_draft_for_outbound_send(
    db: AsyncSession,
    *,
    user_id: int,
    request: ComposeRequest,
    send_id: UUID,
    discard_at: datetime,
) -> DraftSession | None:
    if request.client_draft_id is None:
        return None
    assert request.draft_revision is not None
    await _lock_draft(db, user_id=user_id, client_draft_id=request.client_draft_id)
    draft = await _owned_draft(
        db,
        user_id=user_id,
        client_draft_id=request.client_draft_id,
        for_update=True,
    )
    if draft is None:
        raise DraftNotFound("Draft not found")
    if draft.account_id != request.account_id:
        raise DraftNotFound("Draft not found")
    if draft.state in {"syncing", "discard_pending", "discarded", "sending"}:
        raise DraftConflict("Draft cannot be sent in its current state")
    if draft.revision != request.draft_revision:
        raise DraftConflict("Draft revision is stale")
    manifest, _total = _send_attachment_manifest(request)
    if _payload_hash(_message_payload(request), manifest) != draft.payload_hash:
        raise DraftConflict("Draft content changed before Send")
    draft.state = "sending"
    draft.linked_send_id = send_id
    draft.discard_at = discard_at
    draft.discard_undo_until = discard_at
    draft.next_attempt_at = discard_at
    draft.error_code = None
    draft.error_message = None
    draft.updated_at = utcnow()
    return draft


async def restore_linked_draft_after_outbound_cancel(
    db: AsyncSession,
    *,
    user_id: int,
    draft_session_id: int,
    send_id: UUID,
    now: datetime,
) -> DraftSession | None:
    """Atomically return a pre-provider cancelled send to an editable draft."""
    draft = (
        await db.execute(
            select(DraftSession)
            .where(
                DraftSession.id == draft_session_id,
                DraftSession.user_id == user_id,
                DraftSession.linked_send_id == send_id,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if draft is None or draft.state != "sending":
        return None
    draft.linked_send_id = None
    draft.discard_at = None
    draft.discard_undo_until = None
    draft.error_code = None
    draft.error_message = None
    draft.updated_at = now
    if draft.provider_draft_id is not None and draft.synced_revision == draft.revision:
        draft.state = "synced"
        draft.next_attempt_at = None
    elif draft.provider_create_attempted_at is not None and draft.provider_draft_id is None:
        draft.state = "reconciling"
        draft.next_attempt_at = now
    else:
        draft.state = "pending"
        draft.next_attempt_at = now
    return draft


async def prepare_linked_draft_for_outbound_discard(
    db: AsyncSession,
    *,
    user_id: int,
    draft_session_id: int,
    send_id: UUID,
    now: datetime,
) -> DraftSession | None:
    """Make a sent operation's linked Gmail draft immediately discardable."""
    draft = (
        await db.execute(
            select(DraftSession)
            .where(
                DraftSession.id == draft_session_id,
                DraftSession.user_id == user_id,
                DraftSession.linked_send_id == send_id,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if draft is None or draft.state != "sending":
        return None
    draft.discard_at = now
    draft.discard_undo_until = now
    draft.next_attempt_at = now
    draft.error_code = None
    draft.error_message = None
    draft.updated_at = now
    return draft


async def publish_draft_session_event(draft: DraftSession) -> None:
    await _publish_draft_event(draft.user_id, draft.client_draft_id)


def classify_draft_error(exc: Exception) -> DraftErrorDisposition:
    status = getattr(getattr(exc, "resp", None), "status", None)
    if status is None:
        status = getattr(exc, "status_code", None)
    error_text = str(exc).lower()
    if status == 403 and any(token in error_text for token in ("quota", "rate", "limit")):
        return DraftErrorDisposition(True, "gmail_rate_limit", "Gmail is temporarily unavailable")
    if status in {400, 401, 403}:
        return DraftErrorDisposition(False, "gmail_authorization", "The draft account needs attention")
    if status in {408, 409, 425, 429} or (isinstance(status, int) and status >= 500):
        return DraftErrorDisposition(True, "gmail_unavailable", "Gmail is temporarily unavailable")
    if isinstance(exc, (TimeoutError, ConnectionError, OSError)):
        return DraftErrorDisposition(True, "gmail_transport", "Gmail is temporarily unavailable")
    return DraftErrorDisposition(True, "gmail_unavailable", "Gmail is temporarily unavailable")


def _retry_delay(attempt_count: int) -> timedelta:
    return timedelta(seconds=min(15 * (2 ** max(attempt_count - 1, 0)), 15 * 60))


def _reconcile_delay(reconcile_count: int) -> timedelta:
    return timedelta(seconds=min(30 * (2 ** max(reconcile_count - 1, 0)), 30 * 60))


async def _reclaim_expired_leases(
    db: AsyncSession,
    *,
    account_id: int,
    now: datetime,
) -> None:
    result = await db.execute(
        select(DraftSession)
        .where(
            DraftSession.account_id == account_id,
            DraftSession.state == "syncing",
            DraftSession.lease_expires_at <= now,
        )
        .with_for_update(skip_locked=True)
    )
    for draft in result.scalars().all():
        operation = draft.lease_operation
        draft.lease_operation = None
        draft.lease_token = None
        draft.lease_expires_at = None
        draft.next_attempt_at = now
        draft.updated_at = now
        if operation == "discard":
            draft.state = "sending" if draft.linked_send_id else "discard_pending"
        elif operation == "reconcile" or (
            draft.provider_create_attempted_at is not None
            and draft.provider_draft_id is None
        ):
            draft.state = "reconciling"
        else:
            draft.state = "pending"


async def _scrub_expired_draft_payload(
    db: AsyncSession,
    *,
    draft: DraftSession,
) -> None:
    """Remove message/attachment bytes once the authoritative Undo window ends."""
    await db.execute(
        delete(DraftAttachment).where(DraftAttachment.draft_session_id == draft.id)
    )
    draft.payload = None
    draft.payload_hash = hashlib.sha256(b"discarded").hexdigest()
    draft.attachment_count = 0
    draft.attachment_bytes = 0


async def _claim_due_drafts(
    db: AsyncSession,
    *,
    account_id: int,
    now: datetime,
    limit: int,
) -> list[DraftSession]:
    await _reclaim_expired_leases(db, account_id=account_id, now=now)
    due = or_(
        and_(DraftSession.state == "pending", DraftSession.next_attempt_at <= now),
        and_(DraftSession.state == "reconciling", DraftSession.next_attempt_at <= now),
        and_(
            DraftSession.state.in_(("discard_pending", "sending")),
            DraftSession.discard_at <= now,
        ),
    )
    result = await db.execute(
        select(DraftSession)
        .options(selectinload(DraftSession.attachments))
        .where(DraftSession.account_id == account_id, due)
        .order_by(DraftSession.updated_at, DraftSession.id)
        .limit(limit)
        .with_for_update(skip_locked=True)
    )
    claimed = list(result.scalars().all())
    for draft in claimed:
        if draft.state in {"discard_pending", "sending"}:
            operation = "discard"
            # The Undo deadline is authoritative. Provider deletion may need
            # retries, but local sensitive bytes do not survive that window.
            await _scrub_expired_draft_payload(db, draft=draft)
        elif draft.state == "reconciling":
            operation = "reconcile"
        else:
            operation = "upsert"
        draft.state = "syncing"
        draft.lease_operation = operation
        draft.lease_token = uuid4()
        draft.lease_expires_at = now + timedelta(seconds=DRAFT_LEASE_SECONDS)
        draft.attempt_count += 1
        draft.next_attempt_at = None
        draft.updated_at = now
    await db.commit()
    return claimed


async def _mark_create_attempt_started(
    *,
    draft_id: int,
    lease_token: UUID,
    now: datetime,
) -> bool:
    async with async_session() as db:
        result = await db.execute(
            update(DraftSession)
            .where(
                DraftSession.id == draft_id,
                DraftSession.state == "syncing",
                DraftSession.lease_token == lease_token,
                DraftSession.provider_draft_id.is_(None),
                DraftSession.provider_create_attempted_at.is_(None),
            )
            .values(provider_create_attempted_at=now, updated_at=now)
            .returning(DraftSession.id)
        )
        marked = result.scalar_one_or_none() is not None
        await db.commit()
        return marked


def _provider_identity(resource: dict) -> tuple[str | None, str | None]:
    draft_id = resource.get("id") if isinstance(resource, dict) else None
    message = resource.get("message") if isinstance(resource, dict) else None
    message_id = message.get("id") if isinstance(message, dict) else None
    return (
        str(draft_id) if draft_id else None,
        str(message_id) if message_id else None,
    )


def _provider_headers(resource: dict) -> dict[str, str]:
    message = resource.get("message") if isinstance(resource, dict) else None
    payload = message.get("payload") if isinstance(message, dict) else None
    headers = payload.get("headers") if isinstance(payload, dict) else None
    return {
        str(item.get("name") or "").lower(): str(item.get("value") or "")
        for item in (headers or [])
        if isinstance(item, dict)
    }


def _matched_provider_revision(draft: DraftSession, resource: dict) -> int | None:
    headers = _provider_headers(resource)
    if headers.get("message-id", "").strip() != draft.rfc_message_id:
        return None
    if headers.get("x-mail-client-draft-id", "").strip().lower() != str(draft.client_draft_id):
        return None
    try:
        revision = int(headers.get("x-mail-client-draft-revision", ""))
    except ValueError:
        return None
    return revision if revision > 0 else None


async def _record_synced(
    *,
    claimed: DraftSession,
    provider_resource: dict,
    provider_revision: int,
    now: datetime,
) -> bool:
    if claimed.lease_token is None:
        return False
    provider_draft_id, provider_message_id = _provider_identity(provider_resource)
    if not provider_draft_id or not provider_message_id:
        return False
    async with async_session() as db:
        draft = (
            await db.execute(
                select(DraftSession)
                .where(
                    DraftSession.id == claimed.id,
                    DraftSession.state == "syncing",
                    DraftSession.lease_token == claimed.lease_token,
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if draft is None:
            return False
        draft.provider_draft_id = provider_draft_id
        draft.provider_message_id = provider_message_id
        draft.synced_revision = max(draft.synced_revision or 0, provider_revision)
        draft.reconcile_count = 0
        draft.lease_operation = None
        draft.lease_token = None
        draft.lease_expires_at = None
        draft.error_code = None
        draft.error_message = None
        draft.synced_at = now
        draft.updated_at = now
        if draft.state == "syncing" and draft.revision <= provider_revision:
            draft.state = "synced"
            draft.next_attempt_at = None
        else:
            draft.state = "pending"
            draft.next_attempt_at = now
        await db.commit()
        user_id, client_draft_id = draft.user_id, draft.client_draft_id
    await _publish_draft_event(user_id, client_draft_id)
    return True


async def _record_retry_or_failure(
    *,
    claimed: DraftSession,
    disposition: DraftErrorDisposition,
    now: datetime,
) -> None:
    if claimed.lease_token is None:
        return
    async with async_session() as db:
        draft = (
            await db.execute(
                select(DraftSession)
                .where(
                    DraftSession.id == claimed.id,
                    DraftSession.state == "syncing",
                    DraftSession.lease_token == claimed.lease_token,
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if draft is None:
            return
        draft.lease_operation = None
        draft.lease_token = None
        draft.lease_expires_at = None
        draft.error_code = disposition.code
        draft.error_message = disposition.message
        draft.updated_at = now
        if disposition.retryable and draft.attempt_count < draft.max_attempts:
            draft.state = "pending"
            draft.next_attempt_at = now + _retry_delay(draft.attempt_count)
        else:
            draft.state = "failed"
            draft.next_attempt_at = None
        await db.commit()
        user_id, client_draft_id = draft.user_id, draft.client_draft_id
    await _publish_draft_event(user_id, client_draft_id)


async def _record_reconciling(
    *,
    claimed: DraftSession,
    now: datetime,
    code: str = "draft_outcome_unknown",
    message: str = "Draft save is being confirmed with Gmail",
) -> None:
    if claimed.lease_token is None:
        return
    async with async_session() as db:
        draft = (
            await db.execute(
                select(DraftSession)
                .where(
                    DraftSession.id == claimed.id,
                    DraftSession.state == "syncing",
                    DraftSession.lease_token == claimed.lease_token,
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if draft is None:
            return
        draft.lease_operation = None
        draft.lease_token = None
        draft.lease_expires_at = None
        draft.reconcile_count += 1
        draft.state = "reconciling"
        draft.next_attempt_at = now + _reconcile_delay(draft.reconcile_count)
        draft.error_code = code
        draft.error_message = message
        draft.updated_at = now
        await db.commit()
        user_id, client_draft_id = draft.user_id, draft.client_draft_id
    await _publish_draft_event(user_id, client_draft_id)


async def _record_discard_reconciling(
    *,
    claimed: DraftSession,
    now: datetime,
    code: str = "discard_outcome_unknown",
    message: str = "Draft discard is being confirmed with Gmail",
) -> None:
    """Keep a tombstone while retrying lookup/delete; never revive content."""
    if claimed.lease_token is None:
        return
    async with async_session() as db:
        draft = (
            await db.execute(
                select(DraftSession)
                .where(
                    DraftSession.id == claimed.id,
                    DraftSession.state == "syncing",
                    DraftSession.lease_token == claimed.lease_token,
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if draft is None:
            return
        await _scrub_expired_draft_payload(db, draft=draft)
        draft.lease_operation = None
        draft.lease_token = None
        draft.lease_expires_at = None
        draft.reconcile_count += 1
        draft.state = "sending" if draft.linked_send_id is not None else "discard_pending"
        draft.discard_at = now + _reconcile_delay(draft.reconcile_count)
        draft.error_code = code
        draft.error_message = message
        draft.updated_at = now
        await db.commit()
        user_id, client_draft_id = draft.user_id, draft.client_draft_id
    await _publish_draft_event(user_id, client_draft_id)


async def _record_provider_missing(*, claimed: DraftSession, now: datetime) -> None:
    await _record_retry_or_failure(
        claimed=claimed,
        disposition=DraftErrorDisposition(
            False,
            "provider_draft_missing",
            "The Gmail draft was changed or removed elsewhere",
        ),
        now=now,
    )


async def _finish_discarded(*, claimed: DraftSession, now: datetime) -> None:
    if claimed.lease_token is None:
        return
    async with async_session() as db:
        draft = (
            await db.execute(
                select(DraftSession)
                .where(
                    DraftSession.id == claimed.id,
                    DraftSession.state == "syncing",
                    DraftSession.lease_token == claimed.lease_token,
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if draft is None:
            return
        await _scrub_expired_draft_payload(db, draft=draft)
        draft.provider_draft_id = None
        draft.provider_message_id = None
        draft.state = "discarded"
        draft.lease_operation = None
        draft.lease_token = None
        draft.lease_expires_at = None
        draft.next_attempt_at = None
        draft.error_code = None
        draft.error_message = None
        draft.discarded_at = now
        draft.updated_at = now
        await db.commit()
        user_id, client_draft_id = draft.user_id, draft.client_draft_id
    await _publish_draft_event(user_id, client_draft_id)


async def _persist_refreshed_token(account_id: int, gmail: GmailService) -> None:
    token = gmail.get_refreshed_token()
    if not token:
        return
    try:
        async with async_session() as db:
            await db.execute(
                update(GoogleAccount)
                .where(GoogleAccount.id == account_id)
                .values(encrypted_access_token=encrypt_value(token))
            )
            await db.commit()
    except Exception as error:
        logger.warning(
            "Could not persist refreshed Gmail token for draft account %s; exception_type=%s",
            account_id,
            type(error).__name__,
        )


def _gmail_attachment_payload(draft: DraftSession) -> list[dict]:
    return [
        {
            "filename": attachment.filename,
            "content_type": attachment.content_type,
            "data_base64": base64.b64encode(attachment.content).decode("ascii"),
        }
        for attachment in sorted(draft.attachments, key=lambda item: item.sort_order)
    ]


async def _lookup_provider_draft(
    draft: DraftSession,
    *,
    gmail: GmailService,
) -> tuple[dict | None, int | None, bool]:
    """Return resource, provider revision, ambiguous-multiple flag."""
    if draft.provider_draft_id:
        resource = await gmail.get_draft_resource(draft.provider_draft_id, max_retries=1)
        return resource, _matched_provider_revision(draft, resource), False
    resources = await gmail.find_drafts_by_rfc_message_id(
        draft.rfc_message_id,
        max_retries=1,
    )
    matches = []
    for resource in resources:
        revision = _matched_provider_revision(draft, resource)
        if revision is not None:
            matches.append((resource, revision))
    if len(matches) > 1:
        return None, None, True
    if not matches:
        return None, None, False
    return matches[0][0], matches[0][1], False


async def _process_reconciliation(draft: DraftSession, *, gmail: GmailService) -> None:
    try:
        resource, provider_revision, multiple = await _lookup_provider_draft(draft, gmail=gmail)
        await _persist_refreshed_token(draft.account_id, gmail)
    except HttpError as error:
        await _persist_refreshed_token(draft.account_id, gmail)
        if getattr(error.resp, "status", None) == 404 and draft.provider_draft_id:
            await _record_provider_missing(claimed=draft, now=utcnow())
        else:
            await _record_reconciling(claimed=draft, now=utcnow())
        return
    except Exception:
        await _persist_refreshed_token(draft.account_id, gmail)
        await _record_reconciling(claimed=draft, now=utcnow())
        return
    if multiple:
        await _record_retry_or_failure(
            claimed=draft,
            disposition=DraftErrorDisposition(
                False,
                "draft_identity_ambiguous",
                "Multiple Gmail drafts match this writing session",
            ),
            now=utcnow(),
        )
        return
    if resource is None or provider_revision is None:
        await _record_reconciling(claimed=draft, now=utcnow())
        return
    await _record_synced(
        claimed=draft,
        provider_resource=resource,
        provider_revision=provider_revision,
        now=utcnow(),
    )


async def _process_upsert(draft: DraftSession, *, gmail: GmailService) -> None:
    payload = draft.payload
    if not isinstance(payload, dict):
        await _record_retry_or_failure(
            claimed=draft,
            disposition=DraftErrorDisposition(False, "payload_missing", "Draft content is unavailable"),
            now=utcnow(),
        )
        return
    kwargs = {
        "to": list(payload.get("to") or []),
        "cc": list(payload.get("cc") or []),
        "bcc": list(payload.get("bcc") or []),
        "subject": str(payload.get("subject") or ""),
        "body_html": str(payload.get("body_html") or ""),
        "body_text": str(payload.get("body_text") or ""),
        "thread_id": payload.get("thread_id"),
        "attachments": _gmail_attachment_payload(draft),
        "in_reply_to": payload.get("in_reply_to"),
        "references": payload.get("references"),
        "message_id_header": draft.rfc_message_id,
        "draft_id_header": str(draft.client_draft_id),
        "draft_revision": draft.revision,
        "max_retries": 1,
    }
    if draft.provider_draft_id:
        try:
            resource = await gmail.update_draft_resource(draft.provider_draft_id, **kwargs)
            await _persist_refreshed_token(draft.account_id, gmail)
        except HttpError as error:
            await _persist_refreshed_token(draft.account_id, gmail)
            if getattr(error.resp, "status", None) == 404:
                await _record_provider_missing(claimed=draft, now=utcnow())
            else:
                await _record_reconciling(claimed=draft, now=utcnow())
            return
        except Exception:
            await _persist_refreshed_token(draft.account_id, gmail)
            await _record_reconciling(claimed=draft, now=utcnow())
            return
    else:
        attempted_at = utcnow()
        if not await _mark_create_attempt_started(
            draft_id=draft.id,
            lease_token=draft.lease_token,
            now=attempted_at,
        ):
            return
        draft.provider_create_attempted_at = attempted_at
        try:
            resource = await gmail.create_draft_resource(**kwargs)
            await _persist_refreshed_token(draft.account_id, gmail)
        except Exception:
            await _persist_refreshed_token(draft.account_id, gmail)
            await _record_reconciling(claimed=draft, now=utcnow())
            return
    provider_draft_id, provider_message_id = _provider_identity(resource)
    provider_revision = _matched_provider_revision(draft, resource)
    if not provider_draft_id or not provider_message_id:
        await _record_reconciling(claimed=draft, now=utcnow())
        return
    # Gmail create/update responses may omit payload headers. The request was
    # accepted with both provider identities, so its revision is authoritative.
    if provider_revision is None:
        provider_revision = draft.revision
    await _record_synced(
        claimed=draft,
        provider_resource=resource,
        provider_revision=provider_revision,
        now=utcnow(),
    )


async def _process_discard(draft: DraftSession, *, gmail: GmailService) -> None:
    if not draft.provider_draft_id and draft.provider_create_attempted_at is not None:
        try:
            resource, provider_revision, multiple = await _lookup_provider_draft(draft, gmail=gmail)
            await _persist_refreshed_token(draft.account_id, gmail)
        except Exception:
            await _persist_refreshed_token(draft.account_id, gmail)
            await _record_discard_reconciling(
                claimed=draft,
                now=utcnow(),
            )
            return
        if multiple:
            await _record_discard_reconciling(
                claimed=draft,
                now=utcnow(),
                code="draft_identity_ambiguous",
                message="Multiple Gmail drafts match this writing session",
            )
            return
        if resource is None or provider_revision is None:
            await _record_discard_reconciling(
                claimed=draft,
                now=utcnow(),
            )
            return
        provider_draft_id, _message_id = _provider_identity(resource)
        draft.provider_draft_id = provider_draft_id
    if draft.provider_draft_id:
        try:
            await gmail.delete_draft_resource(draft.provider_draft_id, max_retries=1)
            await _persist_refreshed_token(draft.account_id, gmail)
        except HttpError as error:
            await _persist_refreshed_token(draft.account_id, gmail)
            if getattr(error.resp, "status", None) != 404:
                await _record_discard_reconciling(
                    claimed=draft,
                    now=utcnow(),
                )
                return
        except Exception:
            await _persist_refreshed_token(draft.account_id, gmail)
            await _record_discard_reconciling(
                claimed=draft,
                now=utcnow(),
            )
            return
    await _finish_discarded(claimed=draft, now=utcnow())


async def _process_claimed_draft(draft: DraftSession, *, gmail: GmailService) -> None:
    if draft.lease_operation == "discard":
        await _process_discard(draft, gmail=gmail)
    elif draft.lease_operation == "reconcile":
        await _process_reconciliation(draft, gmail=gmail)
    else:
        await _process_upsert(draft, gmail=gmail)


async def _due_account_ids(now: datetime, limit: int = 50) -> list[int]:
    due = or_(
        and_(DraftSession.state.in_(("pending", "reconciling")), DraftSession.next_attempt_at <= now),
        and_(DraftSession.state.in_(("discard_pending", "sending")), DraftSession.discard_at <= now),
        and_(DraftSession.state == "syncing", DraftSession.lease_expires_at <= now),
    )
    async with async_session() as db:
        result = await db.execute(
            select(DraftSession.account_id)
            .where(due)
            .distinct()
            .order_by(DraftSession.account_id)
            .limit(limit)
        )
        return list(result.scalars().all())


async def _drain_account_drafts(account_id: int, *, max_sessions: int) -> int:
    processed = 0
    async with account_advisory_lock(account_id) as acquired:
        if not acquired:
            return 0
        gmail: GmailService | None = None
        while processed < max_sessions:
            async with async_session() as db:
                claimed = await _claim_due_drafts(
                    db,
                    account_id=account_id,
                    now=utcnow(),
                    limit=max_sessions - processed,
                )
            if not claimed:
                break
            if gmail is None:
                disposition = DraftErrorDisposition(
                    False,
                    "account_unavailable",
                    "The draft account is no longer available",
                )
                try:
                    async with async_session() as db:
                        account = (
                            await db.execute(
                                select(GoogleAccount).where(
                                    GoogleAccount.id == account_id,
                                    GoogleAccount.is_active.is_(True),
                                )
                            )
                        ).scalar_one_or_none()
                        if account is not None:
                            client_id, client_secret = await get_google_credentials(db)
                            gmail = GmailService(
                                account,
                                client_id=client_id,
                                client_secret=client_secret,
                                transport_timeout=DRAFT_GMAIL_TRANSPORT_TIMEOUT_SECONDS,
                            )
                except Exception as error:
                    disposition = classify_draft_error(error)
                if gmail is None:
                    for draft in claimed:
                        if draft.lease_operation == "discard":
                            await _record_discard_reconciling(
                                claimed=draft,
                                now=utcnow(),
                                code=disposition.code,
                                message=disposition.message,
                            )
                        else:
                            await _record_retry_or_failure(
                                claimed=draft,
                                disposition=disposition,
                                now=utcnow(),
                            )
                        processed += 1
                    break
            for draft in claimed:
                await _process_claimed_draft(draft, gmail=gmail)
                processed += 1
    return processed


async def drain_due_draft_sessions() -> int:
    processed = 0
    for account_id in await _due_account_ids(utcnow()):
        remaining = DRAFT_DRAIN_MAX_SESSIONS - processed
        if remaining <= 0:
            break
        try:
            processed += await _drain_account_drafts(account_id, max_sessions=remaining)
        except Exception as error:
            logger.error(
                "Draft drain failed safely for account %s; exception_type=%s",
                account_id,
                type(error).__name__,
            )
    return processed


async def _publish_draft_event(user_id: int, client_draft_id: UUID) -> None:
    try:
        from backend.services.notifications import publish_event

        await asyncio.wait_for(
            publish_event(
                user_id,
                "draft_session_updated",
                {"client_draft_id": str(client_draft_id)},
            ),
            timeout=DRAFT_REDIS_IO_TIMEOUT_SECONDS,
        )
    except Exception:
        logger.warning("Could not publish draft update", exc_info=False)


async def try_enqueue_draft_drain() -> None:
    try:
        await asyncio.wait_for(_enqueue_draft_drain(), timeout=DRAFT_REDIS_IO_TIMEOUT_SECONDS)
    except Exception:
        logger.warning("Could not enqueue draft drain; cron will recover it", exc_info=False)


async def _enqueue_draft_drain() -> None:
    settings = get_settings()
    redis = await create_pool(RedisSettings.from_dsn(settings.redis_url))
    try:
        await redis.enqueue_job("drain_draft_sessions_task", _queue_name=DRAFT_QUEUE_NAME)
    finally:
        await redis.close()
