"""Byte-parity and fail-closed tests for the pure RET1 protocol core."""

from __future__ import annotations

import base64
import hashlib
import json
import os
from copy import deepcopy

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature

from backend.services.terminal.enrollment_protocol import (
    HELLO_ACK_KEYS,
    P256_ORDER,
    EnrollmentProtocolError,
    base64url_encode,
    load_signing_key,
    parse_hello,
    parse_hello_ack,
    parse_status,
    sign_enrollment_ticket,
    validate_config_and_hash,
    validate_handshake,
    validate_p256_point,
    verify_ticket_signature_for_test,
)


CLIENT_PUBLIC = (
    "BGsX0fLhLEJH-Lzm5WOkQPJ3A32BLeszoPShOUXYmMKWT-NC4v4af5uO5-tKfA-eFivOM1drMV7Oy7ZAaDe_UfU"
)
DEVICE_PUBLIC = (
    "BHzyexiNA09-ilI4AwS1GsPAiWnid_IbNaYLSPxHZpl4B3dVENuO0EApPZrGn3Qw27p9reY86YIpngS3nSJ4c9E"
)
CLIENT_NONCE = "AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8"
DEVICE_NONCE = "ICEiIyQlJicoKSorLC0uLzAxMjM0NTY3ODk6Ozw9Pj8"
TRANSCRIPT_SHA256 = "5ee3ed3509c67969cc2d8924386a2557a1ab9be2ce6ea5f329582275af4c3fca"
SESSION_ID = "XuPtNQnGeWnMLYkkOGolVw"
CONFIG = (
    b'{"schema_version":1,"wifi":{"ssid":"FixtureWiFi","password":"correct horse"},'
    b'"server":{"schedule_url":"https://email.mcchord.net/terminal/FIXTURE/schedule.json"}}'
)
CONFIG_SHA256 = "7c41cd4d502120a909e1cf606953999941e8157a6f685e5e67c9bbfbe419bf83"


def _status() -> dict:
    return {
        "v": 1,
        "type": "status",
        "state": "provisioning_required",
        "model": "E1002",
        "firmware_version": "0.2.0-candidate.3",
        "factory_mac": "aa:bb:cc:dd:ee:ff",
        "config_source": "fallback",
        "config_generation": 0,
        "enrollment_available": True,
        "enrollment_key_id": "fixture-2026",
        "identity_strength": "physical_cable_only",
        "attestation": False,
    }


def _hello() -> dict:
    return {
        "v": 1,
        "type": "hello",
        "seq": 0,
        "client_nonce": CLIENT_NONCE,
        "client_public_key": CLIENT_PUBLIC,
    }


def _ack() -> dict:
    return {
        "v": 1,
        "type": "hello_ack",
        "seq": 0,
        "session_id": SESSION_ID,
        "session_sha256": base64url_encode(bytes.fromhex(TRANSCRIPT_SHA256)),
        "device_nonce": DEVICE_NONCE,
        "device_public_key": DEVICE_PUBLIC,
        "model": "E1002",
        "firmware_version": "0.2.0-candidate.3",
        "factory_mac": "aa:bb:cc:dd:ee:ff",
        "chip": "ESP32-S3",
        "chip_revision": 1,
        "config_generation": 0,
        "identity_strength": "physical_cable_only",
        "attestation": False,
    }


def _decode_segment(value: str) -> dict:
    return json.loads(base64.urlsafe_b64decode(value + "=" * (-len(value) % 4)))


def test_firmware_vector_handshake_has_exact_transcript_parity():
    validated = validate_handshake(
        _status(),
        _hello(),
        _ack(),
        expected_key_id="fixture-2026",
    )

    assert validated.model == "E1002"
    assert validated.mac == "aa:bb:cc:dd:ee:ff"
    assert validated.firmware_version == "0.2.0-candidate.3"
    assert validated.generation == 0
    assert validated.transcript_sha256_hex == TRANSCRIPT_SHA256
    assert validated.session_id == SESSION_ID


