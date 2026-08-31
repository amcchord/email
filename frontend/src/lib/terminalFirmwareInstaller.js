/** Browser installer capability detection. This never requests a port. */
export function detectTerminalFirmwareSupport(runtime = globalThis) {
  try {
    const browserWindow = runtime?.window || runtime;
    const browserNavigator = browserWindow?.navigator || runtime?.navigator;
    const secureContext = browserWindow?.isSecureContext === true;
    const webSerial = typeof browserNavigator?.serial?.requestPort === 'function';
    const webLocks = typeof browserNavigator?.locks?.request === 'function';
    const blockers = [];
    if (!secureContext) blockers.push('Open this page over HTTPS.');
    if (!webSerial) blockers.push('Use a browser with Web Serial support.');
    if (!webLocks) blockers.push('This browser cannot reserve the terminal with Web Locks.');
    return {
      secureContext,
      webSerial,
      webLocks,
      supported: blockers.length === 0,
      blockers,
    };
  } catch {
    return {
      secureContext: false,
      webSerial: false,
      webLocks: false,
      supported: false,
      blockers: ['Browser capability detection failed closed.'],
    };
  }
}

const IDENTIFIER_PATTERN = /^[A-Za-z0-9._-]{1,64}$/u;
const SHA256_PATTERN = /^[0-9a-f]{64}$/u;
const GIT_SHA_PATTERN = /^[0-9a-f]{40}$/u;

function exactQualifiedRelease(candidate) {
  if (!candidate || typeof candidate !== 'object' || Array.isArray(candidate)) return false;
  const keys = Object.keys(candidate);
  return keys.length === 4
    && ['release_id', 'firmware_version', 'git_sha', 'models'].every(key => Object.hasOwn(candidate, key))
    && SHA256_PATTERN.test(candidate.release_id || '')
    && typeof candidate.firmware_version === 'string'
    && candidate.firmware_version.length > 0
    && candidate.firmware_version.length <= 128
    && GIT_SHA_PATTERN.test(candidate.git_sha || '')
    && Array.isArray(candidate.models)
    && candidate.models.length > 0
    && candidate.models.every(model => ['E1001', 'E1002'].includes(model))
    && new Set(candidate.models).size === candidate.models.length;
}

export function terminalEnrollmentCapabilitiesReady(capabilities) {
  return capabilities?.schema_version === 1
    && capabilities.state === 'ready'
    && capabilities.enabled === true
    && capabilities.protocol === 'RET1'
    && capabilities.identity_strength === 'physical_cable_only'
    && capabilities.attestation === false
    && Array.isArray(capabilities.allowed_models)
    && capabilities.allowed_models.length > 0
    && capabilities.allowed_models.every(model => ['E1001', 'E1002'].includes(model))
    && new Set(capabilities.allowed_models).size === capabilities.allowed_models.length
    && Array.isArray(capabilities.qualified_releases)
    && capabilities.qualified_releases.length > 0
    && capabilities.qualified_releases.every(exactQualifiedRelease)
    && Array.isArray(capabilities.blockers)
    && capabilities.blockers.length === 0;
}

export function getSelectedTerminalEnrollmentQualification(capabilities, release, model) {
  if (!terminalEnrollmentCapabilitiesReady(capabilities)
    || !release
    || !['E1001', 'E1002'].includes(model)
    || release.manifest_schema_version !== 2
    || !SHA256_PATTERN.test(release.release_id || '')
    || !GIT_SHA_PATTERN.test(release.git_sha || '')
    || typeof release.firmware_version !== 'string'
    || release.firmware_version.length < 1
    || release.firmware_version.length > 128
    || release.serial_enrollment?.protocol !== 'RET1'
    || release.serial_enrollment?.enabled !== true
    || !IDENTIFIER_PATTERN.test(release.serial_enrollment?.trust_key_id || '')
    || !SHA256_PATTERN.test(release.serial_enrollment?.public_key_sha256 || '')
    || release.serial_enrollment?.identity_strength !== 'physical_cable_only'
    || release.serial_enrollment?.attestation !== false) {
    return null;
  }
  const matches = capabilities.qualified_releases.filter(candidate => (
    candidate?.release_id === release.release_id
    && candidate?.firmware_version === release.firmware_version
    && candidate?.git_sha === release.git_sha
    && Array.isArray(candidate.models)
    && candidate.models.includes(model)
  ));
  if (matches.length !== 1 || !capabilities.allowed_models.includes(model)) return null;
  return Object.freeze({
    releaseId: release.release_id,
    enrollmentKeyId: release.serial_enrollment.trust_key_id,
    model,
    firmwareVersion: release.firmware_version,
  });
}

