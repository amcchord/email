const RET1_PREFIX = '@RET1 ';
const UTF8 = new TextEncoder();
const UTF8_FATAL = new TextDecoder('utf-8', { fatal: true });
const BASE64URL_RE = /^[A-Za-z0-9_-]*$/;
const IDENTIFIER_RE = /^[A-Za-z0-9._-]{1,64}$/;
const MAC_RE = /^[0-9a-f]{2}(?::[0-9a-f]{2}){5}$/;
const HEX_PSK_RE = /^[0-9A-Fa-f]{64}$/;
const UINT32_MAX = 0xffffffff;

export const RET1_LIMITS = Object.freeze({
  maxLineBytes: 4096,
  maxConfigBytes: 1536,
  maxTicketBytes: 3072,
  tagBytes: 16,
});

export class Ret1ProtocolError extends Error {
  constructor(code, message = code) {
    super(message);
    this.name = 'Ret1ProtocolError';
    this.code = code;
  }
}

function fail(code, message) {
  throw new Ret1ProtocolError(code, message);
}

function cryptoRuntime(runtime = globalThis.crypto) {
  if (!runtime?.subtle || typeof runtime.getRandomValues !== 'function') {
    fail('crypto_unavailable', 'Required Web Crypto operations are unavailable.');
  }
  return runtime;
}

function bytes(value, code = 'invalid_bytes') {
  if (value instanceof Uint8Array) return value;
  if (value instanceof ArrayBuffer) return new Uint8Array(value);
  if (ArrayBuffer.isView(value)) {
    return new Uint8Array(value.buffer, value.byteOffset, value.byteLength);
  }
  fail(code, 'Expected a byte buffer.');
}

function concatBytes(...parts) {
  const normalized = parts.map(part => bytes(part));
  const output = new Uint8Array(normalized.reduce((sum, part) => sum + part.length, 0));
  let offset = 0;
  for (const part of normalized) {
    output.set(part, offset);
    offset += part.length;
  }
  return output;
}

export function clearMutableBytes(value) {
  if (value instanceof Uint8Array) value.fill(0);
  else if (value instanceof ArrayBuffer) new Uint8Array(value).fill(0);
  else if (ArrayBuffer.isView(value)) {
    new Uint8Array(value.buffer, value.byteOffset, value.byteLength).fill(0);
  }
}

function constantTimeEqual(left, right) {
  const a = bytes(left);
  const b = bytes(right);
  if (a.length !== b.length) return false;
  let difference = 0;
  for (let index = 0; index < a.length; index += 1) difference |= a[index] ^ b[index];
  return difference === 0;
}

function assertWellFormedString(value, code) {
  if (typeof value !== 'string') fail(code, 'Expected a string.');
  for (let index = 0; index < value.length; index += 1) {
    const unit = value.charCodeAt(index);
    if (unit >= 0xd800 && unit <= 0xdbff) {
      const next = value.charCodeAt(index + 1);
      if (!(next >= 0xdc00 && next <= 0xdfff)) fail(code, 'String contains malformed Unicode.');
      index += 1;
    } else if (unit >= 0xdc00 && unit <= 0xdfff) {
      fail(code, 'String contains malformed Unicode.');
    }
  }
  return value;
}

function hasControl(value) {
  for (const character of value) {
    const codepoint = character.codePointAt(0);
    if (codepoint < 0x20 || codepoint === 0x7f) return true;
  }
  return false;
}

function assertBoundedString(value, minimum, maximum, code) {
  assertWellFormedString(value, code);
  const length = UTF8.encode(value).length;
  if (length < minimum || length > maximum || hasControl(value)) {
    fail(code, 'String is outside the RET1 bounds.');
  }
  return value;
}

function assertPlainObject(value, code) {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) {
    fail(code, 'Expected an object.');
  }
  return value;
}

function assertExactKeys(value, required, code) {
  assertPlainObject(value, code);
  const keys = Object.keys(value);
  if (keys.length !== required.length
    || required.some(key => !Object.hasOwn(value, key))
    || keys.some(key => !required.includes(key))) {
    fail(code, 'RET1 object fields do not match the exact schema.');
  }
}

function assertInteger(value, minimum, maximum, code) {
  if (!Number.isSafeInteger(value) || value < minimum || value > maximum) {
    fail(code, 'Integer is outside the RET1 bounds.');
  }
  return value;
}

function encodeBinaryString(input) {
  let value = '';
  for (let index = 0; index < input.length; index += 1) value += String.fromCharCode(input[index]);
  return value;
}

export function encodeBase64Url(value) {
  const input = bytes(value, 'invalid_base64url');
  if (typeof globalThis.btoa !== 'function') fail('base64_unavailable', 'Base64 encoding is unavailable.');
  return globalThis.btoa(encodeBinaryString(input))
    .replaceAll('+', '-')
    .replaceAll('/', '_')
    .replace(/=+$/u, '');
}

