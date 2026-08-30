"""Strict fixture and focused checks for the local firmware trust boundary."""

from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
from typing import Any

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from backend.services.terminal.firmware_artifacts import (
    FirmwareArtifactError,
    FirmwareArtifactNotFound,
    FirmwareCatalogUnavailable,
    FirmwareModelNotQualified,
    build_firmware_catalog,
    read_model_artifact,
    read_release_metadata,
)


MODEL_FIXTURES = (
    (
        "reterminal_e1001",
        "E1001",
        "GDEY075T7",
        [800, 480],
        "ab-v1",
        "partitions/e100x-ab-v1.csv",
        True,
        ["V1.0"],
    ),
    (
        "reterminal_e1002",
        "E1002",
        "GDEP073E01",
        [800, 480],
        "ab-v1",
        "partitions/e100x-ab-v1.csv",
        True,
        ["V1.0"],
    ),
    (
        "reterminal_e1004",
        "E1004",
        "GDEP133C02",
        [1200, 1600],
        "single-slot-e1004-v1",
        "e1004_partitions.csv",
        False,
        [],
    ),
)

ROLE_FILES = {
    "bootloader": ("bootloader.bin", 0x0000, True, True),
    "partition_table": ("partitions.bin", 0x8000, True, True),
    "ota_data_initial": ("boot_app0.bin", 0xE000, True, True),
    "application": ("firmware.bin", 0x10000, True, True),
    "factory_recovery": ("firmware.factory.bin", 0x0000, False, True),
}


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _json_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _partition_entries(model: str):
    littlefs_size = 0x400000 if model == "E1004" else 0xE0000
    coredump_offset = 0x710000 if model == "E1004" else 0x3F0000
    entries = [
        ("nvs", 0x01, 0x02, 0x9000, 0x5000),
        ("otadata", 0x01, 0x00, 0xE000, 0x2000),
        ("app0" if model == "E1004" else "ota_0", 0x00, 0x10, 0x10000, 0x300000),
        ("spiffs", 0x01, 0x82, 0x310000, littlefs_size),
        ("coredump", 0x01, 0x03, coredump_offset, 0x10000),
    ]
    if model != "E1004":
        entries.append(("ota_1", 0x00, 0x11, 0x400000, 0x300000))
    return tuple(entries)


def _partition_source(model: str) -> bytes:
    type_names = {0x00: "app", 0x01: "data"}
    subtype_names = {
        (0x01, 0x02): "nvs",
        (0x01, 0x00): "ota",
        (0x00, 0x10): "ota_0",
        (0x00, 0x11): "ota_1",
        (0x01, 0x82): "spiffs",
        (0x01, 0x03): "coredump",
    }
    lines = ["# Name, Type, SubType, Offset, Size, Flags"]
    lines.extend(
        f"{name},{type_names[type_id]},{subtype_names[(type_id, subtype_id)]},"
        f"0x{offset:x},0x{size:x},"
        for name, type_id, subtype_id, offset, size in _partition_entries(model)
    )
    return ("\n".join(lines) + "\n").encode("utf-8")


def _partition_binary(model: str) -> bytes:
    records = []
    for name, type_id, subtype_id, offset, size in _partition_entries(model):
        label = name.encode("ascii").ljust(16, b"\0")
        records.append(
            b"\xaa\x50"
            + bytes((type_id, subtype_id))
            + offset.to_bytes(4, "little")
            + size.to_bytes(4, "little")
            + label
            + b"\0" * 4
        )
    entries = b"".join(records)
    checksum = hashlib.md5(entries, usedforsecurity=False).digest()
    binary = entries + b"\xeb\xeb" + b"\xff" * 14 + checksum
    return binary + b"\xff" * (0xC00 - len(binary))


def _artifact_record(
    environment: str,
    role: str,
    filename: str,
    raw: bytes,
    flash_offset: int | None,
    preserves_nvs: bool | None = None,
    preserves_littlefs: bool | None = None,
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "path": f"{environment}/{filename}",
        "role": role,
        "flash_offset": flash_offset,
        "size": len(raw),
        "sha256": _sha256(raw),
    }
    if role != "partition_source":
        record["preserves_nvs"] = preserves_nvs
        record["preserves_littlefs"] = preserves_littlefs
    return record


