import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

import {
  Ret1ProtocolError,
  buildAad,
  buildEnrollmentConfig,
  buildHandshakeTranscript,
  completeHandshake,
  decodeBase64Url,
  decryptResult,
  encodeBase64Url,
  encodeRet1Frame,
  encryptProvision,
  generateClientHello,
  makeSequenceNonce,
  parseEnrollmentTicket,
  parseRet1Line,
  parseStrictJsonObject,
  sha256,
  validateHello,
  validateHelloAck,
  validateEnrollmentWifi,
  validateStatus,
} from './terminalEnrollmentProtocol.js';

// Vendored byte-for-byte from private firmware main fd8671bd, source file
// tools/enrollment_protocol_vectors.json (protocol implementation 0fe3908c).
const vector = JSON.parse(await readFile(
  new URL('./fixtures/ret1-v1-vector.json', import.meta.url),
  'utf8',
));

const encoder = new TextEncoder();

function fromHex(value) {
  return Uint8Array.from(value.match(/../gu).map(byte => Number.parseInt(byte, 16)));
}

function toHex(value) {
  return Buffer.from(value).toString('hex');
}

function privateJwk(privateHex, publicBase64Url) {
  const point = decodeBase64Url(publicBase64Url, 65);
  return {
    kty: 'EC',
    crv: 'P-256',
    d: encodeBase64Url(fromHex(privateHex)),
    x: encodeBase64Url(point.subarray(1, 33)),
    y: encodeBase64Url(point.subarray(33, 65)),
    ext: true,
    key_ops: ['deriveBits'],
  };
}

function fixtureHello() {
  return {
    v: 1,
    type: 'hello',
    seq: 0,
    client_nonce: vector.client_nonce_b64url,
    client_public_key: vector.client_public_b64url,
  };
}

function fixtureHelloAck(overrides = {}) {
  return {
    v: 1,
    type: 'hello_ack',
    seq: 0,
    session_id: vector.session_id,
    session_sha256: encodeBase64Url(fromHex(vector.transcript_sha256_hex)),
    device_nonce: vector.device_nonce_b64url,
    device_public_key: vector.device_public_b64url,
    model: 'E1002',
    firmware_version: '0.2.0-candidate.3',
    factory_mac: 'aa:bb:cc:dd:ee:ff',
    chip: 'ESP32-S3',
    chip_revision: 0,
    config_generation: 0,
    identity_strength: 'physical_cable_only',
    attestation: false,
    ...overrides,
  };
}

async function fixtureHandshake() {
  const clientPrivateKey = await crypto.subtle.importKey(
    'jwk',
    privateJwk(vector.client_private_hex, vector.client_public_b64url),
    { name: 'ECDH', namedCurve: 'P-256' },
    false,
    ['deriveBits'],
  );
  return completeHandshake({
    hello: fixtureHello(),
    helloAck: fixtureHelloAck(),
    clientPrivateKey,
  });
}

function fixtureResultMessage(overrides = {}) {
  return {
    v: 1,
    type: 'result',
    session_id: vector.session_id,
    seq: 2,
    ciphertext: vector.result_ciphertext_b64url,
    tag: vector.result_tag_b64url,
    ...overrides,
  };
}

function expectCode(code) {
  return error => error instanceof Ret1ProtocolError && error.code === code;
}

test('strict base64url accepts canonical unpadded values and rejects aliases', () => {
  const value = Uint8Array.of(0xfb, 0xff, 0x00, 0x01);
  const encoded = encodeBase64Url(value);
  assert.equal(encoded, '-_8AAQ');
  assert.deepEqual(decodeBase64Url(encoded, 4), value);

  for (const invalid of ['+/8AAQ', '-_8AAQ==', 'A', 'ab c', 'é']) {
    assert.throws(() => decodeBase64Url(invalid), expectCode('invalid_base64url'));
  }
  assert.throws(() => decodeBase64Url(encoded, 5), expectCode('invalid_base64url'));
});

