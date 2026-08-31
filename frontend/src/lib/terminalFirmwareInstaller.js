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

export const BROWSER_INSTALLER_SAFETY_GATES = Object.freeze({
  browserSignatureVerification: false,
  secureDeviceProvisioning: false,
  hardwareInLoopQualification: false,
});

export function getTerminalInstallerLock(catalogAudit, support) {
  const blockers = [];
  if (!catalogAudit?.valid) blockers.push('The signed firmware catalog did not pass the browser metadata audit.');
  if (catalogAudit?.valid && Array.isArray(catalogAudit.catalog?.blockers)) {
    blockers.push(...catalogAudit.catalog.blockers);
  }
  if (!support?.supported) blockers.push(...(support?.blockers || ['Browser support is incomplete.']));
  if (!BROWSER_INSTALLER_SAFETY_GATES.browserSignatureVerification) {
    blockers.push('Pinned browser-side signature verification is not yet enabled.');
  }
  if (!BROWSER_INSTALLER_SAFETY_GATES.secureDeviceProvisioning) {
    blockers.push('Secure device enrollment and provisioning are not yet qualified.');
  }
  if (!BROWSER_INSTALLER_SAFETY_GATES.hardwareInLoopQualification) {
    blockers.push('Hardware-in-the-loop recovery testing is not yet complete.');
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
