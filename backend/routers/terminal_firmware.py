"""Authenticated, fail-closed browser firmware download endpoints."""

from __future__ import annotations

import hashlib
import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.concurrency import run_in_threadpool

from backend.config import get_settings
from backend.models.user import User
from backend.routers.auth import get_current_user, limiter
from backend.services.terminal.firmware_artifacts import (
    FirmwareArtifactError,
    FirmwareArtifactNotFound,
    FirmwareCatalogUnavailable,
    FirmwareModelNotQualified,
    FirmwareReleaseNotFound,
    build_firmware_catalog,
    read_model_artifact,
    read_release_metadata,
)
from backend.services.terminal.ota_policy import evaluate_ota_policy


router = APIRouter(prefix="/api/terminal/firmware", tags=["terminal-firmware"])
settings = get_settings()

_UNAVAILABLE_BLOCKERS = {
    "No trusted firmware signing key is configured.",
    "No approved firmware catalog is installed.",
    "One or more catalog entries failed verification.",
}
_SAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9._-]")
_PRIVATE_HEADERS = {
    "Cache-Control": "private, no-store",
    "X-Content-Type-Options": "nosniff",
    "Cross-Origin-Resource-Policy": "same-origin",
}


def _service_args() -> tuple[str, str, bool, int]:
    return (
        settings.terminal_firmware_storage_path,
        settings.terminal_firmware_trusted_signing_keys,
        settings.terminal_firmware_browser_flash_enabled,
        settings.terminal_firmware_minimum_catalog_generation,
    )


def _catalog_is_unavailable(catalog: dict[str, Any]) -> bool:
    return any(blocker in _UNAVAILABLE_BLOCKERS for blocker in catalog["blockers"])


async def _verified_catalog() -> dict[str, Any]:
    storage_path, trusted_keys, enabled, minimum_generation = _service_args()
    try:
        catalog = await run_in_threadpool(
            build_firmware_catalog,
            storage_path,
            trusted_keys,
            enabled,
            minimum_generation,
        )
    except FirmwareArtifactError as exc:
        raise HTTPException(status_code=503, detail="Firmware catalog unavailable") from exc
    if _catalog_is_unavailable(catalog):
        raise HTTPException(status_code=503, detail="Firmware catalog unavailable")
    return catalog


def _safe_filename(raw: str) -> str:
    sanitized = _SAFE_FILENAME_RE.sub("_", raw)
    return sanitized[:160] or "firmware.bin"


def _immutable_response(
    raw: bytes,
    media_type: str,
    filename: str,
    *,
    sha256: str | None = None,
) -> Response:
    digest = sha256 or hashlib.sha256(raw).hexdigest()
    safe_filename = _safe_filename(filename)
    return Response(
        content=raw,
        media_type=media_type,
        headers={
            **_PRIVATE_HEADERS,
            "Content-Length": str(len(raw)),
            "ETag": f'"sha256:{digest}"',
            "Content-Disposition": f'attachment; filename="{safe_filename}"',
        },
    )


async def _release_metadata_response(
    release_id: str,
    kind: str,
    filename: str,
) -> Response:
    storage_path, trusted_keys, _enabled, minimum_generation = _service_args()
    try:
        raw, media_type, _service_etag = await run_in_threadpool(
            read_release_metadata,
            storage_path,
            trusted_keys,
            release_id,
            kind,
            minimum_generation,
        )
    except FirmwareReleaseNotFound as exc:
        raise HTTPException(status_code=404, detail="Firmware resource not found") from exc
    except FirmwareArtifactNotFound as exc:
        raise HTTPException(status_code=404, detail="Firmware resource not found") from exc
    except (FirmwareCatalogUnavailable, FirmwareArtifactError) as exc:
        raise HTTPException(status_code=503, detail="Firmware catalog unavailable") from exc
    return _immutable_response(raw, media_type, filename)


@router.get("/catalog")
@limiter.limit("6/minute")
async def firmware_catalog(
    request: Request,
    response: Response,
    _user: User = Depends(get_current_user),
) -> dict[str, Any]:
    catalog = await _verified_catalog()
    response.headers.update(_PRIVATE_HEADERS)
    return catalog


@router.get("/ota/capabilities")
@limiter.limit("12/minute")
async def firmware_ota_capabilities(
    request: Request,
    response: Response,
    _user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Expose the authenticated, read-only OTA lock state.

    No release evidence or event ledger is wired in this milestone, so the
    policy cannot become ready even if a single configuration flag is changed.
    """

    policy = evaluate_ota_policy(
        settings,
        releases=(),
        event_persistence_ready=False,
    )
    response.headers.update(_PRIVATE_HEADERS)
    return policy.as_capabilities()


@router.get("/releases/{release_id}/manifest.json")
@limiter.limit("6/minute")
async def firmware_manifest(
    request: Request,
    release_id: str,
    _user: User = Depends(get_current_user),
) -> Response:
    return await _release_metadata_response(release_id, "manifest", "manifest.json")


@router.get("/releases/{release_id}/manifest.sig")
@limiter.limit("6/minute")
async def firmware_signature(
    request: Request,
    release_id: str,
    _user: User = Depends(get_current_user),
) -> Response:
    return await _release_metadata_response(release_id, "signature", "manifest.sig")


@router.get("/releases/{release_id}/models/{model_name}/artifacts/{role}")
@limiter.limit("12/minute")
async def firmware_artifact(
    request: Request,
    release_id: str,
    model_name: str,
    role: str,
    _user: User = Depends(get_current_user),
) -> Response:
    storage_path, trusted_keys, enabled, minimum_generation = _service_args()
    try:
        raw, artifact, bundle = await run_in_threadpool(
            read_model_artifact,
            storage_path,
            trusted_keys,
            enabled,
            release_id,
            model_name,
            role,
            minimum_generation,
        )
    except (FirmwareReleaseNotFound, FirmwareArtifactNotFound) as exc:
        raise HTTPException(status_code=404, detail="Firmware resource not found") from exc
    except FirmwareModelNotQualified as exc:
        raise HTTPException(status_code=409, detail="Firmware model is not browser-installable") from exc
    except (FirmwareCatalogUnavailable, FirmwareArtifactError) as exc:
        raise HTTPException(status_code=503, detail="Firmware catalog unavailable") from exc
    filename = f"{bundle.firmware_version}-{model_name}-{role}.bin"
    return _immutable_response(
        raw,
        "application/octet-stream",
        filename,
        sha256=artifact.sha256,
    )