@pytest.mark.parametrize(
    ("target", "field", "value", "code"),
    (
        ("status", "model", "E1001", "status_mismatch"),
        ("status", "firmware_version", "0.2.0-other", "status_mismatch"),
        ("status", "factory_mac", "aa:bb:cc:dd:ee:00", "status_mismatch"),
        ("status", "config_generation", 1, "status_mismatch"),
        ("status", "enrollment_available", False, "enrollment_unavailable"),
        ("ack", "identity_strength", "attested", "invalid_identity"),
        ("ack", "attestation", True, "invalid_identity"),
        ("ack", "chip", "ESP32", "invalid_chip"),
    ),
)
def test_handshake_identity_and_status_disagreement_fails_closed(
    target: str,
    field: str,
    value,
    code: str,
):
    status = _status()
    ack = _ack()
    (status if target == "status" else ack)[field] = value
    if field == "enrollment_available":
        status["enrollment_key_id"] = ""

    with pytest.raises(EnrollmentProtocolError) as caught:
        validate_handshake(status, _hello(), ack, expected_key_id="fixture-2026")

    assert caught.value.code == code
    assert caught.value.safe_message == str(caught.value)


def test_handshake_requires_configured_available_key():
    with pytest.raises(EnrollmentProtocolError) as mismatch:
        validate_handshake(
            _status(), _hello(), _ack(), expected_key_id="different-key"
        )
    assert mismatch.value.code == "key_mismatch"

    unavailable = _status()
    unavailable.update(enrollment_available=False, enrollment_key_id="")
    with pytest.raises(EnrollmentProtocolError) as closed:
        validate_handshake(
            unavailable, _hello(), _ack(), expected_key_id="fixture-2026"
        )
    assert closed.value.code == "enrollment_unavailable"


def test_transcript_or_session_tampering_is_rejected():
    ack = _ack()
    ack["device_nonce"] = base64url_encode(b"x" * 32)
    with pytest.raises(EnrollmentProtocolError) as caught:
        validate_handshake(_status(), _hello(), ack, expected_key_id="fixture-2026")
    assert caught.value.code == "transcript_mismatch"

    ack = _ack()
    ack["session_id"] = base64url_encode(b"y" * 16)
    with pytest.raises(EnrollmentProtocolError) as caught:
        parse_hello_ack(ack)
    assert caught.value.code == "session_mismatch"


@pytest.mark.parametrize("parser,value", [
    (parse_status, _status()),
    (parse_hello, _hello()),
    (parse_hello_ack, _ack()),
])
def test_protocol_messages_require_exact_keys(parser, value):
    candidate = deepcopy(value)
    candidate["unexpected"] = True
    with pytest.raises(EnrollmentProtocolError) as caught:
        parser(candidate)
    assert caught.value.code == "invalid_shape"


def test_raw_json_rejects_duplicate_keys_and_non_integer_version_sequence():
    raw = (
        b'{"v":1,"v":1,"type":"hello","seq":0,"client_nonce":"'
        + CLIENT_NONCE.encode()
        + b'","client_public_key":"'
        + CLIENT_PUBLIC.encode()
        + b'"}'
    )
    with pytest.raises(EnrollmentProtocolError) as duplicate:
        parse_hello(raw)
    assert duplicate.value.code == "invalid_json"

    hello = _hello()
    hello["v"] = True
    with pytest.raises(EnrollmentProtocolError):
        parse_hello(hello)


@pytest.mark.parametrize(
    ("field", "value"),
    (("state", {}), ("config_source", [])),
)
def test_status_hostile_container_types_return_protocol_errors(field: str, value):
    status = _status()
    status[field] = value
    with pytest.raises(EnrollmentProtocolError) as caught:
        parse_status(status)
    assert caught.value.code == "invalid_status"
    hello = _hello()
    hello["seq"] = False
    with pytest.raises(EnrollmentProtocolError):
        parse_hello(hello)


@pytest.mark.parametrize("field", ["client_nonce", "client_public_key"])
def test_base64url_must_be_canonical_and_unpadded(field: str):
    hello = _hello()
    hello[field] += "="
    with pytest.raises(EnrollmentProtocolError) as caught:
        parse_hello(hello)
    assert caught.value.code == "invalid_base64url"


def test_p256_points_are_uncompressed_canonical_and_on_curve():
    with pytest.raises(EnrollmentProtocolError):
        validate_p256_point(b"\x04" + b"\x00" * 64, label="Generated test point")
    with pytest.raises(EnrollmentProtocolError):
        validate_p256_point(b"\x02" + b"\x00" * 32, label="Generated test point")


