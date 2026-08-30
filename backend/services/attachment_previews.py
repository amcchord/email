"""Byte-classified, browser-isolated payloads for attachment previews."""

from __future__ import annotations

import asyncio
import io
import re
import unicodedata
import warnings
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from PIL import Image, ImageOps, UnidentifiedImageError

from backend.services.attachment_cache import run_blocking_cache_operation

MAX_ATTACHMENT_PREVIEW_BYTES = 25 * 1024 * 1024
MAX_TEXT_PREVIEW_BYTES = 1024 * 1024
MAX_IMAGE_PREVIEW_OUTPUT_BYTES = 12 * 1024 * 1024
MAX_IMAGE_PREVIEW_AXIS = 8_192
MAX_IMAGE_PREVIEW_PIXELS = 12_000_000
MAX_IMAGE_RENDER_AXIS = 2_048
PREVIEW_PIPELINE_CONCURRENCY = 2
PREVIEW_PIPELINE_QUEUE_TIMEOUT_SECONDS = 2.0

_preview_pipeline_slots = asyncio.BoundedSemaphore(PREVIEW_PIPELINE_CONCURRENCY)

_PDF_HEADER_RE = re.compile(rb"^%PDF-(?:1\.[0-9]|2\.0)(?:[\t\r\n ])")
_PDF_FORBIDDEN_MARKERS = (
    b"/javascript",
    b"/js",
    b"/launch",
    b"/embeddedfile",
    b"/richmedia",
    b"/openaction",
    b"/aa",
    b"/xfa",
    b"/acroform",
    b"/encrypt",
)
_IMAGE_SIGNATURES = (
    b"\x89PNG\r\n\x1a\n",
    b"\xff\xd8\xff",
    b"RIFF",
)
_ALLOWED_IMAGE_FORMATS = {"JPEG", "PNG", "WEBP"}


