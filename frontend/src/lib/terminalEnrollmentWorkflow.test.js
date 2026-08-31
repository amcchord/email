import assert from 'node:assert/strict';
import test from 'node:test';

import * as realProtocol from './terminalEnrollmentProtocol.js';
import {
  describeTerminalEnrollmentState,
  runTerminalEnrollmentPhase,
  waitForTerminalEnrollmentActivation,
} from './terminalEnrollmentWorkflow.js';

const ATTEMPT_ID = '123e4567-e89b-42d3-a456-426614174000';
const TERMINAL_ID = '223e4567-e89b-42d3-a456-426614174000';
const SESSION_ID = realProtocol.encodeBase64Url(new Uint8Array(16).fill(7));
const TICKET = `${'a'.repeat(24)}.${'b'.repeat(48)}.${'c'.repeat(86)}`;
const encoder = new TextEncoder();

function status(overrides = {}) {
  return {
    v: 2,
    type: 'status',
    state: 'provisioning_required',
    model: 'E1002',
    firmware_version: '0.2.0-candidate.8',
    factory_mac: 'aa:bb:cc:dd:ee:ff',
    config_source: 'fallback',
    config_generation: 0,
    enrollment_available: true,
    enrollment_key_id: 'ret1-2026',
    partition_layout: 'ab-v1',
    running_partition: 'ota_0',
    boot_state: 'stable',
    partition_identity_valid: true,
    firmware_build_id: 'a'.repeat(40),
    identity_strength: 'physical_cable_only',
    attestation: false,
    ...overrides,
  };
}

function hello() {
  const point = new Uint8Array(65);
  point[0] = 4;
  return {
    v: 1,
    type: 'hello',
    seq: 0,
    client_nonce: realProtocol.encodeBase64Url(new Uint8Array(32).fill(1)),
    client_public_key: realProtocol.encodeBase64Url(point),
  };
}

function helloAck(overrides = {}) {
  const point = new Uint8Array(65);
  point[0] = 4;
  return {
    v: 1,
    type: 'hello_ack',
    seq: 0,
    session_id: SESSION_ID,
    session_sha256: realProtocol.encodeBase64Url(new Uint8Array(32).fill(2)),
    device_nonce: realProtocol.encodeBase64Url(new Uint8Array(32).fill(3)),
    device_public_key: realProtocol.encodeBase64Url(point),
    model: 'E1002',
    firmware_version: '0.2.0-candidate.8',
    factory_mac: 'aa:bb:cc:dd:ee:ff',
    chip: 'ESP32-S3',
    chip_revision: 0,
    config_generation: 0,
    identity_strength: 'physical_cable_only',
    attestation: false,
    ...overrides,
  };
}

function resultEnvelope() {
  return {
    v: 1,
    type: 'result',
    session_id: SESSION_ID,
    seq: 2,
    ciphertext: 'AA',
    tag: 'AAAAAAAAAAAAAAAAAAAAAA',
  };
}

function attemptRecord(state = 'initialized') {
  return {
    schema_version: 1,
    attempt_id: ATTEMPT_ID,
    state,
    operation: 'provision',
    session_id: SESSION_ID,
    terminal: {
      id: TERMINAL_ID,
      model: 'E1002',
      factory_mac: 'aa:bb:cc:dd:ee:ff',
      firmware_version: '0.2.0-candidate.8',
      observed_generation: 0,
      target_generation: 1,
    },
    firmware_release: {
      release_id: 'b'.repeat(64),
      enrollment_key_id: 'ret1-2026',
    },
    schedule_url_template: `https://email.mcchord.net/terminal/device/${TERMINAL_ID}/{credential}/schedule.json`,
    expires_at: null,
    client_completed_at: state === 'client_confirmed' ? '2026-08-31T01:00:00Z' : null,
    activated_at: state === 'activated' ? '2026-08-31T01:00:01Z' : null,
  };
}

