from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

import backend.services.terminal.enrollment_policy as policy_module
from backend.services.terminal.enrollment_policy import (
    EnrollmentPolicyError,
    evaluate_enrollment_policy,
    normalize_base_url,
    parse_qualified_releases,
)
from backend.tests.test_terminal_firmware_artifacts import stage_signed_bundle


KEY_ID = "ret1-online-2026"
PUBLIC_HASH = "d" * 64


def _settings(tmp_path, fixture, **overrides):
    values = {
        "terminal_enrollment_enabled": True,
        "terminal_enrollment_base_url": "https://email.mcchord.net",
        "terminal_enrollment_signing_key_id": KEY_ID,
        "terminal_enrollment_private_key_path": str(tmp_path / "ret1-key.pem"),
        "terminal_enrollment_qualified_releases": json.dumps(
            {fixture["release_id"]: ["E1001", "E1002"]}
        ),
        "terminal_enrollment_ticket_ttl_seconds": 300,
        "terminal_firmware_storage_path": str(tmp_path),
        "terminal_firmware_trusted_signing_keys": fixture["trusted_keys"],
        "terminal_firmware_minimum_catalog_generation": 1,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _enabled_fixture(tmp_path):
    return stage_signed_bundle(
        tmp_path,
        manifest_schema_version=2,
        serial_enrollment={
            "protocol": "RET1",
            "enabled": True,
            "trust_key_id": KEY_ID,
            "public_key_sha256": PUBLIC_HASH,
            "identity_strength": "physical_cable_only",
            "attestation": False,
        },
    )


def test_https_origin_and_release_allowlist_are_strict():
    assert normalize_base_url(" https://Email.McChord.Net/ ") == "https://email.mcchord.net"
    for invalid in (
        "http://email.mcchord.net",
        "https://user@email.mcchord.net",
        "https://email.mcchord.net/path",
        "https://email.mcchord.net?token=x",
        "https://email.mcchord.net:444",
        "https://email.mcchord.net:bad",
    ):
        with pytest.raises(EnrollmentPolicyError):
            normalize_base_url(invalid)

    release_id = "a" * 64
    assert parse_qualified_releases(
        json.dumps({release_id: ["E1002", "E1001"]})
    ) == {release_id: ("E1001", "E1002")}
    for invalid in (
        "{}",
        '{"duplicate":[],"duplicate":[]}',
        json.dumps({release_id: ["E1004"]}),
        json.dumps({release_id: ["E1001", "E1001"]}),
        json.dumps({"BAD": ["E1001"]}),
    ):
        if invalid == "{}":
            assert parse_qualified_releases(invalid) == {}
        else:
            with pytest.raises(EnrollmentPolicyError):
                parse_qualified_releases(invalid)


def test_policy_is_ready_only_when_signed_release_online_key_and_hil_agree(
    tmp_path,
    monkeypatch,
):
    fixture = _enabled_fixture(tmp_path)
    sentinel_key = object()
    monkeypatch.setattr(
        policy_module,
        "_load_online_identity",
        lambda _path: (sentinel_key, PUBLIC_HASH),
    )

    policy = evaluate_enrollment_policy(_settings(tmp_path, fixture))

    assert policy.state == "ready"
    assert policy.enabled is True
    assert policy.signing_key is sentinel_key
    assert policy.release_for(
        firmware_version="0.2.0-test.1", model="E1001"
    ).release_id == fixture["release_id"]
    assert policy.as_capabilities() == {
        "schema_version": 1,
        "state": "ready",
        "enabled": True,
        "protocol": "RET1",
        "identity_strength": "physical_cable_only",
        "attestation": False,
        "allowed_models": ["E1001", "E1002"],
        "qualified_releases": [{
            "release_id": fixture["release_id"],
            "firmware_version": "0.2.0-test.1",
            "git_sha": "1" * 40,
            "models": ["E1001", "E1002"],
        }],
        "blockers": [],
    }


@pytest.mark.parametrize(
    "overrides, expected",
    (
        ({"terminal_enrollment_enabled": False}, "disabled"),
        ({"terminal_enrollment_base_url": "http://email.mcchord.net"}, "HTTPS"),
        ({"terminal_enrollment_signing_key_id": "wrong-key"}, "online key"),
        ({"terminal_enrollment_qualified_releases": "{}"}, "physical enrollment"),
        ({"terminal_enrollment_ticket_ttl_seconds": 601}, "lifetime"),
        ({"terminal_firmware_minimum_catalog_generation": 0}, "generation"),
    ),
)
def test_policy_failures_are_publicly_safe_and_locked(
    tmp_path,
    monkeypatch,
    overrides,
    expected,
):
    fixture = _enabled_fixture(tmp_path)
    monkeypatch.setattr(
        policy_module,
        "_load_online_identity",
        lambda _path: (object(), PUBLIC_HASH),
    )

    policy = evaluate_enrollment_policy(_settings(tmp_path, fixture, **overrides))

    assert policy.state == "locked"
    assert expected.lower() in " ".join(policy.blockers).lower()
    assert "ret1-key.pem" not in " ".join(policy.blockers)


def test_key_hash_or_manifest_schema_mismatch_never_qualifies(
    tmp_path,
    monkeypatch,
):
    fixture = _enabled_fixture(tmp_path)
    monkeypatch.setattr(
        policy_module,
        "_load_online_identity",
        lambda _path: (object(), "e" * 64),
    )

    policy = evaluate_enrollment_policy(_settings(tmp_path, fixture))

    assert policy.state == "locked"
    assert policy.releases == ()
    assert any("matches the online key" in blocker for blocker in policy.blockers)