export function decodeBase64Url(value, expectedLength = null, maximumLength = null) {
  if (typeof value !== 'string' || !BASE64URL_RE.test(value) || value.length % 4 === 1) {
    fail('invalid_base64url', 'Value is not canonical base64url.');
  }
  if (typeof globalThis.atob !== 'function') fail('base64_unavailable', 'Base64 decoding is unavailable.');
  const padded = value.replaceAll('-', '+').replaceAll('_', '/') + '='.repeat((4 - value.length % 4) % 4);
  let decoded;
  try {
    decoded = globalThis.atob(padded);
  } catch {
    fail('invalid_base64url', 'Value is not valid base64url.');
  }
  const output = new Uint8Array(decoded.length);
  for (let index = 0; index < decoded.length; index += 1) output[index] = decoded.charCodeAt(index);
  if (encodeBase64Url(output) !== value
    || (expectedLength !== null && output.length !== expectedLength)
    || (maximumLength !== null && output.length > maximumLength)) {
    clearMutableBytes(output);
    fail('invalid_base64url', 'Base64url value has an invalid encoding or length.');
  }
  return output;
}

function skipWhitespace(source, cursor) {
  while (cursor.index < source.length && /[\u0009\u000a\u000d\u0020]/u.test(source[cursor.index])) {
    cursor.index += 1;
  }
}

function scanJsonString(source, cursor) {
  const start = cursor.index;
  if (source[cursor.index] !== '"') fail('invalid_json', 'Expected JSON string.');
  cursor.index += 1;
  while (cursor.index < source.length) {
    const unit = source.charCodeAt(cursor.index);
    if (unit === 0x22) {
      cursor.index += 1;
      const raw = source.slice(start, cursor.index);
      try {
        return JSON.parse(raw);
      } catch {
        fail('invalid_json', 'Invalid JSON string.');
      }
    }
    if (unit < 0x20) fail('invalid_json', 'JSON string contains a control character.');
    if (unit === 0x5c) {
      cursor.index += 1;
      const escape = source[cursor.index];
      if ('"\\/bfnrt'.includes(escape)) {
        cursor.index += 1;
        continue;
      }
      if (escape !== 'u' || !/^[0-9A-Fa-f]{4}$/u.test(source.slice(cursor.index + 1, cursor.index + 5))) {
        fail('invalid_json', 'JSON contains an invalid escape.');
      }
      const escaped = Number.parseInt(source.slice(cursor.index + 1, cursor.index + 5), 16);
      cursor.index += 5;
      if (escaped >= 0xd800 && escaped <= 0xdbff) {
        if (source.slice(cursor.index, cursor.index + 2) !== '\\u'
          || !/^[0-9A-Fa-f]{4}$/u.test(source.slice(cursor.index + 2, cursor.index + 6))) {
          fail('invalid_json', 'JSON contains an unpaired surrogate.');
        }
        const low = Number.parseInt(source.slice(cursor.index + 2, cursor.index + 6), 16);
        if (low < 0xdc00 || low > 0xdfff) fail('invalid_json', 'JSON contains an unpaired surrogate.');
        cursor.index += 6;
      } else if (escaped >= 0xdc00 && escaped <= 0xdfff) {
        fail('invalid_json', 'JSON contains an unpaired surrogate.');
      }
      continue;
    }
    if (unit >= 0xd800 && unit <= 0xdbff) {
      const low = source.charCodeAt(cursor.index + 1);
      if (low < 0xdc00 || low > 0xdfff) fail('invalid_json', 'JSON contains malformed Unicode.');
      cursor.index += 2;
      continue;
    }
    if (unit >= 0xdc00 && unit <= 0xdfff) fail('invalid_json', 'JSON contains malformed Unicode.');
    cursor.index += 1;
  }
  fail('invalid_json', 'Unterminated JSON string.');
}

