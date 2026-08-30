const UTF8_FATAL = new TextDecoder('utf-8', { fatal: true });
const SHA256_PATTERN = /^[0-9a-f]{64}$/;
const GIT_SHA_PATTERN = /^[0-9a-f]{40}$/;
const IDENTIFIER_PATTERN = /^[A-Za-z0-9._-]{1,64}$/;
const MAX_MANIFEST_BYTES = 512 * 1024;

// Release signing keys must be reviewed and pinned in source before a browser
// can trust them. An empty production map is an intentional fail-closed state.
export const PINNED_TERMINAL_FIRMWARE_ED25519_KEYS = Object.freeze({});

const FLASH_CONSTRAINTS = Object.freeze({
  minimum_bytes: 32 * 1024 * 1024,
  mode: 'keep',
  frequency: 'keep',
  size: '32MB',
  erase_all: false,
});

const FLASH_SETS = Object.freeze({
  preserve_config: Object.freeze(['bootloader', 'partition_table', 'ota_data_initial', 'application']),
  factory_recovery: Object.freeze(['factory_recovery']),
});

const TOOLCHAIN_CONTRACT = Object.freeze({
  schema_version: 1,
  platformio_core: '6.1.19',
  platform: Object.freeze({
    name: 'pioarduino/platform-espressif32',
    revision: 'fbdfc2962e468ca3c4b51811ae691ed887df903c',
    version: '55.3.38',
    arduino_esp32: '3.3.8',
    esp_idf: '5.5.4',
    esp_idf_revision: '735507283d',
  }),
  libraries: Object.freeze({
    'Adafruit BusIO': '1.17.4',
    'Adafruit GFX Library': '1.12.6',
    ArduinoJson: '7.4.3',
    GxEPD2: '1.6.9',
  }),
  tools: Object.freeze({ esptool: '5.2.0', xtensa_esp32s3_elf: '14.2.0+20260121' }),
});

const MODELS = Object.freeze({
  E1001: Object.freeze({
    environment: 'reterminal_e1001', panel: 'GDEY075T7', resolution: [800, 480],
    partition_layout: 'ab-v1', partition_csv: 'partitions/e100x-ab-v1.csv', panel_qualified: true,
    partition_source_sha256: '931ffb5d9c703672f554b538bf546c230d9ecead380cc0ac42a9de92ee080fe6',
  }),
  E1002: Object.freeze({
    environment: 'reterminal_e1002', panel: 'GDEP073E01', resolution: [800, 480],
    partition_layout: 'ab-v1', partition_csv: 'partitions/e100x-ab-v1.csv', panel_qualified: true,
    partition_source_sha256: '931ffb5d9c703672f554b538bf546c230d9ecead380cc0ac42a9de92ee080fe6',
  }),
  E1004: Object.freeze({
    environment: 'reterminal_e1004', panel: 'GDEP133C02', resolution: [1200, 1600],
    partition_layout: 'single-slot-e1004-v1', partition_csv: 'e1004_partitions.csv', panel_qualified: false,
    partition_source_sha256: '9cf80a35887d3bfa7a595d759cec7016733fef41fdad101e9bb7c76c2c4ab6cb',
  }),
});

const FILES = Object.freeze({
  bootloader: Object.freeze({ filename: 'bootloader.bin', offset: 0x0000, nvs: true }),
  partition_table: Object.freeze({ filename: 'partitions.bin', offset: 0x8000, nvs: true }),
  ota_data_initial: Object.freeze({ filename: 'boot_app0.bin', offset: 0xe000, nvs: true }),
  application: Object.freeze({ filename: 'firmware.bin', offset: 0x10000, nvs: true }),
  factory_recovery: Object.freeze({ filename: 'firmware.factory.bin', offset: 0x0000, nvs: false }),
  partition_source: Object.freeze({ filename: 'partitions.csv', offset: null, nvs: null }),
});
const CATALOG_ARTIFACT_ROLES = Object.freeze([
  'bootloader', 'partition_table', 'ota_data_initial', 'application',
]);

class VerificationError extends Error {}

function fail(message) {
  throw new VerificationError(message);
}

function bytes(value, label) {
  if (value instanceof Uint8Array) return value;
  if (value instanceof ArrayBuffer) return new Uint8Array(value);
  if (ArrayBuffer.isView(value)) return new Uint8Array(value.buffer, value.byteOffset, value.byteLength);
  fail(`${label} is not a byte buffer.`);
}

