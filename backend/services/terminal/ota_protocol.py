"""Exact, transport-independent OTA1 offer and event protocol.

The live application does not route or persist these values yet.  Keeping the
codec and attempt state machine independent from FastAPI and SQLAlchemy lets the
server and firmware agree on a bounded wire contract before any update path can
be enabled.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any

from backend.services.terminal.ota_policy import SHA256_RE, VERSION_RE


OTA_PROTOCOL_SCHEMA = 1
MAX_OFFER_BYTES = 3072
MAX_EVENT_BYTES = 2048
MAX_URL_BYTES = 512
UINT32_MAX = 4_294_967_295

UUID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
)
BUILD_ID_RE = re.compile(r"[0-9a-f]{40}")
CREDENTIAL_RE = re.compile(r"[A-Za-z0-9_-]{43}")
EVENT_TOKEN_RE = re.compile(r"[a-z0-9_]{1,64}")

OFFER_FIELDS = frozenset(
    {
        "schema_version",
        "offer_id",
        "attempt_id",
        "release_id",
        "version",
        "manifest_url",
        "signature_url",
        "application_url",
        "event_url",
        "required",
    }
)
EVENT_FIELDS = frozenset(
    {
        "schema_version",
        "event_id",
        "attempt_id",
        "offer_id",
        "sequence",
        "release_id",
        "state",
        "running_version",
        "running_build_id",
        "running_partition",
        "boot_count",
        "reset_reason",
        "error_code",
    }
)


class OtaProtocolError(ValueError):
    """A bounded OTA1 protocol value is invalid."""


class AttemptState(str, Enum):
    OFFERED = "offered"
    DOWNLOADING = "downloading"
    STAGED = "staged"
    BOOTED_PENDING_VALIDATION = "booted_pending_validation"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"
    RECOVERY_REQUIRED = "recovery_required"


class TransitionDecision(str, Enum):
    ADVANCE = "advance"
    ADVANCE_WITH_GAP = "advance_with_gap"
    REJECT = "reject"


class ReplayDecision(str, Enum):
    DISTINCT = "distinct"
    IDEMPOTENT = "idempotent"
    CONFLICT = "conflict"


@dataclass(frozen=True)
class OtaOffer:
    schema_version: int
    offer_id: str
    attempt_id: str
    release_id: str
    version: str
    manifest_url: str
    signature_url: str
    application_url: str
    event_url: str
    required: bool


@dataclass(frozen=True)
class OtaEvent:
    schema_version: int
    event_id: str
    attempt_id: str
    offer_id: str
    sequence: int
    release_id: str
    state: AttemptState
    running_version: str
    running_build_id: str
    running_partition: str
    boot_count: int
    reset_reason: str | None
    error_code: str | None


_ADJACENT: dict[AttemptState, frozenset[AttemptState]] = {
    AttemptState.OFFERED: frozenset(
        {AttemptState.DOWNLOADING, AttemptState.FAILED}
    ),
    AttemptState.DOWNLOADING: frozenset(
        {AttemptState.STAGED, AttemptState.FAILED}
    ),
    AttemptState.STAGED: frozenset(
        {
            AttemptState.BOOTED_PENDING_VALIDATION,
            AttemptState.ROLLED_BACK,
            AttemptState.RECOVERY_REQUIRED,
        }
    ),
    AttemptState.BOOTED_PENDING_VALIDATION: frozenset(
        {
            AttemptState.SUCCEEDED,
            AttemptState.ROLLED_BACK,
            AttemptState.RECOVERY_REQUIRED,
        }
    ),
    AttemptState.SUCCEEDED: frozenset(),
    AttemptState.FAILED: frozenset(),
    AttemptState.ROLLED_BACK: frozenset(),
    AttemptState.RECOVERY_REQUIRED: frozenset(),
}
_ERROR_STATES = frozenset(
    {
        AttemptState.FAILED,
        AttemptState.ROLLED_BACK,
        AttemptState.RECOVERY_REQUIRED,
    }
)


def _strict_object(raw: bytes, *, maximum: int, label: str) -> dict[str, Any]:
    if type(raw) is not bytes or not 1 <= len(raw) <= maximum:
        raise OtaProtocolError(f"{label} length is invalid")

    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise OtaProtocolError(f"{label} contains a duplicate key")
            result[key] = value
        return result

    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=reject_duplicates)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OtaProtocolError(f"{label} is not valid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise OtaProtocolError(f"{label} must be an object")
    return value


def _valid_uuid(value: Any) -> bool:
    return type(value) is str and UUID_RE.fullmatch(value) is not None


def _valid_event_token(value: Any) -> bool:
    return type(value) is str and EVENT_TOKEN_RE.fullmatch(value) is not None


def _split_scoped_url(value: Any) -> tuple[str, str] | None:
    if (
        type(value) is not str
        or not 1 <= len(value.encode("utf-8")) <= MAX_URL_BYTES
        or not value.isascii()
        or not value.startswith("/")
        or any(character in value for character in ("?", "#", "%", "\\"))
        or "//" in value
    ):
        return None
    segments = value.split("/")
    if any(segment in {".", ".."} for segment in segments):
        return None
    if (
        len(segments) < 7
        or segments[:3] != ["", "terminal", "device"]
        or not _valid_uuid(segments[3])
        or CREDENTIAL_RE.fullmatch(segments[4]) is None
        or segments[5] != "firmware"
    ):
        return None
    return "/".join(segments[:5]), "/".join(segments[5:])


def _validate_offer_urls(offer: OtaOffer) -> None:
    expected = {
        "manifest_url": f"firmware/{offer.release_id}/manifest.json",
        "signature_url": f"firmware/{offer.release_id}/manifest.sig",
        "application_url": f"firmware/{offer.release_id}/application.bin",
        "event_url": "firmware/events",
    }
    scope: str | None = None
    for field, suffix in expected.items():
        parsed = _split_scoped_url(getattr(offer, field))
        if parsed is None or parsed[1] != suffix:
            raise OtaProtocolError(f"OTA offer {field} is invalid")
        if scope is None:
            scope = parsed[0]
        elif parsed[0] != scope:
            raise OtaProtocolError("OTA offer URLs do not share one credential scope")


def validate_offer(offer: OtaOffer) -> OtaOffer:
    if not isinstance(offer, OtaOffer):
        raise OtaProtocolError("OTA offer is invalid")
    if type(offer.schema_version) is not int or offer.schema_version != 1:
        raise OtaProtocolError("OTA offer schema is unsupported")
    if not _valid_uuid(offer.offer_id) or not _valid_uuid(offer.attempt_id):
        raise OtaProtocolError("OTA offer identity is invalid")
    if type(offer.release_id) is not str or SHA256_RE.fullmatch(offer.release_id) is None:
        raise OtaProtocolError("OTA offer release id is invalid")
    if type(offer.version) is not str or VERSION_RE.fullmatch(offer.version) is None:
        raise OtaProtocolError("OTA offer version is invalid")
    if offer.required is not False:
        raise OtaProtocolError("OTA1 cannot require an update")
    _validate_offer_urls(offer)
    return offer


def _offer_mapping(offer: OtaOffer) -> dict[str, Any]:
    return {
        "schema_version": offer.schema_version,
        "offer_id": offer.offer_id,
        "attempt_id": offer.attempt_id,
        "release_id": offer.release_id,
        "version": offer.version,
        "manifest_url": offer.manifest_url,
        "signature_url": offer.signature_url,
        "application_url": offer.application_url,
        "event_url": offer.event_url,
        "required": offer.required,
    }


def encode_offer(offer: OtaOffer) -> bytes:
    validate_offer(offer)
    raw = json.dumps(
        _offer_mapping(offer), separators=(",", ":"), ensure_ascii=True
    ).encode("ascii")
    if len(raw) > MAX_OFFER_BYTES:
        raise OtaProtocolError("OTA offer length is invalid")
    return raw


def parse_offer(raw: bytes) -> OtaOffer:
    value = _strict_object(raw, maximum=MAX_OFFER_BYTES, label="OTA offer")
    if set(value) != OFFER_FIELDS:
        raise OtaProtocolError("OTA offer fields are invalid")
    offer = OtaOffer(**value)
    validate_offer(offer)
    # The canonical form is also the effective bounded-size calculation.
    encode_offer(offer)
    return offer


def validate_event(event: OtaEvent) -> OtaEvent:
    if not isinstance(event, OtaEvent):
        raise OtaProtocolError("OTA event is invalid")
    if type(event.schema_version) is not int or event.schema_version != 1:
        raise OtaProtocolError("OTA event schema is unsupported")
    if not all(
        _valid_uuid(value)
        for value in (event.event_id, event.attempt_id, event.offer_id)
    ):
        raise OtaProtocolError("OTA event identity is invalid")
    if type(event.sequence) is not int or not 1 <= event.sequence <= UINT32_MAX:
        raise OtaProtocolError("OTA event sequence is invalid")
    if type(event.release_id) is not str or SHA256_RE.fullmatch(event.release_id) is None:
        raise OtaProtocolError("OTA event release id is invalid")
    if not isinstance(event.state, AttemptState) or event.state is AttemptState.OFFERED:
        raise OtaProtocolError("OTA device event state is invalid")
    if (
        type(event.running_version) is not str
        or VERSION_RE.fullmatch(event.running_version) is None
    ):
        raise OtaProtocolError("OTA event running version is invalid")
    if (
        type(event.running_build_id) is not str
        or BUILD_ID_RE.fullmatch(event.running_build_id) is None
    ):
        raise OtaProtocolError("OTA event running build id is invalid")
    if (
        type(event.running_partition) is not str
        or event.running_partition not in {"ota_0", "ota_1"}
    ):
        raise OtaProtocolError("OTA event running partition is invalid")
    if type(event.boot_count) is not int or not 1 <= event.boot_count <= UINT32_MAX:
        raise OtaProtocolError("OTA event boot count is invalid")
    if event.reset_reason is not None and not _valid_event_token(event.reset_reason):
        raise OtaProtocolError("OTA event reset reason is invalid")
    if event.state in _ERROR_STATES:
        if not _valid_event_token(event.error_code):
            raise OtaProtocolError("OTA terminal event requires an error code")
    elif event.error_code is not None:
        raise OtaProtocolError("OTA progress event cannot contain an error code")
    return event


def _event_mapping(event: OtaEvent) -> dict[str, Any]:
    return {
        "schema_version": event.schema_version,
        "event_id": event.event_id,
        "attempt_id": event.attempt_id,
        "offer_id": event.offer_id,
        "sequence": event.sequence,
        "release_id": event.release_id,
        "state": event.state.value,
        "running_version": event.running_version,
        "running_build_id": event.running_build_id,
        "running_partition": event.running_partition,
        "boot_count": event.boot_count,
        "reset_reason": event.reset_reason,
        "error_code": event.error_code,
    }


def encode_event(event: OtaEvent) -> bytes:
    validate_event(event)
    raw = json.dumps(
        _event_mapping(event), separators=(",", ":"), ensure_ascii=True
    ).encode("ascii")
    if len(raw) > MAX_EVENT_BYTES:
        raise OtaProtocolError("OTA event length is invalid")
    return raw


def parse_event(raw: bytes) -> OtaEvent:
    value = _strict_object(raw, maximum=MAX_EVENT_BYTES, label="OTA event")
    if set(value) != EVENT_FIELDS:
        raise OtaProtocolError("OTA event fields are invalid")
    try:
        value["state"] = AttemptState(value["state"])
    except (TypeError, ValueError) as exc:
        raise OtaProtocolError("OTA device event state is invalid") from exc
    event = OtaEvent(**value)
    validate_event(event)
    encode_event(event)
    return event


def event_fingerprint(event: OtaEvent) -> str:
    """Return the normalized payload identity stored beside a durable event."""

    return hashlib.sha256(encode_event(event)).hexdigest()


def classify_replay(existing: OtaEvent, incoming: OtaEvent) -> ReplayDecision:
    validate_event(existing)
    validate_event(incoming)
    if existing.event_id != incoming.event_id:
        return ReplayDecision.DISTINCT
    if event_fingerprint(existing) == event_fingerprint(incoming):
        return ReplayDecision.IDEMPOTENT
    return ReplayDecision.CONFLICT


def event_matches_offer(offer: OtaOffer, event: OtaEvent) -> bool:
    validate_offer(offer)
    validate_event(event)
    return (
        event.offer_id == offer.offer_id
        and event.attempt_id == offer.attempt_id
        and event.release_id == offer.release_id
    )


def _reachable(start: AttemptState, target: AttemptState) -> bool:
    pending = list(_ADJACENT[start])
    seen: set[AttemptState] = set()
    while pending:
        state = pending.pop()
        if state == target:
            return True
        if state not in seen:
            seen.add(state)
            pending.extend(_ADJACENT[state])
    return False


def classify_transition(
    previous_state: AttemptState,
    previous_sequence: int,
    next_state: AttemptState,
    next_sequence: int,
) -> TransitionDecision:
    if (
        not isinstance(previous_state, AttemptState)
        or not isinstance(next_state, AttemptState)
        or type(previous_sequence) is not int
        or type(next_sequence) is not int
        or not 0 <= previous_sequence <= UINT32_MAX
        or not 1 <= next_sequence <= UINT32_MAX
        or next_sequence <= previous_sequence
        or next_state is AttemptState.OFFERED
    ):
        return TransitionDecision.REJECT
    if (
        next_sequence == previous_sequence + 1
        and next_state in _ADJACENT[previous_state]
    ):
        return TransitionDecision.ADVANCE
    if next_sequence > previous_sequence + 1 and _reachable(
        previous_state, next_state
    ):
        return TransitionDecision.ADVANCE_WITH_GAP
    return TransitionDecision.REJECT
