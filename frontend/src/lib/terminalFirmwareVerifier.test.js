import assert from 'node:assert/strict';
import { webcrypto } from 'node:crypto';
import test from 'node:test';

import {
  PINNED_TERMINAL_FIRMWARE_ED25519_KEYS,
  verifyTerminalFirmwareRelease,
} from './terminalFirmwareVerifier.js';

const KEY_ID = 'fixture-release-key';
const GIT_SHA = 'b'.repeat(40);
const SHA = 'c'.repeat(64);
const AB_PARTITIONS_SHA = '931ffb5d9c703672f554b538bf546c230d9ecead380cc0ac42a9de92ee080fe6';
const E1004_PARTITIONS_SHA = '9cf80a35887d3bfa7a595d759cec7016733fef41fdad101e9bb7c76c2c4ab6cb';
const SERIAL_ENROLLMENT = Object.freeze({
  protocol: 'RET1',
  enabled: false,
  trust_key_id: null,
  public_key_sha256: null,
  identity_strength: 'physical_cable_only',
  attestation: false,
});

function artifact(role, size, flashOffset) {
  return {
    role,
    size,
    sha256: SHA,
    flash_offset: flashOffset,
    preserves_nvs: true,
    preserves_littlefs: true,
  };
}

function manifestFile(environment, role, filename, size, offset, nvs = true) {
  const item = {
    path: `${environment}/${filename}`,
    role,
    flash_offset: offset,
    size,
    sha256: SHA,
  };
  if (role !== 'partition_source') {
    item.preserves_nvs = nvs;
    item.preserves_littlefs = true;
  }
  return item;
}

function modelContract(name) {
  return {
    E1001: ['reterminal_e1001', 'GDEY075T7', [800, 480], 'ab-v1', 'partitions/e100x-ab-v1.csv', true],
    E1002: ['reterminal_e1002', 'GDEP073E01', [800, 480], 'ab-v1', 'partitions/e100x-ab-v1.csv', true],
    E1004: ['reterminal_e1004', 'GDEP133C02', [1200, 1600], 'single-slot-e1004-v1', 'e1004_partitions.csv', false],
  }[name];
}

function manifestModel(name) {
  const [environment, panel, resolution, layout, csv, panelQualified] = modelContract(name);
  const qualified = name !== 'E1004';
  return {
    environment,
    model: name,
    panel,
    resolution,
    partition_layout: layout,
    partition_csv: csv,
    panel_qualified: panelQualified,
    hardware_revisions: qualified ? ['V1.0'] : [],
    browser_flash_qualified: qualified,
    ota_eligible: false,
    flash_sets: {
      preserve_config: ['bootloader', 'partition_table', 'ota_data_initial', 'application'],
      factory_recovery: ['factory_recovery'],
    },
    files: [
      manifestFile(environment, 'bootloader', 'bootloader.bin', 0x6000, 0x0000),
      manifestFile(environment, 'partition_table', 'partitions.bin', 0x1000, 0x8000),
      manifestFile(environment, 'application', 'firmware.bin', 0x100000, 0x10000),
      manifestFile(environment, 'factory_recovery', 'firmware.factory.bin', 0x110000, 0x0000, false),
      manifestFile(environment, 'ota_data_initial', 'boot_app0.bin', 0x2000, 0xe000),
      {
        ...manifestFile(environment, 'partition_source', 'partitions.csv', 200, null),
        sha256: name === 'E1004' ? E1004_PARTITIONS_SHA : AB_PARTITIONS_SHA,
      },
    ],
  };
}

function manifest() {
  return {
    schema_version: 2,
    firmware_version: '0.4.0-candidate.4',
    git_sha: GIT_SHA,
    source_date_epoch: 1788062400,
    chip: 'ESP32-S3',
    flash: { minimum_bytes: 32 * 1024 * 1024, mode: 'keep', frequency: 'keep', size: '32MB', erase_all: false },
    toolchain: {
      schema_version: 1,
      platformio_core: '6.1.19',
      platform: {
        name: 'pioarduino/platform-espressif32',
        revision: 'fbdfc2962e468ca3c4b51811ae691ed887df903c',
        version: '55.3.38',
        arduino_esp32: '3.3.8',
        esp_idf: '5.5.4',
        esp_idf_revision: '735507283d',
      },
      libraries: {
        'Adafruit BusIO': '1.17.4',
        'Adafruit GFX Library': '1.12.6',
        ArduinoJson: '7.4.3',
        GxEPD2: '1.6.9',
      },
      tools: { esptool: '5.2.0', xtensa_esp32s3_elf: '14.2.0+20260121' },
    },
    toolchain_evidence: { path: 'toolchain-evidence.txt', size: 100, sha256: SHA },
    security: {
      signed: true,
      ota_eligible: false,
      reason: 'Detached-signed candidate; all transport and firmware-write paths remain disabled.',
      serial_enrollment: { ...SERIAL_ENROLLMENT },
    },
    models: [manifestModel('E1001'), manifestModel('E1002'), manifestModel('E1004')],
  };
}

