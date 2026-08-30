import base64
import asyncio
import io
import stat
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from PIL import Image
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
from backend.services.attachment_cache import (
    AttachmentCachePolicy,
    acquire_entry_lease,
    reserve_cache_capacity,
)
from backend.services.attachment_previews import (
    MAX_ATTACHMENT_PREVIEW_BYTES,
    MAX_TEXT_PREVIEW_BYTES,
    AttachmentPreviewError,
    build_attachment_preview,
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
    def __init__(self, live_rows=None):
        self.commits = 0
        self.rollbacks = 0
        self.executes = 0
        self.live_rows = live_rows or [(7, 41, 83)]

    async def execute(self, _statement):
        self.executes += 1
        rows = self.live_rows

        class _Result:
            def all(self):
                return rows

        return _Result()

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


def _generated_png_bytes(size=(32, 20), color=(20, 120, 220, 180)):
    output = io.BytesIO()
    Image.new("RGBA", size, color).save(output, format="PNG")
    return output.getvalue()


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
async def test_preview_attachment_rejects_known_oversized_metadata_before_loading(monkeypatch):
    email, attachment, account = _generated_records(
        size_bytes=MAX_ATTACHMENT_PREVIEW_BYTES + 1,
    )

    async def load_should_not_run(*_args):
        raise AssertionError("Known oversized preview must fail before loading bytes")

    monkeypatch.setattr(email_router, "load_attachment_bytes", load_should_not_run)
    with pytest.raises(HTTPException) as exc_info:
        await email_router.preview_attachment(
            email_id=email.id,
            attachment_id=attachment.id,
            db=_RouteDb((email, attachment, account)),
            user=SimpleNamespace(id=account.user_id),
        )

    assert exc_info.value.status_code == 413
    assert exc_info.value.detail == "This attachment is too large to preview"


@pytest.mark.asyncio
async def test_preview_attachment_acquires_pipeline_admission_before_loading(monkeypatch):
    from backend.services import attachment_previews as preview_service

    email, attachment, account = _generated_records()
    render_slots = asyncio.BoundedSemaphore(1)
    await render_slots.acquire()
    load_called = False

    async def load_should_wait_for_admission(*_args):
        nonlocal load_called
        load_called = True
        return b"generated text"

    monkeypatch.setattr(email_router, "load_attachment_bytes", load_should_wait_for_admission)
    monkeypatch.setattr(preview_service, "_preview_pipeline_slots", render_slots)
    monkeypatch.setattr(preview_service, "PREVIEW_PIPELINE_QUEUE_TIMEOUT_SECONDS", 0.01)
    try:
        with pytest.raises(HTTPException) as exc_info:
            await email_router.preview_attachment(
                email_id=email.id,
                attachment_id=attachment.id,
                db=_RouteDb((email, attachment, account)),
                user=SimpleNamespace(id=account.user_id),
            )
    finally:
        render_slots.release()

    assert load_called is False
    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == "Preview service is busy; try again shortly"


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
async def test_preview_attachment_reuses_owned_join_and_emits_typed_headers(monkeypatch):
    email, attachment, account = _generated_records(
        filename='../../R\u00e9sum\u00e9\r\n".txt',
        content_type="text/html",
    )
    db = _RouteDb((email, attachment, account))

    async def fake_load_attachment_bytes(*_args):
        return b"Generated preview text\n"

    monkeypatch.setattr(email_router, "load_attachment_bytes", fake_load_attachment_bytes)
    response = await email_router.preview_attachment(
        email_id=email.id,
        attachment_id=attachment.id,
        db=db,
        user=SimpleNamespace(id=account.user_id),
    )

    assert response.body == b"Generated preview text\n"
    assert response.headers["content-type"] == "text/plain; charset=utf-8"
    assert response.headers["x-attachment-preview-kind"] == "text"
    assert response.headers["x-attachment-preview-truncated"] == "false"
    assert response.headers["content-disposition"].startswith(
        'inline; filename="Resume_.txt";'
    )
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["cross-origin-resource-policy"] == "same-origin"
    assert response.headers["x-frame-options"] == "SAMEORIGIN"
    assert "sandbox" in response.headers["content-security-policy"]
    assert "script-src 'none'" in response.headers["content-security-policy"]

    compiled = str(
        db.statements[0].compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )
    assert "JOIN attachments ON attachments.email_id = emails.id" in compiled
    assert f"emails.id = {email.id}" in compiled
    assert f"attachments.id = {attachment.id}" in compiled
    assert f"google_accounts.user_id = {account.user_id}" in compiled


@pytest.mark.asyncio
@pytest.mark.parametrize("unavailable_kind", ["foreign", "wrong-message", "missing"])
async def test_preview_attachment_hides_all_unavailable_ids(unavailable_kind):
    db = _RouteDb(None)
    unavailable_ids = {
        "foreign": (41, 83, 999),
        "wrong-message": (42, 83, 501),
        "missing": (41, 999, 501),
    }
    email_id, attachment_id, user_id = unavailable_ids[unavailable_kind]

    with pytest.raises(HTTPException) as exc_info:
        await email_router.preview_attachment(
            email_id=email_id,
            attachment_id=attachment_id,
            db=db,
            user=SimpleNamespace(id=user_id),
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Attachment not found"


@pytest.mark.asyncio
async def test_preview_attachment_preserves_preview_error_status(monkeypatch):
    email, attachment, account = _generated_records()
    db = _RouteDb((email, attachment, account))

    async def fake_load_attachment_bytes(*_args):
        return b"\x00\xff generated binary"

    monkeypatch.setattr(email_router, "load_attachment_bytes", fake_load_attachment_bytes)
    with pytest.raises(HTTPException) as exc_info:
        await email_router.preview_attachment(
            email_id=email.id,
            attachment_id=attachment.id,
            db=db,
            user=SimpleNamespace(id=account.user_id),
        )

    assert exc_info.value.status_code == 415
    assert exc_info.value.detail == "Preview is not available for this attachment"


@pytest.mark.asyncio
async def test_byte_verified_preview_normalizes_supported_raster_images():
    preview = await build_attachment_preview(_generated_png_bytes())

    assert preview.kind == "image"
    assert preview.content_type == "image/png"
    assert preview.content.startswith(b"\x89PNG\r\n\x1a\n")
    with Image.open(io.BytesIO(preview.content)) as normalized:
        assert normalized.size == (32, 20)
        assert normalized.mode == "RGBA"


@pytest.mark.asyncio
async def test_byte_verified_preview_enforces_image_pixel_bounds(monkeypatch):
    from backend.services import attachment_previews as preview_service

    monkeypatch.setattr(preview_service, "MAX_IMAGE_PREVIEW_PIXELS", 100)
    with pytest.raises(AttachmentPreviewError) as exc_info:
        await build_attachment_preview(_generated_png_bytes(size=(20, 20)))

    assert exc_info.value.status_code == 413
    assert exc_info.value.public_detail == "This image is too large to preview"


@pytest.mark.asyncio
async def test_byte_verified_preview_maps_pillow_bomb_warning_to_413(monkeypatch):
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 100)
    with pytest.raises(AttachmentPreviewError) as exc_info:
        await build_attachment_preview(_generated_png_bytes(size=(11, 10)))

    assert exc_info.value.status_code == 413
    assert exc_info.value.public_detail == "This image is too large to preview"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "content",
    [
        b"\x89PNG\r\n\x1a\ncorrupt",
        b"\xff\xd8\xffcorrupt",
        b"RIFF\x08\x00\x00\x00WEBPcorrupt",
    ],
)
async def test_byte_verified_preview_rejects_corrupt_image_signatures(content):
    with pytest.raises(AttachmentPreviewError, match="Image data is invalid"):
        await build_attachment_preview(content)