function scanJsonValue(source, cursor) {
  skipWhitespace(source, cursor);
  const current = source[cursor.index];
  if (current === '{') {
    cursor.index += 1;
    skipWhitespace(source, cursor);
    const keys = new Set();
    if (source[cursor.index] === '}') {
      cursor.index += 1;
      return;
    }
    while (cursor.index < source.length) {
      skipWhitespace(source, cursor);
      const key = scanJsonString(source, cursor);
      if (keys.has(key)) fail('duplicate_json_key', 'JSON object contains a duplicate key.');
      keys.add(key);
      skipWhitespace(source, cursor);
      if (source[cursor.index] !== ':') fail('invalid_json', 'Expected JSON object separator.');
      cursor.index += 1;
      scanJsonValue(source, cursor);
      skipWhitespace(source, cursor);
      if (source[cursor.index] === '}') {
        cursor.index += 1;
        return;
      }
      if (source[cursor.index] !== ',') fail('invalid_json', 'Expected JSON object delimiter.');
      cursor.index += 1;
    }
    fail('invalid_json', 'Unterminated JSON object.');
  }
  if (current === '[') {
    cursor.index += 1;
    skipWhitespace(source, cursor);
    if (source[cursor.index] === ']') {
      cursor.index += 1;
      return;
    }
    while (cursor.index < source.length) {
      scanJsonValue(source, cursor);
      skipWhitespace(source, cursor);
      if (source[cursor.index] === ']') {
        cursor.index += 1;
        return;
      }
      if (source[cursor.index] !== ',') fail('invalid_json', 'Expected JSON array delimiter.');
      cursor.index += 1;
    }
    fail('invalid_json', 'Unterminated JSON array.');
  }
  if (current === '"') {
    scanJsonString(source, cursor);
    return;
  }
  for (const literal of ['true', 'false', 'null']) {
    if (source.startsWith(literal, cursor.index)) {
      cursor.index += literal.length;
      return;
    }
  }
  const match = source.slice(cursor.index).match(/^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?/u);
  if (!match) fail('invalid_json', 'Invalid JSON value.');
  cursor.index += match[0].length;
}

export function parseStrictJsonObject(source) {
  assertWellFormedString(source, 'invalid_json');
  const cursor = { index: 0 };
  scanJsonValue(source, cursor);
  skipWhitespace(source, cursor);
  if (cursor.index !== source.length) fail('invalid_json', 'JSON has trailing data.');
  let parsed;
  try {
    parsed = JSON.parse(source);
  } catch {
    fail('invalid_json', 'Invalid JSON.');
  }
  return assertPlainObject(parsed, 'invalid_json');
}

export function encodeRet1Frame(message) {
  const json = JSON.stringify(assertPlainObject(message, 'invalid_message'));
  const frame = UTF8.encode(`${RET1_PREFIX}${json}\n`);
  if (frame.length > RET1_LIMITS.maxLineBytes + 1) fail('frame_too_large', 'RET1 frame is too large.');
  return frame;
}

export function parseRet1Line(value) {
  let input = bytes(value, 'invalid_frame');
  if (input.length === 0) {
    fail('frame_too_large', 'RET1 frame is too large.');
  }
  if (input[input.length - 1] === 0x0a) {
    input = input.subarray(0, input.length - 1);
    if (input[input.length - 1] === 0x0d) input = input.subarray(0, input.length - 1);
    if (input.length > RET1_LIMITS.maxLineBytes) fail('frame_too_large', 'RET1 frame is too large.');
  } else {
    if (input.length > RET1_LIMITS.maxLineBytes) fail('frame_too_large', 'RET1 frame is too large.');
    if (input[input.length - 1] === 0x0d) fail('invalid_frame', 'A carriage return is valid only before newline.');
  }
  let text;
  try {
    text = UTF8_FATAL.decode(input);
  } catch {
    fail('invalid_utf8', 'RET1 frame is not valid UTF-8.');
  }
  if (!text.startsWith(RET1_PREFIX)) fail('not_ret1_frame', 'Line is not a RET1 frame.');
  return parseStrictJsonObject(text.slice(RET1_PREFIX.length));
}

function validateMac(value, code) {
  if (typeof value !== 'string' || !MAC_RE.test(value)) fail(code, 'Invalid factory MAC.');
  return value;
}

function validateModel(value, code) {
  if (!['E1001', 'E1002', 'E1004'].includes(value)) fail(code, 'Unsupported model.');
  return value;
}

const BUILD_ID_RE = /^(?:[0-9a-f]{40}(?:-dirty)?|unknown)$/;

function validateRuntimeIdentity(message) {
  if (!['ab-v1', 'unknown'].includes(message.partition_layout)
    || !['ota_0', 'ota_1', 'unknown'].includes(message.running_partition)
    || !['stable', 'pending_validation', 'invalid'].includes(message.boot_state)
    || typeof message.partition_identity_valid !== 'boolean'
    || typeof message.firmware_build_id !== 'string'
    || !BUILD_ID_RE.test(message.firmware_build_id)) {
    fail('invalid_status', 'Invalid firmware runtime identity.');
  }
  if (message.partition_identity_valid) {
    if (message.partition_layout !== 'ab-v1'
      || !['ota_0', 'ota_1'].includes(message.running_partition)) {
      fail('invalid_status', 'Validated partition identity is inconsistent.');
    }
  } else if (message.partition_layout !== 'unknown' || message.running_partition !== 'unknown') {
    fail('invalid_status', 'Unvalidated partition identity must remain unknown.');
  }
}

