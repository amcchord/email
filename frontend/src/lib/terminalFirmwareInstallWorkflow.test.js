import assert from 'node:assert/strict';
import test from 'node:test';

import { runTerminalFirmwareInstallWorkflow } from './terminalFirmwareInstallWorkflow.js';
import {
  createFixtureFetch,
  createTerminalFirmwareInstallFixture,
  fixtureArtifactResponse,
  statusFrame,
} from './fixtures/terminalFirmwareInstallTestFixtures.js';

function fakeTransports(fixture, options = {}) {
  const calls = [];
  const rom = {
    async probe() {
      calls.push('probe');
      if (options.probeError) throw options.probeError;
      return options.probe || {
        chip: 'ESP32-S3',
        flashBytes: 32 * 1024 * 1024,
        factoryMac: fixture.factoryMac,
      };
    },
    async writeSegments(segments, writeOptions) {
      calls.push({
        operation: 'write',
        offsets: segments.map(segment => segment.offset),
        roles: segments.map(segment => segment.role),
        eraseAll: writeOptions.eraseAll,
      });
      writeOptions.onProgress({ role: segments[0].role, bytesWritten: segments[0].bytes.length });
      if (options.onWrite) return options.onWrite(segments, writeOptions);
      return true;
    },
    async verifySegments(segments) {
      calls.push({ operation: 'verify', count: segments.length });
      if (options.verifyError) throw options.verifyError;
      return options.verified ?? true;
    },
    async resetToApplication() {
      calls.push('reset');
      if (options.resetError) throw options.resetError;
      return options.reset ?? true;
    },
    async close() {
      calls.push('close-rom');
    },
  };
  const application = {
    async sendStatusRequest(requestOptions) {
      calls.push({
        operation: 'status-request',
        baudRate: requestOptions.baudRate,
        text: new TextDecoder().decode(requestOptions.bytes),
        signal: Boolean(requestOptions.signal),
      });
      return options.statusRequestAccepted ?? true;
    },
    readChunks(readOptions) {
      calls.push({ operation: 'read-status', ...readOptions, signal: Boolean(readOptions.signal) });
      const observedStatus = options.status || fixture.status;
      return (async function* read() {
        yield new TextEncoder().encode('boot diagnostic\r\n');
        yield statusFrame(observedStatus, '\r\n');
      }());
    },
    async close() {
      calls.push('close-application');
    },
  };
  return { rom, application, calls };
}

test('fake transport exercises exact write, verify, reset, and status-v2 success sequence', async () => {
  const fixture = await createTerminalFirmwareInstallFixture();
  const transport = fakeTransports(fixture);
  const states = [];
  const progress = [];
  const fetchCalls = [];
  const result = await runTerminalFirmwareInstallWorkflow({
    plan: fixture.plan,
    fetchImpl: createFixtureFetch(fixture, fetchCalls),
    romTransport: transport.rom,
    applicationTransport: transport.application,
    statusSettleMs: 0,
    onState: event => states.push(event.state),
    onProgress: event => progress.push(event),
  });

  assert.equal(result.ok, true);
  assert.equal(result.state, 'succeeded');
  assert.equal(result.recoveryRequired, false);
  assert.deepEqual(states, [
    'preflight', 'fetching', 'verifying', 'awaiting_rom', 'probing',
    'flashing', 'verifying_flash', 'resetting', 'awaiting_status',
    'verifying_status', 'succeeded',
  ]);
  assert.deepEqual(
    transport.calls.find(item => item?.operation === 'write'),
    {
      operation: 'write',
      offsets: [0, 0x8000, 0xe000, 0x10000],
      roles: ['bootloader', 'partition_table', 'ota_data_initial', 'application'],
      eraseAll: false,
    },
  );
  assert.equal(fetchCalls.length, 4);
  assert.equal(progress[0].stage, 'flashing');
  assert.deepEqual(
    transport.calls.find(item => item?.operation === 'status-request'),
    {
      operation: 'status-request',
      baudRate: 115200,
      text: '@RET1 {"v":2,"type":"status_request"}\n',
      signal: false,
    },
  );
  assert.equal(result.status.firmware_build_id, fixture.release.git_sha);
  assert.equal(result.probe.factoryMac, fixture.factoryMac);
  assert.deepEqual(transport.calls.slice(-2), ['close-application', 'close-rom']);
});

