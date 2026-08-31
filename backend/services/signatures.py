"""Owner-scoped signature settings, immutable snapshots, and pure rendering."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Literal

import nh3
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.account import GoogleAccount
from backend.models.signature import AccountSignature
from backend.schemas.signature import AccountSignatureReplace


SIGNATURE_SANITIZER_VERSION = 1
MAX_RENDERED_MESSAGE_BYTES = 10 * 1024 * 1024
SIGNATURE_HTML_TAGS = {
    "a",
    "b",
    "blockquote",
    "br",
    "div",
    "em",
    "i",
    "li",
    "ol",
    "p",
    "span",
    "strong",
    "u",
    "ul",
}
SIGNATURE_HTML_ATTRIBUTES = {
    "a": {"href", "title"},
}
SIGNATURE_URL_SCHEMES = {"https", "mailto", "tel"}


class SignatureError(Exception):
    """Base class for stable signature failures."""


class SignatureNotFound(SignatureError):
    pass


class SignatureConflict(SignatureError):
    pass


class SignatureValidationError(SignatureError):
    pass


class SignatureRenderedMessageTooLarge(SignatureValidationError):
    pass


@dataclass(frozen=True, slots=True)
class AccountSignatureView:
    account_id: int
    account_email: str
    enabled: bool
    include_on_new: bool
    include_on_replies: bool
    include_on_forwards: bool
    body_html: str
    body_text: str
    revision: int
    sanitizer_version: int


def sanitize_signature_html(value: str) -> str:
    """Return a stable, no-network rich fragment safe for later rendering."""
    return nh3.clean(
        value,
        tags=SIGNATURE_HTML_TAGS,
        attributes=SIGNATURE_HTML_ATTRIBUTES,
        url_schemes=SIGNATURE_URL_SCHEMES,
        strip_comments=True,
        link_rel="noopener noreferrer",
    ).strip()


def _canonical_request(request: AccountSignatureReplace) -> dict:
    body_html = sanitize_signature_html(request.body_html)
    body_text = request.body_text.strip()
    if request.enabled and (not body_html or not body_text):
        raise SignatureValidationError(
            "An enabled signature requires both rich and plain-text content"
        )
    return {
        "enabled": request.enabled,
        "include_on_new": request.include_on_new,
        "include_on_replies": request.include_on_replies,
        "include_on_forwards": request.include_on_forwards,
        "body_html": body_html,
        "body_text": body_text,
        "sanitizer_version": SIGNATURE_SANITIZER_VERSION,
    }


def _view(account: GoogleAccount, signature: AccountSignature | None) -> AccountSignatureView:
    if signature is None:
        return AccountSignatureView(
            account_id=account.id,
            account_email=account.email,
            enabled=False,
            include_on_new=True,
            include_on_replies=True,
            include_on_forwards=True,
            body_html="",
            body_text="",
            revision=0,
            sanitizer_version=SIGNATURE_SANITIZER_VERSION,
        )
    return AccountSignatureView(
        account_id=account.id,
        account_email=account.email,
        enabled=signature.enabled,
        include_on_new=signature.include_on_new,
        include_on_replies=signature.include_on_replies,
        include_on_forwards=signature.include_on_forwards,
        body_html=signature.body_html,
        body_text=signature.body_text,
        revision=signature.revision,
        sanitizer_version=signature.sanitizer_version,
    )


def signature_matches(signature: AccountSignature, values: dict) -> bool:
    return all(getattr(signature, key) == value for key, value in values.items())


async def list_account_signatures(
    db: AsyncSession,
    *,
    user_id: int,
) -> list[AccountSignatureView]:
    result = await db.execute(
        select(GoogleAccount, AccountSignature)
        .outerjoin(AccountSignature, AccountSignature.account_id == GoogleAccount.id)
        .where(
            GoogleAccount.user_id == user_id,
            GoogleAccount.is_active.is_(True),
            GoogleAccount.encrypted_refresh_token.is_not(None),
            GoogleAccount.encrypted_refresh_token != "",
        )
        .order_by(func.lower(GoogleAccount.email), GoogleAccount.id)
    )
    return [_view(account, signature) for account, signature in result.all()]


async def replace_account_signature(
    db: AsyncSession,
    *,
    user_id: int,
    account_id: int,
    request: AccountSignatureReplace,
) -> AccountSignatureView:
    values = _canonical_request(request)
    account = (
        await db.execute(
            select(GoogleAccount)
            .where(
                GoogleAccount.id == account_id,
                GoogleAccount.user_id == user_id,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if account is None:
        raise SignatureNotFound("Signature account not found")

    signature = (
        await db.execute(
            select(AccountSignature).where(AccountSignature.account_id == account.id)
        )
    ).scalar_one_or_none()
    if signature is not None:
        if signature.revision == request.expected_revision + 1 and signature_matches(
            signature, values
        ):
            await db.commit()
            return _view(account, signature)
        if signature.revision != request.expected_revision:
            raise SignatureConflict(
                "This signature changed on another device; refresh it"
            )
        for key, value in values.items():
            setattr(signature, key, value)
        signature.revision += 1
    else:
        if request.expected_revision != 0:
            raise SignatureConflict(
                "This signature changed on another device; refresh it"
            )
        signature = AccountSignature(
            account_id=account.id,
            revision=1,
            **values,
        )
        db.add(signature)

    await db.commit()
    await db.refresh(signature)
    return _view(account, signature)


def _policy_applies(
    signature: AccountSignature | None,
    *,
    composition_kind: Literal["new", "reply", "forward"],
    signature_mode: Literal["default", "enabled", "disabled"],
) -> bool:
    if signature_mode == "disabled":
        return False
    if signature is None or not signature.body_html or not signature.body_text:
        if signature_mode == "enabled":
            raise SignatureValidationError(
                "The selected account does not have a usable signature"
            )
        return False
    if signature_mode == "enabled":
        return True
    if not signature.enabled:
        return False
    return {
        "new": signature.include_on_new,
        "reply": signature.include_on_replies,
        "forward": signature.include_on_forwards,
    }[composition_kind]


def signature_snapshot_hash(snapshot: dict) -> str:
    serialized = json.dumps(snapshot, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _snapshot(
    *,
    account_id: int,
    signature: AccountSignature | None,
    applied: bool,
) -> dict:
    # Keep the accepted content even when this composition suppresses it. That
    # lets a client restore the frozen choice without consulting newer settings.
    body_html = signature.body_html if signature is not None else ""
    body_text = signature.body_text if signature is not None else ""
    snapshot = {
        "applied": applied,
        "account_id": account_id,
        "policy_revision": signature.revision if signature is not None else 0,
        "body_html": body_html,
        "body_text": body_text,
        "sanitizer_version": (
            signature.sanitizer_version
            if signature is not None
            else SIGNATURE_SANITIZER_VERSION
        ),
    }
    snapshot["content_hash"] = signature_snapshot_hash(snapshot)
    return snapshot


async def resolve_signature_snapshot(
    db: AsyncSession,
    *,
    account_id: int,
    composition_kind: Literal["new", "reply", "forward"],
    signature_mode: Literal["default", "enabled", "disabled"],
) -> dict:
    signature = (
        await db.execute(
            select(AccountSignature).where(AccountSignature.account_id == account_id)
        )
    ).scalar_one_or_none()
    applied = _policy_applies(
        signature,
        composition_kind=composition_kind,
        signature_mode=signature_mode,
    )
    return _snapshot(account_id=account_id, signature=signature, applied=applied)


def valid_signature_snapshot(snapshot: object, *, account_id: int) -> dict | None:
    if not isinstance(snapshot, dict):
        return None
    required = {
        "applied",
        "account_id",
        "policy_revision",
        "body_html",
        "body_text",
        "content_hash",
        "sanitizer_version",
    }
    if (
        set(snapshot) != required
        or type(snapshot.get("account_id")) is not int
        or snapshot.get("account_id") != account_id
    ):
        return None
    supplied_hash = snapshot.get("content_hash")
    unhashed = {key: value for key, value in snapshot.items() if key != "content_hash"}
    if not isinstance(supplied_hash, str) or signature_snapshot_hash(unhashed) != supplied_hash:
        return None
    if type(snapshot.get("applied")) is not bool:
        return None
    if type(snapshot.get("policy_revision")) is not int or snapshot["policy_revision"] < 0:
        return None
    if type(snapshot.get("sanitizer_version")) is not int or snapshot["sanitizer_version"] < 1:
        return None
    if not isinstance(snapshot.get("body_html"), str) or not isinstance(snapshot.get("body_text"), str):
        return None
    if bool(snapshot["body_html"]) != bool(snapshot["body_text"]):
        return None
    if snapshot["applied"] and (not snapshot["body_html"] or not snapshot["body_text"]):
        return None
    return dict(snapshot)


def with_signature_snapshot_applied(
    snapshot: object,
    *,
    account_id: int,
    applied: bool,
) -> dict:
    """Toggle only application state while preserving frozen signature content."""
    if type(applied) is not bool:
        raise SignatureValidationError("Signature snapshot application state is invalid")
    validated = valid_signature_snapshot(snapshot, account_id=account_id)
    if validated is None:
        raise SignatureValidationError("Signature snapshot is invalid")
    if applied and (not validated["body_html"] or not validated["body_text"]):
        raise SignatureValidationError("The draft does not contain a usable frozen signature")
    if validated["applied"] == applied:
        return validated
    updated = {**validated, "applied": applied}
    unhashed = {key: value for key, value in updated.items() if key != "content_hash"}
    updated["content_hash"] = signature_snapshot_hash(unhashed)
    return updated


def render_signature_bodies(
    *,
    account_id: int,
    body_html: str,
    body_text: str,
    quoted_html: str,
    quoted_text: str,
    signature_snapshot: object,
) -> tuple[str, str]:
    """Build provider alternatives without mutating any persisted authored field."""
    snapshot = valid_signature_snapshot(
        signature_snapshot,
        account_id=account_id,
    )
    if signature_snapshot is not None and snapshot is None:
        raise SignatureValidationError("Signature snapshot is invalid")
    signature_html = snapshot["body_html"] if snapshot and snapshot["applied"] else ""
    signature_text = snapshot["body_text"] if snapshot and snapshot["applied"] else ""
    html = "<br><br>".join(part for part in (body_html, signature_html, quoted_html) if part)
    text = "\n\n".join(part for part in (body_text, signature_text, quoted_text) if part)
    if len(html.encode("utf-8")) + len(text.encode("utf-8")) > MAX_RENDERED_MESSAGE_BYTES:
        raise SignatureRenderedMessageTooLarge(
            "Rendered message content exceeds the 10 MiB provider limit"
        )
    return html, text
