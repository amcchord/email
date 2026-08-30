"""Fail-closed policy core for signed E1001/E1002 A/B OTA releases.

This module deliberately has no filesystem, database, or HTTP dependencies.
Callers supply already located bytes plus the parent bundle evidence produced
by the release gateway. That keeps the exact-byte OTA descriptor trust boundary
small and lets the device and server verify the same content address.

An otherwise valid release is never offerable unless the operator enables OTA,
the exact descriptor/parent/model/revision tuple is HIL allowlisted, the signed
parent release explicitly permits OTA, the catalog generation is pinned, and a
durable idempotent event store is available.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Iterable

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


OTA_SCHEMA_VERSION = 1
OTA_PROTOCOL = "OTA1"
OTA_LAYOUT = "ab-v1"
OTA_SLOT_SIZE = 0x300000
MAX_DESCRIPTOR_BYTES = 2048
MAX_QUALIFIED_RELEASES = 8
ALLOWED_MODELS = ("E1001", "E1002")

SHA256_RE = re.compile(r"[0-9a-f]{64}")
KEY_ID_RE = re.compile(r"[A-Za-z0-9._-]{1,64}")
VERSION_RE = re.compile(r"[A-Za-z0-9._+-]{1,48}")
HARDWARE_REVISION_RE = re.compile(r"[A-Za-z0-9._-]{1,64}")
DESCRIPTOR_FIELDS = frozenset(
    {
        "schema_version",
        "model",
        "layout",
        "version",
        "firmware_size",
        "firmware_sha256",
    }
)
QUALIFICATION_FIELDS = frozenset(
    {
        "parent_release_id",
        "model",
        "signing_key_id",
        "hardware_revisions",
    }
)


class OtaPolicyError(RuntimeError):
    """OTA evidence or operator policy is invalid."""


@dataclass(frozen=True)
class ParentBundleLink:
    """Verified parent release facts that the OTA descriptor must match."""

    release_id: str
    signing_key_id: str
    catalog_generation: int
    model: str
    firmware_version: str
    partition_layout: str
    application_size: int
    application_sha256: str
    hardware_revisions: tuple[str, ...]
    release_ota_eligible: bool
    model_ota_eligible: bool


@dataclass(frozen=True)
class OtaQualification:
    """Exact operator-authored HIL approval for one OTA content address."""

    release_id: str
    parent_release_id: str
    model: str
    signing_key_id: str
    hardware_revisions: tuple[str, ...]


@dataclass(frozen=True)
class VerifiedOtaRelease:
    """Cryptographically verified OTA descriptor linked to one parent bundle."""

    release_id: str
    signing_key_id: str
    model: str
    layout: str
    version: str
    firmware_size: int
    firmware_sha256: str
    manifest_bytes: bytes
    signature_bytes: bytes
    parent: ParentBundleLink

    def as_public_record(self) -> dict[str, Any]:
        return {
            "release_id": self.release_id,
            "parent_release_id": self.parent.release_id,
            "signing_key_id": self.signing_key_id,
            "model": self.model,
            "layout": self.layout,
            "version": self.version,
            "firmware_size": self.firmware_size,
            "firmware_sha256": self.firmware_sha256,
            "hardware_revisions": list(self.parent.hardware_revisions),
        }


@dataclass(frozen=True)
class OtaPolicy:
    """Effective OTA capability state for a server process."""

    enabled: bool
    state: str
    event_persistence_ready: bool
    releases: tuple[VerifiedOtaRelease, ...]
    blockers: tuple[str, ...]

    @property
    def effective_offer_enabled(self) -> bool:
        return self.state == "ready" and self.enabled

    def as_capabilities(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "state": self.state,
            "enabled": self.enabled,
            "effective_offer_enabled": self.effective_offer_enabled,
            "protocol": OTA_PROTOCOL,
            "allowed_models": list(ALLOWED_MODELS),
            "event_persistence_ready": self.event_persistence_ready,
            "qualified_releases": [
                release.as_public_record() for release in self.releases
            ],
            "blockers": list(self.blockers),
        }

    def require_ready(self) -> "OtaPolicy":
        if not self.effective_offer_enabled:
            raise OtaPolicyError("Terminal OTA is not available")
        return self


def _strict_json(raw: bytes | str, label: str) -> Any:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise OtaPolicyError(f"{label} contains a duplicate key")
            result[key] = value
        return result

    try:
        text = raw.decode("utf-8") if isinstance(raw, bytes) else raw
        if not isinstance(text, str):
            raise TypeError
        return json.loads(text, object_pairs_hook=reject_duplicates)
    except (TypeError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OtaPolicyError(f"{label} is not valid UTF-8 JSON") from exc


def _valid_revisions(raw: Any) -> tuple[str, ...] | None:
    if (
        not isinstance(raw, list)
        or not raw
        or len(raw) > 16
        or any(type(item) is not str for item in raw)
        or len(set(raw)) != len(raw)
        or any(HARDWARE_REVISION_RE.fullmatch(item) is None for item in raw)
    ):
        return None
    return tuple(raw)


def validate_parent_bundle_link(parent: ParentBundleLink) -> ParentBundleLink:
    """Validate caller-supplied facts before they enter descriptor policy."""

    if not isinstance(parent, ParentBundleLink):
        raise OtaPolicyError("OTA parent bundle link is invalid")
    if type(parent.release_id) is not str or SHA256_RE.fullmatch(parent.release_id) is None:
        raise OtaPolicyError("OTA parent release id is invalid")
    if (
        type(parent.signing_key_id) is not str
        or KEY_ID_RE.fullmatch(parent.signing_key_id) is None
    ):
        raise OtaPolicyError("OTA parent signing key id is invalid")
    if type(parent.catalog_generation) is not int or parent.catalog_generation <= 0:
        raise OtaPolicyError("OTA parent catalog generation is invalid")
    if parent.model not in ALLOWED_MODELS:
        raise OtaPolicyError("OTA parent model is unsupported")
    if (
        type(parent.firmware_version) is not str
        or VERSION_RE.fullmatch(parent.firmware_version) is None
    ):
        raise OtaPolicyError("OTA parent firmware version is invalid")
    if parent.partition_layout != OTA_LAYOUT:
        raise OtaPolicyError("OTA parent partition layout is invalid")
    if (
        type(parent.application_size) is not int
        or not 1 <= parent.application_size <= OTA_SLOT_SIZE
    ):
        raise OtaPolicyError("OTA parent application size is invalid")
    if (
        type(parent.application_sha256) is not str
        or SHA256_RE.fullmatch(parent.application_sha256) is None
    ):
        raise OtaPolicyError("OTA parent application hash is invalid")
    if (
        not isinstance(parent.hardware_revisions, tuple)
        or not parent.hardware_revisions
        or len(parent.hardware_revisions) > 16
        or len(set(parent.hardware_revisions)) != len(parent.hardware_revisions)
        or any(
            type(item) is not str or HARDWARE_REVISION_RE.fullmatch(item) is None
            for item in parent.hardware_revisions
        )
    ):
        raise OtaPolicyError("OTA parent hardware revisions are invalid")
    if type(parent.release_ota_eligible) is not bool:
        raise OtaPolicyError("OTA parent release eligibility is invalid")
    if type(parent.model_ota_eligible) is not bool:
        raise OtaPolicyError("OTA parent model eligibility is invalid")
    return parent


def verify_ota_descriptor(
    manifest_bytes: bytes,
    signature_bytes: bytes,
    *,
    expected_release_id: str,
    signing_key_id: str,
    public_key: Ed25519PublicKey,
    parent: ParentBundleLink,
) -> VerifiedOtaRelease:
    """Verify candidate.4's exact OTA1 bytes and their parent-bundle link."""

    if type(manifest_bytes) is not bytes or not 1 <= len(manifest_bytes) <= MAX_DESCRIPTOR_BYTES:
        raise OtaPolicyError("OTA manifest length is invalid")
    if type(signature_bytes) is not bytes or len(signature_bytes) != 64:
        raise OtaPolicyError("OTA manifest signature is invalid")
    if (
        type(expected_release_id) is not str
        or SHA256_RE.fullmatch(expected_release_id) is None
    ):
        raise OtaPolicyError("OTA release id is invalid")
    if type(signing_key_id) is not str or KEY_ID_RE.fullmatch(signing_key_id) is None:
        raise OtaPolicyError("OTA manifest signing key id is invalid")
    if not isinstance(public_key, Ed25519PublicKey):
        raise OtaPolicyError("OTA manifest public key is invalid")
    parent = validate_parent_bundle_link(parent)
    if signing_key_id != parent.signing_key_id:
        raise OtaPolicyError("OTA signing key does not match the parent bundle")
    try:
        public_key.verify(signature_bytes, manifest_bytes)
    except InvalidSignature as exc:
        raise OtaPolicyError("OTA manifest signature is invalid") from exc

    manifest = _strict_json(manifest_bytes, "OTA manifest")
    if not isinstance(manifest, dict) or set(manifest) != DESCRIPTOR_FIELDS:
        raise OtaPolicyError("OTA manifest fields are invalid")
    if type(manifest["schema_version"]) is not int or manifest["schema_version"] != 1:
        raise OtaPolicyError("OTA manifest schema is unsupported")
    model = manifest["model"]
    if model == "E1004":
        raise OtaPolicyError("E1004 is not OTA eligible")
    if model not in ALLOWED_MODELS:
        raise OtaPolicyError("OTA manifest model is unsupported")
    if manifest["layout"] != OTA_LAYOUT:
        raise OtaPolicyError("OTA manifest layout is invalid")
    version = manifest["version"]
    if type(version) is not str or VERSION_RE.fullmatch(version) is None:
        raise OtaPolicyError("OTA manifest version is invalid")
    firmware_size = manifest["firmware_size"]
    if type(firmware_size) is not int or not 1 <= firmware_size <= OTA_SLOT_SIZE:
        raise OtaPolicyError("OTA manifest firmware size is invalid")
    firmware_sha256 = manifest["firmware_sha256"]
    if type(firmware_sha256) is not str or SHA256_RE.fullmatch(firmware_sha256) is None:
        raise OtaPolicyError("OTA manifest firmware hash is invalid")

    if (
        model != parent.model
        or manifest["layout"] != parent.partition_layout
        or version != parent.firmware_version
        or firmware_size != parent.application_size
        or firmware_sha256 != parent.application_sha256
    ):
        raise OtaPolicyError("OTA manifest does not match the parent bundle")

    computed_release_id = hashlib.sha256(manifest_bytes).hexdigest()
    if computed_release_id != expected_release_id:
        raise OtaPolicyError("OTA manifest digest does not match its release id")

    return VerifiedOtaRelease(
        release_id=computed_release_id,
        signing_key_id=signing_key_id,
        model=model,
        layout=OTA_LAYOUT,
        version=version,
        firmware_size=firmware_size,
        firmware_sha256=firmware_sha256,
        manifest_bytes=manifest_bytes,
        signature_bytes=signature_bytes,
        parent=parent,
    )