@pytest.mark.asyncio
async def test_byte_verified_preview_returns_bounded_utf8_text_contract():
    content = ("Generated Unicode r\u00e9sum\u00e9\n".encode() * 60_000)
    preview = await build_attachment_preview(content)

    assert preview.kind == "text"
    assert preview.content_type == "text/plain; charset=utf-8"
    assert preview.truncated is True
    assert len(preview.content) <= MAX_TEXT_PREVIEW_BYTES


@pytest.mark.asyncio
async def test_byte_verified_preview_trims_an_incomplete_utf8_boundary():
    content = (b"a" * (MAX_TEXT_PREVIEW_BYTES - 1)) + "\u00e9".encode() + b"tail"
    preview = await build_attachment_preview(content)

    assert preview.kind == "text"
    assert preview.truncated is True
    assert preview.content == b"a" * (MAX_TEXT_PREVIEW_BYTES - 1)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "content",
    [
        b"<script>window.generatedPreviewExecuted = true</script>",
        b'<svg xmlns="http://www.w3.org/2000/svg"><script>fail()</script></svg>',
    ],
)
async def test_active_markup_is_returned_only_as_literal_plain_text(content):
    preview = await build_attachment_preview(content)

    assert preview.kind == "text"
    assert preview.content_type == "text/plain; charset=utf-8"
    assert preview.content == content


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "content",
    [
        b"plain\x00binary",
        "direction\u202eoverride".encode(),
        b"\xff\xfebinary",
    ],
)
async def test_byte_verified_preview_rejects_binary_and_control_text(content):
    with pytest.raises(AttachmentPreviewError):
        await build_attachment_preview(content)


