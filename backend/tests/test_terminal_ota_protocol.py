from __future__ import annotations

import json
from dataclasses import replace

import pytest

from backend.services.terminal.ota_protocol import (
    AttemptState,
    OtaEvent,
    OtaOffer,
    OtaProtocolError,
    ReplayDecision,
    TransitionDecision,
    classify_replay,
    classify_transition,
    encode_event,
    encode_offer,
    event_fingerprint,
    event_matches_offer,
    parse_event,
    parse_offer,
)


OFFER_ID = "11111111-1111-4111-8111-111111111111"
ATTEMPT_ID = "22222222-2222-4222-8222-222222222222"
EVENT_ID = "33333333-3333-4333-8333-333333333333"
PUBLIC_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
CREDENTIAL = "A" * 43
RELEASE_ID = "b" * 64
BUILD_ID = "c" * 40
SCOPE = f"/terminal/device/{PUBLIC_ID}/{CREDENTIAL}"


def _offer(**overrides) -> OtaOffer:
    values = {
        "schema_version": 1,
        "offer_id": OFFER_ID,
        "attempt_id": ATTEMPT_ID,
        "release_id": RELEASE_ID,
        "version": "0.3.0",
        "manifest_url": f"{SCOPE}/firmware/{RELEASE_ID}/manifest.json",
        "signature_url": f"{SCOPE}/firmware/{RELEASE_ID}/manifest.sig",
        "application_url": f"{SCOPE}/firmware/{RELEASE_ID}/application.bin",
        "event_url": f"{SCOPE}/firmware/events",
        "required": False,
    }
    values.update(overrides)
    return OtaOffer(**values)


def _event(**overrides) -> OtaEvent:
    values = {
        "schema_version": 1,
        "event_id": EVENT_ID,
        "attempt_id": ATTEMPT_ID,
        "offer_id": OFFER_ID,
        "sequence": 1,
        "release_id": RELEASE_ID,
        "state": AttemptState.DOWNLOADING,
        "running_version": "0.2.0-candidate.5",
        "running_build_id": BUILD_ID,
        "running_partition": "ota_0",
        "boot_count": 418,
        "reset_reason": None,
        "error_code": None,
    }
    values.update(overrides)
    return OtaEvent(**values)


def test_offer_round_trip_is_exact_and_scoped():
    offer = _offer()
    raw = encode_offer(offer)

    assert parse_offer(raw) == offer
    assert set(json.loads(raw)) == {
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


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("schema_version", True),
        ("schema_version", 2),
        ("offer_id", "AAAAAAAA-aaaa-4aaa-8aaa-aaaaaaaaaaaa"),
        ("attempt_id", "not-a-uuid"),
        ("release_id", "B" * 64),
        ("version", "bad version"),
        ("required", True),
        ("required", 0),
        ("manifest_url", "https://email.mcchord.net/manifest.json"),
        ("manifest_url", f"{SCOPE}/firmware/{RELEASE_ID}/../manifest.json"),
        ("manifest_url", f"{SCOPE}/firmware/{'d' * 64}/manifest.json"),
        ("event_url", f"{SCOPE}?secret=1"),
        (
            "signature_url",
            f"/terminal/device/{PUBLIC_ID}/{'D' * 43}/firmware/{RELEASE_ID}/manifest.sig",
        ),
    ),
)
def test_offer_rejects_noncanonical_or_cross_scope_values(field, value):
    with pytest.raises(OtaProtocolError):
        encode_offer(replace(_offer(), **{field: value}))


def test_offer_parser_rejects_duplicate_extra_and_oversized_json():
    raw = encode_offer(_offer())
    duplicate = raw.replace(b'{"schema_version":1', b'{"schema_version":1,"schema_version":1')
    with pytest.raises(OtaProtocolError, match="duplicate"):
        parse_offer(duplicate)

    extra = json.loads(raw)
    extra["unexpected"] = False
    with pytest.raises(OtaProtocolError, match="fields"):
        parse_offer(json.dumps(extra).encode())

    with pytest.raises(OtaProtocolError, match="length"):
        parse_offer(b" " * 3073)


def test_event_round_trip_and_normalized_fingerprint_are_stable():
    event = _event()
    raw = encode_event(event)
    reordered = json.dumps(
        dict(reversed(list(json.loads(raw).items()))), separators=(",", ":")
    ).encode()

    assert parse_event(raw) == event
    assert parse_event(reordered) == event
    assert event_fingerprint(parse_event(raw)) == event_fingerprint(parse_event(reordered))


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("schema_version", True),
        ("event_id", "33333333-3333-4333-8333-33333333333Z"),
        ("sequence", True),
        ("sequence", 0),
        ("release_id", "B" * 64),
        ("state", AttemptState.OFFERED),
        ("running_version", "bad version"),
        ("running_build_id", "c" * 39),
        ("running_build_id", "C" * 40),
        ("running_partition", "factory"),
        ("running_partition", []),
        ("boot_count", 0),
        ("reset_reason", "bad reason"),
        ("error_code", "unexpected"),
    ),
)
def test_event_rejects_noncanonical_values(field, value):
    with pytest.raises(OtaProtocolError):
        encode_event(replace(_event(), **{field: value}))


