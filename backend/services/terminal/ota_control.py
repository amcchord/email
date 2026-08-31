"""Durable OTA control-plane invariants and local release reader.

This module performs no database commits and never stores or logs the raw
device credential. Routers supply locked rows and use these helpers to keep
offer, artifact, and event decisions consistent.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

from backend.models.terminal import TerminalDevice, TerminalOtaAttempt
from backend.services.terminal.firmware_artifacts import (
    MAX_ARTIFACT_BYTES,
    FirmwareArtifactError,
    FirmwareCatalogUnavailable,
    FirmwareReleaseNotFound,
    _read_catalog,
    _read_regular_file,
    _validate_catalog_bundles,
    load_trusted_keys,
)
from backend.services.terminal.ota_policy import (
    BUILD_ID_RE,
    SHA256_RE,
    VERSION_RE,
    OtaPolicyError,
    ParentBundleLink,
    VerifiedOtaRelease,
    verify_ota_descriptor,
)
from backend.services.terminal.ota_protocol import (
    AttemptState,
    OtaEvent,
    OtaOffer,
    TransitionDecision,
    encode_offer,
)

OTA_TELEMETRY_MAX_AGE_DEFAULT = 300
OTA_ATTEMPT_TTL_DEFAULT = 3600
OTA_MIN_BATTERY_PCT_DEFAULT = 80
OTA_MIN_BATTERY_MV_DEFAULT = 4000
OTA_RELEASE_LINK_FIELDS = frozenset({"schema_version", "parent_release_id", "model"})
HARDWARE_REVISION_RE = re.compile(r"[A-Za-z0-9._-]{1,64}")

ACTIVE_ATTEMPT_STATES = frozenset(
    {
        AttemptState.OFFERED.value,
        AttemptState.DOWNLOADING.value,
        AttemptState.STAGED.value,
        AttemptState.BOOTED_PENDING_VALIDATION.value,
    }
)
TERMINAL_ATTEMPT_STATES = frozenset(
    {
        AttemptState.SUCCEEDED.value,
        AttemptState.FAILED.value,
        AttemptState.ROLLED_BACK.value,
        AttemptState.RECOVERY_REQUIRED.value,
        "expired",
        "cancelled",
    }
)


class OtaControlError(RuntimeError):
    """An OTA control-plane decision failed closed."""


class OtaReleaseUnavailable(OtaControlError):
    """No exact verified release evidence is available."""


@dataclass(frozen=True)
class OtaTelemetry:
    firmware_version: str
    build_id: str
    running_partition: str
    boot_count: int
    battery_mv: int
    battery_pct: int
    external_power: bool | None
    observed_at: datetime


@dataclass(frozen=True)
class LoadedOtaRelease:
    release: VerifiedOtaRelease
    application_bytes: bytes
    descriptor_signature_sha256: str
    catalog_generation: int


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _strict_json(raw: bytes, label: str) -> Any:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise OtaReleaseUnavailable(f"{label} contains a duplicate key")
            result[key] = value
        return result

    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=reject_duplicates)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OtaReleaseUnavailable(f"{label} is invalid") from exc


def _bounded_int(raw: str | None, minimum: int, maximum: int) -> int | None:
    if raw is None or not raw.isascii() or not raw.isdigit():
        return None
    value = int(raw)
    return value if minimum <= value <= maximum else None


def parse_ota_telemetry(
    headers: Mapping[str, str], *, now: datetime | None = None
) -> OtaTelemetry:
    """Parse one complete active-credential poll snapshot.

    Missing/invalid direct-power evidence remains unknown. Any malformed
    present value invalidates the whole snapshot rather than being guessed.
    """

    firmware_version = (headers.get("x-fw-version") or "").strip()
    build_id = (headers.get("x-firmware-build-id") or "").strip()
    partition = (headers.get("x-running-partition") or "").strip()
    boot_count = _bounded_int(headers.get("x-boot-count"), 1, 4_294_967_295)
    battery_mv = _bounded_int(headers.get("x-battery-mv"), 2500, 5000)
    battery_pct = _bounded_int(headers.get("x-battery-pct"), 0, 100)
    external_raw = headers.get("x-external-power")
    if external_raw is None:
        external_power = None
    elif external_raw == "1":
        external_power = True
    elif external_raw == "0":
        external_power = False
    else:
        raise OtaControlError("Terminal OTA telemetry is invalid")
    if (
        VERSION_RE.fullmatch(firmware_version) is None
        or BUILD_ID_RE.fullmatch(build_id) is None
        or partition not in {"ota_0", "ota_1"}
        or boot_count is None
        or headers.get("x-battery-valid") != "1"
        or battery_mv is None
        or battery_pct is None
    ):
        raise OtaControlError("Terminal OTA telemetry is invalid")
    observed_at = now or _utcnow()
    if observed_at.tzinfo is None:
        raise OtaControlError("Terminal OTA telemetry time is invalid")
    return OtaTelemetry(
        firmware_version=firmware_version,
        build_id=build_id,
        running_partition=partition,
        boot_count=boot_count,
        battery_mv=battery_mv,
        battery_pct=battery_pct,
        external_power=external_power,
        observed_at=observed_at,
    )


def apply_ota_telemetry(device: TerminalDevice, telemetry: OtaTelemetry) -> None:
    device.last_ota_fw_version = telemetry.firmware_version
    device.last_ota_build_id = telemetry.build_id
    device.last_ota_partition = telemetry.running_partition
    device.last_ota_boot_count = telemetry.boot_count
    device.last_ota_battery_mv = telemetry.battery_mv
    device.last_ota_battery_pct = telemetry.battery_pct
    device.last_ota_external_power = telemetry.external_power
    device.last_ota_telemetry_at = telemetry.observed_at


def telemetry_from_device(device: TerminalDevice) -> OtaTelemetry | None:
    values = (
        device.last_ota_fw_version,
        device.last_ota_build_id,
        device.last_ota_partition,
        device.last_ota_boot_count,
        device.last_ota_battery_mv,
        device.last_ota_battery_pct,
        device.last_ota_telemetry_at,
    )
    if any(value is None for value in values):
        return None
    try:
        return OtaTelemetry(
            firmware_version=device.last_ota_fw_version,
            build_id=device.last_ota_build_id,
            running_partition=device.last_ota_partition,
            boot_count=device.last_ota_boot_count,
            battery_mv=device.last_ota_battery_mv,
            battery_pct=device.last_ota_battery_pct,
            external_power=device.last_ota_external_power,
            observed_at=device.last_ota_telemetry_at,
        )
    except (TypeError, ValueError):
        return None


def require_fresh_power_reserve(
    device: TerminalDevice, settings: Any, *, now: datetime | None = None
) -> OtaTelemetry:
    telemetry = telemetry_from_device(device)
    current = now or _utcnow()
    max_age = getattr(
        settings,
        "terminal_ota_telemetry_max_age_seconds",
        OTA_TELEMETRY_MAX_AGE_DEFAULT,
    )
    minimum_pct = getattr(
        settings, "terminal_ota_min_battery_pct", OTA_MIN_BATTERY_PCT_DEFAULT
    )
    minimum_mv = getattr(
        settings, "terminal_ota_min_battery_mv", OTA_MIN_BATTERY_MV_DEFAULT
    )
    if (
        telemetry is None
        or type(max_age) is not int
        or not 30 <= max_age <= 900
        or type(minimum_pct) is not int
        or not 50 <= minimum_pct <= 100
        or type(minimum_mv) is not int
        or not 3700 <= minimum_mv <= 4300
        or current.tzinfo is None
        or telemetry.observed_at < current - timedelta(seconds=max_age)
        or telemetry.observed_at > current + timedelta(seconds=5)
    ):
        raise OtaControlError("Fresh terminal OTA power evidence is required")
    if telemetry.external_power is not True and (
        telemetry.battery_pct < minimum_pct or telemetry.battery_mv < minimum_mv
    ):
        raise OtaControlError("Terminal battery reserve is insufficient for OTA")
    return telemetry


def rollout_bucket(device_public_id: UUID, release_id: str) -> int:
    if (
        not isinstance(device_public_id, UUID)
        or SHA256_RE.fullmatch(release_id) is None
    ):
        raise OtaControlError("Terminal OTA rollout identity is invalid")
    digest = hashlib.sha256(
        f"terminal-ota1:{device_public_id}:{release_id}".encode("ascii")
    ).digest()
    return int.from_bytes(digest[:8], "big") % 10_000


def require_rollout(
    device_public_id: UUID, release_id: str, settings: Any
) -> tuple[int, int]:
    percentage = getattr(settings, "terminal_ota_rollout_percentage", 0)
    if type(percentage) is not int or not 1 <= percentage <= 100:
        raise OtaControlError("Terminal OTA rollout is closed")
    bucket = rollout_bucket(device_public_id, release_id)
    if bucket >= percentage * 100:
        raise OtaControlError("Terminal is outside the OTA rollout cohort")
    return percentage, bucket


def attempt_expiry(settings: Any, *, now: datetime | None = None) -> datetime:
    ttl = getattr(settings, "terminal_ota_attempt_ttl_seconds", OTA_ATTEMPT_TTL_DEFAULT)
    if type(ttl) is not int or not 300 <= ttl <= 86_400:
        raise OtaControlError("Terminal OTA attempt lifetime is invalid")
    return (now or _utcnow()) + timedelta(seconds=ttl)


def request_fingerprint(
    *, device_id: int, release_id: str, client_request_id: UUID
) -> str:
    raw = {
        "client_request_id": str(client_request_id),
        "device_id": device_id,
        "release_id": release_id,
    }
    return hashlib.sha256(
        json.dumps(raw, sort_keys=True, separators=(",", ":")).encode("ascii")
    ).hexdigest()


def build_offer(
    attempt: TerminalOtaAttempt,
    *,
    public_id: UUID,
    credential_token: str,
) -> OtaOffer:
    scope = f"/terminal/device/{public_id}/{credential_token}"
    release_id = attempt.descriptor_release_id
    offer = OtaOffer(
        schema_version=1,
        offer_id=str(attempt.offer_id),
        attempt_id=str(attempt.attempt_id),
        release_id=release_id,
        version=attempt.target_version,
        manifest_url=f"{scope}/firmware/{release_id}/manifest.json",
        signature_url=f"{scope}/firmware/{release_id}/manifest.sig",
        application_url=f"{scope}/firmware/{release_id}/application.bin",
        event_url=f"{scope}/firmware/events",
        required=False,
    )
    encode_offer(offer)
    return offer


def offer_record(offer: OtaOffer) -> dict[str, Any]:
    return json.loads(encode_offer(offer))


def offer_etag_component(offer: OtaOffer | None) -> str:
    return (
        "absent" if offer is None else hashlib.sha256(encode_offer(offer)).hexdigest()
    )


def validate_event_runtime(attempt: TerminalOtaAttempt, event: OtaEvent) -> None:
    source_identity = (
        attempt.source_version,
        attempt.source_build_id,
        attempt.source_partition,
    )
    target_partition = "ota_1" if attempt.source_partition == "ota_0" else "ota_0"
    target_identity = (
        attempt.target_version,
        attempt.target_build_id,
        target_partition,
    )
    observed = (
        event.running_version,
        event.running_build_id,
        event.running_partition,
    )
    if event.state in {
        AttemptState.DOWNLOADING,
        AttemptState.STAGED,
        AttemptState.FAILED,
    }:
        valid = (
            observed == source_identity
            and event.boot_count >= attempt.source_boot_count
        )
    elif event.state in {
        AttemptState.BOOTED_PENDING_VALIDATION,
        AttemptState.SUCCEEDED,
    }:
        valid = (
            observed == target_identity and event.boot_count > attempt.source_boot_count
        )
    elif event.state is AttemptState.ROLLED_BACK:
        valid = (
            observed == source_identity and event.boot_count > attempt.source_boot_count
        )
    else:
        valid = observed in {source_identity, target_identity} and (
            event.boot_count >= attempt.source_boot_count
        )
    if not valid:
        raise OtaControlError(
            "Terminal OTA runtime identity does not match the attempt"
        )


def transition_kind(decision: TransitionDecision) -> str:
    if decision is TransitionDecision.ADVANCE:
        return "advance"
    if decision is TransitionDecision.ADVANCE_WITH_GAP:
        return "advance_with_gap"
    raise OtaControlError("Terminal OTA event transition is invalid")


def attempt_matches_release(
    attempt: TerminalOtaAttempt, loaded: LoadedOtaRelease
) -> bool:
    release = loaded.release
    return (
        attempt.descriptor_release_id == release.release_id
        and attempt.parent_release_id == release.parent.release_id
        and attempt.signing_key_id == release.signing_key_id
        and attempt.catalog_generation == loaded.catalog_generation
        and attempt.device_model == release.model
        and attempt.hardware_revision in release.parent.hardware_revisions
        and attempt.partition_layout == release.layout
        and attempt.target_version == release.version
        and attempt.target_build_id == release.parent.source_build_id
        and attempt.firmware_size == release.firmware_size
        and attempt.firmware_sha256 == release.firmware_sha256
        and attempt.descriptor_signature_sha256 == loaded.descriptor_signature_sha256
    )


def load_ota_release(
    storage_path: str,
    trusted_keys_raw: str,
    minimum_catalog_generation: int,
    release_id: str,
) -> LoadedOtaRelease:
    """Load one content-addressed descriptor linked to an approved parent.

    OTA sidecars live at ``ota/<descriptor release id>/`` and contain exactly
    ``manifest.json``, ``manifest.sig``, and ``link.json``. Application bytes
    always come from the independently signed parent bundle.
    """

    if SHA256_RE.fullmatch(release_id or "") is None:
        raise OtaReleaseUnavailable("Terminal OTA release is unavailable")
    root = Path(storage_path)
    try:
        trusted_keys = load_trusted_keys(trusted_keys_raw)
        if not trusted_keys:
            raise OtaReleaseUnavailable("Terminal OTA release is unavailable")
        catalog = _read_catalog(root, trusted_keys, minimum_catalog_generation)
        if catalog is None:
            raise OtaReleaseUnavailable("Terminal OTA release is unavailable")
        bundles = _validate_catalog_bundles(root, catalog, trusted_keys)
        relative_root = f"ota/{release_id}"
        sidecar_root = root / relative_root
        entries = {entry.name: entry for entry in os.scandir(sidecar_root)}
        if set(entries) != {"manifest.json", "manifest.sig", "link.json"} or any(
            entry.is_symlink() or not entry.is_file(follow_symlinks=False)
            for entry in entries.values()
        ):
            raise OtaReleaseUnavailable("Terminal OTA release is unavailable")
        manifest = _read_regular_file(root, f"{relative_root}/manifest.json", 2048)
        signature = _read_regular_file(root, f"{relative_root}/manifest.sig", 64)
        link_raw = _read_regular_file(root, f"{relative_root}/link.json", 2048)
        link = _strict_json(link_raw, "terminal OTA release link")
        if (
            not isinstance(link, dict)
            or set(link) != OTA_RELEASE_LINK_FIELDS
            or type(link["schema_version"]) is not int
            or link["schema_version"] != 1
            or SHA256_RE.fullmatch(link.get("parent_release_id", "")) is None
            or link.get("model") not in {"E1001", "E1002"}
        ):
            raise OtaReleaseUnavailable("Terminal OTA release is unavailable")
        bundle = bundles.get(link["parent_release_id"])
        model = bundle.models.get(link["model"]) if bundle is not None else None
        public_key = (
            trusted_keys.get(bundle.signing_key_id) if bundle is not None else None
        )
        if bundle is None or model is None or public_key is None:
            raise OtaReleaseUnavailable("Terminal OTA release is unavailable")
        application = _read_regular_file(
            bundle.payload_root,
            model.artifacts["application"].path,
            MAX_ARTIFACT_BYTES,
        )
        parent = ParentBundleLink(
            release_id=bundle.release_id,
            signing_key_id=bundle.signing_key_id,
            catalog_generation=catalog["generation"],
            model=model.model,
            firmware_version=bundle.firmware_version,
            source_build_id=bundle.git_sha,
            partition_layout=model.partition_layout,
            application_size=model.artifacts["application"].size,
            application_sha256=model.artifacts["application"].sha256,
            hardware_revisions=model.hardware_revisions,
            release_ota_eligible=bundle.ota_eligible,
            model_ota_eligible=model.ota_eligible,
        )
        verified = verify_ota_descriptor(
            manifest,
            signature,
            expected_release_id=release_id,
            signing_key_id=bundle.signing_key_id,
            public_key=public_key,
            parent=parent,
        )
        if (
            len(application) != verified.firmware_size
            or hashlib.sha256(application).hexdigest() != verified.firmware_sha256
        ):
            raise OtaReleaseUnavailable("Terminal OTA release is unavailable")
        return LoadedOtaRelease(
            release=verified,
            application_bytes=application,
            descriptor_signature_sha256=hashlib.sha256(signature).hexdigest(),
            catalog_generation=catalog["generation"],
        )
    except OtaReleaseUnavailable:
        raise
    except (
        FileNotFoundError,
        NotADirectoryError,
        OSError,
        FirmwareArtifactError,
        FirmwareCatalogUnavailable,
        FirmwareReleaseNotFound,
        OtaPolicyError,
    ) as exc:
        raise OtaReleaseUnavailable("Terminal OTA release is unavailable") from exc


def artifact_bytes(loaded: LoadedOtaRelease, kind: str) -> tuple[bytes, str]:
    if kind == "manifest.json":
        return loaded.release.manifest_bytes, "application/json"
    if kind == "manifest.sig":
        return loaded.release.signature_bytes, "application/octet-stream"
    if kind == "application.bin":
        return loaded.application_bytes, "application/octet-stream"
    raise OtaReleaseUnavailable("Terminal OTA artifact is unavailable")
