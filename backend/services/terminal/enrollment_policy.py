"""Fail-closed operator policy for RET1 terminal enrollment.

Offline Ed25519 firmware-release signing and the online P-256 enrollment key
are deliberately independent trust boundaries. A server is enrollment-ready
only when an exact signed schema-2 release, its embedded RET1 key hash, the
protected online key, the pinned catalog generation, and an operator-authored
release/model HIL allowlist all agree.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from backend.services.terminal.firmware_artifacts import (
    FirmwareArtifactError,
    build_firmware_catalog,
)


SHA256_RE = re.compile(r"[0-9a-f]{64}")
KEY_ID_RE = re.compile(r"[A-Za-z0-9._-]{1,64}")
ALLOWED_MODELS = ("E1001", "E1002")
MAX_QUALIFIED_RELEASES = 4


class EnrollmentPolicyError(RuntimeError):
    """Configuration or signed-release evidence failed closed."""


@dataclass(frozen=True)
class QualifiedEnrollmentRelease:
    release_id: str
    firmware_version: str
    git_sha: str
    trust_key_id: str
    public_key_sha256: str
    models: tuple[str, ...]

    def as_public_record(self) -> dict[str, Any]:
        return {
            "release_id": self.release_id,
            "firmware_version": self.firmware_version,
            "git_sha": self.git_sha,
            "models": list(self.models),
        }


@dataclass(frozen=True)
class EnrollmentPolicy:
    enabled: bool
    state: str
    base_url: str | None
    signing_key_id: str | None
    signing_key: Any | None
    public_key_sha256: str | None
    ticket_ttl_seconds: int
    releases: tuple[QualifiedEnrollmentRelease, ...]
    blockers: tuple[str, ...]

    def as_capabilities(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "state": self.state,
            "enabled": self.enabled,
            "protocol": "RET1",
            "identity_strength": "physical_cable_only",
            "attestation": False,
            "allowed_models": list(ALLOWED_MODELS),
            "qualified_releases": [
                release.as_public_record() for release in self.releases
            ],
            "blockers": list(self.blockers),
        }

    def require_ready(self) -> "EnrollmentPolicy":
        if self.state != "ready" or not self.enabled:
            raise EnrollmentPolicyError("Terminal enrollment is not available")
        return self

    def release_for(self, *, firmware_version: str, model: str) -> QualifiedEnrollmentRelease:
        matches = [
            release
            for release in self.releases
            if release.firmware_version == firmware_version and model in release.models
        ]
        if len(matches) != 1:
            raise EnrollmentPolicyError("Terminal firmware is not enrollment-qualified")
        return matches[0]


def _strict_json(raw: str, label: str) -> Any:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise EnrollmentPolicyError(f"{label} contains a duplicate key")
            result[key] = value
        return result

    try:
        return json.loads(raw, object_pairs_hook=reject_duplicates)
    except (TypeError, json.JSONDecodeError) as exc:
        raise EnrollmentPolicyError(f"{label} is not valid JSON") from exc


def parse_qualified_releases(raw: str) -> dict[str, tuple[str, ...]]:
    decoded = _strict_json(raw, "terminal enrollment qualification allowlist")
    if not isinstance(decoded, dict) or len(decoded) > MAX_QUALIFIED_RELEASES:
        raise EnrollmentPolicyError("terminal enrollment qualification allowlist is invalid")
    result: dict[str, tuple[str, ...]] = {}
    for release_id, raw_models in decoded.items():
        if not isinstance(release_id, str) or SHA256_RE.fullmatch(release_id) is None:
            raise EnrollmentPolicyError("terminal enrollment release id is invalid")
        if (
            not isinstance(raw_models, list)
            or not raw_models
            or len(raw_models) > len(ALLOWED_MODELS)
            or any(type(model) is not str for model in raw_models)
            or len(set(raw_models)) != len(raw_models)
            or any(model not in ALLOWED_MODELS for model in raw_models)
        ):
            raise EnrollmentPolicyError("terminal enrollment model allowlist is invalid")
        result[release_id] = tuple(model for model in ALLOWED_MODELS if model in raw_models)
    return result


def normalize_base_url(raw: str) -> str:
    value = raw.strip()
    try:
        parsed = urlsplit(value)
    except ValueError as exc:
        raise EnrollmentPolicyError("terminal enrollment base URL is invalid") from exc
    try:
        port = parsed.port
    except ValueError as exc:
        raise EnrollmentPolicyError("terminal enrollment base URL is invalid") from exc
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
        or port not in {None, 443}
    ):
        raise EnrollmentPolicyError("terminal enrollment base URL must be an HTTPS origin")
    hostname = parsed.hostname.lower()
    if ":" in hostname:
        hostname = f"[{hostname}]"
    return f"https://{hostname}"


def _load_online_identity(path: str) -> tuple[Any, str]:
    # Imported lazily so policy parsing remains testable without touching the
    # filesystem and so key-loader failures collapse to one public blocker.
    from backend.services.terminal.enrollment_protocol import load_signing_key

    loaded = load_signing_key(path)
    if isinstance(loaded, tuple) and len(loaded) == 2:
        return loaded
    key = getattr(loaded, "private_key", None) or getattr(loaded, "key", None)
    digest = getattr(loaded, "public_key_sha256", None)
    if key is None or not isinstance(digest, str):
        raise EnrollmentPolicyError("terminal enrollment signing identity is invalid")
    return key, digest


def evaluate_enrollment_policy(settings: Any) -> EnrollmentPolicy:
    blockers: list[str] = []
    enabled = settings.terminal_enrollment_enabled is True
    if not enabled:
        blockers.append("Server-side terminal enrollment is disabled.")

    base_url: str | None = None
    try:
        base_url = normalize_base_url(settings.terminal_enrollment_base_url)
    except EnrollmentPolicyError:
        blockers.append("No exact HTTPS enrollment origin is configured.")

    key_id = settings.terminal_enrollment_signing_key_id
    if not isinstance(key_id, str) or KEY_ID_RE.fullmatch(key_id) is None:
        key_id = None
        blockers.append("No valid online enrollment key id is configured.")

    try:
        ttl = int(settings.terminal_enrollment_ticket_ttl_seconds)
    except (TypeError, ValueError):
        ttl = 0
    if type(settings.terminal_enrollment_ticket_ttl_seconds) is not int or not 1 <= ttl <= 600:
        blockers.append("Enrollment ticket lifetime must be between 1 and 600 seconds.")

    signing_key = None
    public_key_sha256 = None
    try:
        signing_key, public_key_sha256 = _load_online_identity(
            settings.terminal_enrollment_private_key_path
        )
        if SHA256_RE.fullmatch(public_key_sha256) is None:
            raise EnrollmentPolicyError("terminal enrollment public key hash is invalid")
    except Exception:
        blockers.append("The protected online enrollment key is unavailable.")

    try:
        allowlist = parse_qualified_releases(
            settings.terminal_enrollment_qualified_releases
        )
    except EnrollmentPolicyError:
        allowlist = {}
        blockers.append("The release/model enrollment qualification allowlist is invalid.")
    if not allowlist:
        blockers.append("No firmware release/model has completed physical enrollment qualification.")

    minimum_generation = settings.terminal_firmware_minimum_catalog_generation
    if type(minimum_generation) is not int or minimum_generation <= 0:
        blockers.append("No minimum signed firmware catalog generation is pinned.")

    catalog: dict[str, Any] = {"releases": []}
    try:
        catalog = build_firmware_catalog(
            settings.terminal_firmware_storage_path,
            settings.terminal_firmware_trusted_signing_keys,
            False,
            minimum_generation,
        )
    except (FirmwareArtifactError, OSError):
        blockers.append("The approved signed firmware catalog is unavailable.")

    qualified: list[QualifiedEnrollmentRelease] = []
    for release in catalog.get("releases", []):
        release_id = release.get("release_id")
        allowed_models = allowlist.get(release_id)
        if not allowed_models:
            continue
        serial = release.get("serial_enrollment")
        if (
            release.get("manifest_schema_version") != 2
            or not isinstance(serial, dict)
            or serial.get("protocol") != "RET1"
            or serial.get("enabled") is not True
            or serial.get("trust_key_id") != key_id
            or serial.get("public_key_sha256") != public_key_sha256
            or serial.get("identity_strength") != "physical_cable_only"
            or serial.get("attestation") is not False
        ):
            continue
        models_by_name = {
            model.get("model"): model
            for model in release.get("models", [])
            if isinstance(model, dict)
        }
        accepted_models = tuple(
            model_name
            for model_name in allowed_models
            if (
                model_name in models_by_name
                and models_by_name[model_name].get("model") == model_name
            )
        )
        if not accepted_models:
            continue
        qualified.append(
            QualifiedEnrollmentRelease(
                release_id=release_id,
                firmware_version=release["firmware_version"],
                git_sha=release["git_sha"],
                trust_key_id=serial["trust_key_id"],
                public_key_sha256=serial["public_key_sha256"],
                models=accepted_models,
            )
        )
    if allowlist and not qualified:
        blockers.append(
            "No allowlisted signed release matches the online key and physical model evidence."
        )

    blockers = list(dict.fromkeys(blockers))
    state = "ready" if enabled and not blockers and qualified else "locked"
    return EnrollmentPolicy(
        enabled=enabled,
        state=state,
        base_url=base_url,
        signing_key_id=key_id,
        signing_key=signing_key,
        public_key_sha256=public_key_sha256,
        ticket_ttl_seconds=ttl if 1 <= ttl <= 600 else 300,
        releases=tuple(qualified),
        blockers=tuple(blockers),
    )