@pytest.mark.asyncio
async def test_byte_verified_preview_accepts_passive_pdf_and_rejects_obvious_active_markers():
    passive = b"%PDF-1.7\n1 0 obj\n<< /Type /Catalog >>\nendobj\n%%EOF\n"
    preview = await build_attachment_preview(passive)
    assert preview.kind == "pdf"
    assert preview.content_type == "application/pdf"
    assert preview.content == passive

    active = b"%PDF-1.7\n1 0 obj\n<< /OpenAction 2 0 R >>\nendobj\n%%EOF"
    with pytest.raises(AttachmentPreviewError, match="active"):
        await build_attachment_preview(active)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "content",
    [
        b"%PDF-1.7\nmissing eof",
        b"%PDF-9.9\n%%EOF",
        b"%PDF-1.7\n%%EOF\ntrailing-payload",
    ],
)
async def test_byte_verified_preview_rejects_malformed_pdf(content):
    with pytest.raises(AttachmentPreviewError):
        await build_attachment_preview(content)


@pytest.mark.asyncio
async def test_byte_verified_preview_enforces_source_byte_limit():
    with pytest.raises(AttachmentPreviewError) as exc_info:
        await build_attachment_preview(b"x" * (MAX_ATTACHMENT_PREVIEW_BYTES + 1))

    assert exc_info.value.status_code == 413
    assert exc_info.value.public_detail == "This attachment is too large to preview"


@pytest.mark.asyncio
async def test_byte_verified_preview_bounds_render_queue_wait(monkeypatch):
    from backend.services import attachment_previews as preview_service

    render_slots = asyncio.BoundedSemaphore(1)
    await render_slots.acquire()
    monkeypatch.setattr(preview_service, "_preview_pipeline_slots", render_slots)
    monkeypatch.setattr(preview_service, "PREVIEW_PIPELINE_QUEUE_TIMEOUT_SECONDS", 0.01)
    try:
        with pytest.raises(AttachmentPreviewError) as exc_info:
            await preview_service.build_attachment_preview(b"generated text")
    finally:
        render_slots.release()

    assert exc_info.value.status_code == 503
    assert exc_info.value.public_detail == "Preview service is busy; try again shortly"


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
    assert attachment.storage_path == str(legacy_path)
    assert db.commits == 0
    assert db.rollbacks == 0


@pytest.mark.asyncio
async def test_cache_hit_survives_access_time_update_failure(tmp_path, monkeypatch):
    cached_content = b"generated readable cache hit"
    email, attachment, account = _generated_records(size_bytes=len(cached_content))
    canonical_path = _canonical_cache_path(tmp_path, email, attachment, account)
    canonical_path.parent.mkdir(parents=True)
    canonical_path.write_bytes(cached_content)

    async def credentials_should_not_run(_db):
        raise AssertionError("A verified cache hit must not require Gmail")

    def fail_touch(*_args, **_kwargs):
        raise PermissionError("generated read-only metadata")

    monkeypatch.setattr("backend.services.attachments.os.utime", fail_touch)
    content = await load_attachment_bytes(
        _CacheDb(),
        email,
        attachment,
        account,
        storage_root=tmp_path,
        credential_resolver=credentials_should_not_run,
    )

    assert content == cached_content
    assert canonical_path.read_bytes() == cached_content


