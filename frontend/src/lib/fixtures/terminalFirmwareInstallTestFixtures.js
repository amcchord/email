import { compileTerminalFirmwareInstallPlan } from '../terminalFirmwareInstallPlan.js';

const encoder = new TextEncoder();
const ROLES = ['bootloader', 'partition_table', 'ota_data_initial', 'application'];
const OFFSETS = [0x0000, 0x8000, 0xe000, 0x10000];

function hex(value) {
  return [...value].map(item => item.toString(16).padStart(2, '0')).join('');
}

export async function createTerminalFirmwareInstallFixture({
  model = 'E1002',
  hardwareRevision = 'V1.0',
} = {}) {
  const releaseId = 'a'.repeat(64);
  const gitSha = 'b'.repeat(40);
  const firmwareVersion = '0.5.0-candidate.5';
  const artifactBytes = new Map();
  const artifacts = [];
  const files = [];
  for (let index = 0; index < ROLES.length; index += 1) {
    const role = ROLES[index];
    const value = encoder.encode(`${role}-fixture-${index}`);
    const sha256 = hex(new Uint8Array(await crypto.subtle.digest('SHA-256', value)));
    artifactBytes.set(role, value);
    artifacts.push({
      role,
      size: value.length,
      sha256,
      flash_offset: OFFSETS[index],
      preserves_nvs: true,
      preserves_littlefs: true,
      download_url: `/api/terminal/firmware/releases/${releaseId}/models/${model}/artifacts/${role}`,
    });
    files.push({
      path: `reterminal_${model.toLowerCase()}/${role}.bin`,
      role,
      flash_offset: OFFSETS[index],
      size: value.length,
      sha256,
      preserves_nvs: true,
      preserves_littlefs: true,
    });
  }
  const catalogModel = {
    model,
    partition_layout: 'ab-v1',
    hardware_revisions: [hardwareRevision],
    browser_flash_qualified: true,
    install_eligible: true,
    blockers: [],
    flash_set: [...ROLES],
    artifacts,
  };
  const manifestModel = {
    model,
    partition_layout: 'ab-v1',
    hardware_revisions: [hardwareRevision],
    browser_flash_qualified: true,
    flash_sets: {
      preserve_config: [...ROLES],
      factory_recovery: ['factory_recovery'],
    },
    files,
  };
  const release = {
    release_id: releaseId,
    manifest_schema_version: 2,
    firmware_version: firmwareVersion,
    git_sha: gitSha,
    models: [catalogModel],
  };
  const manifest = {
    schema_version: 2,
    firmware_version: firmwareVersion,
    git_sha: gitSha,
    chip: 'ESP32-S3',
    flash: {
      minimum_bytes: 32 * 1024 * 1024,
      mode: 'keep',
      frequency: 'keep',
      size: '32MB',
      erase_all: false,
    },
    models: [manifestModel],
  };
  const verification = { valid: true, errors: [], manifest };
  const plan = compileTerminalFirmwareInstallPlan({
    release,
    verification,
    model,
    hardwareRevision,
  });
  return {
    release,
    manifest,
    verification,
    plan,
    artifactBytes,
    factoryMac: 'aa:bb:cc:dd:ee:ff',
    status: {
      v: 2,
      type: 'status',
      state: 'config_ready',
      model,
      firmware_version: firmwareVersion,
      factory_mac: 'aa:bb:cc:dd:ee:ff',
      config_source: 'nvs',
      config_generation: 7,
      enrollment_available: false,
      enrollment_key_id: '',
      identity_strength: 'physical_cable_only',
      attestation: false,
      partition_layout: 'ab-v1',
      running_partition: 'ota_0',
      boot_state: 'stable',
      partition_identity_valid: true,
      firmware_build_id: gitSha,
    },
  };
}

export function fixtureArtifactResponse(value, overrides = {}) {
  const body = overrides.body || value;
  const contentLength = overrides.contentLength === undefined ? value.length : overrides.contentLength;
  const contentType = overrides.contentType === undefined ? 'application/octet-stream' : overrides.contentType;
  return {
    ok: overrides.ok ?? true,
    redirected: overrides.redirected ?? false,
    headers: {
      get(name) {
        if (name.toLowerCase() === 'content-length') return contentLength === null ? null : String(contentLength);
        if (name.toLowerCase() === 'content-type') return contentType;
        return null;
      },
    },
    async arrayBuffer() {
      return body.buffer.slice(body.byteOffset, body.byteOffset + body.byteLength);
    },
  };
}

export function createFixtureFetch(fixture, calls = [], responseForRole = {}) {
  return async (url, options) => {
    const role = url.split('/').at(-1);
    calls.push({ url, options });
    const configured = responseForRole[role];
    if (configured instanceof Error) throw configured;
    if (configured) return configured;
    return fixtureArtifactResponse(fixture.artifactBytes.get(role));
  };
}

export function statusFrame(status, lineEnding = '\n') {
  return encoder.encode(`@RET1 ${JSON.stringify(status)}${lineEnding}`);
}
