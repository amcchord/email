from __future__ import annotations

from types import SimpleNamespace

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi import HTTPException, Request, Response
from fastapi.testclient import TestClient

import backend.routers.terminal_enrollment as enrollment_router
from backend.main import app
from backend.models.terminal import (
    TerminalDevice,
    TerminalDeviceCredential,
    TerminalEnrollmentAttempt,
)
from backend.routers.auth import get_current_user
from backend.services.terminal.enrollment_policy import EnrollmentPolicy


def _request(
    path: str,
    *,
    method: str = "GET",
    cookie: bool = False,
    origin: str | None = None,
    fetch_site: str | None = None,
) -> Request:
    headers = []
    if cookie:
        headers.append((b"cookie", b"access_token=session"))
    if origin:
        headers.append((b"origin", origin.encode("ascii")))
    if fetch_site:
        headers.append((b"sec-fetch-site", fetch_site.encode("ascii")))
    return Request(
        {
            "type": "http",
            "method": method,
            "path": path,
            "headers": headers,
            "client": ("192.0.2.10", 12345),
            "scheme": "https",
            "server": ("email.mcchord.net", 443),
        }
    )


def _policy(*, enabled=False, state="locked") -> EnrollmentPolicy:
    return EnrollmentPolicy(
        enabled=enabled,
        state=state,
        base_url="https://email.mcchord.net",
        signing_key_id="test-ret1-key",
        signing_key=object(),
        public_key_sha256="a" * 64,
        ticket_ttl_seconds=300,
        releases=(),
        blockers=() if state == "ready" else ("Physical HIL is incomplete.",),
    )


def test_enrollment_api_routes_require_session_auth_and_device_routes_do_not():
    api_routes = [
        route
        for route in enrollment_router.router.routes
        if route.path.startswith("/api/terminal/enrollment/")
    ]
    device_routes = [
        route
        for route in enrollment_router.router.routes
        if route.path.startswith("/terminal/device/")
    ]

    assert {(route.path, next(iter(route.methods))) for route in api_routes} == {
        ("/api/terminal/enrollment/capabilities", "GET"),
        ("/api/terminal/enrollment/intents", "POST"),
        ("/api/terminal/enrollment/intents/{attempt_id}/ticket", "POST"),
        ("/api/terminal/enrollment/intents/{attempt_id}/complete", "POST"),
        ("/api/terminal/enrollment/intents/{attempt_id}", "GET"),
        ("/api/terminal/enrollment/devices/{public_id}/revoke", "POST"),
    }
    assert all(
        any(dependency.call is get_current_user for dependency in route.dependant.dependencies)
        for route in api_routes
    )
    assert {(route.path, next(iter(route.methods))) for route in device_routes} == {
        ("/terminal/device/{public_id}/{credential_token}/schedule.json", "GET"),
        ("/terminal/device/{public_id}/{credential_token}/image.bmp", "GET"),
    }
    assert all(
        not any(dependency.call is get_current_user for dependency in route.dependant.dependencies)
        for route in device_routes
    )


def test_anonymous_enrollment_capabilities_are_rejected():
    response = TestClient(app).get("/api/terminal/enrollment/capabilities")

    assert response.status_code == 401
    assert response.json() == {"detail": "Not authenticated"}


@pytest.mark.asyncio
async def test_capabilities_are_private_and_report_locked_policy(monkeypatch):
    async def locked_policy():
        return _policy()

    monkeypatch.setattr(enrollment_router, "_policy", locked_policy)
    response = Response()

    result = await enrollment_router.enrollment_capabilities(
        _request("/api/terminal/enrollment/capabilities"),
        response,
        _user=SimpleNamespace(id=7),
    )

    assert result["state"] == "locked"
    assert result["enabled"] is False
    assert result["identity_strength"] == "physical_cable_only"
    assert result["attestation"] is False
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["cross-origin-resource-policy"] == "same-origin"