test('strict JSON and RET1 framing reject duplicate keys, trailing data, controls, and malformed UTF-8', () => {
  assert.deepEqual(parseStrictJsonObject('{"a":1,"nested":{"b":2}}'), { a: 1, nested: { b: 2 } });
  assert.throws(() => parseStrictJsonObject('{"a":1,"a":2}'), expectCode('duplicate_json_key'));
  assert.throws(() => parseStrictJsonObject('{"a":1} false'), expectCode('invalid_json'));
  assert.throws(() => parseStrictJsonObject('{"a":"\\ud800"}'), expectCode('invalid_json'));

  const hello = fixtureHello();
  assert.deepEqual(parseRet1Line(encodeRet1Frame(hello)), hello);
  assert.deepEqual(parseRet1Line(encoder.encode(`@RET1 ${JSON.stringify(hello)}\r\n`)), hello);
  assert.throws(
    () => parseRet1Line(Uint8Array.of(...encoder.encode('@RET1 {"v":'), 0xc3, 0x28, 0x7d, 0x0a)),
    expectCode('invalid_utf8'),
  );
  assert.throws(() => parseRet1Line(encoder.encode('diagnostic\n')), expectCode('not_ret1_frame'));
  assert.throws(() => parseRet1Line(encoder.encode('@RET1 {}\r')), expectCode('invalid_frame'));
  assert.throws(
    () => parseRet1Line(encoder.encode(`@RET1 {"v":1,"v":1}${' '.repeat(4096)}\n`)),
    expectCode('frame_too_large'),
  );
});

test('status, hello, and hello_ack validators enforce exact bounded firmware shapes', () => {
  assert.equal(validateHello(fixtureHello()).clientNonce.length, 32);
  assert.equal(validateHelloAck(fixtureHelloAck()).devicePublicKey.length, 65);
  const status = {
    v: 2,
    type: 'status',
    state: 'provisioning_required',
    model: 'E1002',
    firmware_version: '0.2.0-candidate.3',
    factory_mac: 'aa:bb:cc:dd:ee:ff',
    config_source: 'fallback',
    config_generation: 0,
    enrollment_available: true,
    enrollment_key_id: 'fixture-2026',
    partition_layout: 'ab-v1',
    running_partition: 'ota_0',
    boot_state: 'stable',
    partition_identity_valid: true,
    firmware_build_id: '0123456789abcdef0123456789abcdef01234567',
    identity_strength: 'physical_cable_only',
    attestation: false,
  };
  assert.equal(validateStatus(status), status);
  const legacyStatus = {
    ...status,
    v: 1,
  };
  delete legacyStatus.partition_layout;
  delete legacyStatus.running_partition;
  delete legacyStatus.boot_state;
  delete legacyStatus.partition_identity_valid;
  delete legacyStatus.firmware_build_id;
  assert.equal(validateStatus(legacyStatus), legacyStatus);
  assert.throws(
    () => validateStatus({ ...legacyStatus, partition_layout: 'unknown' }),
    expectCode('invalid_status'),
  );

  assert.throws(() => validateHello({ ...fixtureHello(), extra: true }), expectCode('invalid_hello'));
  assert.throws(() => validateHelloAck(fixtureHelloAck({ session_id: 'not-base64!' })), expectCode('invalid_base64url'));
  assert.throws(() => validateHelloAck(fixtureHelloAck({ factory_mac: 'AA:BB:CC:DD:EE:FF' })), expectCode('invalid_hello_ack'));
  assert.throws(() => validateStatus({ ...status, enrollment_available: false }), expectCode('invalid_status'));
  assert.throws(() => validateStatus({ ...status, model: 'E9999' }), expectCode('invalid_status'));
  assert.throws(() => validateStatus({ ...status, partition_layout: 'ab-v2' }), expectCode('invalid_status'));
  assert.throws(() => validateStatus({ ...status, firmware_build_id: 'not-a-build' }), expectCode('invalid_status'));
  assert.equal(validateStatus({
    ...status,
    partition_layout: 'unknown',
    running_partition: 'unknown',
    partition_identity_valid: false,
  }).partition_identity_valid, false);
});

test('deterministic P-256 handshake derives the exact RET1 transcript, HKDF keys, nonces, and AAD', async () => {
  const handshake = await fixtureHandshake();
  assert.equal(toHex(handshake.transcriptSha256), vector.transcript_sha256_hex);
  assert.equal(handshake.sessionId, vector.session_id);
  assert.equal(handshake.clientToDeviceKey.extractable, false);
  assert.equal(handshake.deviceToClientKey.extractable, false);
  assert.equal(toHex(makeSequenceNonce(handshake.clientNoncePrefix, 1)), vector.client_to_device_nonce_seq1_hex);
  assert.equal(toHex(makeSequenceNonce(handshake.deviceNoncePrefix, 2)), vector.result_nonce_seq2_hex);
  assert.equal(
    toHex(buildAad('provision', handshake.transcriptSha256, 1, fromHex(vector.ticket_sha256_hex))),
    vector.provision_aad_hex,
  );
  assert.equal(
    toHex(buildAad('result', handshake.transcriptSha256, 2, fromHex(vector.ticket_sha256_hex))),
    vector.result_aad_hex,
  );
});

