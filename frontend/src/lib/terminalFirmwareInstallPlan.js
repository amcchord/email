import { captureAuthEpoch, isAuthEpochCurrent } from './authSession.js';

const SHA256_PATTERN = /^[0-9a-f]{64}$/;
const GIT_SHA_PATTERN = /^[0-9a-f]{40}$/;
const HARDWARE_REVISION_PATTERN = /^[A-Za-z0-9._-]{1,64}$/;
const FACTORY_MAC_PATTERN = /^[0-9a-f]{2}(?::[0-9a-f]{2}){5}$/;
const REQUIRED_FLASH_BYTES = 32 * 1024 * 1024;
const MAX_ARTIFACT_BYTES = 8 * 1024 * 1024;

export const TERMINAL_FIRMWARE_INSTALL_ROLES = Object.freeze([
  'bootloader',
  'partition_table',
  'ota_data_initial',
  'application',
]);

const ROLE_OFFSETS = Object.freeze({
  bootloader: 0x0000,
  partition_table: 0x8000,
  ota_data_initial: 0xe000,
  application: 0x10000,
});

export class TerminalFirmwareInstallError extends Error {
  constructor(code, message = code) {
    super(message);
    this.name = 'TerminalFirmwareInstallError';
    this.code = code;
  }
}

function fail(code, message) {
  throw new TerminalFirmwareInstallError(code, message);
}