@pytest.mark.asyncio
async def test_interactive_parent_swap_cannot_read_delete_or_replace_outside_cache(
    tmp_path,
    monkeypatch,
):
    gmail_content = b"generated safe fallback"
    email, attachment, account = _generated_records(size_bytes=len(gmail_content))
    canonical_path = _canonical_cache_path(tmp_path, email, attachment, account)
    canonical_path.parent.mkdir(parents=True)
    canonical_path.write_bytes(b"generated invalid cache")
    outside_account = tmp_path / "outside-account"
    outside_blob = outside_account / str(email.id) / canonical_path.name
    outside_blob.parent.mkdir(parents=True)
    outside_blob.write_bytes(b"outside sentinel")
    from backend.services import attachments as attachment_service

    original_read = attachment_service._read_bounded_file
    swapped = False

    def swap_then_fail(*args, **kwargs):
        nonlocal swapped
        if not swapped:
            swapped = True
            account_path = tmp_path / str(account.user_id) / str(email.account_id)
            account_path.rename(account_path.with_name(f"{account_path.name}-original"))
            account_path.symlink_to(outside_account, target_is_directory=True)
        raise AttachmentDownloadError("generated invalid cached bytes")

    monkeypatch.setattr(attachment_service, "_read_bounded_file", swap_then_fail)

    async def fake_credentials(_db):
        return "generated-client", "generated-secret"

    class FakeGmail:
        async def get_attachment(self, *_args, **_kwargs):
            return gmail_content

    try:
        content = await load_attachment_bytes(
            _CacheDb(),
            email,
            attachment,
            account,
            storage_root=tmp_path,
            credential_resolver=fake_credentials,
            gmail_service_factory=lambda *_args, **_kwargs: FakeGmail(),
        )
    finally:
        monkeypatch.setattr(attachment_service, "_read_bounded_file", original_read)

    assert content == gmail_content
    assert outside_blob.read_bytes() == b"outside sentinel"


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

    def fake_gmail_factory(
        account_arg,
        *,
        client_id,
        client_secret,
        transport_timeout,
    ):
        assert account_arg is account
        assert (client_id, client_secret) == ("generated-client", "generated-secret")
        assert transport_timeout == 30
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
    assert Path(attachment.storage_path) != canonical_path
    assert Path(attachment.storage_path).read_bytes() == b"outside root"
    assert stat.S_IMODE(canonical_path.stat().st_mode) == 0o600
    assert list(canonical_path.parent.glob(f".{attachment.id}.blob-*")) == []
    assert db.commits == 0
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


@pytest.mark.asyncio
async def test_load_attachment_collapses_concurrent_cache_misses(tmp_path):
    gmail_content = b"one generated upstream fetch"
    email, attachment, account = _generated_records(size_bytes=len(gmail_content))
    gmail_calls = 0

    async def fake_credentials(_db):
        return "generated-client", "generated-secret"

    class FakeGmail:
        async def get_attachment(self, _message_id, _attachment_id, *, max_bytes):
            nonlocal gmail_calls
            assert max_bytes == MAX_ATTACHMENT_DOWNLOAD_BYTES
            gmail_calls += 1
            await asyncio.sleep(0.05)
            return gmail_content

    def fake_gmail_factory(*_args, **_kwargs):
        return FakeGmail()

    first_db = _CacheDb()
    second_db = _CacheDb()
    first, second = await asyncio.gather(
        load_attachment_bytes(
            first_db,
            email,
            attachment,
            account,
            storage_root=tmp_path,
            credential_resolver=fake_credentials,
            gmail_service_factory=fake_gmail_factory,
        ),
        load_attachment_bytes(
            second_db,
            email,
            attachment,
            account,
            storage_root=tmp_path,
            credential_resolver=fake_credentials,
            gmail_service_factory=fake_gmail_factory,
        ),
    )

    assert first == second == gmail_content
    assert gmail_calls == 1
    assert _canonical_cache_path(tmp_path, email, attachment, account).read_bytes() == gmail_content
    assert first_db.commits == second_db.commits == 0
    assert first_db.rollbacks == second_db.rollbacks == 0