export function validateHello(message) {
  assertExactKeys(message, ['v', 'type', 'seq', 'client_nonce', 'client_public_key'], 'invalid_hello');
  if (message.v !== 1 || message.type !== 'hello' || message.seq !== 0) fail('invalid_hello', 'Invalid hello envelope.');
  const clientNonce = decodeBase64Url(message.client_nonce, 32);
  const clientPublicKey = decodeBase64Url(message.client_public_key, 65);
  if (clientPublicKey[0] !== 0x04) fail('invalid_hello', 'Client public key is not uncompressed P-256.');
  return { message, clientNonce, clientPublicKey };
}

export function validateStatus(message) {
  assertPlainObject(message, 'invalid_status');
  const commonKeys = [
    'v', 'type', 'state', 'model', 'firmware_version', 'factory_mac',
    'config_source', 'config_generation', 'enrollment_available',
    'enrollment_key_id', 'identity_strength', 'attestation',
  ];
  if (message.v === 1) {
    assertExactKeys(message, commonKeys, 'invalid_status');
  } else if (message.v === 2) {
    assertExactKeys(message, [
      ...commonKeys, 'partition_layout', 'running_partition', 'boot_state',
      'partition_identity_valid', 'firmware_build_id',
    ], 'invalid_status');
  } else {
    fail('invalid_status', 'Unsupported RET1 status version.');
  }
  if (message.type !== 'status'
    || !['storage_error', 'config_ready', 'provisioning_required'].includes(message.state)
    || !['nvs', 'file', 'fallback'].includes(message.config_source)
    || typeof message.enrollment_available !== 'boolean'
    || message.identity_strength !== 'physical_cable_only'
    || message.attestation !== false) {
    fail('invalid_status', 'Invalid RET1 status state.');
  }
  validateModel(message.model, 'invalid_status');
  assertBoundedString(message.firmware_version, 1, 128, 'invalid_status');
  validateMac(message.factory_mac, 'invalid_status');
  assertInteger(message.config_generation, 0, UINT32_MAX, 'invalid_status');
  if (message.v === 2) validateRuntimeIdentity(message);
  if (message.enrollment_available) {
    if (typeof message.enrollment_key_id !== 'string' || !IDENTIFIER_RE.test(message.enrollment_key_id)) {
      fail('invalid_status', 'Enrollment key id is invalid.');
    }
  } else if (message.enrollment_key_id !== '') {
    fail('invalid_status', 'Unavailable enrollment must not name a key.');
  }
  return message;
}

export function validateHelloAck(message) {
  assertExactKeys(message, [
    'v', 'type', 'seq', 'session_id', 'session_sha256', 'device_nonce',
    'device_public_key', 'model', 'firmware_version', 'factory_mac', 'chip',
    'chip_revision', 'config_generation', 'identity_strength', 'attestation',
  ], 'invalid_hello_ack');
  if (message.v !== 1 || message.type !== 'hello_ack' || message.seq !== 0
    || message.chip !== 'ESP32-S3' || message.identity_strength !== 'physical_cable_only'
    || message.attestation !== false) {
    fail('invalid_hello_ack', 'Invalid hello acknowledgement envelope.');
  }
  const sessionId = decodeBase64Url(message.session_id, 16);
  const sessionSha256 = decodeBase64Url(message.session_sha256, 32);
  const deviceNonce = decodeBase64Url(message.device_nonce, 32);
  const devicePublicKey = decodeBase64Url(message.device_public_key, 65);
  if (devicePublicKey[0] !== 0x04) fail('invalid_hello_ack', 'Device public key is not uncompressed P-256.');
  validateModel(message.model, 'invalid_hello_ack');
  assertBoundedString(message.firmware_version, 1, 128, 'invalid_hello_ack');
  validateMac(message.factory_mac, 'invalid_hello_ack');
  assertInteger(message.chip_revision, 0, UINT32_MAX, 'invalid_hello_ack');
  assertInteger(message.config_generation, 0, UINT32_MAX, 'invalid_hello_ack');
  return { message, sessionId, sessionSha256, deviceNonce, devicePublicKey };
}

function field(value) {
  const input = bytes(value);
  if (input.length > 0xffff) fail('field_too_large', 'RET1 transcript field is too large.');
  return concatBytes(new Uint8Array([input.length >>> 8, input.length & 0xff]), input);
}

export function buildHandshakeTranscript(hello, helloAck) {
  const client = validateHello(hello);
  const device = validateHelloAck(helloAck);
  return concatBytes(
    UTF8.encode('RET1-HS1'),
    field(UTF8.encode(device.message.model)),
    field(UTF8.encode(device.message.firmware_version)),
    field(UTF8.encode(device.message.factory_mac)),
    field(client.clientPublicKey),
    field(client.clientNonce),
    field(device.devicePublicKey),
    field(device.deviceNonce),
  );
}

