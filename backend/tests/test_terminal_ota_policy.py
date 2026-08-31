from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from backend.config import Settings
from backend.services.terminal.ota_policy import (
    OtaPolicyError,
    ParentBundleLink,
    evaluate_ota_policy,
    parse_qualified_releases,
    verify_ota_descriptor,
)


KEY_ID = "ota-release-2026"
PARENT_RELEASE_ID = "b" * 64
FIRMWARE = b"candidate application bytes"
FIRMWARE_HASH = hashlib.sha256(FIRMWARE).hexdigest()


def _parent(**overrides) -> ParentBundleLink:
    values = {
        "release_id": PARENT_RELEASE_ID,
        "signing_key_id": KEY_ID,
        "catalog_generation": 7,
        "model": "E1002",
        "firmware_version": "0.3.0",
        "source_build_id": "7" * 40,
        "partition_layout": "ab-v1",
        "application_size": len(FIRMWARE),
        "application_sha256": FIRMWARE_HASH,
        "hardware_revisions": ("V1.0",),
        "release_ota_eligible": True,
        "model_ota_eligible": True,
    }
    values.update(overrides)
    return ParentBundleLink(**values)


def _manifest_bytes(**overrides) -> bytes:
    manifest = {
        "schema_version": 1,
        "model": "E1002",
        "layout": "ab-v1",
        "version": "0.3.0",
        "firmware_size": len(FIRMWARE),
        "firmware_sha256": FIRMWARE_HASH,
    }
    manifest.update(overrides)
    return (
        json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        + "\n"
    ).encode("ascii")


def _verified_release(
    private_key: Ed25519PrivateKey,
    *,
    raw: bytes | None = None,
    parent: ParentBundleLink | None = None,
):
    raw = raw or _manifest_bytes()
    release_id = hashlib.sha256(raw).hexdigest()
    return verify_ota_descriptor(
        raw,
        private_key.sign(raw),
        expected_release_id=release_id,
        signing_key_id=KEY_ID,
        public_key=private_key.public_key(),
        parent=parent or _parent(),
    )


def _qualification(release_id: str, **overrides) -> str:
    item = {
        "parent_release_id": PARENT_RELEASE_ID,
        "model": "E1002",
        "signing_key_id": KEY_ID,
        "hardware_revisions": ["V1.0"],
    }
    item.update(overrides)
    return json.dumps({release_id: item}, sort_keys=True)


