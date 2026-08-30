"""Pure RET1 validation and ticket-signing primitives.

This module deliberately has no database, HTTP, logging, or browser concerns.
Callers receive stable, non-secret error codes and must keep configuration
plaintext out of persistence and logs.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import re
import stat
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import (
    decode_dss_signature,
    encode_dss_signature,
)


MAX_FRAME_BYTES = 4096
MAX_CONFIG_BYTES = 1536
MAX_SIGNING_KEY_BYTES = 16 * 1024
MAX_TICKET_TTL_SECONDS = 600
UINT32_MAX = (1 << 32) - 1
P256_ORDER = 0xFFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551

SUPPORTED_MODELS = frozenset({"E1001", "E1002", "E1004"})
KEY_ID_RE = re.compile(r"[A-Za-z0-9._-]{1,64}")
LOWER_SHA256_RE = re.compile(r"[0-9a-f]{64}")
LOWER_MAC_RE = re.compile(r"[0-9a-f]{2}(?::[0-9a-f]{2}){5}")
HEX_PSK_RE = re.compile(r"[0-9A-Fa-f]{64}")

STATUS_KEYS = frozenset(
    {
        "v",
        "type",
        "state",
        "model",
        "firmware_version",
        "factory_mac",
        "config_source",
        "config_generation",
        "enrollment_available",
        "enrollment_key_id",
        "identity_strength",
        "attestation",
    }
)
HELLO_KEYS = frozenset({"v", "type", "seq", "client_nonce", "client_public_key"})
HELLO_ACK_KEYS = frozenset(
    {
        "v",
        "type",
        "seq",
        "session_id",
        "session_sha256",
        "device_nonce",
        "device_public_key",
        "model",
        "firmware_version",
        "factory_mac",
        "chip",
        "chip_revision",
        "config_generation",
        "identity_strength",
        "attestation",
    }
)


class EnrollmentProtocolError(ValueError):
    """A fail-closed RET1 error whose text is safe to show or log."""

    def __init__(self, code: str, safe_message: str):
        self.code = code
        self.safe_message = safe_message
        super().__init__(safe_message)


@dataclass(frozen=True)
class ParsedStatus:
    state: str
    model: str
    firmware_version: str
    factory_mac: str
    config_source: str
    config_generation: int
    enrollment_available: bool
    enrollment_key_id: str


@dataclass(frozen=True)
class ParsedHello:
    client_nonce: bytes
    client_public_key: bytes


@dataclass(frozen=True)
class ParsedHelloAck:
    session_id: str
    session_sha256: bytes
    device_nonce: bytes
    device_public_key: bytes
    model: str
    firmware_version: str
    factory_mac: str
    chip_revision: int
    config_generation: int


@dataclass(frozen=True)
class ValidatedHandshake:
    model: str
    mac: str
    firmware_version: str
    generation: int
    transcript_sha256_hex: str
    session_id: str


@dataclass(frozen=True)
class ValidatedConfig:
    sha256_hex: str
    sha256_base64url: str
    schedule_url: str


def _error(code: str, message: str) -> EnrollmentProtocolError:
    return EnrollmentProtocolError(code, message)


def _reject_constant(_value: str) -> None:
    raise ValueError("non-finite JSON number")


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _reject_surrogates(value: Any) -> None:
    if isinstance(value, str):
        value.encode("utf-8", errors="strict")
    elif isinstance(value, dict):
        for key, nested in value.items():
            key.encode("utf-8", errors="strict")
            _reject_surrogates(nested)
    elif isinstance(value, list):
        for nested in value:
            _reject_surrogates(nested)


def _strict_object(value: Any, label: str, *, max_bytes: int = MAX_FRAME_BYTES) -> dict[str, Any]:
    if isinstance(value, Mapping):
        decoded: Any = dict(value)
    elif isinstance(value, (bytes, bytearray, memoryview, str)):
        if isinstance(value, str):
            try:
                raw = value.encode("utf-8", errors="strict")
            except UnicodeError as exc:
                raise _error("invalid_json", f"{label} is not valid UTF-8 JSON") from exc
        else:
            raw = bytes(value)
        if not raw or len(raw) > max_bytes:
            raise _error("invalid_json", f"{label} JSON size is invalid")
        try:
            decoded = json.loads(
                raw.decode("utf-8", errors="strict"),
                object_pairs_hook=_reject_duplicate_keys,
                parse_constant=_reject_constant,
            )
        except (UnicodeError, ValueError, json.JSONDecodeError) as exc:
            raise _error("invalid_json", f"{label} is not valid strict JSON") from exc
    else:
        raise _error("invalid_json", f"{label} must be a JSON object")
    if not isinstance(decoded, dict):
        raise _error("invalid_json", f"{label} must be a JSON object")
    try:
        _reject_surrogates(decoded)
    except UnicodeError as exc:
        raise _error("invalid_json", f"{label} contains invalid Unicode") from exc
    return decoded


def _require_exact_keys(value: Mapping[str, Any], expected: frozenset[str], label: str) -> None:
    if set(value) != expected:
        raise _error("invalid_shape", f"{label} fields are invalid")


def _is_int(value: Any) -> bool:
    return type(value) is int


def _bounded_text(value: Any, label: str, minimum: int, maximum: int) -> str:
    if not isinstance(value, str):
        raise _error("invalid_field", f"{label} is invalid")
    try:
        raw = value.encode("utf-8", errors="strict")
    except UnicodeError as exc:
        raise _error("invalid_field", f"{label} is invalid") from exc
    if len(raw) < minimum or len(raw) > maximum or any(
        byte < 0x20 or byte == 0x7F for byte in raw
    ):
        raise _error("invalid_field", f"{label} is invalid")
    return value


def base64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def decode_canonical_base64url(value: Any, *, length: int, label: str) -> bytes:
    if (
        not isinstance(value, str)
        or not value
        or re.fullmatch(r"[A-Za-z0-9_-]+", value) is None
    ):
        raise _error("invalid_base64url", f"{label} is not canonical base64url")
    try:
        decoded = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except (ValueError, binascii.Error) as exc:
        raise _error("invalid_base64url", f"{label} is not canonical base64url") from exc
    if len(decoded) != length or base64url_encode(decoded) != value:
        raise _error("invalid_base64url", f"{label} is not canonical base64url")
    return decoded


def validate_p256_point(raw: bytes, *, label: str) -> ec.EllipticCurvePublicKey:
    if len(raw) != 65 or raw[0] != 0x04:
        raise _error("invalid_p256_point", f"{label} is not an uncompressed P-256 point")
    try:
        key = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), raw)
    except ValueError as exc:
        raise _error("invalid_p256_point", f"{label} is not a valid P-256 point") from exc
    if key.public_bytes(
        serialization.Encoding.X962,
        serialization.PublicFormat.UncompressedPoint,
    ) != raw:
        raise _error("invalid_p256_point", f"{label} is not a canonical P-256 point")
    return key


def _validate_model(value: Any) -> str:
    if not isinstance(value, str) or value not in SUPPORTED_MODELS:
        raise _error("unsupported_model", "Terminal model is not supported")
    return value


def _validate_mac(value: Any) -> str:
    if not isinstance(value, str) or LOWER_MAC_RE.fullmatch(value) is None:
        raise _error("invalid_mac", "Terminal factory MAC is invalid")
    return value


def _validate_generation(value: Any, *, allow_zero: bool) -> int:
    minimum = 0 if allow_zero else 1
    if not _is_int(value) or value < minimum or value >= UINT32_MAX:
        raise _error("invalid_generation", "Terminal configuration generation is invalid")
    return value


def parse_status(value: Any) -> ParsedStatus:
    status = _strict_object(value, "RET1 status")
    _require_exact_keys(status, STATUS_KEYS, "RET1 status")
    if not _is_int(status["v"]) or status["v"] != 1 or status["type"] != "status":
        raise _error("invalid_status", "RET1 status version or type is invalid")
    if not isinstance(status["state"], str) or status["state"] not in {
        "storage_error",
        "config_ready",
        "provisioning_required",
    }:
        raise _error("invalid_status", "RET1 status state is invalid")
    if not isinstance(status["config_source"], str) or status["config_source"] not in {
        "nvs",
        "file",
        "fallback",
    }:
        raise _error("invalid_status", "RET1 configuration source is invalid")
    if type(status["enrollment_available"]) is not bool:
        raise _error("invalid_status", "RET1 enrollment availability is invalid")
    key_id = status["enrollment_key_id"]
    if status["enrollment_available"]:
        if not isinstance(key_id, str) or KEY_ID_RE.fullmatch(key_id) is None:
            raise _error("invalid_status", "RET1 enrollment key id is invalid")
    elif key_id != "":
        raise _error("invalid_status", "Unavailable RET1 status declares a key id")
    if status["identity_strength"] != "physical_cable_only" or status["attestation"] is not False:
        raise _error("invalid_identity", "RET1 identity claim is invalid")
    return ParsedStatus(
        state=status["state"],
        model=_validate_model(status["model"]),
        firmware_version=_bounded_text(status["firmware_version"], "Firmware version", 1, 128),
        factory_mac=_validate_mac(status["factory_mac"]),
        config_source=status["config_source"],
        config_generation=_validate_generation(status["config_generation"], allow_zero=True),
        enrollment_available=status["enrollment_available"],
        enrollment_key_id=key_id,
    )


def parse_hello(value: Any) -> ParsedHello:
    hello = _strict_object(value, "RET1 hello")
    _require_exact_keys(hello, HELLO_KEYS, "RET1 hello")
    if (
        not _is_int(hello["v"])
        or hello["v"] != 1
        or hello["type"] != "hello"
        or not _is_int(hello["seq"])
        or hello["seq"] != 0
    ):
        raise _error("invalid_hello", "RET1 hello version, type, or sequence is invalid")
    client_nonce = decode_canonical_base64url(
        hello["client_nonce"], length=32, label="Client nonce"
    )
    client_public_key = decode_canonical_base64url(
        hello["client_public_key"], length=65, label="Client public key"
    )
    validate_p256_point(client_public_key, label="Client public key")
    return ParsedHello(client_nonce=client_nonce, client_public_key=client_public_key)


def parse_hello_ack(value: Any) -> ParsedHelloAck:
    ack = _strict_object(value, "RET1 hello acknowledgement")
    _require_exact_keys(ack, HELLO_ACK_KEYS, "RET1 hello acknowledgement")
    if (
        not _is_int(ack["v"])
        or ack["v"] != 1
        or ack["type"] != "hello_ack"
        or not _is_int(ack["seq"])
        or ack["seq"] != 0
    ):
        raise _error(
            "invalid_hello_ack",
            "RET1 hello acknowledgement version, type, or sequence is invalid",
        )
    session_sha256 = decode_canonical_base64url(
        ack["session_sha256"], length=32, label="Session digest"
    )
    session_id_bytes = decode_canonical_base64url(
        ack["session_id"], length=16, label="Session id"
    )
    if session_id_bytes != session_sha256[:16]:
        raise _error("session_mismatch", "RET1 session id does not match its digest")
    device_nonce = decode_canonical_base64url(
        ack["device_nonce"], length=32, label="Device nonce"
    )
    device_public_key = decode_canonical_base64url(
        ack["device_public_key"], length=65, label="Device public key"
    )
    validate_p256_point(device_public_key, label="Device public key")
    if ack["chip"] != "ESP32-S3" or not _is_int(ack["chip_revision"]) or not (
        0 <= ack["chip_revision"] <= 255
    ):
        raise _error("invalid_chip", "RET1 chip identity is invalid")
    if ack["identity_strength"] != "physical_cable_only" or ack["attestation"] is not False:
        raise _error("invalid_identity", "RET1 identity claim is invalid")
    return ParsedHelloAck(
        session_id=ack["session_id"],
        session_sha256=session_sha256,
        device_nonce=device_nonce,
        device_public_key=device_public_key,
        model=_validate_model(ack["model"]),
        firmware_version=_bounded_text(ack["firmware_version"], "Firmware version", 1, 128),
        factory_mac=_validate_mac(ack["factory_mac"]),
        chip_revision=ack["chip_revision"],
        config_generation=_validate_generation(ack["config_generation"], allow_zero=True),
    )


def _field(raw: bytes) -> bytes:
    if len(raw) > 0xFFFF:
        raise _error("transcript_field_too_large", "RET1 transcript field is too large")
    return len(raw).to_bytes(2, "big") + raw


def reconstruct_transcript(hello: ParsedHello, ack: ParsedHelloAck) -> bytes:
    return b"RET1-HS1" + b"".join(
        _field(raw)
        for raw in (
            ack.model.encode("utf-8"),
            ack.firmware_version.encode("utf-8"),
            ack.factory_mac.encode("ascii"),
            hello.client_public_key,
            hello.client_nonce,
            ack.device_public_key,
            ack.device_nonce,
        )
    )


def validate_handshake(
    status: Any,
    hello: Any,
    hello_ack: Any,
    *,
    expected_key_id: str,
) -> ValidatedHandshake:
    if not isinstance(expected_key_id, str) or KEY_ID_RE.fullmatch(expected_key_id) is None:
        raise _error("invalid_expected_key", "Configured RET1 key id is invalid")
    parsed_status = parse_status(status)
    parsed_hello = parse_hello(hello)
    parsed_ack = parse_hello_ack(hello_ack)
    if not parsed_status.enrollment_available or parsed_status.state == "storage_error":
        raise _error("enrollment_unavailable", "Terminal enrollment is unavailable")
    if parsed_status.enrollment_key_id != expected_key_id:
        raise _error("key_mismatch", "Terminal enrollment key does not match the server")
    if (
        parsed_status.model != parsed_ack.model
        or parsed_status.firmware_version != parsed_ack.firmware_version
        or parsed_status.factory_mac != parsed_ack.factory_mac
        or parsed_status.config_generation != parsed_ack.config_generation
    ):
        raise _error("status_mismatch", "RET1 status and handshake identity disagree")
    transcript_sha256 = hashlib.sha256(
        reconstruct_transcript(parsed_hello, parsed_ack)
    ).digest()
    if transcript_sha256 != parsed_ack.session_sha256:
        raise _error("transcript_mismatch", "RET1 handshake transcript is invalid")
    expected_session_id = base64url_encode(transcript_sha256[:16])
    if parsed_ack.session_id != expected_session_id:
        raise _error("session_mismatch", "RET1 session id is invalid")
    return ValidatedHandshake(
        model=parsed_ack.model,
        mac=parsed_ack.factory_mac,
        firmware_version=parsed_ack.firmware_version,
        generation=parsed_ack.config_generation,
        transcript_sha256_hex=transcript_sha256.hex(),
        session_id=expected_session_id,
    )


def _contains_control(value: str) -> bool:
    return any(ord(character) < 0x20 or ord(character) == 0x7F for character in value)


def _strict_query_key(raw: str) -> str:
    output = bytearray()
    index = 0
    encoded = raw.encode("utf-8", errors="strict")
    while index < len(encoded):
        value = encoded[index]
        if value == ord("+"):
            output.append(ord(" "))
        elif value == ord("%"):
            if index + 2 >= len(encoded):
                raise _error("invalid_schedule_url", "Schedule URL query is invalid")
            pair = bytes(encoded[index + 1 : index + 3])
            try:
                output.append(int(pair, 16))
            except ValueError as exc:
                raise _error("invalid_schedule_url", "Schedule URL query is invalid") from exc
            index += 2
        else:
            output.append(value)
        index += 1
    try:
        return output.decode("utf-8", errors="strict")
    except UnicodeError as exc:
        raise _error("invalid_schedule_url", "Schedule URL query is invalid") from exc


def _validate_schedule_url(value: str) -> None:
    if not value.startswith("https://") or any(character.isspace() for character in value):
        raise _error("invalid_schedule_url", "Schedule URL must use HTTPS")
    try:
        split = urlsplit(value)
        port = split.port
    except ValueError as exc:
        raise _error("invalid_schedule_url", "Schedule URL is invalid") from exc
    if (
        split.scheme != "https"
        or not split.netloc
        or not split.hostname
        or (port is not None and not 1 <= port <= 65535)
    ):
        raise _error("invalid_schedule_url", "Schedule URL is invalid")
    lowered = value.lower()
    if any(
        marker in lowered
        for marker in (
            "replace_with",
            "your_terminal",
            ".example.test",
            "{",
            "}",
            "<",
            ">",
            "%7b",
            "%7d",
        )
    ):
        raise _error("invalid_schedule_url", "Schedule URL contains a template marker")
    query = value.split("?", 1)[1].split("#", 1)[0] if "?" in value else ""
    if query:
        for field in query.split("&"):
            key = field.split("=", 1)[0]
            if _strict_query_key(key).lower() == "variant":
                raise _error("invalid_schedule_url", "Schedule URL reserves the variant query")


def validate_config_and_hash(
    config: bytes | bytearray | memoryview | str,
    *,
    expected_schedule_url: str | None = None,
) -> ValidatedConfig:
    if isinstance(config, str):
        try:
            raw = config.encode("utf-8", errors="strict")
        except UnicodeError as exc:
            raise _error("invalid_config", "Terminal configuration is not valid UTF-8") from exc
    elif isinstance(config, (bytes, bytearray, memoryview)):
        raw = bytes(config)
    else:
        raise _error("invalid_config", "Terminal configuration must be JSON bytes")
    decoded = _strict_object(raw, "Terminal configuration", max_bytes=MAX_CONFIG_BYTES)
    _require_exact_keys(
        decoded,
        frozenset({"schema_version", "wifi", "server"}),
        "Terminal configuration",
    )
    if not _is_int(decoded["schema_version"]) or decoded["schema_version"] != 1:
        raise _error("invalid_config", "Terminal configuration schema is invalid")
    wifi = decoded["wifi"]
    server = decoded["server"]
    if not isinstance(wifi, dict) or not isinstance(server, dict):
        raise _error("invalid_config", "Terminal configuration sections are invalid")
    _require_exact_keys(wifi, frozenset({"ssid", "password"}), "Wi-Fi configuration")
    _require_exact_keys(server, frozenset({"schedule_url"}), "Server configuration")
    ssid = wifi["ssid"]
    password = wifi["password"]
    schedule_url = server["schedule_url"]
    if (
        not isinstance(ssid, str)
        or not isinstance(password, str)
        or not isinstance(schedule_url, str)
    ):
        raise _error("invalid_config", "Terminal configuration values are invalid")
    ssid_bytes = ssid.encode("utf-8", errors="strict")
    password_bytes = password.encode("utf-8", errors="strict")
    schedule_bytes = schedule_url.encode("utf-8", errors="strict")
    password_valid = len(password_bytes) <= 63 or (
        len(password_bytes) == 64 and HEX_PSK_RE.fullmatch(password) is not None
    )
    if (
        not ssid_bytes
        or len(ssid_bytes) > 32
        or not any(not character.isspace() for character in ssid)
        or not password_valid
        or not schedule_bytes
        or len(schedule_bytes) > 1024
        or _contains_control(ssid)
        or _contains_control(password)
        or _contains_control(schedule_url)
    ):
        raise _error("invalid_config", "Terminal configuration values are invalid")
    _validate_schedule_url(schedule_url)
    if expected_schedule_url is not None and schedule_url != expected_schedule_url:
        raise _error("schedule_url_mismatch", "Terminal schedule URL does not match the server")
    digest = hashlib.sha256(raw).digest()
    return ValidatedConfig(
        sha256_hex=digest.hex(),
        sha256_base64url=base64url_encode(digest),
        schedule_url=schedule_url,
    )


def _validate_sha256_hex(value: Any, label: str) -> bytes:
    if not isinstance(value, str) or LOWER_SHA256_RE.fullmatch(value) is None:
        raise _error("invalid_digest", f"{label} is invalid")
    return bytes.fromhex(value)


def _ticket_text(value: Any, label: str, minimum: int, maximum: int) -> str:
    return _bounded_text(value, label, minimum, maximum)


def sign_enrollment_ticket(
    key: ec.EllipticCurvePrivateKey,
    *,
    kid: str,
    operation: str,
    session_sha256_hex: str,
    model: str,
    mac: str,
    terminal_id: str,
    config_sha256_hex: str,
    generation: int,
    jti: str,
    issued_at: int,
    expires_at: int,
) -> str:
    if not isinstance(key, ec.EllipticCurvePrivateKey) or not isinstance(
        key.curve, ec.SECP256R1
    ):
        raise _error("invalid_signing_key", "RET1 signing key is not P-256")
    if not isinstance(kid, str) or KEY_ID_RE.fullmatch(kid) is None:
        raise _error("invalid_kid", "RET1 signing key id is invalid")
    if not isinstance(operation, str) or operation not in {"provision", "rollback"}:
        raise _error("invalid_operation", "RET1 ticket operation is invalid")
    session_sha256 = _validate_sha256_hex(session_sha256_hex, "Session digest")
    config_sha256 = _validate_sha256_hex(config_sha256_hex, "Configuration digest")
    model = _validate_model(model)
    mac = _validate_mac(mac)
    terminal_id = _ticket_text(terminal_id, "Terminal id", 1, 128)
    jti = _ticket_text(jti, "Ticket id", 16, 128)
    generation = _validate_generation(generation, allow_zero=False)
    if (
        not _is_int(issued_at)
        or not _is_int(expires_at)
        or issued_at <= 0
        or expires_at <= issued_at
        or expires_at - issued_at > MAX_TICKET_TTL_SECONDS
    ):
        raise _error("invalid_ticket_time", "RET1 ticket time window is invalid")

    protected = {"alg": "ES256", "kid": kid, "typ": "RET-ENROLL"}
    payload = {
        "v": 1,
        "purpose": "terminal-enrollment",
        "operation": operation,
        "session_sha256": base64url_encode(session_sha256),
        "device_model": model,
        "device_mac": mac,
        "terminal_id": terminal_id,
        "config_sha256": base64url_encode(config_sha256),
        "generation": generation,
        "jti": jti,
        "issued_at": issued_at,
        "expires_at": expires_at,
    }
    header_segment = base64url_encode(
        json.dumps(protected, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    )
    payload_segment = base64url_encode(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    )
    signing_input = f"{header_segment}.{payload_segment}".encode("ascii")
    der_signature = key.sign(signing_input, ec.ECDSA(hashes.SHA256()))
    r, s = decode_dss_signature(der_signature)
    if s > P256_ORDER // 2:
        s = P256_ORDER - s
    raw_signature = r.to_bytes(32, "big") + s.to_bytes(32, "big")
    compact = f"{header_segment}.{payload_segment}.{base64url_encode(raw_signature)}"
    if len(compact.encode("ascii")) > 3072:
        raise _error("ticket_too_large", "RET1 ticket exceeds the firmware limit")
    return compact


def verify_ticket_signature_for_test(
    public_key: ec.EllipticCurvePublicKey,
    compact_jws: str,
) -> None:
    """Verify a compact raw-R||S ticket; useful for isolated parity tests."""
    try:
        header, payload, signature = compact_jws.split(".")
    except ValueError as exc:
        raise _error("invalid_ticket", "RET1 compact ticket is invalid") from exc
    raw = decode_canonical_base64url(signature, length=64, label="Ticket signature")
    r = int.from_bytes(raw[:32], "big")
    s = int.from_bytes(raw[32:], "big")
    try:
        public_key.verify(
            encode_dss_signature(r, s),
            f"{header}.{payload}".encode("ascii"),
            ec.ECDSA(hashes.SHA256()),
        )
    except Exception as exc:
        raise _error("invalid_ticket_signature", "RET1 ticket signature is invalid") from exc


def load_signing_key(
    path: str | os.PathLike[str],
) -> tuple[ec.EllipticCurvePrivateKey, str]:
    key_path = Path(path)
    try:
        before = key_path.lstat()
    except OSError as exc:
        raise _error("signing_key_unavailable", "RET1 signing key is unavailable") from exc
    mode = stat.S_IMODE(before.st_mode)
    if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
        raise _error("unsafe_signing_key", "RET1 signing key must be a regular file")
    if before.st_uid != os.geteuid():
        raise _error("unsafe_signing_key_owner", "RET1 signing key ownership is unsafe")
    if mode not in {0o400, 0o600}:
        raise _error("unsafe_signing_key_mode", "RET1 signing key permissions are unsafe")
    if before.st_size <= 0 or before.st_size > MAX_SIGNING_KEY_BYTES:
        raise _error("unsafe_signing_key_size", "RET1 signing key size is unsafe")

    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    descriptor: int | None = None
    try:
        descriptor = os.open(key_path, flags)
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino)
            or opened.st_uid != before.st_uid
            or opened.st_size != before.st_size
            or stat.S_IMODE(opened.st_mode) != mode
            or stat.S_IMODE(opened.st_mode) not in {0o400, 0o600}
        ):
            raise _error("unsafe_signing_key", "RET1 signing key changed while opening")
        raw = bytearray()
        remaining = opened.st_size
        while remaining:
            chunk = os.read(descriptor, min(4096, remaining))
            if not chunk:
                raise _error("signing_key_unavailable", "RET1 signing key could not be read")
            raw.extend(chunk)
            remaining -= len(chunk)
        if os.read(descriptor, 1):
            raise _error("unsafe_signing_key", "RET1 signing key changed while reading")
    except EnrollmentProtocolError:
        raise
    except OSError as exc:
        raise _error("signing_key_unavailable", "RET1 signing key is unavailable") from exc
    finally:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass

    try:
        try:
            loaded = serialization.load_pem_private_key(bytes(raw), password=None)
        except ValueError:
            loaded = serialization.load_der_private_key(bytes(raw), password=None)
    except (TypeError, ValueError) as exc:
        raise _error("invalid_signing_key", "RET1 signing key could not be decoded") from exc
    finally:
        for index in range(len(raw)):
            raw[index] = 0
    if not isinstance(loaded, ec.EllipticCurvePrivateKey) or not isinstance(
        loaded.curve, ec.SECP256R1
    ):
        raise _error("invalid_signing_key", "RET1 signing key is not P-256")
    public_bytes = loaded.public_key().public_bytes(
        serialization.Encoding.X962,
        serialization.PublicFormat.UncompressedPoint,
    )
    return loaded, hashlib.sha256(public_bytes).hexdigest()