function plainObject(value) {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function exactKeys(value, expected, label) {
  if (!plainObject(value)
    || Object.keys(value).length !== expected.length
    || expected.some(key => !Object.hasOwn(value, key))
    || Object.keys(value).some(key => !expected.includes(key))) {
    fail(`${label} fields do not match the exact schema.`);
  }
}

function strictEqual(actual, expected) {
  if (typeof actual !== typeof expected || Array.isArray(actual) !== Array.isArray(expected)) return false;
  if (Array.isArray(expected)) {
    return actual.length === expected.length && expected.every((item, index) => strictEqual(actual[index], item));
  }
  if (plainObject(expected)) {
    return plainObject(actual)
      && Object.keys(actual).length === Object.keys(expected).length
      && Object.keys(expected).every(key => Object.hasOwn(actual, key) && strictEqual(actual[key], expected[key]));
  }
  return Object.is(actual, expected);
}

function safeString(value, maximum = 256) {
  return typeof value === 'string' && value.length > 0 && value.length <= maximum;
}

function skipWhitespace(source, cursor) {
  while (/\s/u.test(source[cursor.index] || 'x')) cursor.index += 1;
}

function scanString(source, cursor) {
  const start = cursor.index;
  if (source[cursor.index] !== '"') fail('Manifest JSON is invalid.');
  cursor.index += 1;
  while (cursor.index < source.length) {
    const unit = source.charCodeAt(cursor.index);
    if (unit === 0x22) {
      cursor.index += 1;
      try {
        return JSON.parse(source.slice(start, cursor.index));
      } catch {
        fail('Manifest JSON string is invalid.');
      }
    }
    if (unit < 0x20) fail('Manifest JSON string contains a control character.');
    if (unit === 0x5c) {
      cursor.index += 1;
      const escape = source[cursor.index];
      if ('"\\/bfnrt'.includes(escape)) {
        cursor.index += 1;
        continue;
      }
      if (escape !== 'u' || !/^[0-9A-Fa-f]{4}$/u.test(source.slice(cursor.index + 1, cursor.index + 5))) {
        fail('Manifest JSON escape is invalid.');
      }
      cursor.index += 5;
      continue;
    }
    cursor.index += 1;
  }
  fail('Manifest JSON string is unterminated.');
}

function scanValue(source, cursor) {
  skipWhitespace(source, cursor);
  const current = source[cursor.index];
  if (current === '{') {
    cursor.index += 1;
    skipWhitespace(source, cursor);
    const keys = new Set();
    if (source[cursor.index] === '}') { cursor.index += 1; return; }
    while (cursor.index < source.length) {
      skipWhitespace(source, cursor);
      const key = scanString(source, cursor);
      if (keys.has(key)) fail('Manifest JSON contains a duplicate key.');
      keys.add(key);
      skipWhitespace(source, cursor);
      if (source[cursor.index] !== ':') fail('Manifest JSON object is invalid.');
      cursor.index += 1;
      scanValue(source, cursor);
      skipWhitespace(source, cursor);
      if (source[cursor.index] === '}') { cursor.index += 1; return; }
      if (source[cursor.index] !== ',') fail('Manifest JSON object is invalid.');
      cursor.index += 1;
    }
    fail('Manifest JSON object is unterminated.');
  }
  if (current === '[') {
    cursor.index += 1;
    skipWhitespace(source, cursor);
    if (source[cursor.index] === ']') { cursor.index += 1; return; }
    while (cursor.index < source.length) {
      scanValue(source, cursor);
      skipWhitespace(source, cursor);
      if (source[cursor.index] === ']') { cursor.index += 1; return; }
      if (source[cursor.index] !== ',') fail('Manifest JSON array is invalid.');
      cursor.index += 1;
    }
    fail('Manifest JSON array is unterminated.');
  }
  if (current === '"') { scanString(source, cursor); return; }
  for (const literal of ['true', 'false', 'null']) {
    if (source.startsWith(literal, cursor.index)) { cursor.index += literal.length; return; }
  }
  const number = source.slice(cursor.index).match(/^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?/u);
  if (!number) fail('Manifest JSON value is invalid.');
  cursor.index += number[0].length;
}

function parseStrictManifest(raw) {
  let source;
  try {
    source = UTF8_FATAL.decode(raw);
  } catch {
    fail('Manifest is not valid UTF-8.');
  }
  const cursor = { index: 0 };
  scanValue(source, cursor);
  skipWhitespace(source, cursor);
  if (cursor.index !== source.length) fail('Manifest JSON has trailing data.');
  let parsed;
  try {
    parsed = JSON.parse(source);
  } catch {
    fail('Manifest JSON is invalid.');
  }
  if (!plainObject(parsed)) fail('Manifest root is not an object.');
  return parsed;
}

function hexToBytes(value) {
  if (typeof value !== 'string' || !/^[0-9a-f]{64}$/u.test(value)) {
    fail('The source-pinned firmware signing key is invalid.');
  }
  return Uint8Array.from({ length: 32 }, (_, index) => Number.parseInt(value.slice(index * 2, index * 2 + 2), 16));
}

function bytesToHex(value) {
  return [...value].map(item => item.toString(16).padStart(2, '0')).join('');
}

function validateSerialEnrollment(security, release) {
  const base = ['signed', 'ota_eligible', 'reason'];
  const keys = release.manifest_schema_version === 2 ? [...base, 'serial_enrollment'] : base;
  exactKeys(security, keys, 'Manifest security state');
  if (security.signed !== true || security.ota_eligible !== false || !safeString(security.reason, 512)) {
    fail('Manifest security state exceeds the approved browser preflight capability.');
  }
  if (release.manifest_schema_version === 2
    && !strictEqual(security.serial_enrollment, release.serial_enrollment)) {
    fail('Manifest RET1 evidence does not match the authenticated catalog.');
  }
}

function validateFile(item, contract, environment, catalogArtifact) {
  const partitionSource = item?.role === 'partition_source';
  exactKeys(item, partitionSource
    ? ['path', 'role', 'flash_offset', 'size', 'sha256']
    : ['path', 'role', 'flash_offset', 'size', 'sha256', 'preserves_nvs', 'preserves_littlefs'],
  `Manifest ${environment} artifact`);
  if (item.path !== `${environment}/${contract.filename}`
    || item.flash_offset !== contract.offset
    || !Number.isSafeInteger(item.size)
    || item.size <= 0
    || item.size > 8 * 1024 * 1024
    || !SHA256_PATTERN.test(item.sha256)) {
    fail(`Manifest ${environment}/${item.role} metadata is invalid.`);
  }
  if (!partitionSource
    && (item.preserves_nvs !== contract.nvs || item.preserves_littlefs !== true)) {
    fail(`Manifest ${environment}/${item.role} preservation claim is invalid.`);
  }
  if (catalogArtifact && (item.size !== catalogArtifact.size
    || item.sha256 !== catalogArtifact.sha256
    || item.flash_offset !== catalogArtifact.flash_offset
    || item.preserves_nvs !== catalogArtifact.preserves_nvs
    || item.preserves_littlefs !== catalogArtifact.preserves_littlefs)) {
    fail(`Manifest ${environment}/${item.role} does not match the authenticated catalog.`);
  }
}

function validateModel(model, release) {
  exactKeys(model, [
    'environment', 'model', 'panel', 'resolution', 'partition_layout', 'partition_csv',
    'panel_qualified', 'hardware_revisions', 'browser_flash_qualified', 'ota_eligible',
    'flash_sets', 'files',
  ], 'Manifest model');
  const contract = MODELS[model.model];
  const catalogModel = release.models.find(candidate => candidate.model === model.model);
  if (!contract || !catalogModel) fail('Manifest model set is unsupported.');
  for (const key of [
    'environment', 'panel', 'resolution', 'partition_layout', 'partition_csv', 'panel_qualified',
  ]) {
    const expected = contract[key];
    if (!strictEqual(model[key], expected)) fail(`Manifest ${model.model} ${key} is not pinned.`);
  }
  if (!strictEqual(model.hardware_revisions, catalogModel.hardware_revisions)
    || model.browser_flash_qualified !== catalogModel.browser_flash_qualified
    || model.ota_eligible !== false
    || !strictEqual(model.flash_sets, FLASH_SETS)) {
    fail(`Manifest ${model.model} qualification state does not match the authenticated catalog.`);
  }
  if (!Array.isArray(model.files) || model.files.length !== Object.keys(FILES).length) {
    fail(`Manifest ${model.model} file set is incomplete.`);
  }
  const byRole = new Map();
  for (const item of model.files) {
    if (!plainObject(item) || !Object.hasOwn(FILES, item.role) || byRole.has(item.role)) {
      fail(`Manifest ${model.model} file roles are invalid.`);
    }
    byRole.set(item.role, item);
  }
  if (!Array.isArray(catalogModel.artifacts)
    || catalogModel.artifacts.length !== CATALOG_ARTIFACT_ROLES.length
    || new Set(catalogModel.artifacts.map(item => item?.role)).size !== CATALOG_ARTIFACT_ROLES.length
    || CATALOG_ARTIFACT_ROLES.some(role => !catalogModel.artifacts.some(item => item?.role === role))) {
    fail(`Authenticated catalog artifacts for ${model.model} are incomplete.`);
  }
  for (const [role, fileContract] of Object.entries(FILES)) {
    const catalogArtifact = catalogModel.artifacts.find(item => item.role === role);
    validateFile(byRole.get(role), fileContract, contract.environment, catalogArtifact);
  }
  if (byRole.get('partition_source').sha256 !== contract.partition_source_sha256) {
    fail(`Manifest ${model.model} partition source does not match the pinned ${contract.partition_layout} definition.`);
  }
}

function validateManifest(manifest, release) {
  exactKeys(manifest, [
    'schema_version', 'firmware_version', 'git_sha', 'source_date_epoch', 'chip', 'flash',
    'toolchain', 'toolchain_evidence', 'security', 'models',
  ], 'Manifest root');
  if (manifest.schema_version !== release.manifest_schema_version
    || ![1, 2].includes(manifest.schema_version)
    || manifest.firmware_version !== release.firmware_version
    || manifest.git_sha !== release.git_sha
    || manifest.source_date_epoch !== release.source_date_epoch
    || !safeString(manifest.firmware_version, 128)
    || !GIT_SHA_PATTERN.test(manifest.git_sha)
    || !Number.isSafeInteger(manifest.source_date_epoch)
    || manifest.source_date_epoch <= 0) {
    fail('Manifest identity does not match the authenticated catalog.');
  }
  if (manifest.chip !== 'ESP32-S3' || !strictEqual(manifest.flash, FLASH_CONSTRAINTS)) {
    fail('Manifest chip or flash constraints are unsupported.');
  }
  exactKeys(manifest.toolchain_evidence, ['path', 'size', 'sha256'], 'Manifest toolchain evidence');
  if (manifest.toolchain_evidence.path !== 'toolchain-evidence.txt'
    || !Number.isSafeInteger(manifest.toolchain_evidence.size)
    || manifest.toolchain_evidence.size <= 0
    || !SHA256_PATTERN.test(manifest.toolchain_evidence.sha256)
    || !strictEqual(manifest.toolchain, TOOLCHAIN_CONTRACT)) {
    fail('Manifest toolchain evidence is invalid.');
  }
  validateSerialEnrollment(manifest.security, release);
  if (!Array.isArray(manifest.models) || manifest.models.length !== 3
    || new Set(manifest.models.map(model => model?.model)).size !== 3) {
    fail('Manifest must contain the three pinned terminal models exactly once.');
  }
  manifest.models.forEach(model => validateModel(model, release));
}

/**
 * Verify a detached Ed25519 signature over the exact manifest response bytes,
 * then compare the strict manifest with authenticated catalog metadata.
 * This function has no serial, download, persistence, or device-write effects.
 */
export async function verifyTerminalFirmwareRelease({
  release,
  manifestBytes,
  signatureBytes,
  trustedKeys = PINNED_TERMINAL_FIRMWARE_ED25519_KEYS,
  runtime = globalThis.crypto,
}) {
  try {
    if (!plainObject(release) || !SHA256_PATTERN.test(release.release_id)
      || !IDENTIFIER_PATTERN.test(release.signing_key_id)) {
      fail('Authenticated release metadata is invalid.');
    }
    const manifestRaw = bytes(manifestBytes, 'Manifest');
    const signatureRaw = bytes(signatureBytes, 'Manifest signature');
    if (manifestRaw.length === 0 || manifestRaw.length > MAX_MANIFEST_BYTES) {
      fail('Manifest byte length is outside the approved bound.');
    }
    if (signatureRaw.length !== 64) fail('Manifest signature is not 64 bytes.');
    if (!runtime?.subtle) fail('Web Crypto is unavailable in this browser.');
    const pinnedKey = Object.hasOwn(trustedKeys || {}, release.signing_key_id)
      ? trustedKeys[release.signing_key_id]
      : undefined;
    if (pinnedKey === undefined) fail('Release signing key is not pinned in this application build.');
    const publicKeyBytes = hexToBytes(pinnedKey);

    let digest;
    let publicKey;
    let signatureValid;
    try {
      digest = new Uint8Array(await runtime.subtle.digest('SHA-256', manifestRaw));
      publicKey = await runtime.subtle.importKey('raw', publicKeyBytes, { name: 'Ed25519' }, false, ['verify']);
      signatureValid = await runtime.subtle.verify({ name: 'Ed25519' }, publicKey, signatureRaw, manifestRaw);
    } catch {
      fail('Required Ed25519 Web Crypto verification is unavailable.');
    }
    if (bytesToHex(digest) !== release.release_id) {
      fail('Exact manifest bytes do not match the content-addressed release ID.');
    }
    if (signatureValid !== true) fail('Detached manifest signature is invalid.');
    const manifest = parseStrictManifest(manifestRaw);
    validateManifest(manifest, release);
    return { valid: true, errors: [], manifest };
  } catch (error) {
    const message = error instanceof VerificationError
      ? error.message
      : 'Firmware manifest verification failed closed.';
    return { valid: false, errors: [message], manifest: null };
  }
}