def _settings(release_id: str | None = None, **overrides):
    values = {
        "terminal_ota_enabled": True,
        "terminal_ota_qualified_releases": (
            _qualification(release_id) if release_id is not None else "{}"
        ),
        "terminal_firmware_minimum_catalog_generation": 7,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_settings_keep_ota_default_disabled_and_hil_allowlist_empty():
    settings = Settings(_env_file=None)

    assert settings.terminal_ota_enabled is False
    assert settings.terminal_ota_qualified_releases == "{}"


def test_exact_signed_descriptor_is_preserved_and_content_addressed():
    private_key = Ed25519PrivateKey.generate()
    raw = _manifest_bytes()
    release = _verified_release(private_key, raw=raw)

    assert release.release_id == hashlib.sha256(raw).hexdigest()
    assert release.manifest_bytes == raw
    assert release.signature_bytes == private_key.sign(raw)
    assert release.model == "E1002"
    assert release.layout == "ab-v1"
    assert release.version == "0.3.0"
    assert release.firmware_size == len(FIRMWARE)
    assert release.firmware_sha256 == FIRMWARE_HASH
    assert release.parent.release_id == PARENT_RELEASE_ID


def test_descriptor_rejects_wrong_content_address_and_signature():
    private_key = Ed25519PrivateKey.generate()
    raw = _manifest_bytes()
    signature = private_key.sign(raw)

    with pytest.raises(OtaPolicyError, match="release id"):
        verify_ota_descriptor(
            raw,
            signature,
            expected_release_id="0" * 64,
            signing_key_id=KEY_ID,
            public_key=private_key.public_key(),
            parent=_parent(),
        )

    tampered = bytearray(signature)
    tampered[0] ^= 1
    with pytest.raises(OtaPolicyError, match="signature"):
        verify_ota_descriptor(
            raw,
            bytes(tampered),
            expected_release_id=hashlib.sha256(raw).hexdigest(),
            signing_key_id=KEY_ID,
            public_key=private_key.public_key(),
            parent=_parent(),
        )


@pytest.mark.parametrize(
    ("raw", "message"),
    (
        (
            b'{"schema_version":1,"schema_version":1,"model":"E1002",'
            b'"layout":"ab-v1","version":"0.3.0","firmware_size":1,'
            b'"firmware_sha256":"' + b"0" * 64 + b'"}',
            "duplicate",
        ),
        (_manifest_bytes(unexpected=True), "fields"),
        (_manifest_bytes(schema_version=True), "schema"),
        (_manifest_bytes(model="E1004"), "E1004"),
        (_manifest_bytes(model="unknown"), "model"),
        (_manifest_bytes(layout="single-slot-e100x-v1"), "layout"),
        (_manifest_bytes(version="bad version"), "version"),
        (_manifest_bytes(firmware_size=True), "size"),
        (_manifest_bytes(firmware_size=0x300001), "size"),
        (_manifest_bytes(firmware_sha256="A" * 64), "hash"),
    ),
)
def test_descriptor_schema_is_exact_and_fail_closed(raw: bytes, message: str):
    private_key = Ed25519PrivateKey.generate()

    with pytest.raises(OtaPolicyError, match=message):
        verify_ota_descriptor(
            raw,
            private_key.sign(raw),
            expected_release_id=hashlib.sha256(raw).hexdigest(),
            signing_key_id=KEY_ID,
            public_key=private_key.public_key(),
            parent=_parent(),
        )


@pytest.mark.parametrize(
    "parent",
    (
        _parent(signing_key_id="other-key"),
        _parent(model="E1001"),
        _parent(firmware_version="0.3.1"),
        _parent(partition_layout="single-slot-e100x-v1"),
        _parent(application_size=len(FIRMWARE) + 1),
        _parent(application_sha256="0" * 64),
        _parent(hardware_revisions=()),
    ),
)
def test_descriptor_requires_an_exact_valid_parent_bundle_link(parent):
    private_key = Ed25519PrivateKey.generate()
    raw = _manifest_bytes()

    with pytest.raises(OtaPolicyError):
        verify_ota_descriptor(
            raw,
            private_key.sign(raw),
            expected_release_id=hashlib.sha256(raw).hexdigest(),
            signing_key_id=KEY_ID,
            public_key=private_key.public_key(),
            parent=parent,
        )


def test_hil_allowlist_is_exact_and_excludes_e1004():
    release_id = "a" * 64
    parsed = parse_qualified_releases(_qualification(release_id))

    assert parsed[release_id].parent_release_id == PARENT_RELEASE_ID
    assert parsed[release_id].model == "E1002"
    assert parsed[release_id].hardware_revisions == ("V1.0",)
    assert parse_qualified_releases("{}") == {}

    invalid = (
        '{"' + release_id + '":{},"' + release_id + '":{}}',
        json.dumps({release_id: {"model": "E1002"}}),
        _qualification(release_id, model="E1004"),
        _qualification(release_id, hardware_revisions=[]),
        _qualification(release_id, hardware_revisions=["V1.0", "V1.0"]),
        _qualification(release_id, signing_key_id="bad key"),
        json.dumps({"BAD": json.loads(_qualification(release_id))[release_id]}),
    )
    for raw in invalid:
        with pytest.raises(OtaPolicyError):
            parse_qualified_releases(raw)


def test_policy_stays_locked_on_all_default_gates():
    policy = evaluate_ota_policy(
        SimpleNamespace(
            terminal_ota_enabled=False,
            terminal_ota_qualified_releases="{}",
            terminal_firmware_minimum_catalog_generation=0,
        )
    )

    assert policy.state == "locked"
    assert policy.effective_offer_enabled is False
    assert policy.releases == ()
    assert policy.as_capabilities()["qualified_releases"] == []
    assert policy.blockers == (
        "Server-side terminal OTA is disabled.",
        "No OTA release/model has completed physical HIL qualification.",
        "No minimum signed firmware catalog generation is pinned.",
        "Durable idempotent OTA event persistence is unavailable.",
    )


def test_event_persistence_and_signed_parent_eligibility_are_hard_offer_gates():
    private_key = Ed25519PrivateKey.generate()
    release = _verified_release(private_key)
    settings = _settings(release.release_id)

    no_events = evaluate_ota_policy(settings, [release])
    assert no_events.state == "locked"
    assert no_events.releases == (release,)
    assert "Durable idempotent OTA event persistence is unavailable." in no_events.blockers

    candidate_parent = replace(
        release.parent,
        release_ota_eligible=False,
        model_ota_eligible=False,
    )
    candidate = replace(release, parent=candidate_parent)
    unsigned_candidate_policy = evaluate_ota_policy(
        settings,
        [candidate],
        event_persistence_ready=True,
    )
    assert unsigned_candidate_policy.state == "locked"
    assert unsigned_candidate_policy.releases == ()
    assert any("signed parent eligibility" in blocker for blocker in unsigned_candidate_policy.blockers)

    ready = evaluate_ota_policy(
        settings,
        [release],
        event_persistence_ready=True,
    )
    assert ready.state == "ready"
    assert ready.effective_offer_enabled is True
    assert ready.blockers == ()
    assert ready.require_ready() is ready
    assert ready.as_capabilities()["qualified_releases"] == [release.as_public_record()]


def test_hil_and_catalog_generation_must_match_the_exact_release():
    private_key = Ed25519PrivateKey.generate()
    release = _verified_release(private_key)

    mismatched_hil = evaluate_ota_policy(
        _settings(release.release_id, terminal_ota_qualified_releases=_qualification(
            release.release_id,
            hardware_revisions=["V2.0"],
        )),
        [release],
        event_persistence_ready=True,
    )
    assert mismatched_hil.state == "locked"

    stale_catalog = evaluate_ota_policy(
        _settings(release.release_id, terminal_firmware_minimum_catalog_generation=8),
        [release],
        event_persistence_ready=True,
    )
    assert stale_catalog.state == "locked"

    disabled = evaluate_ota_policy(
        _settings(release.release_id, terminal_ota_enabled=False),
        [release],
        event_persistence_ready=True,
    )
    assert disabled.state == "locked"
    assert disabled.effective_offer_enabled is False