def test_config_matches_firmware_vector_and_exact_schedule():
    result = validate_config_and_hash(
        CONFIG,
        expected_schedule_url=(
            "https://email.mcchord.net/terminal/FIXTURE/schedule.json"
        ),
    )
    assert result.sha256_hex == CONFIG_SHA256
    assert result.sha256_base64url == base64url_encode(bytes.fromhex(CONFIG_SHA256))


@pytest.mark.parametrize(
    "raw",
    (
        b'{"schema_version":1,"schema_version":1,"wifi":{},"server":{}}',
        b'{"schema_version":1,"wifi":{"ssid":"x","password":""},"server":{"schedule_url":"https://mail.test/schedule.json"},"extra":true}',
        b'{"schema_version":1,"wifi":{"ssid":"\\ud800","password":""},"server":{"schedule_url":"https://mail.test/schedule.json"}}',
        b'{"schema_version":1,"wifi":{"ssid":"x","password":""},"server":{"schedule_url":"http://mail.test/schedule.json"}}',
        b'{"schema_version":1,"wifi":{"ssid":"x","password":""},"server":{"schedule_url":"https://mail.test/schedule.json?%76ariant=bw"}}',
        b'{"schema_version":1,"wifi":{"ssid":"x","password":"yyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyy"},"server":{"schedule_url":"https://mail.test/schedule.json"}}',
    ),
)
def test_config_shape_unicode_url_and_password_fail_closed(raw: bytes):
    with pytest.raises(EnrollmentProtocolError):
        validate_config_and_hash(raw)


def test_config_accepts_legacy_64_hex_psk_but_binds_exact_raw_json():
    raw = json.dumps(
        {
            "schema_version": 1,
            "wifi": {"ssid": "Fixture", "password": "A" * 64},
            "server": {"schedule_url": "https://mail.test/schedule.json"},
        },
        separators=(",", ":"),
    ).encode()
    first = validate_config_and_hash(raw)
    second = validate_config_and_hash(raw + b"\n")
    assert first.sha256_hex != second.sha256_hex

    with pytest.raises(EnrollmentProtocolError) as caught:
        validate_config_and_hash(
            raw,
            expected_schedule_url="https://mail.test/other/schedule.json",
        )
    assert caught.value.code == "schedule_url_mismatch"


def test_config_wrong_python_type_returns_protocol_error():
    with pytest.raises(EnrollmentProtocolError) as caught:
        validate_config_and_hash(123)  # type: ignore[arg-type]
    assert caught.value.code == "invalid_config"


def test_ticket_has_exact_claims_raw_signature_and_valid_es256():
    key = ec.derive_private_key(3, ec.SECP256R1())
    compact = sign_enrollment_ticket(
        key,
        kid="fixture-2026",
        operation="provision",
        session_sha256_hex=TRANSCRIPT_SHA256,
        model="E1002",
        mac="aa:bb:cc:dd:ee:ff",
        terminal_id="fixture-terminal",
        config_sha256_hex=CONFIG_SHA256,
        generation=1,
        jti="fixture-ticket-0001",
        issued_at=1_788_050_000,
        expires_at=1_788_050_300,
    )
    header_segment, payload_segment, signature_segment = compact.split(".")
    header = _decode_segment(header_segment)
    payload = _decode_segment(payload_segment)
    signature = base64.urlsafe_b64decode(
        signature_segment + "=" * (-len(signature_segment) % 4)
    )

    assert header == {"alg": "ES256", "kid": "fixture-2026", "typ": "RET-ENROLL"}
    assert set(payload) == {
        "v",
        "purpose",
        "operation",
        "session_sha256",
        "device_model",
        "device_mac",
        "terminal_id",
        "config_sha256",
        "generation",
        "jti",
        "issued_at",
        "expires_at",
    }
    assert payload["session_sha256"] == base64url_encode(bytes.fromhex(TRANSCRIPT_SHA256))
    assert payload["config_sha256"] == base64url_encode(bytes.fromhex(CONFIG_SHA256))
    assert len(signature) == 64
    assert int.from_bytes(signature[32:], "big") <= P256_ORDER // 2
    verify_ticket_signature_for_test(key.public_key(), compact)

    r = int.from_bytes(signature[:32], "big")
    s = int.from_bytes(signature[32:], "big")
    key.public_key().verify(
        encode_dss_signature(r, s),
        f"{header_segment}.{payload_segment}".encode(),
        ec.ECDSA(hashes.SHA256()),
    )