test('generated client hello uses a non-extractable private key and valid public RET1 fields', async () => {
  const generated = await generateClientHello();
  const parsed = validateHello(generated.hello);
  assert.equal(generated.clientPrivateKey.extractable, false);
  assert.equal(parsed.clientNonce.length, 32);
  assert.equal(parsed.clientPublicKey.length, 65);
  assert.equal(parsed.clientPublicKey[0], 4);
});

test('transcript mutation and invalid P-256 points fail the handshake closed', async () => {
  const clientPrivateKey = await crypto.subtle.importKey(
    'jwk',
    privateJwk(vector.client_private_hex, vector.client_public_b64url),
    { name: 'ECDH', namedCurve: 'P-256' },
    false,
    ['deriveBits'],
  );
  await assert.rejects(
    completeHandshake({ hello: fixtureHello(), helloAck: fixtureHelloAck({ firmware_version: 'changed' }), clientPrivateKey }),
    expectCode('transcript_mismatch'),
  );
  const invalidPoint = new Uint8Array(65);
  invalidPoint[0] = 4;
  const invalidAck = fixtureHelloAck({ device_public_key: encodeBase64Url(invalidPoint) });
  const invalidTranscriptHash = await sha256(buildHandshakeTranscript(fixtureHello(), invalidAck));
  invalidAck.session_sha256 = encodeBase64Url(invalidTranscriptHash);
  invalidAck.session_id = encodeBase64Url(invalidTranscriptHash.subarray(0, 16));
  await assert.rejects(
    completeHandshake({
      hello: fixtureHello(),
      helloAck: invalidAck,
      clientPrivateKey,
    }),
    expectCode('handshake_failed'),
  );
});

test('config builder reproduces the exact fixture and enforces UTF-8, password, URL, and total bounds', async () => {
  assert.deepEqual(validateEnrollmentWifi({ ssid: 'FixtureWiFi', password: 'correct horse' }), {
    ssidBytes: 11,
    passwordBytes: 13,
  });
  const built = buildEnrollmentConfig({
    ssid: 'FixtureWiFi',
    password: 'correct horse',
    scheduleUrl: 'https://email.mcchord.net/terminal/FIXTURE/schedule.json',
  });
  assert.equal(new TextDecoder().decode(built.bytes), vector.config_utf8);
  assert.equal(toHex(await sha256(built.bytes)), vector.config_sha256_hex);

  assert.throws(() => buildEnrollmentConfig({ ssid: '😀'.repeat(9), password: '', scheduleUrl: 'https://host/x' }), expectCode('invalid_ssid'));
  assert.throws(() => buildEnrollmentConfig({ ssid: '   ', password: '', scheduleUrl: 'https://host/x' }), expectCode('invalid_ssid'));
  assert.throws(() => buildEnrollmentConfig({ ssid: 'ok', password: 'x'.repeat(64), scheduleUrl: 'https://host/x' }), expectCode('invalid_password'));
  assert.doesNotThrow(() => buildEnrollmentConfig({ ssid: 'ok', password: 'a'.repeat(64), scheduleUrl: 'https://host/x' }));
  assert.throws(() => buildEnrollmentConfig({ ssid: 'ok', password: '', scheduleUrl: 'http://host/x' }), expectCode('invalid_schedule_url'));
  assert.throws(() => buildEnrollmentConfig({ ssid: 'ok', password: '', scheduleUrl: 'https://host/x?%76ariant=bw' }), expectCode('invalid_schedule_url'));
  assert.throws(() => buildEnrollmentConfig({ ssid: 'ok', password: '', scheduleUrl: `https://host/${'x'.repeat(1015)}` }), expectCode('invalid_schedule_url'));
  assert.throws(() => buildEnrollmentConfig({ ssid: 'ok', password: '', scheduleUrl: `https://host/${'\\'.repeat(1000)}` }), expectCode('config_too_large'));
  assert.throws(() => buildEnrollmentConfig({ ssid: '\ud800', password: '', scheduleUrl: 'https://host/x' }), expectCode('invalid_ssid'));
});