def parse_qualified_releases(raw: str) -> dict[str, OtaQualification]:
    """Parse an exact descriptor-to-parent/model/revision HIL allowlist."""

    decoded = _strict_json(raw, "terminal OTA qualification allowlist")
    if not isinstance(decoded, dict) or len(decoded) > MAX_QUALIFIED_RELEASES:
        raise OtaPolicyError("terminal OTA qualification allowlist is invalid")
    result: dict[str, OtaQualification] = {}
    for release_id, item in decoded.items():
        if not isinstance(release_id, str) or SHA256_RE.fullmatch(release_id) is None:
            raise OtaPolicyError("terminal OTA release id is invalid")
        if not isinstance(item, dict) or set(item) != QUALIFICATION_FIELDS:
            raise OtaPolicyError("terminal OTA qualification fields are invalid")
        parent_release_id = item["parent_release_id"]
        model = item["model"]
        signing_key_id = item["signing_key_id"]
        revisions = _valid_revisions(item["hardware_revisions"])
        if (
            type(parent_release_id) is not str
            or SHA256_RE.fullmatch(parent_release_id) is None
        ):
            raise OtaPolicyError("terminal OTA parent release id is invalid")
        if model == "E1004":
            raise OtaPolicyError("E1004 cannot be OTA qualified")
        if model not in ALLOWED_MODELS:
            raise OtaPolicyError("terminal OTA qualification model is unsupported")
        if (
            type(signing_key_id) is not str
            or KEY_ID_RE.fullmatch(signing_key_id) is None
        ):
            raise OtaPolicyError("terminal OTA qualification signing key is invalid")
        if revisions is None:
            raise OtaPolicyError("terminal OTA hardware revisions are invalid")
        result[release_id] = OtaQualification(
            release_id=release_id,
            parent_release_id=parent_release_id,
            model=model,
            signing_key_id=signing_key_id,
            hardware_revisions=revisions,
        )
    return result


