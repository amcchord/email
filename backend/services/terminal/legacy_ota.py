"""Signed, per-device OTA channel for legacy ``/config.json`` terminals."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import stat
from contextlib import suppress
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from backend.services.terminal.firmware_artifacts import (
    FirmwareArtifactError,
    _read_regular_file,
)
from backend.services.terminal.ota_protocol import (
    AttemptState,
    OtaProtocolError,
    TransitionDecision,
    classify_transition,
    encode_event,
    event_fingerprint,
    parse_event,
)

MAX_MANIFEST_BYTES = 2048
MAX_APPLICATION_BYTES = 0x300000
MAX_POINTER_BYTES = 512
MAX_EVENT_STATE_BYTES = 2048
RELEASE_RE = re.compile(r"^[0-9a-f]{64}$")
VERSION_RE = re.compile(r"^[A-Za-z0-9._+-]{1,48}$")
MANIFEST_FIELDS = {
    "schema_version",
    "model",
    "layout",
    "version",
    "firmware_size",
    "firmware_sha256",
}
LEGACY_OTA_PUBLIC_KEY = Ed25519PublicKey.from_public_bytes(
    bytes.fromhex("bcb57f796b0c22ea4a6f56fc8c30d5c0d99dcf75609c10bd49360749f6ce476a")
)


class LegacyOtaUnavailable(RuntimeError):
    """The optional legacy OTA channel is absent or internally inconsistent."""


@dataclass(frozen=True)
class LegacyOtaRelease:
    model: str
    version: str
    release_id: str
    manifest: bytes
    signature: bytes
    application: bytes


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise LegacyOtaUnavailable("duplicate JSON member")
        result[key] = value
    return result


def _canonical_device_id(raw: str) -> str:
    try:
        canonical = str(UUID(str(raw)))
    except (TypeError, ValueError) as exc:
        raise LegacyOtaUnavailable("legacy OTA device identity is invalid") from exc
    if canonical != raw:
        raise LegacyOtaUnavailable("legacy OTA device identity is invalid")
    return canonical


def _read_bounded(
    storage_path: str,
    relative: str,
    maximum: int,
    *,
    exact: int | None = None,
) -> bytes:
    try:
        raw = _read_regular_file(Path(storage_path).absolute(), relative, maximum)
    except FirmwareArtifactError as exc:
        raise LegacyOtaUnavailable("legacy OTA artifact is unavailable") from exc
    if not raw or len(raw) > maximum or (exact is not None and len(raw) != exact):
        raise LegacyOtaUnavailable("legacy OTA artifact length is invalid")
    return raw


def _release_relative(model: str, release_id: str) -> str:
    if model not in {"E1001", "E1002"} or RELEASE_RE.fullmatch(release_id) is None:
        raise LegacyOtaUnavailable("legacy OTA identity is invalid")
    return f"legacy/{model}/{release_id}"


@lru_cache(maxsize=16)
def load_release(storage_path: str, model: str, release_id: str) -> LegacyOtaRelease:
    relative = _release_relative(model, release_id)
    manifest = _read_bounded(
        storage_path, f"{relative}/manifest.json", MAX_MANIFEST_BYTES
    )
    signature = _read_bounded(
        storage_path, f"{relative}/manifest.sig", 64, exact=64
    )
    application = _read_bounded(
        storage_path, f"{relative}/application.bin", MAX_APPLICATION_BYTES
    )
    if hashlib.sha256(manifest).hexdigest() != release_id:
        raise LegacyOtaUnavailable("legacy OTA manifest address is invalid")
    try:
        LEGACY_OTA_PUBLIC_KEY.verify(signature, manifest)
    except InvalidSignature as exc:
        raise LegacyOtaUnavailable("legacy OTA manifest signature is invalid") from exc
    try:
        value = json.loads(manifest, object_pairs_hook=_strict_object)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LegacyOtaUnavailable("legacy OTA manifest JSON is invalid") from exc
    if not isinstance(value, dict) or set(value) != MANIFEST_FIELDS:
        raise LegacyOtaUnavailable("legacy OTA manifest fields are invalid")
    if (
        type(value["schema_version"]) is not int
        or value["schema_version"] != 1
        or value["model"] != model
        or value["layout"] != "ab-v1"
        or not isinstance(value["version"], str)
        or VERSION_RE.fullmatch(value["version"]) is None
        or type(value["firmware_size"]) is not int
        or value["firmware_size"] != len(application)
        or not isinstance(value["firmware_sha256"], str)
        or RELEASE_RE.fullmatch(value["firmware_sha256"]) is None
        or hashlib.sha256(application).hexdigest() != value["firmware_sha256"]
    ):
        raise LegacyOtaUnavailable("legacy OTA manifest does not match its payload")
    return LegacyOtaRelease(
        model=model,
        version=value["version"],
        release_id=release_id,
        manifest=manifest,
        signature=signature,
        application=application,
    )


def load_current_release(
    storage_path: str, model: str, device_public_id: str
) -> LegacyOtaRelease | None:
    if model not in {"E1001", "E1002"}:
        return None
    device_id = _canonical_device_id(device_public_id)
    relative = f"legacy/{model}/devices/{device_id}/current.json"
    pointer = Path(storage_path).absolute() / relative
    try:
        metadata = pointer.lstat()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise LegacyOtaUnavailable("legacy OTA pointer is unavailable") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise LegacyOtaUnavailable("legacy OTA pointer is unsafe")
    raw = _read_bounded(storage_path, relative, MAX_POINTER_BYTES)
    try:
        value = json.loads(raw, object_pairs_hook=_strict_object)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LegacyOtaUnavailable("legacy OTA pointer is invalid") from exc
    if (
        not isinstance(value, dict)
        or set(value) != {"schema_version", "release_id"}
        or type(value["schema_version"]) is not int
        or value["schema_version"] != 1
        or not isinstance(value["release_id"], str)
        or RELEASE_RE.fullmatch(value["release_id"]) is None
    ):
        raise LegacyOtaUnavailable("legacy OTA pointer fields are invalid")
    return load_release(storage_path, model, value["release_id"])


def offer_record(
    release: LegacyOtaRelease,
    *,
    schedule_code: str,
    device_public_id: str,
    running_version: str,
) -> dict[str, Any] | None:
    if running_version == release.version:
        return None
    device_id = _canonical_device_id(device_public_id)
    identity = f"{device_id}:{release.release_id}"
    scope = f"/terminal/{schedule_code}"
    return {
        "schema_version": 1,
        "offer_id": str(uuid5(NAMESPACE_URL, f"legacy-ota-offer:{identity}")),
        "attempt_id": str(uuid5(NAMESPACE_URL, f"legacy-ota-attempt:{identity}")),
        "release_id": release.release_id,
        "version": release.version,
        "manifest_url": f"{scope}/firmware/{release.release_id}/manifest.json",
        "signature_url": f"{scope}/firmware/{release.release_id}/manifest.sig",
        "application_url": f"{scope}/firmware/{release.release_id}/application.bin",
        "event_url": f"{scope}/firmware/events",
        "required": False,
    }


def artifact_bytes(release: LegacyOtaRelease, kind: str) -> tuple[bytes, str]:
    if kind == "manifest.json":
        return release.manifest, "application/json"
    if kind == "manifest.sig":
        return release.signature, "application/octet-stream"
    if kind == "application.bin":
        return release.application, "application/octet-stream"
    raise LegacyOtaUnavailable("legacy OTA artifact kind is invalid")


def _event_root(storage_path: str, device_id: str, release_id: str) -> Path:
    root = Path(storage_path).absolute() / "legacy-events" / device_id / release_id
    root.mkdir(mode=0o750, parents=True, exist_ok=True)
    for parent in (root.parent.parent, root.parent, root):
        mode = parent.lstat().st_mode
        if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
            raise LegacyOtaUnavailable("legacy OTA event directory is unsafe")
    return root


def record_event(
    storage_path: str,
    release: LegacyOtaRelease,
    *,
    schedule_code: str,
    device_public_id: str,
    raw: bytes,
) -> tuple[str, bool]:
    device_id = _canonical_device_id(device_public_id)
    try:
        event = parse_event(raw)
    except OtaProtocolError as exc:
        raise LegacyOtaUnavailable("legacy OTA event is invalid") from exc
    expected = offer_record(
        release,
        schedule_code=schedule_code,
        device_public_id=device_id,
        running_version="",
    )
    if (
        expected is None
        or event.attempt_id != expected["attempt_id"]
        or event.offer_id != expected["offer_id"]
        or event.release_id != release.release_id
    ):
        raise LegacyOtaUnavailable("legacy OTA event binding is invalid")
    canonical = encode_event(event)
    fingerprint = event_fingerprint(event)
    root = _event_root(storage_path, device_id, release.release_id)
    lock_fd = os.open(root / ".lock", os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        event_path = root / f"{event.event_id}.json"
        if event_path.exists():
            if event_path.is_symlink() or event_path.read_bytes() != canonical:
                raise LegacyOtaUnavailable("legacy OTA event replay conflicts")
            return event.state.value, True
        state_path = root / "state.json"
        if state_path.exists():
            relative = state_path.relative_to(Path(storage_path).absolute()).as_posix()
            state_raw = _read_bounded(storage_path, relative, MAX_EVENT_STATE_BYTES)
            try:
                state_value = json.loads(state_raw, object_pairs_hook=_strict_object)
                current = AttemptState(state_value["state"])
                last_sequence = int(state_value["sequence"])
            except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                raise LegacyOtaUnavailable("legacy OTA event state is invalid") from exc
        else:
            current = AttemptState.OFFERED
            last_sequence = 0
        decision = classify_transition(current, last_sequence, event.state, event.sequence)
        if decision is TransitionDecision.REJECT:
            raise LegacyOtaUnavailable("legacy OTA event transition is invalid")
        with event_path.open("xb") as stream:
            stream.write(canonical)
        os.chmod(event_path, 0o640)
        state = json.dumps(
            {
                "schema_version": 1,
                "state": event.state.value,
                "sequence": event.sequence,
                "event_id": event.event_id,
                "payload_sha256": fingerprint,
                "has_gap": decision is TransitionDecision.ADVANCE_WITH_GAP,
            },
            separators=(",", ":"),
            sort_keys=True,
        ).encode("ascii")
        temporary = root / f".state.tmp-{os.getpid()}"
        with temporary.open("xb") as stream:
            stream.write(state)
        os.chmod(temporary, 0o640)
        temporary.replace(state_path)
        return event.state.value, False
    except OSError as exc:
        raise LegacyOtaUnavailable("legacy OTA event could not be retained") from exc
    finally:
        with suppress(OSError):
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
        with suppress(OSError):
            os.close(lock_fd)
