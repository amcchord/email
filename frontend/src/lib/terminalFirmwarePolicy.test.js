import assert from 'node:assert/strict';
import test from 'node:test';

import { validateTerminalFirmwareCatalog } from './terminalFirmwarePolicy.js';

const RELEASE_ID = 'a'.repeat(64);
const GIT_SHA = 'b'.repeat(40);
const KEY_ID = 'release-key-1';

function artifact(role, size, flashOffset) {
  return {
    role,
    size,
    sha256: 'c'.repeat(64),
    flash_offset: flashOffset,
    preserves_nvs: true,
    preserves_littlefs: true,
  };
}

function model(name, options = {}) {
  const contracts = {
    E1001: ['reterminal_e1001', 'GDEY075T7', [800, 480], 'ab-v1'],
    E1002: ['reterminal_e1002', 'GDEP073E01', [800, 480], 'ab-v1'],
    E1004: ['reterminal_e1004', 'GDEP133C02', [1200, 1600], 'single-slot-e1004-v1'],
  };
  const [environment, panel, resolution, partitionLayout] = contracts[name];
  const littlefsSize = name === 'E1004' ? 0x400000 : 0xe0000;
  const qualified = options.qualified ?? (name !== 'E1004');
  return {
    model: name,
    environment,
    panel,
    resolution,
    partition_layout: partitionLayout,
    hardware_revisions: qualified ? ['V1.0'] : [],
    browser_flash_qualified: qualified,
    install_eligible: false,
    blockers: qualified ? [] : ['This model has not completed browser-flash qualification.'],
    protected_ranges: [
      { name: 'nvs', offset: 0x9000, size: 0x5000 },
      { name: 'littlefs', offset: 0x310000, size: littlefsSize },
    ],
    flash_set: ['bootloader', 'partition_table', 'ota_data_initial', 'application'],
    artifacts: [
      artifact('bootloader', 0x6000, 0x0000),
      artifact('partition_table', 0x1000, 0x8000),
      artifact('ota_data_initial', 0x1000, 0xe000),
      artifact('application', 0x100000, 0x10000),
    ],
  };
}

function catalog() {
  return {
    schema_version: 2,
    installer_state: 'locked',
    browser_flash_enabled: false,
    trusted_key_ids: [KEY_ID],
    blockers: ['Browser firmware writing is disabled until provisioning is qualified.'],
    releases: [{
      release_id: RELEASE_ID,
      firmware_version: '0.2.0',
      git_sha: GIT_SHA,
      source_date_epoch: 1788062400,
      manifest_schema_version: 1,
      signing_key_id: KEY_ID,
      serial_enrollment: {
        protocol: 'RET1',
        enabled: false,
        trust_key_id: null,
        public_key_sha256: null,
        identity_strength: 'physical_cable_only',
        attestation: false,
      },
      manifest_url: `/api/terminal/firmware/releases/${RELEASE_ID}/manifest.json`,
      signature_url: `/api/terminal/firmware/releases/${RELEASE_ID}/manifest.sig`,
      models: [model('E1001'), model('E1002'), model('E1004')],
    }],
  };
}

test('accepts a closed signed catalog with qualified E1001/E1002 metadata', () => {
  const result = validateTerminalFirmwareCatalog(catalog());
  assert.equal(result.valid, true);
  assert.equal(result.catalog.releases[0].models.length, 3);
});

test('accepts normalized schema-two disabled and enabled RET1 evidence', () => {
  const disabled = catalog();
  disabled.releases[0].manifest_schema_version = 2;
  assert.equal(validateTerminalFirmwareCatalog(disabled).valid, true);

  const enabled = catalog();
  enabled.releases[0].manifest_schema_version = 2;
  enabled.releases[0].serial_enrollment = {
    protocol: 'RET1',
    enabled: true,
    trust_key_id: 'terminal-enrollment-2026-01',
    public_key_sha256: 'd'.repeat(64),
    identity_strength: 'physical_cable_only',
    attestation: false,
  };
  const result = validateTerminalFirmwareCatalog(enabled);
  assert.equal(result.valid, true);
  assert.equal(result.catalog.releases[0].serial_enrollment.enabled, true);
});

test('rejects RET1 enablement on a legacy schema-one manifest', () => {
  const candidate = catalog();
  candidate.releases[0].serial_enrollment.enabled = true;
  candidate.releases[0].serial_enrollment.trust_key_id = 'terminal-enrollment-2026-01';
  candidate.releases[0].serial_enrollment.public_key_sha256 = 'd'.repeat(64);

  const result = validateTerminalFirmwareCatalog(candidate);

  assert.equal(result.valid, false);
  assert.match(result.errors.join(' '), /legacy manifest/i);
});