export async function generateClientHello(runtime = globalThis.crypto) {
  const crypto = cryptoRuntime(runtime);
  const keyPair = await crypto.subtle.generateKey(
    { name: 'ECDH', namedCurve: 'P-256' },
    false,
    ['deriveBits'],
  );
  const clientPublicKey = new Uint8Array(await crypto.subtle.exportKey('raw', keyPair.publicKey));
  const clientNonce = crypto.getRandomValues(new Uint8Array(32));
  const hello = {
    v: 1,
    type: 'hello',
    seq: 0,
    client_nonce: encodeBase64Url(clientNonce),
    client_public_key: encodeBase64Url(clientPublicKey),
  };
  validateHello(hello);
  return { hello, clientPrivateKey: keyPair.privateKey, clientNonce, clientPublicKey };
}

export async function completeHandshake({ hello, helloAck, clientPrivateKey, runtime = globalThis.crypto }) {
  const crypto = cryptoRuntime(runtime);
  if (!clientPrivateKey) fail('missing_client_key', 'Client private key is required.');
  const client = validateHello(hello);
  const device = validateHelloAck(helloAck);
  const transcript = buildHandshakeTranscript(hello, helloAck);
  const transcriptSha256 = new Uint8Array(await crypto.subtle.digest('SHA-256', transcript));
  if (!constantTimeEqual(transcriptSha256, device.sessionSha256)
    || !constantTimeEqual(transcriptSha256.subarray(0, 16), device.sessionId)) {
    fail('transcript_mismatch', 'Device session does not match the RET1 transcript.');
  }

  let sharedSecret;
  let material;
  try {
    const devicePublic = await crypto.subtle.importKey(
      'raw',
      device.devicePublicKey,
      { name: 'ECDH', namedCurve: 'P-256' },
      false,
      [],
    );
    sharedSecret = new Uint8Array(await crypto.subtle.deriveBits(
      { name: 'ECDH', public: devicePublic },
      clientPrivateKey,
      256,
    ));
    const saltInput = concatBytes(UTF8.encode('RET1-SALT1'), client.clientNonce, device.deviceNonce);
    const salt = new Uint8Array(await crypto.subtle.digest('SHA-256', saltInput));
    clearMutableBytes(saltInput);
    const hkdfKey = await crypto.subtle.importKey('raw', sharedSecret, 'HKDF', false, ['deriveBits']);
    material = new Uint8Array(await crypto.subtle.deriveBits({
      name: 'HKDF',
      hash: 'SHA-256',
      salt,
      info: concatBytes(UTF8.encode('reterminal-enrollment-v1'), transcriptSha256),
    }, hkdfKey, 72 * 8));
    clearMutableBytes(salt);
    const clientToDeviceKey = await crypto.subtle.importKey(
      'raw', material.subarray(0, 32), 'AES-GCM', false, ['encrypt'],
    );
    const deviceToClientKey = await crypto.subtle.importKey(
      'raw', material.subarray(32, 64), 'AES-GCM', false, ['decrypt'],
    );
    return Object.freeze({
      sessionId: helloAck.session_id,
      transcriptSha256,
      clientToDeviceKey,
      deviceToClientKey,
      clientNoncePrefix: material.slice(64, 68),
      deviceNoncePrefix: material.slice(68, 72),
      model: helloAck.model,
      firmwareVersion: helloAck.firmware_version,
      factoryMac: helloAck.factory_mac,
      configGeneration: helloAck.config_generation,
    });
  } catch (error) {
    if (error instanceof Ret1ProtocolError) throw error;
    fail('handshake_failed', 'RET1 key agreement failed.');
  } finally {
    clearMutableBytes(sharedSecret);
    clearMutableBytes(material);
  }
}

function validateScheduleUrl(value) {
  assertWellFormedString(value, 'invalid_schedule_url');
  const encoded = UTF8.encode(value);
  if (encoded.length === 0 || encoded.length > 1024 || hasControl(value)
    || [...value].some(character => /\s/u.test(character))
    || !value.startsWith('https://')) {
    fail('invalid_schedule_url', 'Schedule URL is outside the RET1 security bounds.');
  }
  const lower = value.toLowerCase();
  for (const marker of ['replace_with', 'your_terminal', '.example.test', '{', '}', '<', '>', '%7b', '%7d']) {
    if (lower.includes(marker)) fail('invalid_schedule_url', 'Schedule URL contains a template marker.');
  }
  let parsed;
  try {
    parsed = new URL(value);
  } catch {
    fail('invalid_schedule_url', 'Schedule URL is invalid.');
  }
  if (parsed.protocol !== 'https:' || !parsed.hostname) {
    fail('invalid_schedule_url', 'Schedule URL must use an HTTPS host.');
  }
  const queryStart = lower.indexOf('?');
  if (queryStart >= 0) {
    const fragmentStart = lower.indexOf('#', queryStart + 1);
    const query = lower.slice(queryStart + 1, fragmentStart < 0 ? undefined : fragmentStart);
    for (const item of query.split('&')) {
      const rawKey = item.split('=', 1)[0].replaceAll('+', ' ');
      let key;
      try {
        key = decodeURIComponent(rawKey);
      } catch {
        fail('invalid_schedule_url', 'Schedule URL query encoding is invalid.');
      }
      if (key.toLowerCase() === 'variant') fail('invalid_schedule_url', 'Schedule URL must not set variant.');
    }
  }
  return value;
}

