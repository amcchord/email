import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

import { encodeBase64Url, encodeRet1Frame } from './terminalEnrollmentProtocol.js';
import {
  TerminalEnrollmentTransportError,
  readTerminalEnrollmentResponse,
} from './terminalEnrollmentTransport.js';

const vector = JSON.parse(await readFile(
  new URL('./fixtures/ret1-v1-vector.json', import.meta.url),
  'utf8',
));
const encoder = new TextEncoder();

function fromHex(value) {
  return Uint8Array.from(value.match(/../gu).map(byte => Number.parseInt(byte, 16)));
}

function helloAck(overrides = {}) {
  return {
    v: 1,
    type: 'hello_ack',
    seq: 0,
    session_id: vector.session_id,
    session_sha256: encodeBase64Url(fromHex(vector.transcript_sha256_hex)),
    device_nonce: vector.device_nonce_b64url,
    device_public_key: vector.device_public_b64url,
    model: 'E1002',
    firmware_version: '0.2.0-candidate.7',
    factory_mac: 'aa:bb:cc:dd:ee:ff',
    chip: 'ESP32-S3',
    chip_revision: 0,
    config_generation: 0,
    identity_strength: 'physical_cable_only',
    attestation: false,
    ...overrides,
  };
}

function status() {
  return {
    v: 2,
    type: 'status',
    state: 'provisioning_required',
    model: 'E1002',
    firmware_version: '0.2.0-candidate.7',
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
  };
}

async function* chunks(...values) {
  for (const value of values) yield value;
}

function code(expected) {
  return error => error instanceof TerminalEnrollmentTransportError && error.code === expected;
}

test('bounded RET1 reader ignores diagnostics and consistent status before split hello acknowledgement', async () => {
  const ack = encodeRet1Frame(helloAck());
  const observed = await readTerminalEnrollmentResponse({
    chunks: chunks(
      encoder.encode('boot log without secrets\r\n'),
      encodeRet1Frame(status()),
      ack.subarray(0, 17),
      ack.subarray(17),
    ),
    expectedType: 'hello_ack',
    timeoutMs: 100,
  });
  assert.deepEqual(observed, helloAck());
});

test('result envelope is session-bound while errors and unexpected frames fail closed', async () => {
  const result = {
    v: 1,
    type: 'result',
    session_id: vector.session_id,
    seq: 2,
    ciphertext: 'AA',
    tag: 'AAAAAAAAAAAAAAAAAAAAAA',
  };
  assert.deepEqual(await readTerminalEnrollmentResponse({
    chunks: chunks(encodeRet1Frame(result)),
    expectedType: 'result',
    expectedSessionId: vector.session_id,
    timeoutMs: 100,
  }), result);

  await assert.rejects(
    readTerminalEnrollmentResponse({
      chunks: chunks(encodeRet1Frame({
        v: 1, type: 'error', code: 'authorization_failed', session_id: vector.session_id,
      })),
      expectedType: 'result',
      expectedSessionId: vector.session_id,
      timeoutMs: 100,
    }),
    code('device_rejected'),
  );
  await assert.rejects(
    readTerminalEnrollmentResponse({
      chunks: chunks(encodeRet1Frame(helloAck())),
      expectedType: 'result',
      expectedSessionId: vector.session_id,
      timeoutMs: 100,
    }),
    code('unexpected_frame'),
  );
});

test('malformed, oversized, incomplete, timed-out, and cancelled reads are bounded', async () => {
  for (const value of [
    encoder.encode('@RET1 {"v":1,"v":1}\n'),
    encoder.encode(`@RET1 ${'x'.repeat(4097)}\n`),
    encoder.encode('@RET1 {"v":1'),
  ]) {
    await assert.rejects(
      readTerminalEnrollmentResponse({
        chunks: chunks(value),
        expectedType: 'hello_ack',
        timeoutMs: 100,
      }),
      error => error instanceof TerminalEnrollmentTransportError,
    );
  }

  const stalled = {
    [Symbol.asyncIterator]() {
      return {
        next: () => new Promise(() => {}),
        return: async () => ({ done: true }),
      };
    },
  };
  await assert.rejects(
    readTerminalEnrollmentResponse({ chunks: stalled, expectedType: 'hello_ack', timeoutMs: 5 }),
    code('response_timeout'),
  );
  const controller = new AbortController();
  controller.abort();
  await assert.rejects(
    readTerminalEnrollmentResponse({
      chunks: stalled,
      expectedType: 'hello_ack',
      timeoutMs: 100,
      signal: controller.signal,
    }),
    error => error?.name === 'AbortError',
  );
});
