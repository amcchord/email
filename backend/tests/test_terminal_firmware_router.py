"""Endpoint policy tests for authenticated firmware delivery."""

from __future__ import annotations

import hashlib
import itertools
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException, Request, Response
from fastapi.testclient import TestClient

import backend.routers.terminal_firmware as firmware_router
from backend.routers.auth import get_current_user
from backend.services.terminal.firmware_artifacts import (
    build_firmware_catalog,
    read_model_artifact,
)
from backend.tests.test_terminal_firmware_artifacts import stage_signed_bundle


_REQUEST_SEQUENCE = itertools.count(1)


def _configure(
    monkeypatch,
    root: Path,
    trusted_keys: str,
    *,
    enabled: bool = True,
    minimum_generation: int = 1,
):
    monkeypatch.setattr(
        firmware_router,
        "settings",
        SimpleNamespace(
            terminal_firmware_storage_path=str(root),
            terminal_firmware_trusted_signing_keys=trusted_keys,
            terminal_firmware_minimum_catalog_generation=minimum_generation,
            terminal_firmware_browser_flash_enabled=enabled,
            terminal_ota_enabled=False,
            terminal_ota_qualified_releases="{}",
        ),
    )


def _response_headers(response):
    return {key.lower(): value for key, value in response.headers.items()}


def _request(path: str = "/api/terminal/firmware/catalog") -> Request:
    sequence = next(_REQUEST_SEQUENCE)
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": path,
            "headers": [],
            "client": (f"192.0.2.{sequence}", 12345),
            "scheme": "https",
            "server": ("testserver", 443),
        }
    )


def test_every_firmware_route_requires_an_authenticated_user():
    routes = [route for route in firmware_router.router.routes if hasattr(route, "dependant")]

    assert len(routes) == 5
    for route in routes:
        assert any(
            dependency.call is get_current_user
            for dependency in route.dependant.dependencies
        ), route.path


@pytest.mark.asyncio
async def test_ota_capabilities_are_authenticated_read_only_and_default_locked(
    tmp_path: Path,
    monkeypatch,
):
    fixture = stage_signed_bundle(tmp_path)
    _configure(monkeypatch, tmp_path, fixture["trusted_keys"])
    response = Response()

    capabilities = await firmware_router.firmware_ota_capabilities(
        _request("/api/terminal/firmware/ota/capabilities"),
        response,
        _user=None,
    )

    assert capabilities["state"] == "locked"
    assert capabilities["enabled"] is False
    assert capabilities["effective_offer_enabled"] is False
    assert capabilities["event_persistence_ready"] is True
    assert capabilities["qualified_releases"] == []
    assert "Server-side terminal OTA is disabled." in capabilities["blockers"]
    assert response.headers["cache-control"] == "private, no-store"


def test_registered_catalog_endpoint_rejects_anonymous_requests():
    from backend.main import app

    response = TestClient(app).get("/api/terminal/firmware/catalog")

    assert response.status_code == 401
    assert response.json() == {"detail": "Not authenticated"}


@pytest.mark.asyncio
async def test_catalog_and_artifact_service_work_runs_in_threadpool(
    tmp_path: Path,
    monkeypatch,
):
    fixture = stage_signed_bundle(tmp_path)
    _configure(monkeypatch, tmp_path, fixture["trusted_keys"])
    calls = []

    async def capture_threadpool(function, *args):
        calls.append(function)
        return function(*args)

    monkeypatch.setattr(firmware_router, "run_in_threadpool", capture_threadpool)

    catalog_response = Response()
    catalog = await firmware_router.firmware_catalog(
        _request(),
        catalog_response,
        _user=None,
    )
    response = await firmware_router.firmware_artifact(
        _request(), fixture["release_id"], "E1001", "application", _user=None
    )

    assert catalog["installer_state"] == "ready"
    assert catalog_response.headers["cache-control"] == "private, no-store"
    assert catalog_response.headers["x-content-type-options"] == "nosniff"
    assert catalog_response.headers["cross-origin-resource-policy"] == "same-origin"
    assert response.body == fixture["artifacts"][("E1001", "application")]
    assert calls == [
        build_firmware_catalog,
        read_model_artifact,
    ]


