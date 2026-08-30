const SHA256_PATTERN = /^[0-9a-f]{64}$/;
const GIT_SHA_PATTERN = /^[0-9a-f]{40}$/;
const IDENTIFIER_PATTERN = /^[A-Za-z0-9._-]{1,64}$/;
const MAX_FLASH_BYTES = 32 * 1024 * 1024;

export const PRESERVE_CONFIG_ROLES = Object.freeze([
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

const MODEL_CONTRACTS = Object.freeze({
  E1001: Object.freeze({
    environment: 'reterminal_e1001',
    panel: 'GDEY075T7',
    resolution: Object.freeze([800, 480]),
    partitionLayout: 'ab-v1',
    protectedRanges: Object.freeze({
      nvs: Object.freeze({ offset: 0x9000, size: 0x5000 }),
      littlefs: Object.freeze({ offset: 0x310000, size: 0xe0000 }),
    }),
    browserCapable: true,
  }),
  E1002: Object.freeze({
    environment: 'reterminal_e1002',
    panel: 'GDEP073E01',
    resolution: Object.freeze([800, 480]),
    partitionLayout: 'ab-v1',
    protectedRanges: Object.freeze({
      nvs: Object.freeze({ offset: 0x9000, size: 0x5000 }),
      littlefs: Object.freeze({ offset: 0x310000, size: 0xe0000 }),
    }),
    browserCapable: true,
  }),
  E1004: Object.freeze({
    environment: 'reterminal_e1004',
    panel: 'GDEP133C02',
    resolution: Object.freeze([1200, 1600]),
    partitionLayout: 'single-slot-e1004-v1',
    protectedRanges: Object.freeze({
      nvs: Object.freeze({ offset: 0x9000, size: 0x5000 }),
      littlefs: Object.freeze({ offset: 0x310000, size: 0x400000 }),
    }),
    browserCapable: false,
  }),
});

function isPlainObject(value) {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function hasExactKeys(value, required, optional = []) {
  if (!isPlainObject(value)) return false;
  const allowed = new Set([...required, ...optional]);
  const keys = Object.keys(value);
  return required.every(key => Object.hasOwn(value, key))
    && keys.every(key => allowed.has(key));
}

function isSafeString(value, maxLength = 256) {
  return typeof value === 'string' && value.length > 0 && value.length <= maxLength;
}

function isUniqueSafeStringArray(value, pattern = null) {
  return Array.isArray(value)
    && new Set(value).size === value.length
    && value.every(item => isSafeString(item, 256) && (!pattern || pattern.test(item)));
}

function isPositiveInteger(value) {
  return Number.isSafeInteger(value) && value > 0;
}

function releaseLabel(release) {
  return typeof release?.release_id === 'string' ? release.release_id.slice(0, 8) : 'unknown';
}

function rangesOverlap(left, right) {
  return left.offset < right.offset + right.size
    && left.offset + left.size > right.offset;
}

function validateProtectedRanges(model, contract, errors, prefix) {
  const ranges = model.protected_ranges;
  if (!Array.isArray(ranges) || ranges.length !== 2) {
    errors.push(`${prefix} must declare exactly the NVS and LittleFS protected ranges.`);
    return [];
  }

  const byName = new Map();
  ranges.forEach((range, index) => {
    if (!hasExactKeys(range, ['name', 'offset', 'size'])) {
      errors.push(`${prefix} protected range ${index + 1} has an invalid schema.`);
      return;
    }
    if (!['nvs', 'littlefs'].includes(range.name) || byName.has(range.name)) {
      errors.push(`${prefix} protected range names must be unique NVS and LittleFS entries.`);
      return;
    }
    if (!Number.isSafeInteger(range.offset) || range.offset < 0 || !isPositiveInteger(range.size)) {
      errors.push(`${prefix} protected range ${range.name} has an invalid offset or size.`);
      return;
    }
    if (range.offset + range.size > MAX_FLASH_BYTES) {
      errors.push(`${prefix} protected range ${range.name} exceeds the 32 MB flash boundary.`);
      return;
    }
    byName.set(range.name, range);
  });

  if (!byName.has('nvs') || !byName.has('littlefs')) {
    errors.push(`${prefix} must protect both NVS and LittleFS.`);
  }
  for (const [name, expected] of Object.entries(contract.protectedRanges)) {
    const actual = byName.get(name);
    if (actual && (actual.offset !== expected.offset || actual.size !== expected.size)) {
      errors.push(`${prefix} ${name} bounds do not match the pinned partition layout.`);
    }
  }
  const validRanges = [...byName.values()];
  if (validRanges.length === 2 && rangesOverlap(validRanges[0], validRanges[1])) {
    errors.push(`${prefix} protected ranges overlap.`);
  }
  return validRanges;
}

function validateArtifacts(release, model, protectedRanges, errors, prefix) {
  if (!Array.isArray(model.flash_set)
    || model.flash_set.length !== PRESERVE_CONFIG_ROLES.length
    || !PRESERVE_CONFIG_ROLES.every((role, index) => model.flash_set[index] === role)) {
    errors.push(`${prefix} flash set is not the canonical preserve-config set.`);
  }

  if (!Array.isArray(model.artifacts) || model.artifacts.length !== PRESERVE_CONFIG_ROLES.length) {
    errors.push(`${prefix} must declare exactly four preserve-config artifacts.`);
    return;
  }

  const seenRoles = new Set();
  const artifactRanges = [];
  for (const artifact of model.artifacts) {
    if (!hasExactKeys(
      artifact,
      ['role', 'size', 'sha256', 'flash_offset', 'preserves_nvs', 'preserves_littlefs'],
      ['download_url'],
    )) {
      errors.push(`${prefix} contains an artifact with an invalid schema.`);
      continue;
    }
    if (!PRESERVE_CONFIG_ROLES.includes(artifact.role) || seenRoles.has(artifact.role)) {
      errors.push(`${prefix} artifact roles must be unique members of the preserve-config set.`);
      continue;
    }
    seenRoles.add(artifact.role);
    const validFlashRange = isPositiveInteger(artifact.size)
      && artifact.flash_offset === ROLE_OFFSETS[artifact.role]
      && artifact.flash_offset + artifact.size <= MAX_FLASH_BYTES;
    if (!validFlashRange) {
      errors.push(`${prefix} ${artifact.role} has an invalid flash range.`);
    }
    if (!SHA256_PATTERN.test(artifact.sha256)) {
      errors.push(`${prefix} ${artifact.role} has an invalid SHA-256 digest.`);
    }
    if (artifact.preserves_nvs !== true || artifact.preserves_littlefs !== true) {
      errors.push(`${prefix} ${artifact.role} does not preserve both configuration stores.`);
    }
    if (Object.hasOwn(artifact, 'download_url')) {
      const expected = `/api/terminal/firmware/releases/${release.release_id}/models/${model.model}/artifacts/${artifact.role}`;
      if (!model.install_eligible || artifact.download_url !== expected) {
        errors.push(`${prefix} ${artifact.role} has an unexpected download URL.`);
      }
    } else if (model.install_eligible) {
      errors.push(`${prefix} ${artifact.role} is missing its qualified download URL.`);
    }
    if (validFlashRange) {
      artifactRanges.push({ offset: artifact.flash_offset, size: artifact.size });
    }
  }

  if (seenRoles.size !== PRESERVE_CONFIG_ROLES.length) {
    errors.push(`${prefix} artifact set is incomplete.`);
  }
  for (const artifactRange of artifactRanges) {
    if (protectedRanges.some(range => rangesOverlap(artifactRange, range))) {
      errors.push(`${prefix} artifact flash ranges overlap protected configuration storage.`);
      break;
    }
  }
  for (let left = 0; left < artifactRanges.length; left += 1) {
    for (let right = left + 1; right < artifactRanges.length; right += 1) {
      if (rangesOverlap(artifactRanges[left], artifactRanges[right])) {
        errors.push(`${prefix} artifact flash ranges overlap each other.`);
        return;
      }
    }
  }
}

function validateSerialEnrollment(release, errors) {
  const prefix = `Release ${releaseLabel(release)} serial enrollment`;
  const enrollment = release.serial_enrollment;
  if (!hasExactKeys(enrollment, [
    'protocol',
    'enabled',
    'trust_key_id',
    'public_key_sha256',
    'identity_strength',
    'attestation',
  ])) {
    errors.push(`${prefix} has an invalid schema.`);
    return;
  }
  if (![1, 2].includes(release.manifest_schema_version)
    || enrollment.protocol !== 'RET1'
    || typeof enrollment.enabled !== 'boolean'
    || enrollment.identity_strength !== 'physical_cable_only'
    || enrollment.attestation !== false) {
    errors.push(`${prefix} has an invalid trust state.`);
    return;
  }
  if (release.manifest_schema_version === 1 && enrollment.enabled) {
    errors.push(`${prefix} cannot enable RET1 from a legacy manifest.`);
  }
  if (enrollment.enabled) {
    if (!IDENTIFIER_PATTERN.test(enrollment.trust_key_id)
      || !SHA256_PATTERN.test(enrollment.public_key_sha256)) {
      errors.push(`${prefix} has invalid trust-key evidence.`);
    }
  } else if (enrollment.trust_key_id !== null || enrollment.public_key_sha256 !== null) {
    errors.push(`${prefix} is disabled but still declares trust material.`);
  }
}

function validateModel(release, model, trustedKeyIds, errors) {
  const prefix = `Release ${releaseLabel(release)} model ${model?.model || 'unknown'}`;
  if (!hasExactKeys(model, [
    'model',
    'environment',
    'panel',
    'resolution',
    'partition_layout',
    'hardware_revisions',
    'browser_flash_qualified',
    'install_eligible',
    'blockers',
    'protected_ranges',
    'flash_set',
    'artifacts',
  ])) {
    errors.push(`${prefix} has an invalid schema.`);
    return;
  }
  const contract = MODEL_CONTRACTS[model.model];
  if (!contract) {
    errors.push(`${prefix} is not a supported catalog model.`);
    return;
  }
  if (model.environment !== contract.environment
    || model.panel !== contract.panel
    || model.partition_layout !== contract.partitionLayout
    || !Array.isArray(model.resolution)
    || model.resolution.length !== 2
    || model.resolution.some((value, index) => value !== contract.resolution[index])) {
    errors.push(`${prefix} identity or panel metadata does not match the pinned model contract.`);
  }
  const revisionsValid = isUniqueSafeStringArray(model.hardware_revisions, IDENTIFIER_PATTERN);
  const blockersValid = isUniqueSafeStringArray(model.blockers);
  if (!revisionsValid) {
    errors.push(`${prefix} hardware revision allowlist is invalid.`);
  }
  if (typeof model.browser_flash_qualified !== 'boolean'
    || typeof model.install_eligible !== 'boolean'
    || !blockersValid) {
    errors.push(`${prefix} qualification state is invalid.`);
  }
  if (!contract.browserCapable && (model.browser_flash_qualified || model.install_eligible)) {
    errors.push(`${prefix} cannot be qualified for browser flashing.`);
  }
  if (model.browser_flash_qualified && (!revisionsValid || model.hardware_revisions.length === 0)) {
    errors.push(`${prefix} is qualified without an approved hardware revision.`);
  }
  if (model.install_eligible && (!model.browser_flash_qualified || !trustedKeyIds.has(release.signing_key_id))) {
    errors.push(`${prefix} is install-eligible without qualification and a trusted signing key.`);
  }
  if (model.install_eligible && (!blockersValid || model.blockers.length > 0)) {
    errors.push(`${prefix} is install-eligible despite reported blockers.`);
  }
  const protectedRanges = validateProtectedRanges(model, contract, errors, prefix);
  validateArtifacts(release, model, protectedRanges, errors, prefix);
}

function validateRelease(release, trustedKeyIds, errors) {
  if (!hasExactKeys(release, [
    'release_id',
    'firmware_version',
    'git_sha',
    'source_date_epoch',
    'manifest_schema_version',
    'signing_key_id',
    'serial_enrollment',
    'manifest_url',
    'signature_url',
    'models',
  ])) {
    errors.push('Firmware release has an invalid schema.');
    return;
  }
  if (!SHA256_PATTERN.test(release.release_id)
    || !GIT_SHA_PATTERN.test(release.git_sha)
    || !isSafeString(release.firmware_version, 128)
    || !isPositiveInteger(release.source_date_epoch)
    || !IDENTIFIER_PATTERN.test(release.signing_key_id)) {
    errors.push('Firmware release identity or provenance is invalid.');
  }
  if (!trustedKeyIds.has(release.signing_key_id)) {
    errors.push(`Release ${releaseLabel(release)} uses an untrusted signing key.`);
  }
  validateSerialEnrollment(release, errors);
  const expectedManifest = `/api/terminal/firmware/releases/${release.release_id}/manifest.json`;
  const expectedSignature = `/api/terminal/firmware/releases/${release.release_id}/manifest.sig`;
  if (release.manifest_url !== expectedManifest || release.signature_url !== expectedSignature) {
    errors.push(`Release ${releaseLabel(release)} metadata URLs are not canonical.`);
  }
  if (!Array.isArray(release.models) || release.models.length !== 3) {
    errors.push(`Release ${releaseLabel(release)} does not declare exactly three models.`);
    return;
  }
  const modelNames = release.models.map(model => model?.model);
  if (new Set(modelNames).size !== 3 || !Object.keys(MODEL_CONTRACTS).every(name => modelNames.includes(name))) {
    errors.push(`Release ${releaseLabel(release)} model set is incomplete or duplicated.`);
  }
  release.models.forEach(model => validateModel(release, model, trustedKeyIds, errors));
}

/**
 * Strictly audit the server catalog before presenting any release metadata.
 * This validates metadata only; it does not make a release browser-installable.
 */
export function validateTerminalFirmwareCatalog(catalog) {
  const errors = [];
  if (!hasExactKeys(catalog, [
    'schema_version',
    'installer_state',
    'browser_flash_enabled',
    'trusted_key_ids',
    'blockers',
    'releases',
  ])) {
    return { valid: false, errors: ['Firmware catalog schema is invalid.'], catalog: null };
  }
  if (catalog.schema_version !== 2
    || !['locked', 'ready'].includes(catalog.installer_state)
    || typeof catalog.browser_flash_enabled !== 'boolean'
    || !isUniqueSafeStringArray(catalog.trusted_key_ids, IDENTIFIER_PATTERN)
    || !isUniqueSafeStringArray(catalog.blockers)) {
    errors.push('Firmware catalog state is invalid.');
  }
  if (!Array.isArray(catalog.releases) || catalog.releases.length > 1) {
    errors.push('Firmware catalog release list is invalid.');
  } else {
    const releaseIds = catalog.releases.map(release => release?.release_id);
    if (new Set(releaseIds).size !== releaseIds.length) {
      errors.push('Firmware catalog contains duplicate releases.');
    }
    const trustedKeyIds = new Set(Array.isArray(catalog.trusted_key_ids) ? catalog.trusted_key_ids : []);
    catalog.releases.forEach(release => validateRelease(release, trustedKeyIds, errors));
    const hasEligibleModel = catalog.releases.some(release =>
      Array.isArray(release?.models) && release.models.some(model => model?.install_eligible === true));
    if ((catalog.installer_state === 'ready') !== hasEligibleModel
      || (hasEligibleModel && !catalog.browser_flash_enabled)) {
      errors.push('Firmware catalog readiness is internally inconsistent.');
    }
    if (catalog.installer_state === 'locked'
      && (!Array.isArray(catalog.blockers) || catalog.blockers.length === 0)) {
      errors.push('Locked firmware catalog does not explain its blockers.');
    }
  }
  return { valid: errors.length === 0, errors, catalog: errors.length === 0 ? catalog : null };
}