@pytest.mark.asyncio
async def test_parallel_attachment_writes_never_exceed_per_user_quota(tmp_path):
    content = b"123456"
    email, first_attachment, account = _generated_records(size_bytes=len(content))
    _, second_attachment, _ = _generated_records(id=84, size_bytes=len(content))
    started = 0
    both_started = asyncio.Event()

    async def fake_credentials(_db):
        return "generated-client", "generated-secret"

    class FakeGmail:
        async def get_attachment(self, _message_id, _attachment_id, *, max_bytes):
            nonlocal started
            assert max_bytes == MAX_ATTACHMENT_DOWNLOAD_BYTES
            started += 1
            if started == 2:
                both_started.set()
            await asyncio.wait_for(both_started.wait(), timeout=1)
            return content

    policy = AttachmentCachePolicy(
        hard_limit_bytes=10,
        target_bytes=6,
        idle_retention_seconds=10_000,
        orphan_grace_seconds=1_000,
        temp_grace_seconds=100,
    )
    live_rows = [(7, 41, 83), (7, 41, 84)]
    results = await asyncio.gather(
        load_attachment_bytes(
            _CacheDb(live_rows),
            email,
            first_attachment,
            account,
            storage_root=tmp_path,
            credential_resolver=fake_credentials,
            gmail_service_factory=lambda *_args, **_kwargs: FakeGmail(),
            cache_policy=policy,
        ),
        load_attachment_bytes(
            _CacheDb(live_rows),
            email,
            second_attachment,
            account,
            storage_root=tmp_path,
            credential_resolver=fake_credentials,
            gmail_service_factory=lambda *_args, **_kwargs: FakeGmail(),
            cache_policy=policy,
        ),
    )

    assert results == [content, content]
    cached_files = list((tmp_path / "501").glob("*/*/*.blob"))
    assert sum(path.stat().st_size for path in cached_files) <= policy.hard_limit_bytes
    assert len(cached_files) == 1


@pytest.mark.asyncio
async def test_cache_lifecycle_failure_never_discards_downloaded_bytes(tmp_path, monkeypatch):
    content = b"generated cache failure bytes"
    email, attachment, account = _generated_records(size_bytes=len(content))
    db = _CacheDb()

    async def fake_credentials(_db):
        return "generated-client", "generated-secret"

    class FakeGmail:
        async def get_attachment(self, *_args, **_kwargs):
            return content

    def fail_cache_reservation(*_args, **_kwargs):
        raise PermissionError("generated cache reservation failure")

    monkeypatch.setattr(
        "backend.services.attachments.reserve_cache_capacity",
        fail_cache_reservation,
    )

    result = await load_attachment_bytes(
        db,
        email,
        attachment,
        account,
        storage_root=tmp_path,
        credential_resolver=fake_credentials,
        gmail_service_factory=lambda *_args, **_kwargs: FakeGmail(),
    )

    assert result == content
    assert not _canonical_cache_path(tmp_path, email, attachment, account).exists()
    assert db.commits == 0
    assert db.rollbacks == 0