export function getTerminalInstallerLock(catalogAudit, support, enrollmentCapabilities) {
  const blockers = [];
  if (!catalogAudit?.valid) blockers.push('The signed firmware catalog did not pass the browser metadata audit.');
  if (catalogAudit?.valid && Array.isArray(catalogAudit.catalog?.blockers)) {
    blockers.push(...catalogAudit.catalog.blockers);
  }
  if (!support?.supported) blockers.push(...(support?.blockers || ['Browser support is incomplete.']));
  if (!terminalEnrollmentCapabilitiesReady(enrollmentCapabilities)) {
    const reported = Array.isArray(enrollmentCapabilities?.blockers)
      ? enrollmentCapabilities.blockers.filter(item => typeof item === 'string' && item.trim())
      : [];
    blockers.push(...(reported.length > 0
      ? reported
      : ['Server enrollment policy has not qualified an exact RET1 release and physical model.']));
  }
  const uniqueBlockers = [...new Set(blockers)];
  return { locked: uniqueBlockers.length > 0, blockers: uniqueBlockers };
}

const OPERATOR_PRESENTATIONS = Object.freeze({
  preflight: ['neutral', 'Preparing preflight', 'Confirm the exact release, model, and physical hardware revision.'],
  fetching: ['neutral', 'Downloading signed package', 'All four preserve-config artifacts are being loaded before any device connection.'],
  verifying: ['neutral', 'Verifying package', 'Artifact byte lengths and SHA-256 digests are being checked in this browser.'],
  awaiting_rom: ['neutral', 'Ready for ROM mode', 'The verified package is ready. Connect only the confirmed terminal and choose its serial port.'],
  probing: ['neutral', 'Checking device identity', 'Confirming ESP32-S3, flash capacity, and factory MAC.'],
  flashing: ['warning', 'Writing firmware', 'Do not unplug the terminal. An interruption now requires recovery.'],
  verifying_flash: ['warning', 'Verifying flash', 'The written segments are being read back before reset.'],
  resetting: ['warning', 'Restarting terminal', 'Waiting for the application firmware to start.'],
  awaiting_status: ['warning', 'Reading terminal status', 'Waiting for the bounded RET1 status-v2 recovery window.'],
  verifying_status: ['warning', 'Confirming runtime identity', 'Checking model, release, build, slot, boot state, and factory MAC.'],
  succeeded: ['success', 'Firmware verified', 'The terminal reported the exact signed build from stable ota_0.'],
  cancelled_before_write: ['neutral', 'Cancelled safely', 'No firmware bytes were written.'],
  blocked: ['danger', 'Installer blocked', 'A qualification or preflight check failed closed before writing.'],
  recovery_required: ['danger', 'Recovery required', 'Leave the USB cable connected, return the terminal to ROM mode, and retry only the exact preserve-config package.'],
});

export function describeTerminalFirmwareInstallState(state, errorCode = '') {
  const [tone, title, detail] = OPERATOR_PRESENTATIONS[state] || OPERATOR_PRESENTATIONS.blocked;
  return Object.freeze({
    state: Object.hasOwn(OPERATOR_PRESENTATIONS, state) ? state : 'blocked',
    tone,
    title,
    detail,
    errorCode: typeof errorCode === 'string' ? errorCode : '',
    recoveryRequired: state === 'recovery_required',
    canDisconnect: [
      'preflight', 'fetching', 'verifying', 'awaiting_rom', 'probing',
      'succeeded', 'cancelled_before_write', 'blocked',
    ].includes(state),
  });
}

export function createTerminalFirmwareDeviceSession() {
  let current = null;
  return Object.freeze({
    attach({ abortController, transports = [] }) {
      if (current) throw new Error('A terminal device session is already active.');
      if (!abortController || typeof abortController.abort !== 'function' || !Array.isArray(transports)) {
        throw new Error('Terminal device cleanup contract is invalid.');
      }
      current = { abortController, transports: [...new Set(transports.filter(Boolean))] };
    },
    isActive() {
      return current !== null;
    },
    release() {
      const active = current !== null;
      current = null;
      return active;
    },
    async disconnect() {
      const session = current;
      current = null;
      if (!session) return false;
      session.abortController.abort();
      await Promise.allSettled(session.transports.map(async transport => {
        await transport?.close?.();
      }));
      return true;
    },
  });
}