test('throwing UI observers cannot interrupt an in-flight flash or hide success', async () => {
  const fixture = await createTerminalFirmwareInstallFixture();
  const transport = fakeTransports(fixture);
  const result = await runTerminalFirmwareInstallWorkflow({
    plan: fixture.plan,
    fetchImpl: createFixtureFetch(fixture),
    romTransport: transport.rom,
    applicationTransport: transport.application,
    statusSettleMs: 0,
    onState() {
      throw new Error('render failed');
    },
    onProgress() {
      throw new Error('telemetry failed');
    },
  });

  assert.equal(result.ok, true);
  assert.equal(result.state, 'succeeded');
  assert.equal(transport.calls.some(item => item?.operation === 'verify'), true);
  assert.deepEqual(transport.calls.slice(-2), ['close-application', 'close-rom']);
});

test('artifact failure blocks before ROM probe or any write', async () => {
  const fixture = await createTerminalFirmwareInstallFixture();
  const transport = fakeTransports(fixture);
  const application = fixture.artifactBytes.get('application');
  const changed = Uint8Array.from(application);
  changed[0] ^= 1;
  const result = await runTerminalFirmwareInstallWorkflow({
    plan: fixture.plan,
    fetchImpl: createFixtureFetch(fixture, [], {
      application: fixtureArtifactResponse(application, { body: changed }),
    }),
    romTransport: transport.rom,
    applicationTransport: transport.application,
  });

  assert.equal(result.ok, false);
  assert.equal(result.state, 'blocked');
  assert.equal(result.error.code, 'artifact_hash_mismatch');
  assert.equal(transport.calls.includes('probe'), false);
  assert.equal(transport.calls.some(item => item?.operation === 'write'), false);
  assert.deepEqual(transport.calls, ['close-application', 'close-rom']);
});

test('unsupported ROM remains blocked before write', async () => {
  const fixture = await createTerminalFirmwareInstallFixture();
  const transport = fakeTransports(fixture, {
    probe: {
      chip: 'ESP32-S3',
      flashBytes: 16 * 1024 * 1024,
      factoryMac: fixture.factoryMac,
    },
  });
  const result = await runTerminalFirmwareInstallWorkflow({
    plan: fixture.plan,
    fetchImpl: createFixtureFetch(fixture),
    romTransport: transport.rom,
    applicationTransport: transport.application,
  });

  assert.equal(result.state, 'blocked');
  assert.equal(result.error.code, 'flash_too_small');
  assert.equal(result.recoveryRequired, false);
  assert.equal(transport.calls.some(item => item?.operation === 'write'), false);
});

test('disconnect or cancellation after write entry always requires explicit recovery', async () => {
  const fixture = await createTerminalFirmwareInstallFixture();
  const controller = new AbortController();
  const transport = fakeTransports(fixture, {
    onWrite() {
      controller.abort();
      const error = new Error('disconnected');
      error.name = 'AbortError';
      throw error;
    },
  });
  const result = await runTerminalFirmwareInstallWorkflow({
    plan: fixture.plan,
    fetchImpl: createFixtureFetch(fixture),
    romTransport: transport.rom,
    applicationTransport: transport.application,
    signal: controller.signal,
  });

  assert.equal(result.state, 'recovery_required');
  assert.equal(result.recoveryRequired, true);
  assert.equal(result.error.code, 'write_interrupted');
  assert.equal(result.history.at(-1).state, 'recovery_required');
});

test('flash verify, reset, and exact status mismatch failures remain recovery-required', async () => {
  const fixture = await createTerminalFirmwareInstallFixture();
  for (const options of [
    { verified: false, expectedCode: 'flash_verify_failed' },
    { reset: false, expectedCode: 'reset_failed' },
    {
      status: { ...fixture.status, running_partition: 'ota_1' },
      expectedCode: 'status_mismatch',
    },
  ]) {
    const transport = fakeTransports(fixture, options);
    const result = await runTerminalFirmwareInstallWorkflow({
      plan: fixture.plan,
      fetchImpl: createFixtureFetch(fixture),
      romTransport: transport.rom,
      applicationTransport: transport.application,
      statusSettleMs: 0,
    });
    assert.equal(result.state, 'recovery_required');
    assert.equal(result.error.code, options.expectedCode);
  }
});

test('abort before artifact or transport work is a safe cancelled-before-write state', async () => {
  const fixture = await createTerminalFirmwareInstallFixture();
  const transport = fakeTransports(fixture);
  const controller = new AbortController();
  controller.abort();
  const result = await runTerminalFirmwareInstallWorkflow({
    plan: fixture.plan,
    fetchImpl: createFixtureFetch(fixture),
    romTransport: transport.rom,
    applicationTransport: transport.application,
    signal: controller.signal,
  });

  assert.equal(result.state, 'cancelled_before_write');
  assert.equal(result.recoveryRequired, false);
  assert.equal(transport.calls.some(item => item?.operation === 'write'), false);
});