export function buildEnrollmentConfig({ ssid, password, scheduleUrl }) {
  assertWellFormedString(ssid, 'invalid_ssid');
  assertWellFormedString(password, 'invalid_password');
  const ssidBytes = UTF8.encode(ssid);
  const passwordBytes = UTF8.encode(password);
  if (ssidBytes.length === 0 || ssidBytes.length > 32 || hasControl(ssid)) {
    fail('invalid_ssid', 'SSID must be 1 to 32 UTF-8 bytes without controls.');
  }
  if (hasControl(password)
    || !(passwordBytes.length <= 63 || (passwordBytes.length === 64 && HEX_PSK_RE.test(password)))) {
    fail('invalid_password', 'Wi-Fi password is outside the RET1 bounds.');
  }
  validateScheduleUrl(scheduleUrl);
  const value = {
    schema_version: 1,
    wifi: { ssid, password },
    server: { schedule_url: scheduleUrl },
  };
  const encoded = UTF8.encode(JSON.stringify(value));
  clearMutableBytes(ssidBytes);
  clearMutableBytes(passwordBytes);
  if (encoded.length === 0 || encoded.length > RET1_LIMITS.maxConfigBytes) {
    clearMutableBytes(encoded);
    fail('config_too_large', 'Enrollment configuration exceeds 1536 bytes.');
  }
  return { bytes: encoded };
}

export async function sha256(value, runtime = globalThis.crypto) {
  const crypto = cryptoRuntime(runtime);
  return new Uint8Array(await crypto.subtle.digest('SHA-256', bytes(value)));
}

async function sha256Text(value, runtime) {
  const encoded = UTF8.encode(value);
  try {
    return await sha256(encoded, runtime);
  } finally {
    clearMutableBytes(encoded);
  }
}

function decodeTicketJson(segment, maximumLength) {
  const raw = decodeBase64Url(segment, null, maximumLength);
  let text;
  try {
    text = UTF8_FATAL.decode(raw);
  } catch {
    clearMutableBytes(raw);
    fail('invalid_ticket', 'Ticket JSON is not UTF-8.');
  }
  clearMutableBytes(raw);
  return parseStrictJsonObject(text);
}

export function parseEnrollmentTicket(compact, expected = {}) {
  assertWellFormedString(compact, 'invalid_ticket');
  if (UTF8.encode(compact).length > RET1_LIMITS.maxTicketBytes) fail('invalid_ticket', 'Ticket is too large.');
  const segments = compact.split('.');
  if (segments.length !== 3 || segments.some(segment => segment.length === 0)) fail('invalid_ticket', 'Ticket is not compact JWS.');
  const header = decodeTicketJson(segments[0], 256);
  const payload = decodeTicketJson(segments[1], 1536);
  const signature = decodeBase64Url(segments[2], 64);
  clearMutableBytes(signature);
  assertExactKeys(header, ['alg', 'kid', 'typ'], 'invalid_ticket');
  assertExactKeys(payload, [
    'v', 'purpose', 'operation', 'session_sha256', 'device_model', 'device_mac',
    'terminal_id', 'config_sha256', 'generation', 'jti', 'issued_at', 'expires_at',
  ], 'invalid_ticket');
  if (header.alg !== 'ES256' || header.typ !== 'RET-ENROLL'
    || typeof header.kid !== 'string' || !IDENTIFIER_RE.test(header.kid)
    || payload.v !== 1 || payload.purpose !== 'terminal-enrollment'
    || !['provision', 'rollback'].includes(payload.operation)) {
    fail('invalid_ticket', 'Ticket header or purpose is invalid.');
  }
  const sessionSha256 = decodeBase64Url(payload.session_sha256, 32);
  const configSha256 = decodeBase64Url(payload.config_sha256, 32);
  validateModel(payload.device_model, 'invalid_ticket');
  validateMac(payload.device_mac, 'invalid_ticket');
  assertBoundedString(payload.terminal_id, 1, 128, 'invalid_ticket');
  assertBoundedString(payload.jti, 16, 128, 'invalid_ticket');
  assertInteger(payload.generation, 1, UINT32_MAX - 1, 'invalid_ticket');
  assertInteger(payload.issued_at, 1, Number.MAX_SAFE_INTEGER, 'invalid_ticket');
  assertInteger(payload.expires_at, 1, Number.MAX_SAFE_INTEGER, 'invalid_ticket');
  if (payload.expires_at <= payload.issued_at || payload.expires_at - payload.issued_at > 600) {
    fail('invalid_ticket', 'Ticket lifetime is invalid.');
  }
  const comparisons = [
    ['kid', header.kid], ['operation', payload.operation], ['model', payload.device_model],
    ['mac', payload.device_mac], ['generation', payload.generation],
  ];
  for (const [key, actual] of comparisons) {
    if (expected[key] !== undefined && expected[key] !== actual) fail('ticket_mismatch', `Ticket ${key} does not match.`);
  }
  if (expected.sessionSha256 && !constantTimeEqual(sessionSha256, expected.sessionSha256)) fail('ticket_mismatch', 'Ticket session does not match.');
  if (expected.configSha256 && !constantTimeEqual(configSha256, expected.configSha256)) fail('ticket_mismatch', 'Ticket config does not match.');
  if (expected.nowEpochSeconds !== undefined) {
    assertInteger(expected.nowEpochSeconds, 1, Number.MAX_SAFE_INTEGER, 'invalid_ticket_time');
    if (expected.nowEpochSeconds < payload.issued_at || expected.nowEpochSeconds >= payload.expires_at) {
      fail('ticket_expired', 'Ticket is not active at the supplied server time.');
    }
  }
  return { header, payload, sessionSha256, configSha256 };
}

