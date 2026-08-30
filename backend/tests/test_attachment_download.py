import base64
import asyncio
import stat
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy.dialects import postgresql

import backend.routers.emails as email_router
from backend.services.attachments import (
    MAX_ATTACHMENT_DOWNLOAD_BYTES,
    AttachmentDownloadError,
    attachment_content_disposition,
    load_attachment_bytes,
    safe_attachment_filename,
    safe_content_type,
)
from backend.services.gmail import _decode_attachment_data


class _RouteResult:
    def __init__(self, row):
        self.row = row

    def one_or_none(self):
        return self.row


class _RouteDb:
    def __init__(self, row):
        self.row = row
        self.statements = []

    async def execute(self, statement):
        self.statements.append(statement)
        return _RouteResult(self.row)


class _CacheDb:
    def __init__(self):
        self.commits = 0
        self.rollbacks = 0

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        self.rollbacks += 1


def _generated_records(**attachment_overrides):
    email = SimpleNamespace(
        id=41,
        account_id=7,
        gmail_message_id="generated-message-id",
    )
    attachment_values = {
        "id": 83,
        "email_id": email.id,
        "gmail_attachment_id": "generated-attachment-id",
        "filename": "generated-notes.txt",
        "content_type": "text/plain",
        "size_bytes": 28,
        "storage_path": None,
    }
    attachment_values.update(attachment_overrides)
    attachment = SimpleNamespace(**attachment_values)
    account = SimpleNamespace(id=email.account_id, user_id=501, email="owner@example.test")
    return email, attachment, account


def _canonical_cache_path(root, email, attachment, account):
    return (
        Path(root)
        / str(account.user_id)
        / str(email.account_id)
        / str(email.id)
        / f"{attachment.id}.blob"
    )


@pytest.mark.asyncio
async def test_download_attachment_enforces_one_owned_membership_join(monkeypatch):
    email, attachment, account = _generated_records(
        filename='../../R\u00e9sum\u00e9\r\n"; injected=.pdf',
        content_type="text/html\r\nX-Injected: true",
    )
    db = _RouteDb((email, attachment, account))
    calls = []

    async def fake_load_attachment_bytes(db_arg, email_arg, attachment_arg, account_arg):
        calls.append((db_arg, email_arg, attachment_arg, account_arg))
        return b"generated attachment content"

    monkeypatch.setattr(email_router, "load_attachment_bytes", fake_load_attachment_bytes)

    response = await email_router.download_attachment(
        email_id=email.id,
        attachment_id=attachment.id,
        db=db,
        user=SimpleNamespace(id=account.user_id),
    )

    assert response.body == b"generated attachment content"
    assert calls == [(db, email, attachment, account)]
    assert response.headers["content-type"] == "application/octet-stream"
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["cross-origin-resource-policy"] == "same-origin"
    disposition = response.headers["content-disposition"]
    assert disposition.startswith('attachment; filename="Resume_ injected_.pdf";')
    assert "filename*=UTF-8''R%C3%A9sum%C3%A9%22%3B%20injected%3D.pdf" in disposition
    assert "\r" not in disposition and "\n" not in disposition

    compiled = str(
        db.statements[0].compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )
    assert "JOIN attachments ON attachments.email_id = emails.id" in compiled
    assert "JOIN google_accounts ON google_accounts.id = emails.account_id" in compiled
    assert f"emails.id = {email.id}" in compiled
    assert f"attachments.id = {attachment.id}" in compiled
    assert f"google_accounts.user_id = {account.user_id}" in compiled


