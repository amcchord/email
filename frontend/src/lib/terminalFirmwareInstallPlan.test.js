import assert from 'node:assert/strict';
import test from 'node:test';

import {
  TerminalFirmwareInstallError,
  compileTerminalFirmwareInstallPlan,
  loadTerminalFirmwareInstallArtifacts,
  validateTerminalFirmwareRomIdentity,
} from './terminalFirmwareInstallPlan.js';
import {
  createFixtureFetch,
  createTerminalFirmwareInstallFixture,
  fixtureArtifactResponse,
} from './fixtures/terminalFirmwareInstallTestFixtures.js';

function code(expected) {
  return error => error instanceof TerminalFirmwareInstallError && error.code === expected;
}

test('compiles and loads only the exact four-segment preserve-config plan', async () => {
  const fixture = await createTerminalFirmwareInstallFixture();
  const calls = [];
  const loaded = await loadTerminalFirmwareInstallArtifacts(fixture.plan, {
    fetchImpl: createFixtureFetch(fixture, calls),
  });

  assert.equal(Object.isFrozen(fixture.plan), true);
  assert.equal(Object.isFrozen(fixture.plan.segments), true);
  assert.deepEqual(fixture.plan.segments.map(item => item.offset), [0, 0x8000, 0xe000, 0x10000]);
  assert.deepEqual(loaded.segments.map(item => item.role), [
    'bootloader', 'partition_table', 'ota_data_initial', 'application',
  ]);
  assert.equal(loaded.eraseAll, false);
  assert.equal(loaded.requiredFlashBytes, 32 * 1024 * 1024);
  assert.equal(loaded.artifactsVerified, true);
  assert.equal(calls.length, 4);
  for (const call of calls) {
    assert.deepEqual(call.options, {
      method: 'GET',
      credentials: 'include',
      cache: 'no-store',
      redirect: 'error',
      signal: undefined,
    });
  }
});

test('fails closed for unverified, legacy, ineligible, E1004, or unconfirmed plans', async () => {
  const fixture = await createTerminalFirmwareInstallFixture();
  assert.throws(
    () => compileTerminalFirmwareInstallPlan({
      release: fixture.release,
      verification: { ...fixture.verification, valid: false },
      model: 'E1002',
      hardwareRevision: 'V1.0',
    }),
    code('release_unverified'),
  );

  const legacyRelease = { ...fixture.release, manifest_schema_version: 1 };
  assert.throws(
    () => compileTerminalFirmwareInstallPlan({
      release: legacyRelease,
      verification: fixture.verification,
      model: 'E1002',
      hardwareRevision: 'V1.0',
    }),
    code('plan_invalid'),
  );

  assert.throws(
    () => compileTerminalFirmwareInstallPlan({
      release: fixture.release,
      verification: fixture.verification,
      model: 'E1004',
      hardwareRevision: 'V1.0',
    }),
    code('unsupported_model'),
  );
  assert.throws(
    () => compileTerminalFirmwareInstallPlan({
      release: fixture.release,
      verification: fixture.verification,
      model: 'E1002',
      hardwareRevision: 'V9.9',
    }),
    code('hardware_revision_unqualified'),
  );

  const ineligible = structuredClone(fixture.release);
  ineligible.models[0].install_eligible = false;
  assert.throws(
    () => compileTerminalFirmwareInstallPlan({
      release: ineligible,
      verification: fixture.verification,
      model: 'E1002',
      hardwareRevision: 'V1.0',
    }),
    code('hardware_revision_unqualified'),
  );
});

test('artifact loading requires exact headers, byte length, and SHA-256 before transport', async () => {
  const fixture = await createTerminalFirmwareInstallFixture();
  const bootloader = fixture.artifactBytes.get('bootloader');
  const changed = Uint8Array.from(bootloader);
  changed[0] ^= 1;

  await assert.rejects(
    loadTerminalFirmwareInstallArtifacts(fixture.plan, {
      fetchImpl: createFixtureFetch(fixture, [], {
        bootloader: fixtureArtifactResponse(bootloader, { contentLength: null }),
      }),
    }),
    code('artifact_invalid'),
  );
  await assert.rejects(
    loadTerminalFirmwareInstallArtifacts(fixture.plan, {
      fetchImpl: createFixtureFetch(fixture, [], {
        bootloader: fixtureArtifactResponse(bootloader, { body: changed }),
      }),
    }),
    code('artifact_hash_mismatch'),
  );
  await assert.rejects(
    loadTerminalFirmwareInstallArtifacts(fixture.plan, {
      fetchImpl: createFixtureFetch(fixture, [], {
        bootloader: fixtureArtifactResponse(bootloader, { redirected: true }),
      }),
    }),
    code('artifact_unavailable'),
  );
});

test('ROM identity accepts only ESP32-S3, 32 MB or larger flash, and canonical MAC', async () => {
  const fixture = await createTerminalFirmwareInstallFixture();
  assert.deepEqual(validateTerminalFirmwareRomIdentity({
    chip: 'ESP32-S3',
    flashBytes: 32 * 1024 * 1024,
    factoryMac: fixture.factoryMac,
  }, fixture.plan), {
    chip: 'ESP32-S3',
    flashBytes: 32 * 1024 * 1024,
    factoryMac: fixture.factoryMac,
  });
  assert.throws(
    () => validateTerminalFirmwareRomIdentity({
      chip: 'ESP32', flashBytes: 32 * 1024 * 1024, factoryMac: fixture.factoryMac,
    }, fixture.plan),
    code('unsupported_chip'),
  );
  assert.throws(
    () => validateTerminalFirmwareRomIdentity({
      chip: 'ESP32-S3', flashBytes: 16 * 1024 * 1024, factoryMac: fixture.factoryMac,
    }, fixture.plan),
    code('flash_too_small'),
  );
});