function fixture({
  completeState = 'client_confirmed',
  failAfterProvision = false,
  failTicket = false,
  failCancel = false,
} = {}) {
  const apiCalls = [];
  const serialWrites = [];
  let configReference = null;
  let configSha256 = '';
  let readIndex = 0;
  const protocol = {
    ...realProtocol,
    async generateClientHello() {
      return { hello: hello(), clientPrivateKey: { fixture: true } };
    },
    async completeHandshake() {
      return {
        sessionId: SESSION_ID,
        transcriptSha256: new Uint8Array(32).fill(2),
        clientToDeviceKey: { fixture: true },
        deviceToClientKey: { fixture: true },
        clientNoncePrefix: new Uint8Array(4).fill(4),
        deviceNoncePrefix: new Uint8Array(4).fill(5),
        model: 'E1002',
        firmwareVersion: '0.2.0-candidate.8',
        factoryMac: 'aa:bb:cc:dd:ee:ff',
        configGeneration: 0,
      };
    },
    async encryptProvision({ configBytes }) {
      configReference = configBytes;
      const digest = await realProtocol.sha256(configBytes);
      configSha256 = [...digest].map(item => item.toString(16).padStart(2, '0')).join('');
      return {
        frame: realProtocol.encodeRet1Frame({
          v: 1,
          type: 'provision',
          session_id: SESSION_ID,
          seq: 1,
          ticket: TICKET,
          ciphertext: 'encrypted',
          tag: 'AAAAAAAAAAAAAAAAAAAAAA',
        }),
        configSha256: digest,
      };
    },
    async decryptResult({ expected }) {
      return {
        ok: true,
        operation: 'provision',
        generation: expected.generation,
        configSha256: expected.configSha256,
        rebooting: true,
      };
    },
  };
  const applicationTransport = {
    async sendRet1Frame({ bytes }) {
      serialWrites.push(new TextDecoder().decode(bytes));
      if (failAfterProvision && serialWrites.length === 2) return true;
      return true;
    },
    readChunks() {
      const response = readIndex++ === 0 ? helloAck() : resultEnvelope();
      if (failAfterProvision && readIndex === 2) {
        return (async function* failRead() { throw new Error('serial disconnected'); }());
      }
      return (async function* read() { yield realProtocol.encodeRet1Frame(response); }());
    },
  };
  const api = {
    async createIntent(payload) {
      apiCalls.push(['create', payload]);
      return attemptRecord('initialized');
    },
    async issueTicket(attemptId, payload) {
      apiCalls.push(['ticket', attemptId, payload]);
      if (failTicket) throw new Error('ticket unavailable');
      return {
        schema_version: 1,
        attempt_id: ATTEMPT_ID,
        state: 'issued',
        operation: 'provision',
        generation: 1,
        config_sha256: payload.config_sha256,
        ticket: TICKET,
        issued_at: '2026-08-31T01:00:00Z',
        expires_at: '2026-08-31T01:05:00Z',
        activation: 'first_scoped_https_checkin',
      };
    },
    async completeIntent(attemptId, payload) {
      apiCalls.push(['complete', attemptId, payload]);
      assert.equal(payload.config_sha256, configSha256);
      return attemptRecord(completeState);
    },
    async cancelIntent(attemptId, payload) {
      apiCalls.push(['cancel', attemptId, payload]);
      if (failCancel) throw new Error('cancel unavailable');
      return attemptRecord('superseded');
    },
    async getIntent() {
      return attemptRecord('activated');
    },
  };
  return {
    api,
    apiCalls,
    applicationTransport,
    protocol,
    serialWrites,
    configReference: () => configReference,
  };
}

const expected = {
  releaseId: 'b'.repeat(64),
  enrollmentKeyId: 'ret1-2026',
  model: 'E1002',
  firmwareVersion: '0.2.0-candidate.8',
  factoryMac: 'aa:bb:cc:dd:ee:ff',
};

test('RET1 phase keeps Wi-Fi and the raw credential out of APIs and serial plaintext', async () => {
  const value = fixture();
  const states = [];
  const outcome = await runTerminalEnrollmentPhase({
    status: status(),
    expected,
    credentials: { ssid: 'Private Network', password: 'correct horse battery' },
    applicationTransport: value.applicationTransport,
    api: value.api,
    protocol: value.protocol,
    onState: event => states.push(event.state),
    responseTimeoutMs: 100,
  });

  assert.equal(outcome.ok, true);
  assert.equal(outcome.state, 'activation_pending');
  assert.deepEqual(states, [
    'preflight', 'sending_hello', 'verifying_identity', 'creating_intent',
    'preparing_configuration', 'issuing_ticket', 'writing_configuration',
    'verifying_result', 'reporting_result', 'activation_pending',
  ]);
  const apiSerialized = JSON.stringify(value.apiCalls);
  const serialSerialized = value.serialWrites.join('\n');
  for (const secret of ['Private Network', 'correct horse battery', 'schedule.json']) {
    assert.doesNotMatch(apiSerialized, new RegExp(secret.replace('.', '\\.')));
    assert.doesNotMatch(serialSerialized, new RegExp(secret.replace('.', '\\.')));
  }
  assert.ok(value.configReference().every(item => item === 0), 'owned canonical config bytes are cleared');
  assert.equal(value.serialWrites.length, 2, 'one hello and one provision frame are written');
  assert.equal(value.apiCalls.map(item => item[0]).join(','), 'create,ticket,complete');
});