export function makeSequenceNonce(prefix, sequence) {
  const input = bytes(prefix, 'invalid_nonce_prefix');
  if (input.length !== 4) fail('invalid_nonce_prefix', 'RET1 nonce prefix must be four bytes.');
  if (typeof sequence !== 'bigint' && (!Number.isSafeInteger(sequence) || sequence < 0)) {
    fail('invalid_sequence', 'RET1 sequence is outside uint64.');
  }
  const numeric = typeof sequence === 'bigint' ? sequence : BigInt(sequence);
  if (numeric < 0n || numeric > 0xffffffffffffffffn) fail('invalid_sequence', 'RET1 sequence is outside uint64.');
  const nonce = new Uint8Array(12);
  nonce.set(input, 0);
  let remaining = numeric;
  for (let index = 11; index >= 4; index -= 1) {
    nonce[index] = Number(remaining & 0xffn);
    remaining >>= 8n;
  }
  return nonce;
}

export function buildAad(messageType, transcriptSha256, sequence, ticketSha256) {
  assertBoundedString(messageType, 1, 64, 'invalid_message_type');
  const transcript = bytes(transcriptSha256);
  const ticket = bytes(ticketSha256);
  if (transcript.length !== 32 || ticket.length !== 32) fail('invalid_aad', 'RET1 AAD hashes must be 32 bytes.');
  const sequenceBytes = makeSequenceNonce(new Uint8Array(4), sequence).subarray(4);
  return concatBytes(UTF8.encode('RET1-AAD1'), field(UTF8.encode(messageType)), transcript, sequenceBytes, ticket);
}