@pytest.mark.parametrize(
    "state",
    (
        AttemptState.FAILED,
        AttemptState.ROLLED_BACK,
        AttemptState.RECOVERY_REQUIRED,
    ),
)
def test_terminal_failure_states_require_bounded_error_codes(state):
    with pytest.raises(OtaProtocolError, match="requires"):
        encode_event(_event(state=state, error_code=None))

    event = _event(state=state, error_code="self_test_failed")
    assert parse_event(encode_event(event)) == event


def test_event_parser_rejects_duplicate_extra_unknown_state_and_oversize():
    raw = encode_event(_event())
    duplicate = raw.replace(b'{"schema_version":1', b'{"schema_version":1,"schema_version":1')
    with pytest.raises(OtaProtocolError, match="duplicate"):
        parse_event(duplicate)

    for field, value in (("unexpected", 1), ("state", "offered")):
        decoded = json.loads(raw)
        decoded[field] = value
        with pytest.raises(OtaProtocolError):
            parse_event(json.dumps(decoded).encode())

    with pytest.raises(OtaProtocolError, match="length"):
        parse_event(b" " * 2049)


def test_offer_binding_and_event_idempotency_are_exact():
    offer = _offer()
    event = _event()

    assert event_matches_offer(offer, event)
    assert not event_matches_offer(offer, replace(event, release_id="d" * 64))
    assert classify_replay(event, event) is ReplayDecision.IDEMPOTENT
    assert (
        classify_replay(event, replace(event, boot_count=419))
        is ReplayDecision.CONFLICT
    )
    assert (
        classify_replay(event, replace(event, event_id="44444444-4444-4444-8444-444444444444"))
        is ReplayDecision.DISTINCT
    )


@pytest.mark.parametrize(
    ("previous", "following"),
    (
        (AttemptState.OFFERED, AttemptState.DOWNLOADING),
        (AttemptState.OFFERED, AttemptState.FAILED),
        (AttemptState.DOWNLOADING, AttemptState.STAGED),
        (AttemptState.DOWNLOADING, AttemptState.FAILED),
        (AttemptState.STAGED, AttemptState.BOOTED_PENDING_VALIDATION),
        (AttemptState.STAGED, AttemptState.ROLLED_BACK),
        (AttemptState.STAGED, AttemptState.RECOVERY_REQUIRED),
        (AttemptState.BOOTED_PENDING_VALIDATION, AttemptState.SUCCEEDED),
        (AttemptState.BOOTED_PENDING_VALIDATION, AttemptState.ROLLED_BACK),
        (AttemptState.BOOTED_PENDING_VALIDATION, AttemptState.RECOVERY_REQUIRED),
    ),
)
def test_adjacent_attempt_transitions_advance(previous, following):
    assert classify_transition(previous, 3, following, 4) is TransitionDecision.ADVANCE


def test_forward_gaps_are_distinct_from_clean_advancement():
    assert (
        classify_transition(AttemptState.OFFERED, 0, AttemptState.SUCCEEDED, 4)
        is TransitionDecision.ADVANCE_WITH_GAP
    )
    assert (
        classify_transition(AttemptState.STAGED, 2, AttemptState.SUCCEEDED, 4)
        is TransitionDecision.ADVANCE_WITH_GAP
    )
    assert (
        classify_transition(AttemptState.OFFERED, 0, AttemptState.DOWNLOADING, 2)
        is TransitionDecision.ADVANCE_WITH_GAP
    )


@pytest.mark.parametrize(
    ("previous", "previous_sequence", "following", "next_sequence"),
    (
        (AttemptState.OFFERED, 0, AttemptState.STAGED, 1),
        (AttemptState.DOWNLOADING, 2, AttemptState.OFFERED, 3),
        (AttemptState.STAGED, 3, AttemptState.DOWNLOADING, 4),
        (AttemptState.SUCCEEDED, 4, AttemptState.ROLLED_BACK, 5),
        (AttemptState.FAILED, 1, AttemptState.DOWNLOADING, 2),
        (AttemptState.DOWNLOADING, 2, AttemptState.STAGED, 2),
        (AttemptState.DOWNLOADING, 2, AttemptState.STAGED, 1),
    ),
)
def test_backward_skipped_or_post_terminal_transitions_reject(
    previous, previous_sequence, following, next_sequence
):
    assert (
        classify_transition(previous, previous_sequence, following, next_sequence)
        is TransitionDecision.REJECT
    )