def test_enrollment_mutations_require_cookie_and_exact_same_origin():
    policy = _policy(enabled=True, state="ready")
    enrollment_router._require_same_origin_session(
        _request(
            "/api/terminal/enrollment/intents",
            method="POST",
            cookie=True,
            origin="https://email.mcchord.net",
            fetch_site="same-origin",
        ),
        policy,
    )

    invalid_requests = (
        _request(
            "/api/terminal/enrollment/intents",
            method="POST",
            origin="https://email.mcchord.net",
        ),
        _request(
            "/api/terminal/enrollment/intents",
            method="POST",
            cookie=True,
            origin="https://evil.example",
        ),
        _request(
            "/api/terminal/enrollment/intents",
            method="POST",
            cookie=True,
            origin="https://email.mcchord.net",
            fetch_site="cross-site",
        ),
    )
    for request in invalid_requests:
        with pytest.raises(HTTPException) as exc_info:
            enrollment_router._require_same_origin_session(request, policy)
        assert exc_info.value.status_code == 403


def test_revocation_requires_cookie_and_configured_application_origin(monkeypatch):
    monkeypatch.setattr(
        enrollment_router.settings,
        "allowed_origins",
        "https://email.mcchord.net,https://other.example",
    )
    enrollment_router._require_owner_mutation(
        _request(
            "/api/terminal/enrollment/devices/device/revoke",
            method="POST",
            cookie=True,
            origin="https://email.mcchord.net",
            fetch_site="same-origin",
        )
    )
    with pytest.raises(HTTPException) as exc_info:
        enrollment_router._require_owner_mutation(
            _request(
                "/api/terminal/enrollment/devices/device/revoke",
                method="POST",
                cookie=True,
                origin="https://evil.example",
                fetch_site="same-origin",
            )
        )
    assert exc_info.value.status_code == 403


def test_raw_device_credentials_are_canonical_and_only_persisted_as_hashes():
    token = "A" * 43
    assert enrollment_router.TOKEN_RE.fullmatch(token)
    digest = enrollment_router._hash_token(token)
    assert digest == enrollment_router._hash_token(token)
    assert len(digest) == 64
    assert token not in digest


def test_enrollment_models_and_migration_form_one_additive_head():
    assert "public_id" in TerminalDevice.__table__.c
    assert "enrollment_generation" in TerminalDevice.__table__.c
    assert "token_sha256" in TerminalDeviceCredential.__table__.c
    assert "compact_jws" in TerminalEnrollmentAttempt.__table__.c
    assert "credential" not in TerminalDevice.__table__.c
    assert "credential" not in TerminalDeviceCredential.__table__.c
    assert "credential" not in TerminalEnrollmentAttempt.__table__.c

    credential_constraints = {
        constraint.name: str(getattr(constraint, "sqltext", ""))
        for constraint in TerminalDeviceCredential.__table__.constraints
    }
    assert "uq_terminal_device_credentials_token_sha256" in credential_constraints
    assert "uq_terminal_device_credentials_device_generation" in credential_constraints
    assert "ck_terminal_device_credentials_hashes" in credential_constraints
    secure_mac_index = next(
        index
        for index in TerminalDevice.__table__.indexes
        if index.name == "uq_terminal_devices_secure_mac"
    )
    assert secure_mac_index.unique is True
    assert "enrollment_state <> 'legacy'" in str(
        secure_mac_index.dialect_options["postgresql"]["where"]
    )

    attempt_constraints = {
        constraint.name: str(getattr(constraint, "sqltext", ""))
        for constraint in TerminalEnrollmentAttempt.__table__.constraints
    }
    assert "target_generation = observed_generation + 1" in attempt_constraints[
        "ck_terminal_enrollment_attempts_generations"
    ]
    assert "client_ticket_id IS NULL" in attempt_constraints[
        "ck_terminal_enrollment_attempts_ticket_shape"
    ]

    config = Config()
    config.set_main_option("script_location", "alembic")
    scripts = ScriptDirectory.from_config(config)
    revision = scripts.get_revision("f3a4b5c6d7e8")
    assert revision.down_revision == "e2f3a4b5c6d7"
    assert scripts.get_revision("a4b5c6d7e8f9").down_revision == "f3a4b5c6d7e8"
    assert scripts.get_revision("b5c6d7e8f9a0").down_revision == "a4b5c6d7e8f9"
    assert scripts.get_heads() == ["b5c6d7e8f9a0"]