test('ticket parser enforces exact JWS fields, bounds, lifetime, and expected bindings', () => {
  const parsed = parseEnrollmentTicket(vector.compact_jws, {
    kid: 'fixture-2026',
    operation: 'provision',
    sessionSha256: fromHex(vector.transcript_sha256_hex),
    configSha256: fromHex(vector.config_sha256_hex),
    model: 'E1002',
    mac: 'aa:bb:cc:dd:ee:ff',
    generation: 1,
    nowEpochSeconds: 1788050001,
  });
  assert.equal(parsed.payload.terminal_id, 'fixture-terminal');

  assert.throws(() => parseEnrollmentTicket(`${vector.compact_jws}=`), expectCode('invalid_base64url'));
  assert.throws(() => parseEnrollmentTicket(vector.compact_jws, { generation: 2 }), expectCode('ticket_mismatch'));
  assert.throws(() => parseEnrollmentTicket(vector.compact_jws, { kid: 'wrong-key' }), expectCode('ticket_mismatch'));
  assert.throws(() => parseEnrollmentTicket(vector.compact_jws, { nowEpochSeconds: 1788050300 }), expectCode('ticket_expired'));
  const [header, payload, signature] = vector.compact_jws.split('.');
  const duplicated = encodeBase64Url(encoder.encode('{"alg":"ES256","alg":"ES256","kid":"fixture-2026","typ":"RET-ENROLL"}'));
  assert.throws(() => parseEnrollmentTicket(`${duplicated}.${payload}.${signature}`), expectCode('duplicate_json_key'));
  assert.doesNotThrow(() => parseEnrollmentTicket(`${header}.${payload}.${signature}`));
});

test('provision encryption matches the exact firmware vector and frame contract', async () => {
  const handshake = await fixtureHandshake();
  const config = encoder.encode(vector.config_utf8);
  const provision = await encryptProvision({
    handshake,
    ticket: vector.compact_jws,
    configBytes: config,
    expectedKeyId: 'fixture-2026',
  });
  assert.equal(provision.message.ciphertext, vector.provision_ciphertext_b64url);
  assert.equal(provision.message.tag, vector.provision_tag_b64url);
  assert.deepEqual(parseRet1Line(provision.frame), provision.message);
  assert.equal(toHex(provision.configSha256), vector.config_sha256_hex);
  assert.equal(toHex(provision.ticketSha256), vector.ticket_sha256_hex);

  const nonCanonical = encoder.encode(`{ "schema_version":1,"wifi":{"ssid":"FixtureWiFi","password":"correct horse"},"server":{"schedule_url":"https://email.mcchord.net/terminal/FIXTURE/schedule.json"}}`);
  await assert.rejects(
    encryptProvision({ handshake, ticket: vector.compact_jws, configBytes: nonCanonical }),
    expectCode('invalid_config'),
  );
});

test('result decryption matches the vector and rejects wrong tag, AAD, nonce, envelope, and expectation', async () => {
  const handshake = await fixtureHandshake();
  const expected = {
    operation: 'provision',
    generation: 1,
    configSha256: fromHex(vector.config_sha256_hex),
  };
  const result = await decryptResult({
    handshake,
    ticket: vector.compact_jws,
    message: fixtureResultMessage(),
    expected,
  });
  assert.equal(result.operation, 'provision');
  assert.equal(result.generation, 1);
  assert.equal(toHex(result.configSha256), vector.config_sha256_hex);

  const wrongTag = decodeBase64Url(vector.result_tag_b64url, 16);
  wrongTag[15] ^= 1;
  await assert.rejects(
    decryptResult({ handshake, ticket: vector.compact_jws, message: fixtureResultMessage({ tag: encodeBase64Url(wrongTag) }), expected }),
    expectCode('result_authentication_failed'),
  );
  const wrongAadHandshake = { ...handshake, transcriptSha256: handshake.transcriptSha256.slice() };
  wrongAadHandshake.transcriptSha256[31] ^= 1;
  await assert.rejects(
    decryptResult({ handshake: wrongAadHandshake, ticket: vector.compact_jws, message: fixtureResultMessage(), expected }),
    expectCode('result_authentication_failed'),
  );
  const wrongNonceHandshake = { ...handshake, deviceNoncePrefix: handshake.deviceNoncePrefix.slice() };
  wrongNonceHandshake.deviceNoncePrefix[3] ^= 1;
  await assert.rejects(
    decryptResult({ handshake: wrongNonceHandshake, ticket: vector.compact_jws, message: fixtureResultMessage(), expected }),
    expectCode('result_authentication_failed'),
  );
  await assert.rejects(
    decryptResult({ handshake, ticket: vector.compact_jws, message: fixtureResultMessage({ seq: 1 }), expected }),
    expectCode('invalid_result'),
  );
  await assert.rejects(
    decryptResult({ handshake, ticket: vector.compact_jws, message: fixtureResultMessage(), expected: { ...expected, generation: 2 } }),
    expectCode('result_mismatch'),
  );
});