def stage_signed_bundle(
    root: Path,
    *,
    manifest_schema_version: int = 1,
    serial_enrollment: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Stage one complete deterministic signed bundle and return test metadata."""

    evidence = b"generated deterministic toolchain evidence\n"
    payloads: dict[str, bytes] = {"toolchain-evidence.txt": evidence}
    models = []
    model_artifacts: dict[tuple[str, str], bytes] = {}
    for (
        environment,
        model,
        panel,
        resolution,
        partition_layout,
        partition_csv,
        qualified,
        revisions,
    ) in MODEL_FIXTURES:
        partition_source = _partition_source(model)
        partition_binary = _partition_binary(model)
        bootloader = f"{environment}:bootloader".encode("ascii")
        ota_data = (
            f"{environment}:ota-data".encode("ascii")
            + b"\xff" * 0x2000
        )[:0x2000]
        application = (f"{environment}:application:" * 8).encode("ascii")
        factory = bytearray(b"\xff" * (0x10000 + len(application)))
        factory[0 : len(bootloader)] = bootloader
        factory[0x8000 : 0x8000 + len(partition_binary)] = partition_binary
        factory[0xE000 : 0xE000 + len(ota_data)] = ota_data
        factory[0x10000 : 0x10000 + len(application)] = application
        role_payloads = {
            "bootloader": bootloader,
            "partition_table": partition_binary,
            "ota_data_initial": ota_data,
            "application": application,
            "factory_recovery": bytes(factory),
        }
        files = []
        for role, (filename, offset, preserves_nvs, preserves_littlefs) in ROLE_FILES.items():
            raw = role_payloads[role]
            path = f"{environment}/{filename}"
            payloads[path] = raw
            model_artifacts[(model, role)] = raw
            files.append(
                _artifact_record(
                    environment,
                    role,
                    filename,
                    raw,
                    offset,
                    preserves_nvs,
                    preserves_littlefs,
                )
            )
        partition_filename = "partitions.csv"
        partition_path = f"{environment}/{partition_filename}"
        payloads[partition_path] = partition_source
        files.append(
            _artifact_record(
                environment,
                "partition_source",
                partition_filename,
                partition_source,
                None,
            )
        )
        models.append(
            {
                "environment": environment,
                "model": model,
                "panel": panel,
                "resolution": resolution,
                "partition_layout": partition_layout,
                "partition_csv": partition_csv,
                "panel_qualified": qualified,
                "hardware_revisions": revisions,
                "browser_flash_qualified": qualified,
                "ota_eligible": False,
                "flash_sets": {
                    "preserve_config": [
                        "bootloader",
                        "partition_table",
                        "ota_data_initial",
                        "application",
                    ],
                    "factory_recovery": ["factory_recovery"],
                },
                "files": files,
            }
        )
    security: dict[str, Any] = {
        "signed": True,
        "ota_eligible": False,
        "reason": "test fixture is detached-signed but OTA remains disabled",
    }
    if manifest_schema_version == 2:
        security["serial_enrollment"] = serial_enrollment or {
            "protocol": "RET1",
            "enabled": False,
            "trust_key_id": None,
            "public_key_sha256": None,
            "identity_strength": "physical_cable_only",
            "attestation": False,
        }
    manifest = {
        "schema_version": manifest_schema_version,
        "firmware_version": "0.2.0-test.1",
        "git_sha": "1" * 40,
        "source_date_epoch": 1_700_000_000,
        "chip": "ESP32-S3",
        "flash": {
            "minimum_bytes": 32 * 1024 * 1024,
            "mode": "keep",
            "frequency": "keep",
            "size": "32MB",
            "erase_all": False,
        },
        "toolchain": {"platformio": "test", "framework": "arduino"},
        "toolchain_evidence": {
            "path": "toolchain-evidence.txt",
            "size": len(evidence),
            "sha256": _sha256(evidence),
        },
        "security": security,
        "models": models,
    }
    manifest_bytes = _json_bytes(manifest)
    release_id = _sha256(manifest_bytes)
    payloads["manifest.json"] = manifest_bytes
    sums = "\n".join(
        sorted(f"{_sha256(raw)}  {path}" for path, raw in payloads.items())
    ) + "\n"
    payloads["SHA256SUMS"] = sums.encode("utf-8")

    private_key = Ed25519PrivateKey.generate()
    signature = private_key.sign(manifest_bytes)
    public_key = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    trusted_keys = json.dumps(
        {
            "test-key": base64.urlsafe_b64encode(public_key)
            .decode("ascii")
            .rstrip("=")
        }
    )
    bundle_root = root / "bundles" / release_id
    payload_root = bundle_root / "payload"
    for path, raw in payloads.items():
        target = payload_root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
    (bundle_root / "manifest.sig").write_bytes(signature)
    catalog = {
        "schema_version": 1,
        "generation": 1,
        "signing_key_id": "test-key",
        "releases": [
            {
                "manifest_sha256": release_id,
                "state": "approved",
                "signing_key_id": "test-key",
                "signature_sha256": _sha256(signature),
            }
        ],
    }
    catalog_bytes = _json_bytes(catalog)
    (root / "catalog.json").write_bytes(catalog_bytes)
    (root / "catalog.sig").write_bytes(private_key.sign(catalog_bytes))
    return {
        "root": root,
        "release_id": release_id,
        "trusted_keys": trusted_keys,
        "private_key": private_key,
        "signature": signature,
        "manifest": manifest_bytes,
        "payload_root": payload_root,
        "artifacts": model_artifacts,
    }


def _rewrite_catalog(fixture: dict[str, Any], **entry_updates: Any) -> None:
    catalog_path = fixture["root"] / "catalog.json"
    catalog = json.loads(catalog_path.read_text())
    catalog["releases"][0].update(entry_updates)
    catalog_bytes = _json_bytes(catalog)
    catalog_path.write_bytes(catalog_bytes)
    (fixture["root"] / "catalog.sig").write_bytes(
        fixture["private_key"].sign(catalog_bytes)
    )


def _resign_manifest(fixture: dict[str, Any], mutate) -> None:
    """Mutate, re-sign, and content-address an otherwise coherent bundle."""

    old_bundle_root = fixture["payload_root"].parent
    manifest = json.loads((fixture["payload_root"] / "manifest.json").read_text())
    mutate(manifest, fixture["payload_root"])
    manifest_bytes = _json_bytes(manifest)
    release_id = _sha256(manifest_bytes)
    (fixture["payload_root"] / "manifest.json").write_bytes(manifest_bytes)
    payload_files = {
        path.relative_to(fixture["payload_root"]).as_posix(): path.read_bytes()
        for path in fixture["payload_root"].rglob("*")
        if path.is_file() and path.name != "SHA256SUMS"
    }
    sums = "\n".join(
        sorted(f"{_sha256(raw)}  {path}" for path, raw in payload_files.items())
    ) + "\n"
    (fixture["payload_root"] / "SHA256SUMS").write_bytes(sums.encode("utf-8"))
    signature = fixture["private_key"].sign(manifest_bytes)
    (old_bundle_root / "manifest.sig").write_bytes(signature)
    new_bundle_root = old_bundle_root.parent / release_id
    old_bundle_root.rename(new_bundle_root)
    fixture.update(
        {
            "release_id": release_id,
            "signature": signature,
            "manifest": manifest_bytes,
            "payload_root": new_bundle_root / "payload",
        }
    )
    _rewrite_catalog(
        fixture,
        manifest_sha256=release_id,
        signature_sha256=_sha256(signature),
    )


def test_signed_qualified_bundle_is_installable(tmp_path: Path):
    fixture = stage_signed_bundle(tmp_path)

    catalog = build_firmware_catalog(str(tmp_path), fixture["trusted_keys"], True, 1)

    assert catalog["schema_version"] == 2
    assert catalog["installer_state"] == "ready"
    assert catalog["blockers"] == []
    release = catalog["releases"][0]
    assert release["release_id"] == fixture["release_id"]
    assert release["manifest_schema_version"] == 1
    assert release["serial_enrollment"] == {
        "protocol": "RET1",
        "enabled": False,
        "trust_key_id": None,
        "public_key_sha256": None,
        "identity_strength": "physical_cable_only",
        "attestation": False,
    }
    by_model = {model["model"]: model for model in release["models"]}
    assert by_model["E1001"]["install_eligible"] is True
    assert by_model["E1002"]["install_eligible"] is True
    assert by_model["E1004"]["install_eligible"] is False
    assert by_model["E1001"]["partition_layout"] == "ab-v1"
    assert by_model["E1002"]["partition_layout"] == "ab-v1"
    assert by_model["E1004"]["partition_layout"] == "single-slot-e1004-v1"
    assert by_model["E1001"]["protected_ranges"] == [
        {"name": "nvs", "offset": 0x9000, "size": 0x5000},
        {"name": "littlefs", "offset": 0x310000, "size": 0xE0000},
    ]
    assert by_model["E1004"]["protected_ranges"][1] == {
        "name": "littlefs",
        "offset": 0x310000,
        "size": 0x400000,
    }
    assert "download_url" in by_model["E1001"]["artifacts"][0]


def test_schema_two_disabled_enrollment_is_normalized(tmp_path: Path):
    fixture = stage_signed_bundle(tmp_path, manifest_schema_version=2)

    catalog = build_firmware_catalog(str(tmp_path), fixture["trusted_keys"], False, 1)

    release = catalog["releases"][0]
    assert release["manifest_schema_version"] == 2
    assert release["serial_enrollment"] == {
        "protocol": "RET1",
        "enabled": False,
        "trust_key_id": None,
        "public_key_sha256": None,
        "identity_strength": "physical_cable_only",
        "attestation": False,
    }


def test_schema_two_enabled_enrollment_is_normalized(tmp_path: Path):
    enrollment = {
        "protocol": "RET1",
        "enabled": True,
        "trust_key_id": "terminal-enrollment-2026-01",
        "public_key_sha256": "2" * 64,
        "identity_strength": "physical_cable_only",
        "attestation": False,
    }
    fixture = stage_signed_bundle(
        tmp_path,
        manifest_schema_version=2,
        serial_enrollment=enrollment,
    )

    catalog = build_firmware_catalog(str(tmp_path), fixture["trusted_keys"], False, 1)

    assert catalog["releases"][0]["serial_enrollment"] == enrollment


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("protocol", "RET2"),
        ("enabled", 1),
        ("trust_key_id", "bad key id"),
        ("public_key_sha256", "A" * 64),
        ("identity_strength", "attested"),
        ("attestation", True),
        ("unexpected", True),
    ),
)
def test_schema_two_malformed_enrollment_fails_closed(
    tmp_path: Path,
    field: str,
    value: Any,
):
    enrollment = {
        "protocol": "RET1",
        "enabled": True,
        "trust_key_id": "terminal-enrollment-2026-01",
        "public_key_sha256": "2" * 64,
        "identity_strength": "physical_cable_only",
        "attestation": False,
    }
    enrollment[field] = value
    fixture = stage_signed_bundle(
        tmp_path,
        manifest_schema_version=2,
        serial_enrollment=enrollment,
    )

    with pytest.raises(FirmwareCatalogUnavailable):
        build_firmware_catalog(str(tmp_path), fixture["trusted_keys"], False, 1)


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("trust_key_id", "unexpected-key"),
        ("public_key_sha256", "2" * 64),
    ),
)
def test_schema_two_disabled_enrollment_rejects_trust_material(
    tmp_path: Path,
    field: str,
    value: str,
):
    fixture = stage_signed_bundle(tmp_path, manifest_schema_version=2)

    def add_disabled_key(manifest, _payload_root):
        manifest["security"]["serial_enrollment"][field] = value

    _resign_manifest(fixture, add_disabled_key)

    with pytest.raises(FirmwareCatalogUnavailable):
        build_firmware_catalog(str(tmp_path), fixture["trusted_keys"], False, 1)


@pytest.mark.parametrize("schema_version", [1, 2])
def test_manifest_security_unknown_fields_fail_closed(
    tmp_path: Path,
    schema_version: int,
):
    fixture = stage_signed_bundle(
        tmp_path,
        manifest_schema_version=schema_version,
    )

    def add_unknown_field(manifest, _payload_root):
        manifest["security"]["unexpected"] = True

    _resign_manifest(fixture, add_unknown_field)

    with pytest.raises(FirmwareCatalogUnavailable):
        build_firmware_catalog(str(tmp_path), fixture["trusted_keys"], False, 1)


def test_schema_two_requires_serial_enrollment_claim(tmp_path: Path):
    fixture = stage_signed_bundle(tmp_path, manifest_schema_version=2)

    def remove_enrollment_claim(manifest, _payload_root):
        del manifest["security"]["serial_enrollment"]

    _resign_manifest(fixture, remove_enrollment_claim)

    with pytest.raises(FirmwareCatalogUnavailable):
        build_firmware_catalog(str(tmp_path), fixture["trusted_keys"], False, 1)


def test_global_gate_locks_downloads_without_hiding_verified_release(tmp_path: Path):
    fixture = stage_signed_bundle(tmp_path)

    catalog = build_firmware_catalog(str(tmp_path), fixture["trusted_keys"], False)

    assert catalog["installer_state"] == "locked"
    assert len(catalog["releases"]) == 1
    assert all(
        "download_url" not in artifact
        for model in catalog["releases"][0]["models"]
        for artifact in model["artifacts"]
    )
    with pytest.raises(FirmwareModelNotQualified):
        read_model_artifact(
            str(tmp_path),
            fixture["trusted_keys"],
            False,
            fixture["release_id"],
            "E1001",
            "application",
        )


def test_reads_only_verified_preserve_config_bytes(tmp_path: Path):
    fixture = stage_signed_bundle(tmp_path)

    manifest, media_type, _etag = read_release_metadata(
        str(tmp_path), fixture["trusted_keys"], fixture["release_id"], "manifest"
    )
    artifact, metadata, _bundle = read_model_artifact(
        str(tmp_path),
        fixture["trusted_keys"],
        True,
        fixture["release_id"],
        "E1001",
        "application",
        minimum_catalog_generation=1,
    )

    assert manifest == fixture["manifest"]
    assert media_type == "application/json"
    assert artifact == fixture["artifacts"][("E1001", "application")]
    assert metadata.sha256 == _sha256(artifact)


def test_artifact_mutation_fails_closed(tmp_path: Path):
    fixture = stage_signed_bundle(tmp_path)
    build_firmware_catalog(str(tmp_path), fixture["trusted_keys"], True, 1)
    application = fixture["payload_root"] / "reterminal_e1001" / "firmware.bin"
    application.write_bytes(application.read_bytes() + b"tampered")

    with pytest.raises(FirmwareCatalogUnavailable, match="failed verification"):
        read_model_artifact(
            str(tmp_path),
            fixture["trusted_keys"],
            True,
            fixture["release_id"],
            "E1001",
            "application",
            minimum_catalog_generation=1,
        )


def test_invalid_signature_is_rejected(tmp_path: Path):
    fixture = stage_signed_bundle(tmp_path)
    signature_path = tmp_path / "bundles" / fixture["release_id"] / "manifest.sig"
    signature = bytearray(signature_path.read_bytes())
    signature[0] ^= 0x01
    signature_path.write_bytes(signature)
    _rewrite_catalog(fixture, signature_sha256=_sha256(bytes(signature)))

    with pytest.raises(FirmwareCatalogUnavailable, match="failed verification"):
        read_release_metadata(
            str(tmp_path), fixture["trusted_keys"], fixture["release_id"], "manifest"
        )


def test_invalid_catalog_approval_signature_is_rejected(tmp_path: Path):
    fixture = stage_signed_bundle(tmp_path)
    signature_path = tmp_path / "catalog.sig"
    signature = bytearray(signature_path.read_bytes())
    signature[-1] ^= 0x01
    signature_path.write_bytes(signature)

    with pytest.raises(FirmwareCatalogUnavailable, match="catalog signature is invalid"):
        build_firmware_catalog(str(tmp_path), fixture["trusted_keys"], True, 1)


def test_catalog_generation_floor_prevents_signed_rollback(tmp_path: Path):
    fixture = stage_signed_bundle(tmp_path)

    with pytest.raises(FirmwareCatalogUnavailable, match="generation is not approved"):
        build_firmware_catalog(
            str(tmp_path),
            fixture["trusted_keys"],
            True,
            minimum_catalog_generation=2,
        )


def test_partition_binary_checksum_is_required(tmp_path: Path):
    fixture = stage_signed_bundle(tmp_path)

    def corrupt_partition_checksum(manifest, payload_root):
        path = payload_root / "reterminal_e1001" / "partitions.bin"
        raw = bytearray(path.read_bytes())
        checksum_offset = len(_partition_entries("E1001")) * 32 + 16
        raw[checksum_offset] ^= 0x01
        path.write_bytes(raw)
        partition = next(
            item
            for item in manifest["models"][0]["files"]
            if item["role"] == "partition_table"
        )
        partition["sha256"] = _sha256(bytes(raw))

    _resign_manifest(fixture, corrupt_partition_checksum)

    with pytest.raises(FirmwareCatalogUnavailable):
        build_firmware_catalog(str(tmp_path), fixture["trusted_keys"], True, 1)


def test_symlinked_artifact_is_rejected(tmp_path: Path):
    fixture = stage_signed_bundle(tmp_path)
    application = fixture["payload_root"] / "reterminal_e1001" / "firmware.bin"
    replacement = tmp_path / "replacement.bin"
    replacement.write_bytes(application.read_bytes())
    application.unlink()
    os.symlink(replacement, application)

    with pytest.raises(FirmwareCatalogUnavailable, match="failed verification"):
        read_release_metadata(
            str(tmp_path), fixture["trusted_keys"], fixture["release_id"], "manifest"
        )


def test_fifo_artifact_fails_without_blocking(tmp_path: Path):
    fixture = stage_signed_bundle(tmp_path)
    application = fixture["payload_root"] / "reterminal_e1001" / "firmware.bin"
    application.unlink()
    os.mkfifo(application)

    with pytest.raises(FirmwareCatalogUnavailable):
        build_firmware_catalog(str(tmp_path), fixture["trusted_keys"], True, 1)


def test_duplicate_catalog_key_is_rejected(tmp_path: Path):
    fixture = stage_signed_bundle(tmp_path)
    (tmp_path / "catalog.json").write_text(
        '{"schema_version":1,"schema_version":1,"releases":[]}'
    )

    with pytest.raises(FirmwareArtifactError, match="duplicate key: schema_version"):
        build_firmware_catalog(str(tmp_path), fixture["trusted_keys"], True, 1)


def test_no_trusted_keys_keeps_pure_service_catalog_locked(tmp_path: Path):
    stage_signed_bundle(tmp_path)

    catalog = build_firmware_catalog(str(tmp_path), "{}", True)

    assert catalog["installer_state"] == "locked"
    assert catalog["trusted_key_ids"] == []
    assert catalog["releases"] == []
    assert "No trusted firmware signing key is configured." in catalog["blockers"]
    assert "No signed, browser-qualified firmware is installable." in catalog["blockers"]


def test_corrupt_approved_entry_aborts_catalog_instead_of_returning_partial_results(
    tmp_path: Path,
):
    fixture = stage_signed_bundle(tmp_path)
    application = fixture["payload_root"] / "reterminal_e1001" / "firmware.bin"
    application.write_bytes(application.read_bytes() + b"tampered")

    with pytest.raises(
        FirmwareCatalogUnavailable,
        match="Approved firmware catalog failed verification",
    ):
        build_firmware_catalog(str(tmp_path), fixture["trusted_keys"], True, 1)


@pytest.mark.parametrize("manifest_schema_version", [1, 2])
def test_signed_manifest_with_unsigned_security_claim_is_rejected(
    tmp_path: Path,
    manifest_schema_version: int,
):
    fixture = stage_signed_bundle(
        tmp_path,
        manifest_schema_version=manifest_schema_version,
    )

    def mark_unsigned(manifest, _payload_root):
        manifest["security"]["signed"] = False

    _resign_manifest(fixture, mark_unsigned)

    with pytest.raises(FirmwareCatalogUnavailable):
        build_firmware_catalog(str(tmp_path), fixture["trusted_keys"], True, 1)


def test_unknown_signing_key_is_rejected(tmp_path: Path):
    fixture = stage_signed_bundle(tmp_path)
    _rewrite_catalog(fixture, signing_key_id="unknown-key")

    with pytest.raises(FirmwareCatalogUnavailable):
        build_firmware_catalog(str(tmp_path), fixture["trusted_keys"], True, 1)


def test_signed_manifest_with_bad_artifact_hash_is_rejected(tmp_path: Path):
    fixture = stage_signed_bundle(tmp_path)

    def corrupt_hash(manifest, _payload_root):
        application = next(
            item
            for item in manifest["models"][0]["files"]
            if item["role"] == "application"
        )
        application["sha256"] = "0" * 64

    _resign_manifest(fixture, corrupt_hash)

    with pytest.raises(FirmwareCatalogUnavailable):
        build_firmware_catalog(str(tmp_path), fixture["trusted_keys"], True, 1)


def test_unlisted_payload_file_is_rejected(tmp_path: Path):
    fixture = stage_signed_bundle(tmp_path)
    (fixture["payload_root"] / "unexpected.bin").write_bytes(b"not in the manifest")

    with pytest.raises(FirmwareCatalogUnavailable):
        build_firmware_catalog(str(tmp_path), fixture["trusted_keys"], True, 1)


def test_unlisted_bundle_shell_entry_is_rejected(tmp_path: Path):
    fixture = stage_signed_bundle(tmp_path)
    (fixture["payload_root"].parent / "release-notes.txt").write_text("unexpected")

    with pytest.raises(FirmwareCatalogUnavailable):
        build_firmware_catalog(str(tmp_path), fixture["trusted_keys"], True, 1)


def test_symlinked_artifact_parent_directory_is_rejected(tmp_path: Path):
    fixture = stage_signed_bundle(tmp_path)
    model_directory = fixture["payload_root"] / "reterminal_e1001"
    external_directory = tmp_path / "external-e1001"
    model_directory.rename(external_directory)
    os.symlink(external_directory, model_directory)

    with pytest.raises(FirmwareCatalogUnavailable):
        build_firmware_catalog(str(tmp_path), fixture["trusted_keys"], True, 1)


@pytest.mark.parametrize("role", ["factory_recovery", "../application", "unknown"])
def test_non_preserving_or_unsafe_role_cannot_be_served(tmp_path: Path, role: str):
    fixture = stage_signed_bundle(tmp_path)

    with pytest.raises(FirmwareArtifactNotFound, match="Firmware artifact not found"):
        read_model_artifact(
            str(tmp_path),
            fixture["trusted_keys"],
            True,
            fixture["release_id"],
            "E1001",
            role,
            minimum_catalog_generation=1,
        )


def test_unknown_role_is_404_even_when_browser_flashing_is_disabled(tmp_path: Path):
    fixture = stage_signed_bundle(tmp_path)

    with pytest.raises(FirmwareArtifactNotFound, match="Firmware artifact not found"):
        read_model_artifact(
            str(tmp_path),
            fixture["trusted_keys"],
            False,
            fixture["release_id"],
            "E1001",
            "unknown",
        )


def test_signed_partition_overlap_is_rejected(tmp_path: Path):
    fixture = stage_signed_bundle(tmp_path)

    def overlap_littlefs(manifest, payload_root):
        source_path = payload_root / "reterminal_e1001" / "partitions.csv"
        source = source_path.read_bytes().replace(b"0x310000", b"0x300000")
        source_path.write_bytes(source)
        partition_source = next(
            item
            for item in manifest["models"][0]["files"]
            if item["role"] == "partition_source"
        )
        partition_source["size"] = len(source)
        partition_source["sha256"] = _sha256(source)

    _resign_manifest(fixture, overlap_littlefs)

    with pytest.raises(FirmwareCatalogUnavailable):
        build_firmware_catalog(str(tmp_path), fixture["trusted_keys"], True, 1)