function plainObject(value) {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function bytes(value, code = 'artifact_invalid') {
  if (value instanceof Uint8Array) return value;
  if (value instanceof ArrayBuffer) return new Uint8Array(value);
  if (ArrayBuffer.isView(value)) {
    return new Uint8Array(value.buffer, value.byteOffset, value.byteLength);
  }
  fail(code, 'Firmware artifact is not a byte buffer.');
}

function bytesToHex(value) {
  return [...value].map(item => item.toString(16).padStart(2, '0')).join('');
}

function freezeSegment(segment) {
  return Object.freeze({ ...segment });
}

function matchingModel(models, model, label) {
  if (!Array.isArray(models)) fail('plan_invalid', `${label} model set is unavailable.`);
  const matches = models.filter(candidate => candidate?.model === model);
  if (matches.length !== 1) fail('plan_invalid', `${label} model selection is ambiguous.`);
  return matches[0];
}

function artifactMap(artifacts, label) {
  if (!Array.isArray(artifacts) || artifacts.length !== TERMINAL_FIRMWARE_INSTALL_ROLES.length) {
    fail('plan_invalid', `${label} preserve-config artifact set is incomplete.`);
  }
  const result = new Map();
  for (const artifact of artifacts) {
    if (!plainObject(artifact)
      || !TERMINAL_FIRMWARE_INSTALL_ROLES.includes(artifact.role)
      || result.has(artifact.role)) {
      fail('plan_invalid', `${label} preserve-config artifact roles are invalid.`);
    }
    result.set(artifact.role, artifact);
  }
  if (TERMINAL_FIRMWARE_INSTALL_ROLES.some(role => !result.has(role))) {
    fail('plan_invalid', `${label} preserve-config artifact set is incomplete.`);
  }
  return result;
}

/**
 * Compile the exact, non-destructive browser install plan from a release that
 * already passed both catalog validation and verifyTerminalFirmwareRelease.
 * This module has no browser or device transport dependency.
 */
export function compileTerminalFirmwareInstallPlan({
  release,
  verification,
  model,
  hardwareRevision,
}) {
  if (!plainObject(release)
    || !plainObject(verification)
    || verification.valid !== true
    || !plainObject(verification.manifest)
    || !Array.isArray(verification.errors)
    || verification.errors.length !== 0) {
    fail('release_unverified', 'Firmware release did not pass exact signature and manifest verification.');
  }
  if (!['E1001', 'E1002'].includes(model)) {
    fail('unsupported_model', 'Only HIL-qualified E1001 or E1002 plans may be compiled.');
  }
  if (typeof hardwareRevision !== 'string'
    || !HARDWARE_REVISION_PATTERN.test(hardwareRevision)) {
    fail('model_unconfirmed', 'An exact physical hardware revision confirmation is required.');
  }
  const manifest = verification.manifest;
  if (!SHA256_PATTERN.test(release.release_id)
    || !GIT_SHA_PATTERN.test(release.git_sha)
    || release.manifest_schema_version !== 2
    || manifest.schema_version !== 2
    || manifest.git_sha !== release.git_sha
    || manifest.firmware_version !== release.firmware_version
    || manifest.chip !== 'ESP32-S3'
    || manifest.flash?.minimum_bytes !== REQUIRED_FLASH_BYTES
    || manifest.flash?.size !== '32MB'
    || manifest.flash?.erase_all !== false) {
    fail('plan_invalid', 'Verified firmware identity or flash constraints are not browser-installable.');
  }

  const catalogModel = matchingModel(release.models, model, 'Catalog');
  const manifestModel = matchingModel(manifest.models, model, 'Manifest');
  if (catalogModel.browser_flash_qualified !== true
    || catalogModel.install_eligible !== true
    || !Array.isArray(catalogModel.blockers)
    || catalogModel.blockers.length !== 0
    || catalogModel.partition_layout !== 'ab-v1'
    || manifestModel.partition_layout !== 'ab-v1'
    || manifestModel.browser_flash_qualified !== true
    || !Array.isArray(catalogModel.hardware_revisions)
    || !Array.isArray(manifestModel.hardware_revisions)
    || !catalogModel.hardware_revisions.includes(hardwareRevision)
    || !manifestModel.hardware_revisions.includes(hardwareRevision)) {
    fail('hardware_revision_unqualified', 'The selected model and hardware revision are not browser-flash qualified.');
  }
  if (!Array.isArray(catalogModel.flash_set)
    || !Array.isArray(manifestModel.flash_sets?.preserve_config)
    || catalogModel.flash_set.length !== TERMINAL_FIRMWARE_INSTALL_ROLES.length
    || manifestModel.flash_sets.preserve_config.length !== TERMINAL_FIRMWARE_INSTALL_ROLES.length
    || TERMINAL_FIRMWARE_INSTALL_ROLES.some((role, index) => (
      catalogModel.flash_set[index] !== role
      || manifestModel.flash_sets.preserve_config[index] !== role
    ))) {
    fail('plan_invalid', 'The release does not use the exact preserve-config flash set.');
  }

  const catalogArtifacts = artifactMap(catalogModel.artifacts, 'Catalog');
  const manifestArtifacts = artifactMap(
    manifestModel.files.filter(file => TERMINAL_FIRMWARE_INSTALL_ROLES.includes(file?.role)),
    'Manifest',
  );
  const segments = TERMINAL_FIRMWARE_INSTALL_ROLES.map(role => {
    const artifact = catalogArtifacts.get(role);
    const manifestArtifact = manifestArtifacts.get(role);
    const expectedUrl = `/api/terminal/firmware/releases/${release.release_id}/models/${model}/artifacts/${role}`;
    if (!Number.isSafeInteger(artifact.size)
      || artifact.size <= 0
      || artifact.size > MAX_ARTIFACT_BYTES
      || artifact.flash_offset !== ROLE_OFFSETS[role]
      || !SHA256_PATTERN.test(artifact.sha256)
      || artifact.preserves_nvs !== true
      || artifact.preserves_littlefs !== true
      || artifact.download_url !== expectedUrl
      || manifestArtifact.size !== artifact.size
      || manifestArtifact.sha256 !== artifact.sha256
      || manifestArtifact.flash_offset !== artifact.flash_offset
      || manifestArtifact.preserves_nvs !== true
      || manifestArtifact.preserves_littlefs !== true) {
      fail('plan_invalid', `The ${role} artifact does not match the verified preserve-config contract.`);
    }
    return freezeSegment({
      role,
      offset: artifact.flash_offset,
      size: artifact.size,
      sha256: artifact.sha256,
      downloadUrl: artifact.download_url,
      preservesNvs: true,
      preservesLittlefs: true,
    });
  });

  return Object.freeze({
    schemaVersion: 1,
    releaseId: release.release_id,
    model,
    hardwareRevision,
    requiredChip: 'ESP32-S3',
    requiredFlashBytes: REQUIRED_FLASH_BYTES,
    eraseAll: false,
    expectedStatus: Object.freeze({
      version: 2,
      model,
      firmwareVersion: release.firmware_version,
      firmwareBuildId: release.git_sha,
      partitionLayout: 'ab-v1',
      runningPartition: 'ota_0',
    }),
    segments: Object.freeze(segments),
  });
}

function assertPlan(plan) {
  if (!plainObject(plan)
    || plan.schemaVersion !== 1
    || !SHA256_PATTERN.test(plan.releaseId)
    || !['E1001', 'E1002'].includes(plan.model)
    || !HARDWARE_REVISION_PATTERN.test(plan.hardwareRevision)
    || plan.requiredChip !== 'ESP32-S3'
    || plan.requiredFlashBytes !== REQUIRED_FLASH_BYTES
    || plan.eraseAll !== false
    || !plainObject(plan.expectedStatus)
    || plan.expectedStatus.version !== 2
    || plan.expectedStatus.model !== plan.model
    || typeof plan.expectedStatus.firmwareVersion !== 'string'
    || plan.expectedStatus.firmwareVersion.length === 0
    || plan.expectedStatus.firmwareVersion.length > 128
    || !GIT_SHA_PATTERN.test(plan.expectedStatus.firmwareBuildId)
    || plan.expectedStatus.partitionLayout !== 'ab-v1'
    || plan.expectedStatus.runningPartition !== 'ota_0'
    || !Array.isArray(plan.segments)
    || plan.segments.length !== TERMINAL_FIRMWARE_INSTALL_ROLES.length) {
    fail('plan_invalid', 'Firmware install plan is invalid.');
  }
  plan.segments.forEach((segment, index) => {
    const role = TERMINAL_FIRMWARE_INSTALL_ROLES[index];
    const expectedUrl = `/api/terminal/firmware/releases/${plan.releaseId}/models/${plan.model}/artifacts/${role}`;
    if (!plainObject(segment)
      || segment.role !== role
      || segment.offset !== ROLE_OFFSETS[role]
      || !Number.isSafeInteger(segment.size)
      || segment.size <= 0
      || segment.size > MAX_ARTIFACT_BYTES
      || !SHA256_PATTERN.test(segment.sha256)
      || segment.downloadUrl !== expectedUrl
      || segment.preservesNvs !== true
      || segment.preservesLittlefs !== true) {
      fail('plan_invalid', `Firmware install plan ${role} segment is invalid.`);
    }
  });
  return plan;
}

function authSessionChanged() {
  const error = new TerminalFirmwareInstallError(
    'auth_session_changed',
    'Authentication session changed while firmware artifacts were loading.',
  );
  error.name = 'AbortError';
  return error;
}

async function readArtifact(response, segment, runtime) {
  if (!response?.ok || response.redirected === true) {
    fail('artifact_unavailable', `${segment.role} firmware artifact is unavailable.`);
  }
  const contentType = response.headers?.get?.('content-type')?.split(';', 1)[0]?.trim()?.toLowerCase();
  const rawLength = response.headers?.get?.('content-length');
  const declaredLength = Number(rawLength);
  if (contentType !== 'application/octet-stream'
    || rawLength === null
    || rawLength === undefined
    || !Number.isSafeInteger(declaredLength)
    || declaredLength !== segment.size) {
    fail('artifact_invalid', `${segment.role} firmware artifact headers are invalid.`);
  }
  const raw = bytes(await response.arrayBuffer());
  if (raw.length !== segment.size) {
    fail('artifact_invalid', `${segment.role} firmware artifact byte length changed.`);
  }
  if (!runtime?.subtle) fail('crypto_unavailable', 'SHA-256 verification is unavailable.');
  let digest;
  try {
    digest = new Uint8Array(await runtime.subtle.digest('SHA-256', raw));
  } catch {
    fail('crypto_unavailable', 'SHA-256 verification is unavailable.');
  }
  if (bytesToHex(digest) !== segment.sha256) {
    fail('artifact_hash_mismatch', `${segment.role} firmware artifact failed SHA-256 verification.`);
  }
  return Object.freeze({ ...segment, bytes: raw });
}

/**
 * Fetch and hash every immutable segment before any device transport is used.
 */
export async function loadTerminalFirmwareInstallArtifacts(
  plan,
  { fetchImpl = globalThis.fetch, runtime = globalThis.crypto, signal } = {},
) {
  assertPlan(plan);
  if (typeof fetchImpl !== 'function') fail('artifact_unavailable', 'Firmware artifact fetch is unavailable.');
  if (signal?.aborted) {
    const error = new Error('Firmware artifact loading was cancelled.');
    error.name = 'AbortError';
    throw error;
  }
  const authEpoch = captureAuthEpoch();
  const loaded = [];
  for (const segment of plan.segments) {
    let response;
    try {
      response = await fetchImpl(segment.downloadUrl, {
        method: 'GET',
        credentials: 'include',
        cache: 'no-store',
        redirect: 'error',
        signal,
      });
    } catch (error) {
      if (error?.name === 'AbortError') throw error;
      fail('artifact_unavailable', `${segment.role} firmware artifact could not be loaded.`);
    }
    if (!isAuthEpochCurrent(authEpoch)) throw authSessionChanged();
    loaded.push(await readArtifact(response, segment, runtime));
    if (!isAuthEpochCurrent(authEpoch)) throw authSessionChanged();
  }
  return Object.freeze({ ...plan, segments: Object.freeze(loaded), artifactsVerified: true });
}

export function validateTerminalFirmwareRomIdentity(probe, plan) {
  assertPlan(plan);
  if (!plainObject(probe) || probe.chip !== plan.requiredChip) {
    fail('unsupported_chip', 'Connected ROM is not an ESP32-S3.');
  }
  if (!Number.isSafeInteger(probe.flashBytes) || probe.flashBytes < plan.requiredFlashBytes) {
    fail('flash_too_small', 'Connected terminal does not expose the required 32 MB flash.');
  }
  if (typeof probe.factoryMac !== 'string' || !FACTORY_MAC_PATTERN.test(probe.factoryMac)) {
    fail('rom_identity_invalid', 'Connected ROM did not provide a canonical factory MAC.');
  }
  return Object.freeze({
    chip: probe.chip,
    flashBytes: probe.flashBytes,
    factoryMac: probe.factoryMac,
  });
}
