import assert from 'node:assert/strict';
import test from 'node:test';

import { TerminalFirmwareInstallError } from './terminalFirmwareInstallPlan.js';
import {
  TerminalFirmwareStatusReader,
  createTerminalFirmwareStatusRequest,
  readTerminalFirmwareRecoveryStatus,
  verifyTerminalFirmwareRecoveryStatus,
} from './terminalFirmwareRecovery.js';
import {
  createTerminalFirmwareInstallFixture,
  statusFrame,
} from './fixtures/terminalFirmwareInstallTestFixtures.js';

const encoder = new TextEncoder();

function code(expected) {
  return error => error instanceof TerminalFirmwareInstallError && error.code === expected;
}

async function* chunks(...values) {
  for (const value of values) yield value;
}

test('bounded RET1 readback accepts noisy split CRLF status v2 and exact signed identity', async () => {
  const fixture = await createTerminalFirmwareInstallFixture();
  const frame = statusFrame(fixture.status, '\r\n');
  const observed = await readTerminalFirmwareRecoveryStatus({
    chunks: chunks(
      encoder.encode('ESP-ROM:esp32s3 diagnostic\r\n'),
      frame.subarray(0, 9),
      frame.subarray(9, 47),
      frame.subarray(47),
    ),
    expected: fixture.plan.expectedStatus,
    factoryMac: fixture.factoryMac,
    timeoutMs: 100,
    settleMs: 0,
  });

  assert.equal(observed.v, 2);
  assert.equal(observed.model, 'E1002');
  assert.equal(observed.running_partition, 'ota_0');
  assert.equal(observed.firmware_build_id, fixture.release.git_sha);
  assert.equal(observed.attestation, false);
});

test('status listener request uses the firmware exact RET1 v2 frame', () => {
  assert.equal(
    new TextDecoder().decode(createTerminalFirmwareStatusRequest()),
    '@RET1 {"v":2,"type":"status_request"}\n',
  );
});

test('readback rejects legacy, dirty, pending, invalid-slot, wrong model/MAC/build, and storage-error states', async () => {
  const fixture = await createTerminalFirmwareInstallFixture();
  const cases = [];
  const legacy = { ...fixture.status, v: 1 };
  for (const key of [
    'partition_layout', 'running_partition', 'boot_state', 'partition_identity_valid', 'firmware_build_id',
  ]) delete legacy[key];
  cases.push(legacy);
  cases.push({ ...fixture.status, firmware_build_id: `${fixture.release.git_sha}-dirty` });
  cases.push({ ...fixture.status, boot_state: 'pending_validation' });
  cases.push({ ...fixture.status, running_partition: 'ota_1' });
  cases.push({ ...fixture.status, model: 'E1001' });
  cases.push({ ...fixture.status, factory_mac: '11:22:33:44:55:66' });
  cases.push({ ...fixture.status, firmware_version: '0.5.1' });
  cases.push({ ...fixture.status, state: 'storage_error' });

  for (const candidate of cases) {
    assert.throws(
      () => verifyTerminalFirmwareRecoveryStatus(
        candidate,
        fixture.plan.expectedStatus,
        fixture.factoryMac,
      ),
      code('status_mismatch'),
    );
  }

  assert.throws(
    () => verifyTerminalFirmwareRecoveryStatus(
      { ...fixture.status, partition_layout: 'unknown' },
      fixture.plan.expectedStatus,
      fixture.factoryMac,
    ),
    code('status_malformed'),
  );
});

test('reader accepts an identical duplicate but fails closed on contradictory status frames', async () => {
  const fixture = await createTerminalFirmwareInstallFixture();
  const same = new TerminalFirmwareStatusReader({
    expected: fixture.plan.expectedStatus,
    factoryMac: fixture.factoryMac,
  });
  same.push(statusFrame(fixture.status));
  same.push(statusFrame(fixture.status));
  assert.equal(same.finish().config_generation, 7);

  const contradictory = new TerminalFirmwareStatusReader({
    expected: fixture.plan.expectedStatus,
    factoryMac: fixture.factoryMac,
  });
  contradictory.push(statusFrame(fixture.status));
  assert.throws(
    () => contradictory.push(statusFrame({ ...fixture.status, config_generation: 8 })),
    code('status_mismatch'),
  );
});

test('reader ignores bounded diagnostics but rejects malformed, oversized, and incomplete RET1 frames', async () => {
  const fixture = await createTerminalFirmwareInstallFixture();
  const reader = new TerminalFirmwareStatusReader({
    expected: fixture.plan.expectedStatus,
    factoryMac: fixture.factoryMac,
  });
  reader.push(encoder.encode(`${'x'.repeat(5000)}\n`));
  reader.push(statusFrame(fixture.status));
  assert.equal(reader.finish().state, 'config_ready');

  for (const raw of [
    '@RET1 {"v":2,"v":2}\n',
    `@RET1 ${'x'.repeat(4096)}\n`,
    '@RET1 {"v":2',
  ]) {
    const malformed = new TerminalFirmwareStatusReader({
      expected: fixture.plan.expectedStatus,
      factoryMac: fixture.factoryMac,
    });
    if (raw.endsWith('\n')) {
      assert.throws(() => malformed.push(encoder.encode(raw)), code('status_malformed'));
    } else {
      malformed.push(encoder.encode(raw));
      assert.throws(() => malformed.finish(), code('status_malformed'));
    }
  }
});

test('async status read has a real deadline and cancellation path', async () => {
  const fixture = await createTerminalFirmwareInstallFixture();
  const stalled = {
    [Symbol.asyncIterator]() {
      return {
        next: () => new Promise(() => {}),
        return: async () => ({ done: true }),
      };
    },
  };
  await assert.rejects(
    readTerminalFirmwareRecoveryStatus({
      chunks: stalled,
      expected: fixture.plan.expectedStatus,
      factoryMac: fixture.factoryMac,
      timeoutMs: 5,
      settleMs: 0,
    }),
    code('status_timeout'),
  );

  const controller = new AbortController();
  controller.abort();
  await assert.rejects(
    readTerminalFirmwareRecoveryStatus({
      chunks: stalled,
      expected: fixture.plan.expectedStatus,
      factoryMac: fixture.factoryMac,
      signal: controller.signal,
      timeoutMs: 100,
      settleMs: 0,
    }),
    error => error?.name === 'AbortError',
  );
});

test('status timeout remains bounded when iterator cleanup also stalls', async () => {
  const fixture = await createTerminalFirmwareInstallFixture();
  const stalled = {
    [Symbol.asyncIterator]() {
      return {
        next: () => new Promise(() => {}),
        return: () => new Promise(() => {}),
      };
    },
  };
  const started = Date.now();
  await assert.rejects(
    readTerminalFirmwareRecoveryStatus({
      chunks: stalled,
      expected: fixture.plan.expectedStatus,
      factoryMac: fixture.factoryMac,
      timeoutMs: 5,
      settleMs: 0,
    }),
    code('status_timeout'),
  );
  assert.ok(Date.now() - started < 500);
});