class AttachmentPreviewError(Exception):
    """Raised when bytes do not meet the bounded preview contract."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int = 415,
        public_detail: str = "Preview is not available for this attachment",
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.public_detail = public_detail


@dataclass(frozen=True)
class AttachmentPreview:
    content: bytes
    content_type: str
    kind: str
    truncated: bool = False


def _validate_preview_source(content: bytes) -> None:
    if not content:
        raise AttachmentPreviewError("Attachment preview source is empty")
    if len(content) > MAX_ATTACHMENT_PREVIEW_BYTES:
        raise AttachmentPreviewError(
            "Attachment exceeds the preview size limit",
            status_code=413,
            public_detail="This attachment is too large to preview",
        )


def _looks_like_pdf(content: bytes) -> bool:
    return content.startswith(b"%PDF-")


def _build_pdf_preview(content: bytes) -> AttachmentPreview | None:
    if not _looks_like_pdf(content):
        return None
    if not _PDF_HEADER_RE.match(content):
        raise AttachmentPreviewError("PDF header is invalid")

    eof_offset = content.rfind(b"%%EOF")
    if eof_offset < max(0, len(content) - 4096):
        raise AttachmentPreviewError("PDF end marker is missing")
    if content[eof_offset + len(b"%%EOF"):].strip(b"\x00\t\r\n "):
        raise AttachmentPreviewError("PDF has data after its end marker")

    lowered = content.lower()
    if any(marker in lowered for marker in _PDF_FORBIDDEN_MARKERS):
        raise AttachmentPreviewError(
            "PDF contains active, embedded, encrypted, or form features",
            public_detail="This PDF uses features that are not available in preview",
        )
    return AttachmentPreview(content, "application/pdf", "pdf")


def _looks_like_image(content: bytes) -> bool:
    if content.startswith(_IMAGE_SIGNATURES[:2]):
        return True
    return content.startswith(b"RIFF") and content[8:12] == b"WEBP"


def _normalized_image_preview(content: bytes) -> AttachmentPreview | None:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            source = Image.open(io.BytesIO(content))
            source_format = (source.format or "").upper()
            if source_format not in _ALLOWED_IMAGE_FORMATS:
                if _looks_like_image(content):
                    raise AttachmentPreviewError(
                        f"Image format {source_format or 'unknown'} is not allowed"
                    )
                return None
            width, height = source.size
            if width <= 0 or height <= 0:
                raise AttachmentPreviewError("Image dimensions are invalid")
            if (
                width > MAX_IMAGE_PREVIEW_AXIS
                or height > MAX_IMAGE_PREVIEW_AXIS
                or width * height > MAX_IMAGE_PREVIEW_PIXELS
            ):
                raise AttachmentPreviewError(
                    "Image dimensions exceed the preview limit",
                    status_code=413,
                    public_detail="This image is too large to preview",
                )
            source.verify()

        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            image = Image.open(io.BytesIO(content))
            image.seek(0)
            image.load()
            image = ImageOps.exif_transpose(image)
            image.thumbnail(
                (MAX_IMAGE_RENDER_AXIS, MAX_IMAGE_RENDER_AXIS),
                Image.Resampling.LANCZOS,
            )
            has_alpha = "A" in image.getbands() or (
                image.mode == "P" and "transparency" in image.info
            )
            output = io.BytesIO()
            if has_alpha:
                image.convert("RGBA").save(output, format="PNG", optimize=True)
                content_type = "image/png"
            else:
                image.convert("RGB").save(
                    output,
                    format="JPEG",
                    quality=88,
                    optimize=True,
                    progressive=True,
                )
                content_type = "image/jpeg"
            rendered = output.getvalue()
    except AttachmentPreviewError:
        raise
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise AttachmentPreviewError(
            "Image dimensions exceed Pillow's preview limit",
            status_code=413,
            public_detail="This image is too large to preview",
        ) from exc
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        if _looks_like_image(content):
            raise AttachmentPreviewError("Image data is invalid") from exc
        return None

    if not rendered or len(rendered) > MAX_IMAGE_PREVIEW_OUTPUT_BYTES:
        raise AttachmentPreviewError(
            "Normalized image exceeds the preview output limit",
            status_code=413,
            public_detail="This image is too large to preview",
        )
    return AttachmentPreview(rendered, content_type, "image")


def _build_text_preview(content: bytes) -> AttachmentPreview | None:
    preview_bytes = content[:MAX_TEXT_PREVIEW_BYTES]
    try:
        text = preview_bytes.decode("utf-8-sig", errors="strict")
    except UnicodeDecodeError as exc:
        if not (
            len(content) > len(preview_bytes)
            and exc.reason == "unexpected end of data"
            and exc.end == len(preview_bytes)
        ):
            return None
        for trim_bytes in range(1, 4):
            try:
                candidate = preview_bytes[:-trim_bytes]
                text = candidate.decode("utf-8-sig", errors="strict")
                preview_bytes = candidate
                break
            except UnicodeDecodeError:
                continue
        else:
            return None
    if not text:
        return None
    if any(
        unicodedata.category(character).startswith("C")
        and character not in {"\n", "\r", "\t"}
        for character in text
    ):
        return None
    return AttachmentPreview(
        text.encode("utf-8"),
        "text/plain; charset=utf-8",
        "text",
        truncated=len(content) > len(preview_bytes),
    )


def _build_attachment_preview(content: bytes) -> AttachmentPreview:
    _validate_preview_source(content)

    pdf_preview = _build_pdf_preview(content)
    if pdf_preview is not None:
        return pdf_preview

    image_preview = _normalized_image_preview(content)
    if image_preview is not None:
        return image_preview

    text_preview = _build_text_preview(content)
    if text_preview is not None:
        return text_preview

    raise AttachmentPreviewError("Attachment bytes do not match a preview renderer")


async def load_and_build_attachment_preview(
    loader: Callable[[], Awaitable[bytes]],
) -> AttachmentPreview:
    """Bound retrieval memory and classification inside one admission lease."""
    acquired = False
    try:
        async with asyncio.timeout(PREVIEW_PIPELINE_QUEUE_TIMEOUT_SECONDS):
            await _preview_pipeline_slots.acquire()
            acquired = True
    except TimeoutError as exc:
        raise AttachmentPreviewError(
            "Attachment preview render queue is full",
            status_code=503,
            public_detail="Preview service is busy; try again shortly",
        ) from exc

    try:
        content = await loader()
        return await run_blocking_cache_operation(_build_attachment_preview, content)
    finally:
        if acquired:
            _preview_pipeline_slots.release()


async def build_attachment_preview(content: bytes) -> AttachmentPreview:
    """Classify already-resident untrusted bytes within the pipeline budget."""

    async def load_resident_content() -> bytes:
        return content

    return await load_and_build_attachment_preview(load_resident_content)