@pytest.mark.asyncio
async def test_cancellation_releases_an_entry_lease_acquired_in_a_worker_thread(
    tmp_path,
    monkeypatch,
):
    email, attachment, account = _generated_records()
    started = threading.Event()
    original_acquire = acquire_entry_lease

    def delayed_acquire(*args, **kwargs):
        started.set()
        time.sleep(0.05)
        return original_acquire(*args, **kwargs)

    monkeypatch.setattr("backend.services.attachments.acquire_entry_lease", delayed_acquire)
    task = asyncio.create_task(load_attachment_bytes(
        _CacheDb(),
        email,
        attachment,
        account,
        storage_root=tmp_path,
    ))
    assert await asyncio.to_thread(started.wait, 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    probe = original_acquire(
        tmp_path.resolve(),
        account.user_id,
        email.account_id,
        email.id,
        attachment.id,
        blocking=False,
    )
    assert probe is not None
    probe.release()


@pytest.mark.asyncio
async def test_cancellation_releases_a_completed_quota_reservation(tmp_path, monkeypatch):
    content = b"generated quota cancellation"
    email, attachment, account = _generated_records(size_bytes=len(content))
    started = threading.Event()
    original_reserve = reserve_cache_capacity

    async def fake_credentials(_db):
        return "generated-client", "generated-secret"

    class FakeGmail:
        async def get_attachment(self, *_args, **_kwargs):
            return content

    def delayed_reserve(*args, **kwargs):
        started.set()
        time.sleep(0.05)
        return original_reserve(*args, **kwargs)

    monkeypatch.setattr("backend.services.attachments.reserve_cache_capacity", delayed_reserve)
    task = asyncio.create_task(load_attachment_bytes(
        _CacheDb(),
        email,
        attachment,
        account,
        storage_root=tmp_path,
        credential_resolver=fake_credentials,
        gmail_service_factory=lambda *_args, **_kwargs: FakeGmail(),
    ))
    assert await asyncio.to_thread(started.wait, 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    probe = original_reserve(
        tmp_path.resolve(),
        account.user_id,
        reservation_bytes=0,
        live_keys={(email.account_id, email.id, attachment.id)},
        protected_key=None,
        timeout_seconds=0.1,
    )
    assert probe.can_store
    probe.release()


@pytest.mark.asyncio
async def test_cancellation_waits_for_atomic_cache_write_before_unlocking(tmp_path, monkeypatch):
    content = b"generated cancellation-safe write"
    email, attachment, account = _generated_records(size_bytes=len(content))
    started = threading.Event()
    from backend.services import attachments as attachment_service

    original_write = attachment_service._write_private_file_atomic

    async def fake_credentials(_db):
        return "generated-client", "generated-secret"

    class FakeGmail:
        async def get_attachment(self, *_args, **_kwargs):
            return content

    def delayed_write(*args, **kwargs):
        started.set()
        time.sleep(0.05)
        return original_write(*args, **kwargs)

    monkeypatch.setattr(attachment_service, "_write_private_file_atomic", delayed_write)
    task = asyncio.create_task(load_attachment_bytes(
        _CacheDb(),
        email,
        attachment,
        account,
        storage_root=tmp_path,
        credential_resolver=fake_credentials,
        gmail_service_factory=lambda *_args, **_kwargs: FakeGmail(),
    ))
    assert await asyncio.to_thread(started.wait, 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    canonical_path = _canonical_cache_path(tmp_path, email, attachment, account)
    assert canonical_path.read_bytes() == content
    probe = acquire_entry_lease(
        tmp_path.resolve(),
        account.user_id,
        email.account_id,
        email.id,
        attachment.id,
        blocking=False,
    )
    assert probe is not None
    probe.release()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("upstream_message", "expected_status", "expected_public_detail"),
    [
        ("Attachment exceeds size limit", 413, "Attachment is too large to download"),
        ("Attachment data is invalid", 502, "Attachment data is invalid"),
    ],
)
async def test_gmail_decoder_failures_have_stable_public_status(
    tmp_path,
    upstream_message,
    expected_status,
    expected_public_detail,
):
    email, attachment, account = _generated_records()

    async def fake_credentials(_db):
        return "generated-client", "generated-secret"

    class FakeGmail:
        async def get_attachment(self, *_args, **_kwargs):
            raise ValueError(upstream_message)

    with pytest.raises(AttachmentDownloadError) as exc_info:
        await load_attachment_bytes(
            _CacheDb(),
            email,
            attachment,
            account,
            storage_root=tmp_path,
            credential_resolver=fake_credentials,
            gmail_service_factory=lambda *_args, **_kwargs: FakeGmail(),
        )

    assert exc_info.value.status_code == expected_status
    assert exc_info.value.public_detail == expected_public_detail


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
