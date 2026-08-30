"""Fail-closed local firmware catalog and immutable artifact reader.

Production never fetches firmware from GitHub at request time. Operators stage
content-addressed bundles under ``terminal_firmware_storage_path`` and publish a
small catalog atomically. Every request revalidates the detached Ed25519
signature, manifest contract, file list, hashes, partition layout, and browser
qualification before bytes can leave the process.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import re
import stat
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


CATALOG_NAME = "catalog.json"
CATALOG_SIGNATURE_NAME = "catalog.sig"
CATALOG_SCHEMA = 1
CATALOG_RESPONSE_SCHEMA = 2
SUPPORTED_MANIFEST_SCHEMAS = {1, 2}
MAX_CATALOG_BYTES = 256 * 1024
MAX_MANIFEST_BYTES = 512 * 1024
MAX_ARTIFACT_BYTES = 8 * 1024 * 1024
MAX_BUNDLE_BYTES = 64 * 1024 * 1024
SHA256_RE = re.compile(r"[0-9a-f]{64}")
GIT_SHA_RE = re.compile(r"[0-9a-f]{40}")
KEY_ID_RE = re.compile(r"[A-Za-z0-9._-]{1,64}")

FLASH_CONSTRAINTS = {
    "minimum_bytes": 32 * 1024 * 1024,
    "mode": "keep",
    "frequency": "keep",
    "size": "32MB",
    "erase_all": False,
}
FLASH_OFFSETS = {
    "bootloader": 0x0000,
    "partition_table": 0x8000,
    "ota_data_initial": 0xE000,
    "application": 0x10000,
    "factory_recovery": 0x0000,
}
PRESERVE_CONFIG_ROLES = (
    "bootloader",
    "partition_table",
    "ota_data_initial",
    "application",
)
SOURCE_FILENAMES = {
    "bootloader": "bootloader.bin",
    "partition_table": "partitions.bin",
    "ota_data_initial": "boot_app0.bin",
    "application": "firmware.bin",
    "factory_recovery": "firmware.factory.bin",
    "partition_source": "partitions.csv",
}
EXPECTED_ROLES = set(SOURCE_FILENAMES)
MODEL_CONSTRAINTS = {
    "reterminal_e1001": {
        "model": "E1001",
        "panel": "GDEY075T7",
        "resolution": [800, 480],
        "partition_layout": "ab-v1",
        "partition_csv": "partitions/e100x-ab-v1.csv",
    },
    "reterminal_e1002": {
        "model": "E1002",
        "panel": "GDEP073E01",
        "resolution": [800, 480],
        "partition_layout": "ab-v1",
        "partition_csv": "partitions/e100x-ab-v1.csv",
    },
    "reterminal_e1004": {
        "model": "E1004",
        "panel": "GDEP133C02",
        "resolution": [1200, 1600],
        "partition_layout": "single-slot-e1004-v1",
        "partition_csv": "e1004_partitions.csv",
    },
}
PARTITION_LAYOUTS = {
    "reterminal_e1001": (
        ("nvs", "data", "nvs", 0x9000, 0x5000),
        ("otadata", "data", "ota", 0xE000, 0x2000),
        ("ota_0", "app", "ota_0", 0x10000, 0x300000),
        ("spiffs", "data", "spiffs", 0x310000, 0xE0000),
        ("coredump", "data", "coredump", 0x3F0000, 0x10000),
        ("ota_1", "app", "ota_1", 0x400000, 0x300000),
    ),
    "reterminal_e1002": (
        ("nvs", "data", "nvs", 0x9000, 0x5000),
        ("otadata", "data", "ota", 0xE000, 0x2000),
        ("ota_0", "app", "ota_0", 0x10000, 0x300000),
        ("spiffs", "data", "spiffs", 0x310000, 0xE0000),
        ("coredump", "data", "coredump", 0x3F0000, 0x10000),
        ("ota_1", "app", "ota_1", 0x400000, 0x300000),
    ),
    "reterminal_e1004": (
        ("nvs", "data", "nvs", 0x9000, 0x5000),
        ("otadata", "data", "ota", 0xE000, 0x2000),
        ("app0", "app", "ota_0", 0x10000, 0x300000),
        ("spiffs", "data", "spiffs", 0x310000, 0x400000),
        ("coredump", "data", "coredump", 0x710000, 0x10000),
    ),
}
PARTITION_TYPE_IDS = {"app": 0x00, "data": 0x01}
PARTITION_SUBTYPE_IDS = {
    ("data", "ota"): 0x00,
    ("data", "nvs"): 0x02,
    ("data", "coredump"): 0x03,
    ("data", "spiffs"): 0x82,
    ("data", "littlefs"): 0x82,
    ("app", "ota_0"): 0x10,
    ("app", "ota_1"): 0x11,
}


class FirmwareArtifactError(RuntimeError):
    """Base class for safe, user-displayable firmware catalog failures."""


class FirmwareCatalogUnavailable(FirmwareArtifactError):
    pass


class FirmwareReleaseNotFound(FirmwareArtifactError):
    pass


class FirmwareModelNotQualified(FirmwareArtifactError):
    pass


class FirmwareArtifactNotFound(FirmwareArtifactError):
    pass


@dataclass(frozen=True)
class VerifiedArtifact:
    role: str
    path: str
    size: int
    sha256: str
    flash_offset: int | None
    preserves_nvs: bool | None
    preserves_littlefs: bool | None


@dataclass(frozen=True)
class VerifiedModel:
    environment: str
    model: str
    panel: str
    resolution: tuple[int, int]
    partition_layout: str
    hardware_revisions: tuple[str, ...]
    browser_flash_qualified: bool
    panel_qualified: bool
    artifacts: dict[str, VerifiedArtifact]
    protected_ranges: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class VerifiedSerialEnrollment:
    protocol: str
    enabled: bool
    trust_key_id: str | None
    public_key_sha256: str | None
    identity_strength: str
    attestation: bool

    def as_catalog_record(self) -> dict[str, Any]:
        return {
            "protocol": self.protocol,
            "enabled": self.enabled,
            "trust_key_id": self.trust_key_id,
            "public_key_sha256": self.public_key_sha256,
            "identity_strength": self.identity_strength,
            "attestation": self.attestation,
        }


@dataclass(frozen=True)
class VerifiedBundle:
    release_id: str
    signing_key_id: str
    firmware_version: str
    git_sha: str
    source_date_epoch: int
    manifest_schema_version: int
    serial_enrollment: VerifiedSerialEnrollment
    manifest_bytes: bytes
    signature_bytes: bytes
    payload_root: Path
    models: dict[str, VerifiedModel]


LEGACY_SERIAL_ENROLLMENT = VerifiedSerialEnrollment(
    protocol="RET1",
    enabled=False,
    trust_key_id=None,
    public_key_sha256=None,
    identity_strength="physical_cable_only",
    attestation=False,
)


def _strict_json_equal(actual: Any, expected: Any) -> bool:
    if type(actual) is not type(expected):
        return False
    if isinstance(expected, dict):
        return set(actual) == set(expected) and all(
            _strict_json_equal(actual[key], value) for key, value in expected.items()
        )
    if isinstance(expected, list):
        return len(actual) == len(expected) and all(
            _strict_json_equal(left, right)
            for left, right in zip(actual, expected, strict=True)
        )
    return actual == expected


def _validate_manifest_security(
    schema_version: int,
    security: Any,
) -> VerifiedSerialEnrollment:
    base_keys = {"signed", "ota_eligible", "reason"}
    expected_keys = base_keys if schema_version == 1 else base_keys | {"serial_enrollment"}
    if (
        not isinstance(security, dict)
        or set(security) != expected_keys
        or security.get("signed") is not True
        or security.get("ota_eligible") is not False
        or not isinstance(security.get("reason"), str)
    ):
        raise FirmwareArtifactError("firmware security state is not browser-installable")
    if schema_version == 1:
        return LEGACY_SERIAL_ENROLLMENT

    claim = security["serial_enrollment"]
    expected_claim_keys = {
        "protocol",
        "enabled",
        "trust_key_id",
        "public_key_sha256",
        "identity_strength",
        "attestation",
    }
    if (
        not isinstance(claim, dict)
        or set(claim) != expected_claim_keys
        or claim.get("protocol") != "RET1"
        or type(claim.get("enabled")) is not bool
        or claim.get("identity_strength") != "physical_cable_only"
        or claim.get("attestation") is not False
    ):
        raise FirmwareArtifactError("firmware serial enrollment state is invalid")

    enabled = claim["enabled"]
    key_id = claim["trust_key_id"]
    public_key_sha256 = claim["public_key_sha256"]
    if enabled:
        if (
            not isinstance(key_id, str)
            or KEY_ID_RE.fullmatch(key_id) is None
            or not isinstance(public_key_sha256, str)
            or SHA256_RE.fullmatch(public_key_sha256) is None
        ):
            raise FirmwareArtifactError("firmware serial enrollment trust key is invalid")
    elif key_id is not None or public_key_sha256 is not None:
        raise FirmwareArtifactError("disabled serial enrollment declares trust material")

    return VerifiedSerialEnrollment(
        protocol="RET1",
        enabled=enabled,
        trust_key_id=key_id,
        public_key_sha256=public_key_sha256,
        identity_strength="physical_cable_only",
        attestation=False,
    )


def _read_json_bytes(raw: bytes, label: str) -> Any:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise FirmwareArtifactError(f"{label} has duplicate key: {key}")
            result[key] = value
        return result

    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=reject_duplicates)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FirmwareArtifactError(f"{label} is not valid UTF-8 JSON") from exc


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _decode_base64url(raw: str, label: str) -> bytes:
    if not isinstance(raw, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", raw):
        raise FirmwareCatalogUnavailable(f"{label} is not unpadded base64url")
    try:
        decoded = base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))
    except (ValueError, binascii.Error) as exc:
        raise FirmwareCatalogUnavailable(f"{label} is invalid base64url") from exc
    if base64.urlsafe_b64encode(decoded).rstrip(b"=").decode("ascii") != raw:
        raise FirmwareCatalogUnavailable(f"{label} is not canonical base64url")
    return decoded


def load_trusted_keys(raw: str) -> dict[str, Ed25519PublicKey]:
    try:
        decoded = _read_json_bytes(raw.encode("utf-8"), "trusted signing keys")
    except FirmwareArtifactError as exc:
        raise FirmwareCatalogUnavailable(str(exc)) from exc
    if not isinstance(decoded, dict):
        raise FirmwareCatalogUnavailable("trusted signing keys must be an object")
    keys: dict[str, Ed25519PublicKey] = {}
    for key_id, encoded_key in decoded.items():
        if not isinstance(key_id, str) or KEY_ID_RE.fullmatch(key_id) is None:
            raise FirmwareCatalogUnavailable("trusted signing key id is invalid")
        key_bytes = _decode_base64url(encoded_key, f"trusted key {key_id}")
        if len(key_bytes) != 32:
            raise FirmwareCatalogUnavailable(f"trusted key {key_id} is not 32 bytes")
        keys[key_id] = Ed25519PublicKey.from_public_bytes(key_bytes)
    return keys


def _assert_directory(path: Path, label: str) -> None:
    try:
        mode = path.lstat().st_mode
    except OSError as exc:
        raise FirmwareCatalogUnavailable(f"{label} is missing or unavailable") from exc
    if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
        raise FirmwareCatalogUnavailable(f"{label} must be a real directory")


def _safe_relative_path(raw: str) -> PurePosixPath:
    if not isinstance(raw, str) or not raw or "\\" in raw:
        raise FirmwareArtifactError("artifact path is invalid")
    relative = PurePosixPath(raw)
    if relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
        raise FirmwareArtifactError("artifact path is not a safe relative path")
    return relative


def _directory_open_flags() -> int:
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    return flags


def _open_child_directory(parent_descriptor: int, name: str, label: str) -> int:
    descriptor: int | None = None
    try:
        before = os.stat(name, dir_fd=parent_descriptor, follow_symlinks=False)
        if stat.S_ISLNK(before.st_mode) or not stat.S_ISDIR(before.st_mode):
            raise FirmwareArtifactError(f"artifact parent is unsafe: {label}")
        descriptor = os.open(
            name,
            _directory_open_flags(),
            dir_fd=parent_descriptor,
        )
        after = os.fstat(descriptor)
    except OSError as exc:
        if descriptor is not None:
            with suppress(OSError):
                os.close(descriptor)
        raise FirmwareArtifactError(f"artifact parent is missing or unsafe: {label}") from exc
    if (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino):
        with suppress(OSError):
            os.close(descriptor)
        raise FirmwareArtifactError(f"artifact parent changed while opening: {label}")
    return descriptor


def _open_directory_descriptor(path: Path, label: str) -> int:
    absolute = path.absolute()
    try:
        descriptor = os.open(os.sep, _directory_open_flags())
    except OSError as exc:
        raise FirmwareArtifactError(f"artifact root is unavailable: {label}") from exc
    try:
        for part in absolute.parts[1:]:
            next_descriptor = _open_child_directory(descriptor, part, label)
            with suppress(OSError):
                os.close(descriptor)
            descriptor = next_descriptor
        return descriptor
    except Exception:
        with suppress(OSError):
            os.close(descriptor)
        raise


def _read_regular_file(root: Path, relative_raw: str, max_bytes: int) -> bytes:
    relative = _safe_relative_path(relative_raw)
    directory_descriptor = _open_directory_descriptor(root, relative_raw)
    descriptor: int | None = None
    try:
        for part in relative.parts[:-1]:
            next_descriptor = _open_child_directory(
                directory_descriptor,
                part,
                relative_raw,
            )
            with suppress(OSError):
                os.close(directory_descriptor)
            directory_descriptor = next_descriptor
        filename = relative.parts[-1]
        try:
            before = os.stat(
                filename,
                dir_fd=directory_descriptor,
                follow_symlinks=False,
            )
            if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
                raise FirmwareArtifactError(f"artifact is missing or unsafe: {relative_raw}")
            flags = os.O_RDONLY
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            if hasattr(os, "O_CLOEXEC"):
                flags |= os.O_CLOEXEC
            if hasattr(os, "O_NONBLOCK"):
                flags |= os.O_NONBLOCK
            descriptor = os.open(filename, flags, dir_fd=directory_descriptor)
        except OSError as exc:
            raise FirmwareArtifactError(
                f"artifact is missing or unsafe: {relative_raw}"
            ) from exc
        metadata = os.fstat(descriptor)
        if (before.st_dev, before.st_ino) != (metadata.st_dev, metadata.st_ino):
            raise FirmwareArtifactError(f"artifact changed while opening: {relative_raw}")
        if not stat.S_ISREG(metadata.st_mode):
            raise FirmwareArtifactError(f"artifact is not a regular file: {relative_raw}")
        if metadata.st_size < 0 or metadata.st_size > max_bytes:
            raise FirmwareArtifactError(f"artifact size is unsafe: {relative_raw}")
        chunks: list[bytes] = []
        remaining = metadata.st_size
        while remaining:
            chunk = os.read(descriptor, min(1024 * 1024, remaining))
            if not chunk:
                raise FirmwareArtifactError(f"artifact changed while reading: {relative_raw}")
            chunks.append(chunk)
            remaining -= len(chunk)
        if os.read(descriptor, 1):
            raise FirmwareArtifactError(f"artifact grew while reading: {relative_raw}")
        return b"".join(chunks)
    except OSError as exc:
        raise FirmwareArtifactError(
            f"artifact could not be read safely: {relative_raw}"
        ) from exc
    finally:
        if descriptor is not None:
            with suppress(OSError):
                os.close(descriptor)
        with suppress(OSError):
            os.close(directory_descriptor)


def _catalog_path(root: Path) -> Path:
    return root / CATALOG_NAME


def _read_catalog(
    root: Path,
    trusted_keys: dict[str, Ed25519PublicKey],
    minimum_generation: int,
) -> dict[str, Any] | None:
    if not root.exists():
        return None
    _assert_directory(root, "firmware storage directory")
    path = _catalog_path(root)
    if not path.exists():
        if path.is_symlink():
            raise FirmwareCatalogUnavailable("firmware catalog path is unsafe")
        return None
    raw = _read_regular_file(root, CATALOG_NAME, MAX_CATALOG_BYTES)
    catalog = _read_json_bytes(raw, "firmware catalog")
    if not isinstance(catalog, dict) or set(catalog) != {
        "schema_version",
        "generation",
        "signing_key_id",
        "releases",
    }:
        raise FirmwareCatalogUnavailable("firmware catalog schema is invalid")
    if type(catalog["schema_version"]) is not int or catalog["schema_version"] != 1:
        raise FirmwareCatalogUnavailable("firmware catalog version is unsupported")
    if (
        type(minimum_generation) is not int
        or minimum_generation < 0
        or type(catalog["generation"]) is not int
        or catalog["generation"] <= 0
        or catalog["generation"] < minimum_generation
    ):
        raise FirmwareCatalogUnavailable("firmware catalog generation is not approved")
    key_id = catalog["signing_key_id"]
    if not isinstance(key_id, str) or KEY_ID_RE.fullmatch(key_id) is None:
        raise FirmwareCatalogUnavailable("firmware catalog signing key is invalid")
    public_key = trusted_keys.get(key_id)
    if public_key is None:
        raise FirmwareCatalogUnavailable("firmware catalog signing key is not trusted")
    try:
        signature = _read_regular_file(root, CATALOG_SIGNATURE_NAME, 64)
    except FirmwareArtifactError as exc:
        raise FirmwareCatalogUnavailable("firmware catalog signature is unavailable") from exc
    if len(signature) != 64:
        raise FirmwareCatalogUnavailable("firmware catalog signature is invalid")
    try:
        public_key.verify(signature, raw)
    except InvalidSignature as exc:
        raise FirmwareCatalogUnavailable("firmware catalog signature is invalid") from exc
    releases = catalog["releases"]
    if not isinstance(releases, list) or len(releases) > 1:
        raise FirmwareCatalogUnavailable("firmware catalog releases are invalid")
    seen: set[str] = set()
    for entry in releases:
        if not isinstance(entry, dict) or set(entry) != {
            "manifest_sha256",
            "state",
            "signing_key_id",
            "signature_sha256",
        }:
            raise FirmwareCatalogUnavailable("firmware catalog release entry is invalid")
        release_id = entry["manifest_sha256"]
        if not isinstance(release_id, str) or SHA256_RE.fullmatch(release_id) is None:
            raise FirmwareCatalogUnavailable("firmware catalog release id is invalid")
        if release_id in seen:
            raise FirmwareCatalogUnavailable("firmware catalog has duplicate release")
        seen.add(release_id)
        if entry["state"] != "approved":
            raise FirmwareCatalogUnavailable("firmware catalog state is unsupported")
        if not isinstance(entry["signing_key_id"], str) or KEY_ID_RE.fullmatch(
            entry["signing_key_id"]
        ) is None:
            raise FirmwareCatalogUnavailable("firmware catalog signing key is invalid")
        if not isinstance(entry["signature_sha256"], str) or SHA256_RE.fullmatch(
            entry["signature_sha256"]
        ) is None:
            raise FirmwareCatalogUnavailable("firmware catalog signature hash is invalid")
    return catalog


def _parse_partition_csv(raw: bytes) -> list[dict[str, Any]]:
    try:
        lines = raw.decode("utf-8").splitlines()
    except UnicodeDecodeError as exc:
        raise FirmwareArtifactError("partition source is not UTF-8") from exc
    entries: list[dict[str, Any]] = []
    names: set[str] = set()
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        fields = [field.strip() for field in stripped.split(",")]
        if len(fields) not in {5, 6}:
            raise FirmwareArtifactError("partition source row is invalid")
        name, kind, subtype, raw_offset, raw_size = fields[:5]
        flags = fields[5] if len(fields) == 6 else ""
        if flags:
            raise FirmwareArtifactError("partition source flags are unsupported")
        if not name or name in names:
            raise FirmwareArtifactError("partition source has duplicate name")
        try:
            offset = int(raw_offset, 0)
            size = int(raw_size, 0)
        except ValueError as exc:
            raise FirmwareArtifactError("partition source needs explicit bounds") from exc
        if offset < 0 or size <= 0:
            raise FirmwareArtifactError("partition source bounds are invalid")
        names.add(name)
        entries.append(
            {
                "name": name,
                "type": kind,
                "subtype": subtype,
                "offset": offset,
                "size": size,
                "flags": flags,
            }
        )
    return entries


def _assert_partition_binary(raw: bytes, entries: list[dict[str, Any]]) -> None:
    if len(raw) != 0xC00:
        raise FirmwareArtifactError("partition binary length is not canonical")
    actual: list[dict[str, Any]] = []
    entries_end = len(entries) * 32
    for offset in range(0, entries_end, 32):
        record = raw[offset : offset + 32]
        if record[:2] != b"\xaa\x50":
            raise FirmwareArtifactError("partition binary entry magic is invalid")
        try:
            label = record[12:28].split(b"\0", 1)[0].decode("ascii")
        except UnicodeDecodeError as exc:
            raise FirmwareArtifactError("partition binary label is invalid") from exc
        actual.append(
            {
                "name": label,
                "label_bytes": record[12:28],
                "type_id": record[2],
                "subtype_id": record[3],
                "offset": int.from_bytes(record[4:8], "little"),
                "size": int.from_bytes(record[8:12], "little"),
                "flags": int.from_bytes(record[28:32], "little"),
            }
        )
    for source, binary in zip(entries, actual, strict=True):
        expected_type = PARTITION_TYPE_IDS.get(source["type"])
        expected_subtype = PARTITION_SUBTYPE_IDS.get((source["type"], source["subtype"]))
        expected = {
            "name": source["name"],
            "label_bytes": source["name"].encode("ascii").ljust(16, b"\0"),
            "type_id": expected_type,
            "subtype_id": expected_subtype,
            "offset": source["offset"],
            "size": source["size"],
            "flags": 0,
        }
        if expected_type is None or expected_subtype is None or binary != expected:
            raise FirmwareArtifactError("partition binary does not match source")
    checksum_record = raw[entries_end : entries_end + 32]
    checksum_prefix = b"\xeb\xeb" + b"\xff" * 14
    digest = hashlib.md5(raw[:entries_end], usedforsecurity=False).digest()
    if checksum_record != checksum_prefix + digest:
        raise FirmwareArtifactError("partition binary checksum is invalid")
    if raw[entries_end + 32 :] != b"\xff" * (0xC00 - entries_end - 32):
        raise FirmwareArtifactError("partition binary padding is invalid")


def _artifact_from_item(item: Any, environment: str) -> VerifiedArtifact:
    if not isinstance(item, dict):
        raise FirmwareArtifactError("manifest artifact entry is invalid")
    role = item.get("role")
    if role not in EXPECTED_ROLES:
        raise FirmwareArtifactError("manifest artifact role is invalid")
    partition_source = role == "partition_source"
    expected_keys = {"path", "role", "flash_offset", "size", "sha256"}
    if not partition_source:
        expected_keys |= {"preserves_nvs", "preserves_littlefs"}
    if set(item) != expected_keys:
        raise FirmwareArtifactError("manifest artifact fields are invalid")
    expected_path = f"{environment}/{SOURCE_FILENAMES[role]}"
    if item["path"] != expected_path:
        raise FirmwareArtifactError("manifest artifact path is not canonical")
    size = item["size"]
    digest = item["sha256"]
    if type(size) is not int or size <= 0 or size > MAX_ARTIFACT_BYTES:
        raise FirmwareArtifactError("manifest artifact size is invalid")
    if not isinstance(digest, str) or SHA256_RE.fullmatch(digest) is None:
        raise FirmwareArtifactError("manifest artifact hash is invalid")
    if partition_source:
        if item["flash_offset"] is not None:
            raise FirmwareArtifactError("partition source cannot have a flash offset")
        preserves_nvs = None
        preserves_littlefs = None
    else:
        if item["flash_offset"] != FLASH_OFFSETS[role]:
            raise FirmwareArtifactError("manifest artifact flash offset is invalid")
        expected_nvs = role != "factory_recovery"
        if item["preserves_nvs"] is not expected_nvs:
            raise FirmwareArtifactError("manifest NVS preservation claim is invalid")
        if item["preserves_littlefs"] is not True:
            raise FirmwareArtifactError("manifest LittleFS preservation claim is invalid")
        preserves_nvs = item["preserves_nvs"]
        preserves_littlefs = item["preserves_littlefs"]
    return VerifiedArtifact(
        role=role,
        path=item["path"],
        size=size,
        sha256=digest,
        flash_offset=item["flash_offset"],
        preserves_nvs=preserves_nvs,
        preserves_littlefs=preserves_littlefs,
    )


def _validate_model(
    model: Any,
    payload_root: Path,
    all_payload_files: dict[str, bytes],
) -> VerifiedModel:
    if not isinstance(model, dict):
        raise FirmwareArtifactError("manifest model entry is invalid")
    environment = model.get("environment")
    constraint = MODEL_CONSTRAINTS.get(environment) if isinstance(environment, str) else None
    if constraint is None:
        raise FirmwareArtifactError("manifest model environment is invalid")
    expected_keys = set(constraint) | {
        "environment",
        "panel_qualified",
        "hardware_revisions",
        "browser_flash_qualified",
        "ota_eligible",
        "flash_sets",
        "files",
    }
    if set(model) != expected_keys:
        raise FirmwareArtifactError("manifest model fields are invalid")
    for key, expected in constraint.items():
        if not _strict_json_equal(model[key], expected):
            raise FirmwareArtifactError(f"manifest model {key} is invalid")
    if type(model["panel_qualified"]) is not bool:
        raise FirmwareArtifactError("manifest panel qualification is invalid")
    if type(model["browser_flash_qualified"]) is not bool:
        raise FirmwareArtifactError("manifest browser qualification is invalid")
    if model["ota_eligible"] is not False:
        raise FirmwareArtifactError("firmware is not approved for OTA installation")
    revisions = model["hardware_revisions"]
    if not isinstance(revisions, list) or any(
        not isinstance(value, str)
        or not value
        or len(value) > 64
        or re.fullmatch(r"[A-Za-z0-9._-]+", value) is None
        for value in revisions
    ):
        raise FirmwareArtifactError("manifest hardware revisions are invalid")
    if len(set(revisions)) != len(revisions):
        raise FirmwareArtifactError("manifest hardware revisions are duplicated")
    expected_flash_sets = {
        "preserve_config": list(PRESERVE_CONFIG_ROLES),
        "factory_recovery": ["factory_recovery"],
    }
    if not _strict_json_equal(model["flash_sets"], expected_flash_sets):
        raise FirmwareArtifactError("manifest flash sets are invalid")
    if not isinstance(model["files"], list):
        raise FirmwareArtifactError("manifest files are invalid")
    artifacts: dict[str, VerifiedArtifact] = {}
    for item in model["files"]:
        artifact = _artifact_from_item(item, environment)
        if artifact.role in artifacts:
            raise FirmwareArtifactError("manifest artifact role is duplicated")
        artifacts[artifact.role] = artifact
    if set(artifacts) != EXPECTED_ROLES:
        raise FirmwareArtifactError("manifest artifact roles are incomplete")

    for artifact in artifacts.values():
        raw = _read_regular_file(payload_root, artifact.path, MAX_ARTIFACT_BYTES)
        if len(raw) != artifact.size or _sha256(raw) != artifact.sha256:
            raise FirmwareArtifactError("firmware artifact length or hash is invalid")
        all_payload_files[artifact.path] = raw

    partition_entries = _parse_partition_csv(all_payload_files[artifacts["partition_source"].path])
    expected_partition_entries = [
        {
            "name": name,
            "type": kind,
            "subtype": subtype,
            "offset": offset,
            "size": size,
            "flags": "",
        }
        for name, kind, subtype, offset, size in PARTITION_LAYOUTS[environment]
    ]
    if not _strict_json_equal(partition_entries, expected_partition_entries):
        raise FirmwareArtifactError("partition source does not match the pinned model layout")
    by_name = {entry["name"]: entry for entry in partition_entries}
    app_entries = [entry for entry in partition_entries if entry["type"] == "app"]
    filesystem_entries = [
        entry
        for entry in partition_entries
        if entry["type"] == "data" and entry["subtype"] in {"spiffs", "littlefs"}
    ]
    expected_app_names = (
        {"app0"}
        if environment == "reterminal_e1004"
        else {"ota_0", "ota_1"}
    )
    if (
        {entry["name"] for entry in app_entries} != expected_app_names
        or len(filesystem_entries) != 1
        or "nvs" not in by_name
    ):
        raise FirmwareArtifactError("partition layout lacks required protected ranges")
    application_partition = by_name[
        "app0" if environment == "reterminal_e1004" else "ota_0"
    ]
    filesystem_partition = filesystem_entries[0]
    if application_partition["offset"] != FLASH_OFFSETS["application"]:
        raise FirmwareArtifactError("application partition offset is invalid")
    ordered_partitions = sorted(partition_entries, key=lambda entry: entry["offset"])
    previous_end = 0
    for entry in ordered_partitions:
        entry_end = entry["offset"] + entry["size"]
        if entry["offset"] < previous_end or entry_end > FLASH_CONSTRAINTS["minimum_bytes"]:
            raise FirmwareArtifactError("partition source overlaps or exceeds flash")
        previous_end = entry_end
    if application_partition["offset"] + application_partition["size"] > filesystem_partition[
        "offset"
    ]:
        raise FirmwareArtifactError("application partition overlaps protected storage")
    if environment != "reterminal_e1004":
        ota_1_partition = by_name["ota_1"]
        if ota_1_partition["size"] != application_partition["size"]:
            raise FirmwareArtifactError("A/B application partitions are not equal size")
    ota_partition = by_name.get("otadata")
    if ota_partition is None or (
        ota_partition["offset"] != FLASH_OFFSETS["ota_data_initial"]
        or ota_partition["size"] != 0x2000
    ):
        raise FirmwareArtifactError("OTA data partition bounds are invalid")
    _assert_partition_binary(
        all_payload_files[artifacts["partition_table"].path], partition_entries
    )
    normal_ranges = [
        (
            artifacts[role].flash_offset,
            artifacts[role].flash_offset + artifacts[role].size,
            role,
        )
        for role in PRESERVE_CONFIG_ROLES
    ]
    protected = (
        {
            "name": "nvs",
            "offset": by_name["nvs"]["offset"],
            "size": by_name["nvs"]["size"],
        },
        {
            "name": "littlefs",
            "offset": filesystem_partition["offset"],
            "size": filesystem_partition["size"],
        },
    )
    for start, end, role in normal_ranges:
        if start is None or end > FLASH_CONSTRAINTS["minimum_bytes"]:
            raise FirmwareArtifactError(f"{role} flash range is invalid")
        for protected_range in protected:
            protected_start = protected_range["offset"]
            protected_end = protected_start + protected_range["size"]
            if start < protected_end and end > protected_start:
                raise FirmwareArtifactError(f"{role} overlaps protected storage")
    application = artifacts["application"]
    if application.size > application_partition["size"]:
        raise FirmwareArtifactError("application exceeds its partition")
    bootloader = all_payload_files[artifacts["bootloader"].path]
    partition_table = all_payload_files[artifacts["partition_table"].path]
    ota_data = all_payload_files[artifacts["ota_data_initial"].path]
    application_bytes = all_payload_files[application.path]
    factory = all_payload_files[artifacts["factory_recovery"].path]
    if len(bootloader) > FLASH_OFFSETS["partition_table"]:
        raise FirmwareArtifactError("bootloader overlaps the partition table")
    if FLASH_OFFSETS["partition_table"] + len(partition_table) > by_name["nvs"]["offset"]:
        raise FirmwareArtifactError("partition table overlaps NVS")
    if len(ota_data) != ota_partition["size"]:
        raise FirmwareArtifactError("OTA initializer size is invalid")
    embedded_ranges = (
        (FLASH_OFFSETS["bootloader"], bootloader, "bootloader"),
        (FLASH_OFFSETS["partition_table"], partition_table, "partition table"),
        (FLASH_OFFSETS["ota_data_initial"], ota_data, "OTA initializer"),
        (FLASH_OFFSETS["application"], application_bytes, "application"),
    )
    for offset, expected, label in embedded_ranges:
        if factory[offset : offset + len(expected)] != expected:
            raise FirmwareArtifactError(f"factory image has unexpected {label}")
    if len(factory) > filesystem_partition["offset"]:
        raise FirmwareArtifactError("factory image reaches protected LittleFS")
    blank_ranges = (
        (len(bootloader), FLASH_OFFSETS["partition_table"]),
        (
            FLASH_OFFSETS["partition_table"] + len(partition_table),
            by_name["nvs"]["offset"],
        ),
        (by_name["nvs"]["offset"], by_name["nvs"]["offset"] + by_name["nvs"]["size"]),
    )
    for start, end in blank_ranges:
        if factory[start:end] != b"\xff" * (end - start):
            raise FirmwareArtifactError("factory image has non-blank protected data")

    qualified = model["browser_flash_qualified"]
    if qualified and (
        environment not in {"reterminal_e1001", "reterminal_e1002"}
        or model["panel_qualified"] is not True
        or not revisions
    ):
        raise FirmwareArtifactError("browser qualification exceeds model evidence")
    return VerifiedModel(
        environment=environment,
        model=constraint["model"],
        panel=constraint["panel"],
        resolution=tuple(constraint["resolution"]),
        partition_layout=constraint["partition_layout"],
        hardware_revisions=tuple(revisions),
        browser_flash_qualified=qualified,
        panel_qualified=model["panel_qualified"],
        artifacts=artifacts,
        protected_ranges=protected,
    )


def _validate_bundle(
    root: Path,
    entry: dict[str, Any],
    trusted_keys: dict[str, Ed25519PublicKey],
) -> VerifiedBundle:
    release_id = entry["manifest_sha256"]
    key_id = entry["signing_key_id"]
    public_key = trusted_keys.get(key_id)
    if public_key is None:
        raise FirmwareArtifactError("firmware signing key is not trusted")
    bundle_root = root / "bundles" / release_id
    _assert_directory(root / "bundles", "firmware bundles directory")
    _assert_directory(bundle_root, "firmware bundle directory")
    try:
        bundle_entries = {entry.name: entry for entry in os.scandir(bundle_root)}
    except OSError as exc:
        raise FirmwareArtifactError("firmware bundle cannot be inspected") from exc
    if set(bundle_entries) != {"manifest.sig", "payload"}:
        raise FirmwareArtifactError("firmware bundle contains unlisted entries")
    if (
        bundle_entries["manifest.sig"].is_symlink()
        or not bundle_entries["manifest.sig"].is_file(follow_symlinks=False)
        or bundle_entries["payload"].is_symlink()
        or not bundle_entries["payload"].is_dir(follow_symlinks=False)
    ):
        raise FirmwareArtifactError("firmware bundle contains an unsafe entry")
    payload_root = bundle_root / "payload"
    _assert_directory(payload_root, "firmware payload directory")
    signature = _read_regular_file(bundle_root, "manifest.sig", 64)
    if len(signature) != 64 or _sha256(signature) != entry["signature_sha256"]:
        raise FirmwareArtifactError("firmware signature is invalid")
    manifest_bytes = _read_regular_file(payload_root, "manifest.json", MAX_MANIFEST_BYTES)
    if _sha256(manifest_bytes) != release_id:
        raise FirmwareArtifactError("firmware manifest digest does not match bundle id")
    try:
        public_key.verify(signature, manifest_bytes)
    except InvalidSignature as exc:
        raise FirmwareArtifactError("firmware manifest signature is invalid") from exc
    manifest = _read_json_bytes(manifest_bytes, "firmware manifest")
    expected_root_keys = {
        "schema_version",
        "firmware_version",
        "git_sha",
        "source_date_epoch",
        "chip",
        "flash",
        "toolchain",
        "toolchain_evidence",
        "security",
        "models",
    }
    if not isinstance(manifest, dict) or set(manifest) != expected_root_keys:
        raise FirmwareArtifactError("firmware manifest root is invalid")
    manifest_schema_version = manifest["schema_version"]
    if (
        type(manifest_schema_version) is not int
        or manifest_schema_version not in SUPPORTED_MANIFEST_SCHEMAS
    ):
        raise FirmwareArtifactError("firmware manifest schema is unsupported")
    if (
        not isinstance(manifest["firmware_version"], str)
        or not manifest["firmware_version"]
        or len(manifest["firmware_version"]) > 128
    ):
        raise FirmwareArtifactError("firmware version is invalid")
    if not isinstance(manifest["git_sha"], str) or GIT_SHA_RE.fullmatch(
        manifest["git_sha"]
    ) is None:
        raise FirmwareArtifactError("firmware Git SHA is invalid")
    if type(manifest["source_date_epoch"]) is not int or manifest["source_date_epoch"] <= 0:
        raise FirmwareArtifactError("firmware source epoch is invalid")
    if manifest["chip"] != "ESP32-S3" or not _strict_json_equal(
        manifest["flash"], FLASH_CONSTRAINTS
    ):
        raise FirmwareArtifactError("firmware chip or flash contract is invalid")
    if not isinstance(manifest["toolchain"], dict):
        raise FirmwareArtifactError("firmware toolchain metadata is invalid")
    serial_enrollment = _validate_manifest_security(
        manifest_schema_version,
        manifest["security"],
    )

    evidence = manifest["toolchain_evidence"]
    if not isinstance(evidence, dict) or set(evidence) != {"path", "size", "sha256"}:
        raise FirmwareArtifactError("toolchain evidence descriptor is invalid")
    if evidence["path"] != "toolchain-evidence.txt":
        raise FirmwareArtifactError("toolchain evidence path is invalid")
    if (
        type(evidence["size"]) is not int
        or evidence["size"] <= 0
        or evidence["size"] > MAX_ARTIFACT_BYTES
        or not isinstance(evidence["sha256"], str)
        or SHA256_RE.fullmatch(evidence["sha256"]) is None
    ):
        raise FirmwareArtifactError("toolchain evidence metadata is invalid")
    evidence_bytes = _read_regular_file(payload_root, evidence["path"], MAX_ARTIFACT_BYTES)
    if len(evidence_bytes) != evidence["size"] or _sha256(evidence_bytes) != evidence["sha256"]:
        raise FirmwareArtifactError("toolchain evidence length or hash is invalid")

    models = manifest["models"]
    if not isinstance(models, list) or len(models) != len(MODEL_CONSTRAINTS):
        raise FirmwareArtifactError("firmware manifest model set is invalid")
    payload_files: dict[str, bytes] = {
        "manifest.json": manifest_bytes,
        evidence["path"]: evidence_bytes,
    }
    verified_models: dict[str, VerifiedModel] = {}
    for raw_model in models:
        verified_model = _validate_model(raw_model, payload_root, payload_files)
        if verified_model.model in verified_models:
            raise FirmwareArtifactError("firmware model is duplicated")
        verified_models[verified_model.model] = verified_model
    if set(verified_models) != {"E1001", "E1002", "E1004"}:
        raise FirmwareArtifactError("firmware model set is incomplete")

    sums_bytes = _read_regular_file(payload_root, "SHA256SUMS", MAX_MANIFEST_BYTES)
    expected_sums = [f"{release_id}  manifest.json", f"{evidence['sha256']}  {evidence['path']}"]
    for verified_model in verified_models.values():
        expected_sums.extend(
            f"{artifact.sha256}  {artifact.path}"
            for artifact in verified_model.artifacts.values()
        )
    if sums_bytes != ("\n".join(sorted(expected_sums)) + "\n").encode("utf-8"):
        raise FirmwareArtifactError("firmware SHA256SUMS is invalid")
    payload_files["SHA256SUMS"] = sums_bytes

    actual_files: set[str] = set()
    actual_directories: set[str] = set()
    total_bytes = 0
    def reject_walk_error(exc: OSError) -> None:
        raise FirmwareArtifactError("firmware payload cannot be inspected") from exc

    try:
        for directory, directory_names, filenames in os.walk(
            payload_root,
            followlinks=False,
            onerror=reject_walk_error,
        ):
            directory_path = Path(directory)
            for name in list(directory_names):
                candidate = directory_path / name
                if candidate.is_symlink():
                    raise FirmwareArtifactError("firmware payload contains a symlink")
                actual_directories.add(candidate.relative_to(payload_root).as_posix())
            for filename in filenames:
                candidate = directory_path / filename
                if candidate.is_symlink() or not candidate.is_file():
                    raise FirmwareArtifactError("firmware payload contains an unsafe file")
                relative = candidate.relative_to(payload_root).as_posix()
                actual_files.add(relative)
                total_bytes += candidate.stat().st_size
    except OSError as exc:
        raise FirmwareArtifactError("firmware payload cannot be inspected") from exc
    if (
        actual_files != set(payload_files)
        or actual_directories != set(MODEL_CONSTRAINTS)
        or total_bytes > MAX_BUNDLE_BYTES
    ):
        raise FirmwareArtifactError("firmware payload contains missing or unlisted files")
    return VerifiedBundle(
        release_id=release_id,
        signing_key_id=key_id,
        firmware_version=manifest["firmware_version"],
        git_sha=manifest["git_sha"],
        source_date_epoch=manifest["source_date_epoch"],
        manifest_schema_version=manifest_schema_version,
        serial_enrollment=serial_enrollment,
        manifest_bytes=manifest_bytes,
        signature_bytes=signature,
        payload_root=payload_root,
        models=verified_models,
    )


def _validate_catalog_bundles(
    root: Path,
    catalog: dict[str, Any],
    trusted_keys: dict[str, Ed25519PublicKey],
) -> dict[str, VerifiedBundle]:
    bundles: dict[str, VerifiedBundle] = {}
    for entry in catalog["releases"]:
        try:
            bundle = _validate_bundle(root, entry, trusted_keys)
        except FirmwareArtifactError as exc:
            raise FirmwareCatalogUnavailable(
                "Approved firmware catalog failed verification"
            ) from exc
        bundles[bundle.release_id] = bundle
    return bundles


def build_firmware_catalog(
    storage_path: str,
    trusted_keys_raw: str,
    browser_flash_enabled: bool,
    minimum_catalog_generation: int = 0,
) -> dict[str, Any]:
    root = Path(storage_path)
    trusted_keys = load_trusted_keys(trusted_keys_raw)
    blockers: list[str] = []
    if not trusted_keys:
        return {
            "schema_version": CATALOG_RESPONSE_SCHEMA,
            "installer_state": "locked",
            "browser_flash_enabled": browser_flash_enabled,
            "trusted_key_ids": [],
            "blockers": [
                "No trusted firmware signing key is configured.",
                "No signed, browser-qualified firmware is installable.",
            ],
            "releases": [],
        }
    catalog = _read_catalog(root, trusted_keys, minimum_catalog_generation)
    generation_gate_blocker = None
    if browser_flash_enabled and minimum_catalog_generation <= 0:
        generation_gate_blocker = "No minimum signed catalog generation is pinned."
        blockers.append(generation_gate_blocker)
    if catalog is None:
        blockers.append("No approved firmware catalog is installed.")
        releases: list[dict[str, Any]] = []
    else:
        releases = []
        for bundle in _validate_catalog_bundles(root, catalog, trusted_keys).values():
            model_records = []
            for model in bundle.models.values():
                qualified = model.browser_flash_qualified
                model_blockers: list[str] = []
                if not qualified:
                    model_blockers.append("This model has not completed browser-flash qualification.")
                if not model.hardware_revisions:
                    model_blockers.append("No hardware revision is approved.")
                if model.model == "E1004":
                    model_blockers.append("E1004 browser flashing is not supported.")
                if generation_gate_blocker:
                    model_blockers.append(generation_gate_blocker)
                artifacts = []
                for role in PRESERVE_CONFIG_ROLES:
                    artifact = model.artifacts[role]
                    record = {
                        "role": role,
                        "size": artifact.size,
                        "sha256": artifact.sha256,
                        "flash_offset": artifact.flash_offset,
                        "preserves_nvs": artifact.preserves_nvs,
                        "preserves_littlefs": artifact.preserves_littlefs,
                    }
                    if browser_flash_enabled and not model_blockers:
                        record["download_url"] = (
                            f"/api/terminal/firmware/releases/{bundle.release_id}/"
                            f"models/{model.model}/artifacts/{role}"
                        )
                    artifacts.append(record)
                model_records.append(
                    {
                        "model": model.model,
                        "environment": model.environment,
                        "panel": model.panel,
                        "resolution": list(model.resolution),
                        "partition_layout": model.partition_layout,
                        "hardware_revisions": list(model.hardware_revisions),
                        "browser_flash_qualified": qualified,
                        "install_eligible": browser_flash_enabled and not model_blockers,
                        "blockers": model_blockers,
                        "protected_ranges": list(model.protected_ranges),
                        "flash_set": list(PRESERVE_CONFIG_ROLES),
                        "artifacts": artifacts,
                    }
                )
            releases.append(
                {
                    "release_id": bundle.release_id,
                    "firmware_version": bundle.firmware_version,
                    "git_sha": bundle.git_sha,
                    "source_date_epoch": bundle.source_date_epoch,
                    "manifest_schema_version": bundle.manifest_schema_version,
                    "signing_key_id": bundle.signing_key_id,
                    "serial_enrollment": bundle.serial_enrollment.as_catalog_record(),
                    "manifest_url": (
                        f"/api/terminal/firmware/releases/{bundle.release_id}/manifest.json"
                    ),
                    "signature_url": (
                        f"/api/terminal/firmware/releases/{bundle.release_id}/manifest.sig"
                    ),
                    "models": model_records,
                }
            )
    if not browser_flash_enabled:
        blockers.append("Browser firmware writing is disabled until provisioning is qualified.")
    installable = any(
        model["install_eligible"]
        for release in releases
        for model in release["models"]
    )
    if not installable:
        blockers.append("No signed, browser-qualified firmware is installable.")
    return {
        "schema_version": CATALOG_RESPONSE_SCHEMA,
        "installer_state": "ready" if installable else "locked",
        "browser_flash_enabled": browser_flash_enabled,
        "trusted_key_ids": sorted(trusted_keys),
        "blockers": list(dict.fromkeys(blockers)),
        "releases": releases,
    }


def read_release_metadata(
    storage_path: str,
    trusted_keys_raw: str,
    release_id: str,
    kind: str,
    minimum_catalog_generation: int = 0,
) -> tuple[bytes, str, str]:
    if SHA256_RE.fullmatch(release_id) is None:
        raise FirmwareReleaseNotFound("Firmware release not found")
    root = Path(storage_path)
    trusted_keys = load_trusted_keys(trusted_keys_raw)
    catalog = _read_catalog(root, trusted_keys, minimum_catalog_generation)
    if catalog is None:
        raise FirmwareReleaseNotFound("Firmware release not found")
    bundle = _validate_catalog_bundles(root, catalog, trusted_keys).get(release_id)
    if bundle is None:
        raise FirmwareReleaseNotFound("Firmware release not found")
    if kind == "manifest":
        return bundle.manifest_bytes, "application/json", f'"sha256:{release_id}"'
    if kind == "signature":
        digest = _sha256(bundle.signature_bytes)
        return bundle.signature_bytes, "application/octet-stream", f'"sha256:{digest}"'
    raise FirmwareArtifactNotFound("Firmware artifact not found")


def read_model_artifact(
    storage_path: str,
    trusted_keys_raw: str,
    browser_flash_enabled: bool,
    release_id: str,
    model_name: str,
    role: str,
    minimum_catalog_generation: int = 0,
) -> tuple[bytes, VerifiedArtifact, VerifiedBundle]:
    if SHA256_RE.fullmatch(release_id) is None:
        raise FirmwareReleaseNotFound("Firmware release not found")
    root = Path(storage_path)
    trusted_keys = load_trusted_keys(trusted_keys_raw)
    catalog = _read_catalog(root, trusted_keys, minimum_catalog_generation)
    if catalog is None:
        raise FirmwareReleaseNotFound("Firmware release not found")
    bundle = _validate_catalog_bundles(root, catalog, trusted_keys).get(release_id)
    if bundle is None:
        raise FirmwareReleaseNotFound("Firmware release not found")
    model = bundle.models.get(model_name)
    if model is None:
        raise FirmwareReleaseNotFound("Firmware release not found")
    if role not in PRESERVE_CONFIG_ROLES:
        raise FirmwareArtifactNotFound("Firmware artifact not found")
    if (
        not browser_flash_enabled
        or minimum_catalog_generation <= 0
        or not model.browser_flash_qualified
        or not model.hardware_revisions
        or model.model == "E1004"
    ):
        raise FirmwareModelNotQualified("Firmware model is not browser-installable")
    artifact = model.artifacts[role]
    raw = _read_regular_file(bundle.payload_root, artifact.path, MAX_ARTIFACT_BYTES)
    if len(raw) != artifact.size or _sha256(raw) != artifact.sha256:
        raise FirmwareCatalogUnavailable("Firmware artifact changed after verification")
    return raw, artifact, bundle