export async function encryptProvision({
  handshake,
  ticket,
  configBytes,
  expectedKeyId = undefined,
  runtime = globalThis.crypto,
}) {
  const crypto = cryptoRuntime(runtime);
  if (!handshake?.clientToDeviceKey || !handshake?.transcriptSha256) fail('invalid_handshake', 'Completed handshake is required.');
  const config = bytes(configBytes, 'invalid_config');
  if (config.length === 0 || config.length > RET1_LIMITS.maxConfigBytes) fail('invalid_config', 'Config bytes are outside the RET1 bounds.');
  let configText;
  try {
    configText = UTF8_FATAL.decode(config);
  } catch {
    fail('invalid_config', 'Config is not valid UTF-8.');
  }
  const parsed = parseStrictJsonObject(configText);
  assertExactKeys(parsed, ['schema_version', 'wifi', 'server'], 'invalid_config');
  assertExactKeys(parsed.wifi, ['ssid', 'password'], 'invalid_config');
  assertExactKeys(parsed.server, ['schedule_url'], 'invalid_config');
  const rebuilt = buildEnrollmentConfig({
    ssid: parsed.wifi.ssid,
    password: parsed.wifi.password,
    scheduleUrl: parsed.server.schedule_url,
  });
  if (!constantTimeEqual(config, rebuilt.bytes)) {
    clearMutableBytes(rebuilt.bytes);
    fail('invalid_config', 'Config bytes are not in the exact RET1 encoding.');
  }
  clearMutableBytes(rebuilt.bytes);
  const configSha256 = await sha256(config, crypto);
  const parsedTicket = parseEnrollmentTicket(ticket, {
    kid: expectedKeyId,
    operation: 'provision',
    sessionSha256: handshake.transcriptSha256,
    configSha256,
    model: handshake.model,
    mac: handshake.factoryMac,
    generation: handshake.configGeneration + 1,
  });
  const ticketSha256 = await sha256Text(ticket, crypto);
  const nonce = makeSequenceNonce(handshake.clientNoncePrefix, 1);
  const aad = buildAad('provision', handshake.transcriptSha256, 1, ticketSha256);
  let sealed;
  try {
    sealed = new Uint8Array(await crypto.subtle.encrypt({
      name: 'AES-GCM', iv: nonce, additionalData: aad, tagLength: 128,
    }, handshake.clientToDeviceKey, config));
  } catch {
    fail('provision_encryption_failed', 'RET1 provision encryption failed.');
  } finally {
    clearMutableBytes(nonce);
    clearMutableBytes(aad);
  }
  const ciphertext = sealed.slice(0, -RET1_LIMITS.tagBytes);
  const tag = sealed.slice(-RET1_LIMITS.tagBytes);
  clearMutableBytes(sealed);
  try {
    const message = {
      v: 1,
      type: 'provision',
      session_id: handshake.sessionId,
      seq: 1,
      ticket,
      ciphertext: encodeBase64Url(ciphertext),
      tag: encodeBase64Url(tag),
    };
    const frame = encodeRet1Frame(message);
    return { message, frame, configSha256, ticketSha256, ticket: parsedTicket };
  } finally {
    clearMutableBytes(ciphertext);
    clearMutableBytes(tag);
  }
}

function validateResultMessage(message, sessionId) {
  assertExactKeys(message, ['v', 'type', 'session_id', 'seq', 'ciphertext', 'tag'], 'invalid_result');
  if (message.v !== 1 || message.type !== 'result' || message.seq !== 2 || message.session_id !== sessionId) {
    fail('invalid_result', 'Invalid result envelope.');
  }
  return {
    ciphertext: decodeBase64Url(message.ciphertext, null, RET1_LIMITS.maxConfigBytes),
    tag: decodeBase64Url(message.tag, RET1_LIMITS.tagBytes),
  };
}

export async function decryptResult({ handshake, ticket, message, expected = {}, runtime = globalThis.crypto }) {
  const crypto = cryptoRuntime(runtime);
  if (!handshake?.deviceToClientKey || !handshake?.transcriptSha256) fail('invalid_handshake', 'Completed handshake is required.');
  const encrypted = validateResultMessage(message, handshake.sessionId);
  const ticketSha256 = await sha256Text(ticket, crypto);
  const nonce = makeSequenceNonce(handshake.deviceNoncePrefix, 2);
  const aad = buildAad('result', handshake.transcriptSha256, 2, ticketSha256);
  const sealed = concatBytes(encrypted.ciphertext, encrypted.tag);
  clearMutableBytes(encrypted.ciphertext);
  clearMutableBytes(encrypted.tag);
  let plaintext;
  try {
    plaintext = new Uint8Array(await crypto.subtle.decrypt({
      name: 'AES-GCM', iv: nonce, additionalData: aad, tagLength: 128,
    }, handshake.deviceToClientKey, sealed));
  } catch {
    fail('result_authentication_failed', 'RET1 result authentication failed.');
  } finally {
    clearMutableBytes(nonce);
    clearMutableBytes(aad);
    clearMutableBytes(sealed);
  }
  try {
    const text = UTF8_FATAL.decode(plaintext);
    const result = parseStrictJsonObject(text);
    assertExactKeys(result, ['ok', 'operation', 'generation', 'config_sha256', 'rebooting'], 'invalid_result');
    const configSha256 = decodeBase64Url(result.config_sha256, 32);
    if (result.ok !== true || !['provision', 'rollback'].includes(result.operation)
      || result.rebooting !== true) fail('invalid_result', 'Invalid committed result.');
    assertInteger(result.generation, 1, UINT32_MAX - 1, 'invalid_result');
    if (expected.operation !== undefined && result.operation !== expected.operation) fail('result_mismatch', 'Result operation does not match.');
    if (expected.generation !== undefined && result.generation !== expected.generation) fail('result_mismatch', 'Result generation does not match.');
    if (expected.configSha256 && !constantTimeEqual(configSha256, expected.configSha256)) fail('result_mismatch', 'Result config hash does not match.');
    return { ok: true, operation: result.operation, generation: result.generation, configSha256, rebooting: true };
  } catch (error) {
    if (error instanceof Ret1ProtocolError) throw error;
    fail('invalid_result', 'Result plaintext is invalid.');
  } finally {
    clearMutableBytes(plaintext);
  }
}