def evaluate_ota_policy(
    settings: Any,
    releases: Iterable[VerifiedOtaRelease] = (),
    *,
    event_persistence_ready: bool = False,
) -> OtaPolicy:
    """Compute effective offer state without weakening any independent gate."""

    blockers: list[str] = []
    enabled = getattr(settings, "terminal_ota_enabled", False) is True
    if not enabled:
        blockers.append("Server-side terminal OTA is disabled.")

    try:
        qualifications = parse_qualified_releases(
            getattr(settings, "terminal_ota_qualified_releases", "{}")
        )
    except OtaPolicyError:
        qualifications = {}
        blockers.append("The terminal OTA qualification allowlist is invalid.")
    if not qualifications:
        blockers.append("No OTA release/model has completed physical HIL qualification.")

    minimum_generation = getattr(
        settings, "terminal_firmware_minimum_catalog_generation", 0
    )
    if type(minimum_generation) is not int or minimum_generation <= 0:
        blockers.append("No minimum signed firmware catalog generation is pinned.")

    if type(event_persistence_ready) is not bool or not event_persistence_ready:
        event_persistence_ready = False
        blockers.append("Durable idempotent OTA event persistence is unavailable.")

    candidates = tuple(releases)
    if len(candidates) > MAX_QUALIFIED_RELEASES or any(
        not isinstance(release, VerifiedOtaRelease) for release in candidates
    ):
        candidates = ()
        blockers.append("OTA release evidence is invalid.")

    qualified: list[VerifiedOtaRelease] = []
    seen_release_ids: set[str] = set()
    for release in candidates:
        if release.release_id in seen_release_ids:
            blockers.append("OTA release evidence contains a duplicate release.")
            continue
        seen_release_ids.add(release.release_id)
        qualification = qualifications.get(release.release_id)
        if qualification is None:
            continue
        parent = release.parent
        if (
            qualification.parent_release_id != parent.release_id
            or qualification.model != release.model
            or qualification.signing_key_id != release.signing_key_id
            or not set(qualification.hardware_revisions).issubset(
                parent.hardware_revisions
            )
        ):
            continue
        if (
            not parent.release_ota_eligible
            or not parent.model_ota_eligible
            or parent.catalog_generation < minimum_generation
            or release.model == "E1004"
        ):
            continue
        qualified.append(release)

    if qualifications and not qualified:
        blockers.append(
            "No allowlisted OTA descriptor matches signed parent eligibility and HIL evidence."
        )

    blockers = list(dict.fromkeys(blockers))
    ready = enabled and event_persistence_ready and bool(qualified) and not blockers
    return OtaPolicy(
        enabled=enabled,
        state="ready" if ready else "locked",
        event_persistence_ready=event_persistence_ready,
        releases=tuple(qualified),
        blockers=tuple(blockers),
    )