function catalogModel(rawModel) {
  return {
    model: rawModel.model,
    environment: rawModel.environment,
    panel: rawModel.panel,
    resolution: rawModel.resolution,
    partition_layout: rawModel.partition_layout,
    hardware_revisions: rawModel.hardware_revisions,
    browser_flash_qualified: rawModel.browser_flash_qualified,
    artifacts: [
      artifact('bootloader', 0x6000, 0x0000),
      artifact('partition_table', 0x1000, 0x8000),
      artifact('ota_data_initial', 0x2000, 0xe000),
      artifact('application', 0x100000, 0x10000),
    ],
  };
}

async function signedFixture(rawManifest = manifest()) {
  const keyPair = await webcrypto.subtle.generateKey({ name: 'Ed25519' }, true, ['sign', 'verify']);
  const publicKey = new Uint8Array(await webcrypto.subtle.exportKey('raw', keyPair.publicKey));
  const manifestBytes = typeof rawManifest === 'string'
    ? new TextEncoder().encode(rawManifest)
    : new TextEncoder().encode(`${JSON.stringify(rawManifest)}\n`);
  const releaseId = [...new Uint8Array(await webcrypto.subtle.digest('SHA-256', manifestBytes))]
    .map(value => value.toString(16).padStart(2, '0')).join('');
  const signatureBytes = new Uint8Array(await webcrypto.subtle.sign('Ed25519', keyPair.privateKey, manifestBytes));
  const parsed = typeof rawManifest === 'string' ? JSON.parse(rawManifest) : rawManifest;
  const release = {
    release_id: releaseId,
    signing_key_id: KEY_ID,
    manifest_schema_version: parsed.schema_version,
    firmware_version: parsed.firmware_version,
    git_sha: parsed.git_sha,
    source_date_epoch: parsed.source_date_epoch,
    serial_enrollment: { ...SERIAL_ENROLLMENT },
    models: parsed.models.map(catalogModel),
  };
  const keyHex = [...publicKey].map(value => value.toString(16).padStart(2, '0')).join('');
  return { release, manifestBytes, signatureBytes, trustedKeys: { [KEY_ID]: keyHex } };
}

test('verifies exact candidate.4 bytes, Ed25519 signature, ab-v1, and locked OTA claims', async () => {
  const fixture = await signedFixture();
  const result = await verifyTerminalFirmwareRelease({ ...fixture, runtime: webcrypto });

  assert.equal(result.valid, true);
  assert.equal(result.manifest.models[0].partition_layout, 'ab-v1');
  assert.equal(result.manifest.models[0].ota_eligible, false);
  assert.equal(result.manifest.models[2].partition_layout, 'single-slot-e1004-v1');
});

test('production key map is empty and therefore default-locked', async () => {
  assert.deepEqual(PINNED_TERMINAL_FIRMWARE_ED25519_KEYS, {});
  const fixture = await signedFixture();
  const result = await verifyTerminalFirmwareRelease({
    release: fixture.release,
    manifestBytes: fixture.manifestBytes,
    signatureBytes: fixture.signatureBytes,
    runtime: webcrypto,
  });
  assert.equal(result.valid, false);
  assert.match(result.errors.join(' '), /not pinned/i);
});

test('fails closed for signature drift, unsupported crypto, and A/B contract drift', async () => {
  const fixture = await signedFixture();
  const badSignature = Uint8Array.from(fixture.signatureBytes);
  badSignature[0] ^= 1;
  let result = await verifyTerminalFirmwareRelease({ ...fixture, signatureBytes: badSignature, runtime: webcrypto });
  assert.equal(result.valid, false);
  assert.match(result.errors.join(' '), /signature/i);

  result = await verifyTerminalFirmwareRelease({ ...fixture, runtime: { subtle: {} } });
  assert.equal(result.valid, false);
  assert.match(result.errors.join(' '), /unavailable/i);

  const drifted = manifest();
  drifted.models[0].partition_layout = 'single-slot-e100x-v1';
  const driftedFixture = await signedFixture(drifted);
  result = await verifyTerminalFirmwareRelease({ ...driftedFixture, runtime: webcrypto });
  assert.equal(result.valid, false);
  assert.match(result.errors.join(' '), /not pinned/i);
});

test('rejects cryptographically valid JSON with duplicate keys', async () => {
  const raw = JSON.stringify(manifest()).replace(
    '"schema_version":2',
    '"schema_version":2,"schema_version":2',
  );
  const fixture = await signedFixture(raw);
  const result = await verifyTerminalFirmwareRelease({ ...fixture, runtime: webcrypto });
  assert.equal(result.valid, false);
  assert.match(result.errors.join(' '), /duplicate key/i);
});