@pytest.mark.asyncio
@pytest.mark.parametrize("unavailable_kind", ["foreign", "wrong-message", "missing"])
async def test_download_attachment_hides_all_unavailable_ids(unavailable_kind):
    db = _RouteDb(None)
    unavailable_ids = {
        "foreign": (41, 83, 999),
        "wrong-message": (42, 83, 501),
        "missing": (41, 999, 501),
    }
    email_id, attachment_id, user_id = unavailable_ids[unavailable_kind]

    with pytest.raises(HTTPException) as exc_info:
        await email_router.download_attachment(
            email_id=email_id,
            attachment_id=attachment_id,
            db=db,
            user=SimpleNamespace(id=user_id),
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Attachment not found"
    compiled = str(
        db.statements[0].compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )
    assert f"emails.id = {email_id}" in compiled
    assert f"attachments.id = {attachment_id}" in compiled
    assert f"google_accounts.user_id = {user_id}" in compiled


@pytest.mark.asyncio
async def test_download_attachment_returns_generic_upstream_failure(monkeypatch):
    email, attachment, account = _generated_records()
    db = _RouteDb((email, attachment, account))

    async def unavailable(*_args):
        raise AttachmentDownloadError("private upstream detail")

    monkeypatch.setattr(email_router, "load_attachment_bytes", unavailable)

    with pytest.raises(HTTPException) as exc_info:
        await email_router.download_attachment(
            email_id=email.id,
            attachment_id=attachment.id,
            db=db,
            user=SimpleNamespace(id=account.user_id),
        )

    assert exc_info.value.status_code == 502
    assert exc_info.value.detail == "Attachment is temporarily unavailable"


@pytest.mark.asyncio
async def test_download_attachment_preserves_safe_public_error_semantics(monkeypatch):
    email, attachment, account = _generated_records()
    db = _RouteDb((email, attachment, account))

    async def too_large(*_args):
        raise AttachmentDownloadError(
            "private size detail",
            status_code=413,
            public_detail="Attachment is too large to download",
        )

    monkeypatch.setattr(email_router, "load_attachment_bytes", too_large)

    with pytest.raises(HTTPException) as exc_info:
        await email_router.download_attachment(
            email_id=email.id,
            attachment_id=attachment.id,
            db=db,
            user=SimpleNamespace(id=account.user_id),
        )

    assert exc_info.value.status_code == 413
    assert exc_info.value.detail == "Attachment is too large to download"


@pytest.mark.asyncio
async def test_load_attachment_reads_only_the_canonical_bounded_cache(tmp_path):
    cached_content = b"canonical generated fixture"
    email, attachment, account = _generated_records(
        storage_path=str(tmp_path / "legacy" / "filename-keyed.txt"),
        size_bytes=len(cached_content),
    )
    legacy_path = Path(attachment.storage_path)
    legacy_path.parent.mkdir()
    legacy_path.write_bytes(b"legacy content must not be trusted")
    canonical_path = _canonical_cache_path(tmp_path, email, attachment, account)
    canonical_path.parent.mkdir(parents=True)
    canonical_path.write_bytes(cached_content)

    async def credentials_should_not_run(_db):
        raise AssertionError("Canonical cache hit should not resolve Gmail credentials")

    db = _CacheDb()
    content = await load_attachment_bytes(
        db,
        email,
        attachment,
        account,
        storage_root=tmp_path,
        credential_resolver=credentials_should_not_run,
    )

    assert content == cached_content
    assert attachment.storage_path == str(canonical_path)
    assert db.commits == 1


@pytest.mark.asyncio
async def test_load_attachment_rejects_a_symlink_at_the_canonical_cache_path(tmp_path):
    email, attachment, account = _generated_records(size_bytes=7)
    canonical_path = _canonical_cache_path(tmp_path, email, attachment, account)
    canonical_path.parent.mkdir(parents=True)
    alternate_path = tmp_path / "alternate-attachment"
    alternate_path.write_bytes(b"private")
    canonical_path.symlink_to(alternate_path)

    async def credentials_should_not_run(_db):
        raise AssertionError("Unsafe cache topology must fail before Gmail access")

    with pytest.raises(AttachmentDownloadError, match="cache path is invalid"):
        await load_attachment_bytes(
            _CacheDb(),
            email,
            attachment,
            account,
            storage_root=tmp_path,
            credential_resolver=credentials_should_not_run,
        )


@pytest.mark.asyncio
async def test_load_attachment_uses_gmail_fallback_and_atomic_private_cache(tmp_path):
    gmail_content = b"generated Gmail bytes"
    email, attachment, account = _generated_records(
        filename="../../generated-notes.txt",
        storage_path=str(tmp_path.parent / f"{tmp_path.name}-outside-private-file"),
        size_bytes=len(gmail_content),
    )
    Path(attachment.storage_path).write_bytes(b"outside root")
    db = _CacheDb()
    gmail_calls = []

    async def fake_credentials(db_arg):
        assert db_arg is db
        return "generated-client", "generated-secret"

    class FakeGmail:
        async def get_attachment(self, message_id, attachment_id, *, max_bytes):
            assert max_bytes == MAX_ATTACHMENT_DOWNLOAD_BYTES
            gmail_calls.append((message_id, attachment_id))
            return gmail_content

    def fake_gmail_factory(account_arg, *, client_id, client_secret):
        assert account_arg is account
        assert (client_id, client_secret) == ("generated-client", "generated-secret")
        return FakeGmail()

    content = await load_attachment_bytes(
        db,
        email,
        attachment,
        account,
        storage_root=tmp_path,
        credential_resolver=fake_credentials,
        gmail_service_factory=fake_gmail_factory,
    )

    canonical_path = _canonical_cache_path(tmp_path, email, attachment, account)
    assert content == gmail_content
    assert gmail_calls == [(email.gmail_message_id, attachment.gmail_attachment_id)]
    assert canonical_path.read_bytes() == content
    assert Path(attachment.storage_path) == canonical_path
    assert stat.S_IMODE(canonical_path.stat().st_mode) == 0o600
    assert list(canonical_path.parent.glob(f".{attachment.id}.blob-*")) == []
    assert db.commits == 1
    assert db.rollbacks == 0


@pytest.mark.asyncio
async def test_load_attachment_replaces_a_cache_length_mismatch_from_gmail(tmp_path):
    gmail_content = b"verified generated content"
    email, attachment, account = _generated_records(size_bytes=len(gmail_content))
    canonical_path = _canonical_cache_path(tmp_path, email, attachment, account)
    canonical_path.parent.mkdir(parents=True)
    canonical_path.write_bytes(b"truncated")

    async def fake_credentials(_db):
        return "generated-client", "generated-secret"

    class FakeGmail:
        async def get_attachment(self, _message_id, _attachment_id, *, max_bytes):
            assert max_bytes == MAX_ATTACHMENT_DOWNLOAD_BYTES
            return gmail_content

    content = await load_attachment_bytes(
        _CacheDb(),
        email,
        attachment,
        account,
        storage_root=tmp_path,
        credential_resolver=fake_credentials,
        gmail_service_factory=lambda *_args, **_kwargs: FakeGmail(),
    )

    assert content == gmail_content
    assert canonical_path.read_bytes() == gmail_content


@pytest.mark.asyncio
@pytest.mark.parametrize("source", ["metadata", "cache", "gmail"])
async def test_load_attachment_enforces_size_limit_before_and_after_reads(tmp_path, source):
    email, attachment, account = _generated_records()
    db = _CacheDb()
    canonical_path = _canonical_cache_path(tmp_path, email, attachment, account)

    if source == "metadata":
        attachment.size_bytes = MAX_ATTACHMENT_DOWNLOAD_BYTES + 1
    elif source == "cache":
        canonical_path.parent.mkdir(parents=True)
        canonical_path.write_bytes(b"x" * (MAX_ATTACHMENT_DOWNLOAD_BYTES + 1))

    async def fake_credentials(_db):
        return "generated-client", "generated-secret"

    class FakeGmail:
        async def get_attachment(self, _message_id, _attachment_id, *, max_bytes):
            assert max_bytes == MAX_ATTACHMENT_DOWNLOAD_BYTES
            if source == "gmail":
                return b"x" * (MAX_ATTACHMENT_DOWNLOAD_BYTES + 1)
            raise RuntimeError("cache fallback deliberately unavailable")

    with pytest.raises(AttachmentDownloadError):
        await load_attachment_bytes(
            db,
            email,
            attachment,
            account,
            storage_root=tmp_path,
            credential_resolver=fake_credentials,
            gmail_service_factory=lambda *_args, **_kwargs: FakeGmail(),
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("content", [b"", b"metadata mismatch"])
async def test_load_attachment_rejects_empty_or_mismatched_gmail_content(tmp_path, content):
    email, attachment, account = _generated_records(size_bytes=1)

    async def fake_credentials(_db):
        return "generated-client", "generated-secret"

    class FakeGmail:
        async def get_attachment(self, _message_id, _attachment_id, *, max_bytes):
            assert max_bytes == MAX_ATTACHMENT_DOWNLOAD_BYTES
            return content

    with pytest.raises(AttachmentDownloadError):
        await load_attachment_bytes(
            _CacheDb(),
            email,
            attachment,
            account,
            storage_root=tmp_path,
            credential_resolver=fake_credentials,
            gmail_service_factory=lambda *_args, **_kwargs: FakeGmail(),
        )


@pytest.mark.asyncio
async def test_load_attachment_bounds_interactive_gmail_wait(tmp_path, monkeypatch):
    email, attachment, account = _generated_records(size_bytes=4)

    async def fake_credentials(_db):
        return "generated-client", "generated-secret"

    class SlowGmail:
        async def get_attachment(self, *_args, **_kwargs):
            await asyncio.sleep(1)
            return b"late"

    monkeypatch.setattr(
        "backend.services.attachments.ATTACHMENT_DOWNLOAD_TIMEOUT_SECONDS",
        0.001,
    )

    with pytest.raises(AttachmentDownloadError) as exc_info:
        await load_attachment_bytes(
            _CacheDb(),
            email,
            attachment,
            account,
            storage_root=tmp_path,
            credential_resolver=fake_credentials,
            gmail_service_factory=lambda *_args, **_kwargs: SlowGmail(),
        )

    assert exc_info.value.status_code == 503
    assert exc_info.value.public_detail == "Attachment download is temporarily unavailable"


def test_attachment_headers_remove_paths_controls_and_invalid_mime_data():
    assert safe_attachment_filename("../../generated\r\nreport.pdf") == "generatedreport.pdf"
    assert safe_attachment_filename("safe\u202etxt.exe") == "safetxt.exe"
    assert safe_content_type("application/pdf; charset=binary") == "application/pdf"
    assert safe_content_type("text/plain\r\nX-Private: yes") == "application/octet-stream"
    disposition = attachment_content_disposition("../../R\u00e9sum\u00e9 2026.pdf")
    assert disposition == (
        'attachment; filename="Resume 2026.pdf"; '
        "filename*=UTF-8''R%C3%A9sum%C3%A9%202026.pdf"
    )


def test_gmail_attachment_decoder_rejects_oversize_before_and_after_decode():
    allowed = base64.urlsafe_b64encode(b"four").decode()
    assert _decode_attachment_data(allowed, max_bytes=4) == b"four"

    with pytest.raises(ValueError, match="size limit"):
        _decode_attachment_data(allowed, max_bytes=2)

    assert _decode_attachment_data(allowed.rstrip("="), max_bytes=4) == b"four"
    with pytest.raises(ValueError, match="invalid"):
        _decode_attachment_data("not*base64", max_bytes=32)