test('post-provision disconnect is result-unknown and never auto-replays sequence one', async () => {
  const value = fixture({ failAfterProvision: true });
  const outcome = await runTerminalEnrollmentPhase({
    status: status(),
    expected,
    credentials: { ssid: 'Private Network', password: '' },
    applicationTransport: value.applicationTransport,
    api: value.api,
    protocol: value.protocol,
    responseTimeoutMs: 100,
  });
  assert.equal(outcome.ok, false);
  assert.equal(outcome.state, 'result_unknown');
  assert.equal(value.serialWrites.length, 2);
  assert.equal(value.apiCalls.map(item => item[0]).join(','), 'create,ticket');
});

test('identity mismatch blocks before intent creation or any encrypted configuration write', async () => {
  const value = fixture();
  const outcome = await runTerminalEnrollmentPhase({
    status: status({ factory_mac: '11:22:33:44:55:66' }),
    expected,
    credentials: { ssid: 'Private Network', password: '' },
    applicationTransport: value.applicationTransport,
    api: value.api,
    protocol: value.protocol,
    responseTimeoutMs: 100,
  });
  assert.equal(outcome.state, 'blocked');
  assert.equal(value.apiCalls.length, 0);
  assert.equal(value.serialWrites.length, 0);
});

test('pre-write server failure supersedes the durable attempt before allowing a retry', async () => {
  const value = fixture({ failTicket: true });
  const outcome = await runTerminalEnrollmentPhase({
    status: status(),
    expected,
    credentials: { ssid: 'Private Network', password: '' },
    applicationTransport: value.applicationTransport,
    api: value.api,
    protocol: value.protocol,
    responseTimeoutMs: 100,
  });
  assert.equal(outcome.state, 'blocked');
  assert.equal(value.serialWrites.length, 1, 'only the public hello was written');
  assert.equal(value.apiCalls.map(item => item[0]).join(','), 'create,ticket,cancel');
  assert.equal(value.apiCalls.at(-1)[1], ATTEMPT_ID);
  assert.deepEqual(value.apiCalls.at(-1)[2], {
    client_intent_id: value.apiCalls[0][1].client_intent_id,
    operation: 'cancel',
  });
});

test('failed durable cancellation never claims that a pre-write retry is safe', async () => {
  const value = fixture({ failTicket: true, failCancel: true });
  const outcome = await runTerminalEnrollmentPhase({
    status: status(),
    expected,
    credentials: { ssid: 'Private Network', password: '' },
    applicationTransport: value.applicationTransport,
    api: value.api,
    protocol: value.protocol,
    responseTimeoutMs: 100,
  });
  assert.equal(outcome.state, 'blocked');
  assert.equal(outcome.error.code, 'cancellation_failed');
  assert.equal(value.apiCalls.map(item => item[0]).join(','), 'create,ticket,cancel');
});

test('activation remains pending until the server reports credential-authenticated check-in', async () => {
  const calls = [];
  const records = [attemptRecord('client_confirmed'), attemptRecord('activated')];
  const result = await waitForTerminalEnrollmentActivation({
    attemptId: ATTEMPT_ID,
    api: {
      createIntent() {},
      issueTicket() {},
      completeIntent() {},
      async getIntent() {
        calls.push('get');
        return records.shift();
      },
    },
    timeoutMs: 100,
    pollMs: 1,
  });
  assert.equal(result.activated, true);
  assert.equal(calls.length, 2);
});

test('operator states distinguish irreversible result uncertainty from delayed activation', () => {
  assert.equal(describeTerminalEnrollmentState('writing_configuration').irreversible, true);
  assert.equal(describeTerminalEnrollmentState('result_unknown').tone, 'danger');
  assert.equal(describeTerminalEnrollmentState('activation_delayed').activated, false);
  assert.equal(describeTerminalEnrollmentState('activated').activated, true);
});