test('rejects malformed or ambiguous normalized RET1 evidence', () => {
  const cases = [
    enrollment => { enrollment.protocol = 'RET2'; },
    enrollment => { enrollment.enabled = 1; },
    enrollment => { enrollment.trust_key_id = 'bad key'; },
    enrollment => { enrollment.public_key_sha256 = 'D'.repeat(64); },
    enrollment => { enrollment.identity_strength = 'attested'; },
    enrollment => { enrollment.attestation = true; },
    enrollment => { enrollment.unexpected = true; },
  ];

  for (const mutate of cases) {
    const candidate = catalog();
    candidate.releases[0].manifest_schema_version = 2;
    candidate.releases[0].serial_enrollment.enabled = true;
    candidate.releases[0].serial_enrollment.trust_key_id = 'terminal-enrollment-2026-01';
    candidate.releases[0].serial_enrollment.public_key_sha256 = 'd'.repeat(64);
    mutate(candidate.releases[0].serial_enrollment);
    assert.equal(validateTerminalFirmwareCatalog(candidate).valid, false);
  }
});

test('rejects disabled RET1 evidence that retains either trust field', () => {
  for (const field of ['trust_key_id', 'public_key_sha256']) {
    const candidate = catalog();
    candidate.releases[0].manifest_schema_version = 2;
    candidate.releases[0].serial_enrollment[field] = field === 'trust_key_id'
      ? 'terminal-enrollment-2026-01'
      : 'd'.repeat(64);
    const result = validateTerminalFirmwareCatalog(candidate);
    assert.equal(result.valid, false);
    assert.match(result.errors.join(' '), /declares trust material/i);
  }
});

test('rejects unknown fields instead of silently widening the catalog contract', () => {
  const candidate = catalog();
  candidate.releases[0].models[0].unexpected = true;
  const result = validateTerminalFirmwareCatalog(candidate);
  assert.equal(result.valid, false);
  assert.match(result.errors.join(' '), /invalid schema/i);
});

test('rejects more than the single active release allowed by the server', () => {
  const candidate = catalog();
  const second = JSON.parse(JSON.stringify(candidate.releases[0]));
  second.release_id = 'd'.repeat(64);
  second.manifest_url = `/api/terminal/firmware/releases/${second.release_id}/manifest.json`;
  second.signature_url = `/api/terminal/firmware/releases/${second.release_id}/manifest.sig`;
  for (const releaseModel of second.models) {
    for (const releaseArtifact of releaseModel.artifacts) {
      delete releaseArtifact.download_url;
    }
  }
  candidate.releases.push(second);

  const result = validateTerminalFirmwareCatalog(candidate);
  assert.equal(result.valid, false);
  assert.match(result.errors.join(' '), /release list is invalid/i);
});

test('rejects an untrusted release and an installable E1004 image', () => {
  const candidate = catalog();
  candidate.releases[0].signing_key_id = 'unknown-key';
  candidate.releases[0].models[2].browser_flash_qualified = true;
  candidate.releases[0].models[2].install_eligible = true;
  const result = validateTerminalFirmwareCatalog(candidate);
  assert.equal(result.valid, false);
  assert.match(result.errors.join(' '), /untrusted signing key/i);
  assert.match(result.errors.join(' '), /cannot be qualified/i);
});

test('rejects artifacts that overlap NVS or LittleFS', () => {
  const candidate = catalog();
  candidate.releases[0].models[0].protected_ranges[0] = {
    name: 'nvs',
    offset: 0x10000,
    size: 0x1000,
  };
  const result = validateTerminalFirmwareCatalog(candidate);
  assert.equal(result.valid, false);
  assert.match(result.errors.join(' '), /overlap protected configuration storage/i);
});

test('rejects protected-range drift and overlaps between flash artifacts', () => {
  const candidate = catalog();
  candidate.releases[0].models[0].protected_ranges[1].offset = 0x320000;
  candidate.releases[0].models[1].artifacts[0].size = 0x9000;
  const result = validateTerminalFirmwareCatalog(candidate);
  assert.equal(result.valid, false);
  assert.match(result.errors.join(' '), /pinned partition layout/i);
  assert.match(result.errors.join(' '), /overlap each other/i);
});

test('rejects flash offset, hash, and preservation claim drift', () => {
  const candidate = catalog();
  const artifactUnderTest = candidate.releases[0].models[1].artifacts[3];
  artifactUnderTest.flash_offset = 0x20000;
  artifactUnderTest.sha256 = 'not-a-hash';
  artifactUnderTest.preserves_littlefs = false;
  const result = validateTerminalFirmwareCatalog(candidate);
  assert.equal(result.valid, false);
  const errors = result.errors.join(' ');
  assert.match(errors, /invalid flash range/i);
  assert.match(errors, /invalid SHA-256/i);
  assert.match(errors, /does not preserve/i);
});

test('malformed nested values fail closed without throwing', () => {
  const invalidTopLevel = catalog();
  invalidTopLevel.trusted_key_ids = null;
  invalidTopLevel.blockers = null;
  assert.doesNotThrow(() => validateTerminalFirmwareCatalog(invalidTopLevel));
  assert.equal(validateTerminalFirmwareCatalog(invalidTopLevel).valid, false);

  const invalidRelease = catalog();
  invalidRelease.releases[0].release_id = null;
  invalidRelease.releases[0].models[0].hardware_revisions = null;
  invalidRelease.releases[0].models[0].blockers = null;
  invalidRelease.releases[0].models[0].install_eligible = true;
  assert.doesNotThrow(() => validateTerminalFirmwareCatalog(invalidRelease));
  assert.equal(validateTerminalFirmwareCatalog(invalidRelease).valid, false);
});