@pytest.mark.parametrize(
    ("override", "code"),
    (
        ({"operation": "erase"}, "invalid_operation"),
        ({"generation": 0}, "invalid_generation"),
        ({"generation": (1 << 32) - 1}, "invalid_generation"),
        ({"expires_at": 1_788_050_601}, "invalid_ticket_time"),
        ({"jti": "short"}, "invalid_field"),
        ({"session_sha256_hex": "A" * 64}, "invalid_digest"),
        ({"operation": {}}, "invalid_operation"),
        ({"terminal_id": "bad\ud800value"}, "invalid_field"),
    ),
)
def test_ticket_inputs_fail_closed(override: dict, code: str):
    values = {
        "kid": "fixture-2026",
        "operation": "provision",
        "session_sha256_hex": TRANSCRIPT_SHA256,
        "model": "E1002",
        "mac": "aa:bb:cc:dd:ee:ff",
        "terminal_id": "fixture-terminal",
        "config_sha256_hex": CONFIG_SHA256,
        "generation": 1,
        "jti": "fixture-ticket-0001",
        "issued_at": 1_788_050_000,
        "expires_at": 1_788_050_300,
    }
    values.update(override)
    with pytest.raises(EnrollmentProtocolError) as caught:
        sign_enrollment_ticket(ec.generate_private_key(ec.SECP256R1()), **values)
    assert caught.value.code == code


def test_signing_key_loader_requires_protected_regular_p256_file(tmp_path):
    source_key = ec.derive_private_key(7, ec.SECP256R1())
    pem = source_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    path = tmp_path / "ret1-key.pem"
    path.write_bytes(pem)
    path.chmod(0o600)

    loaded, public_hash = load_signing_key(path)

    expected_public = source_key.public_key().public_bytes(
        serialization.Encoding.X962,
        serialization.PublicFormat.UncompressedPoint,
    )
    assert loaded.private_numbers().private_value == 7
    assert public_hash == hashlib.sha256(expected_public).hexdigest()


def test_signing_key_loader_rejects_symlink_permissions_curve_and_size(tmp_path):
    key = ec.generate_private_key(ec.SECP256R1())
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    target = tmp_path / "target.pem"
    target.write_bytes(pem)
    target.chmod(0o600)
    link = tmp_path / "link.pem"
    link.symlink_to(target)
    with pytest.raises(EnrollmentProtocolError) as symlink:
        load_signing_key(link)
    assert symlink.value.code == "unsafe_signing_key"

    target.chmod(0o644)
    with pytest.raises(EnrollmentProtocolError) as mode:
        load_signing_key(target)
    assert mode.value.code == "unsafe_signing_key_mode"

    wrong_curve = ec.generate_private_key(ec.SECP384R1()).private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    target.write_bytes(wrong_curve)
    target.chmod(0o400)
    with pytest.raises(EnrollmentProtocolError) as curve:
        load_signing_key(target)
    assert curve.value.code == "invalid_signing_key"

    target.chmod(0o600)
    target.write_bytes(os.urandom(16 * 1024 + 1))
    target.chmod(0o600)
    with pytest.raises(EnrollmentProtocolError) as size:
        load_signing_key(target)
    assert size.value.code == "unsafe_signing_key_size"


def test_signing_key_loader_rejects_a_file_not_owned_by_the_process(tmp_path, monkeypatch):
    key = ec.generate_private_key(ec.SECP256R1())
    path = tmp_path / "ret1-owner.pem"
    path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    path.chmod(0o600)
    monkeypatch.setattr(os, "geteuid", lambda: path.stat().st_uid + 1)

    with pytest.raises(EnrollmentProtocolError) as owner:
        load_signing_key(path)

    assert owner.value.code == "unsafe_signing_key_owner"


def test_hello_ack_fixture_tracks_exact_firmware_shape():
    assert set(_ack()) == HELLO_ACK_KEYS