@pytest.mark.asyncio
async def test_downloads_have_private_integrity_and_safe_binary_headers(
    tmp_path: Path,
    monkeypatch,
):
    fixture = stage_signed_bundle(tmp_path)
    _configure(monkeypatch, tmp_path, fixture["trusted_keys"])

    manifest = await firmware_router.firmware_manifest(
        _request(), fixture["release_id"], _user=None
    )
    signature = await firmware_router.firmware_signature(
        _request(), fixture["release_id"], _user=None
    )
    artifact = await firmware_router.firmware_artifact(
        _request(), fixture["release_id"], "E1001", "application", _user=None
    )

    for response, expected_name in (
        (manifest, "manifest.json"),
        (signature, "manifest.sig"),
        (artifact, "0.2.0-test.1-E1001-application.bin"),
    ):
        headers = _response_headers(response)
        assert headers["cache-control"] == "private, no-store"
        assert headers["x-content-type-options"] == "nosniff"
        assert headers["cross-origin-resource-policy"] == "same-origin"
        assert headers["content-length"] == str(len(response.body))
        assert headers["etag"] == f'"sha256:{hashlib.sha256(response.body).hexdigest()}"'
        assert headers["content-disposition"] == f'attachment; filename="{expected_name}"'
        assert "\r" not in headers["content-disposition"]
        assert "\n" not in headers["content-disposition"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("model", "role"),
    (
        ("E9999", "application"),
        ("E1001", "factory_recovery"),
        ("E1001", "../../application"),
    ),
)
async def test_unknown_model_and_role_are_uniform_404(
    tmp_path: Path,
    monkeypatch,
    model: str,
    role: str,
):
    fixture = stage_signed_bundle(tmp_path)
    _configure(monkeypatch, tmp_path, fixture["trusted_keys"])

    with pytest.raises(HTTPException) as caught:
        await firmware_router.firmware_artifact(
            _request(), fixture["release_id"], model, role, _user=None
        )

    assert caught.value.status_code == 404
    assert caught.value.detail == "Firmware resource not found"


@pytest.mark.asyncio
async def test_unknown_release_is_uniform_404(tmp_path: Path, monkeypatch):
    fixture = stage_signed_bundle(tmp_path)
    _configure(monkeypatch, tmp_path, fixture["trusted_keys"])

    with pytest.raises(HTTPException) as manifest_error:
        await firmware_router.firmware_manifest(_request(), "0" * 64, _user=None)
    with pytest.raises(HTTPException) as artifact_error:
        await firmware_router.firmware_artifact(
            _request(), "0" * 64, "E1001", "application", _user=None
        )

    assert manifest_error.value.status_code == 404
    assert artifact_error.value.status_code == 404
    assert manifest_error.value.detail == artifact_error.value.detail


@pytest.mark.asyncio
async def test_unqualified_or_disabled_model_is_409(tmp_path: Path, monkeypatch):
    fixture = stage_signed_bundle(tmp_path)
    _configure(monkeypatch, tmp_path, fixture["trusted_keys"], enabled=False)

    with pytest.raises(HTTPException) as caught:
        await firmware_router.firmware_artifact(
            _request(), fixture["release_id"], "E1001", "application", _user=None
        )

    assert caught.value.status_code == 409
    assert caught.value.detail == "Firmware model is not browser-installable"


@pytest.mark.asyncio
async def test_missing_generation_floor_keeps_enabled_installer_locked(
    tmp_path: Path,
    monkeypatch,
):
    fixture = stage_signed_bundle(tmp_path)
    _configure(
        monkeypatch,
        tmp_path,
        fixture["trusted_keys"],
        enabled=True,
        minimum_generation=0,
    )

    catalog = await firmware_router.firmware_catalog(
        _request(),
        Response(),
        _user=None,
    )
    with pytest.raises(HTTPException) as caught:
        await firmware_router.firmware_artifact(
            _request(), fixture["release_id"], "E1001", "application", _user=None
        )

    assert catalog["installer_state"] == "locked"
    assert "No minimum signed catalog generation is pinned." in catalog["blockers"]
    assert caught.value.status_code == 409


@pytest.mark.asyncio
async def test_unknown_role_stays_404_when_browser_flashing_is_disabled(
    tmp_path: Path,
    monkeypatch,
):
    fixture = stage_signed_bundle(tmp_path)
    _configure(monkeypatch, tmp_path, fixture["trusted_keys"], enabled=False)

    with pytest.raises(HTTPException) as caught:
        await firmware_router.firmware_artifact(
            _request(), fixture["release_id"], "E1001", "unknown", _user=None
        )

    assert caught.value.status_code == 404
    assert caught.value.detail == "Firmware resource not found"


@pytest.mark.asyncio
async def test_missing_current_catalog_is_503(tmp_path: Path, monkeypatch):
    fixture = stage_signed_bundle(tmp_path / "key-source")
    empty_root = tmp_path / "empty"
    empty_root.mkdir()
    _configure(monkeypatch, empty_root, fixture["trusted_keys"])

    with pytest.raises(HTTPException) as caught:
        await firmware_router.firmware_catalog(_request(), Response(), _user=None)

    assert caught.value.status_code == 503
    assert caught.value.detail == "Firmware catalog unavailable"


@pytest.mark.asyncio
async def test_corrupt_approved_bundle_is_503(tmp_path: Path, monkeypatch):
    fixture = stage_signed_bundle(tmp_path)
    _configure(monkeypatch, tmp_path, fixture["trusted_keys"])
    application = fixture["payload_root"] / "reterminal_e1001" / "firmware.bin"
    application.write_bytes(application.read_bytes() + b"tampered")

    with pytest.raises(HTTPException) as catalog_error:
        await firmware_router.firmware_catalog(_request(), Response(), _user=None)
    with pytest.raises(HTTPException) as artifact_error:
        await firmware_router.firmware_artifact(
            _request(), fixture["release_id"], "E1001", "application", _user=None
        )

    assert catalog_error.value.status_code == 503
    assert artifact_error.value.status_code == 503
