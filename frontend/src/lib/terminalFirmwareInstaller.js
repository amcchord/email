/**
 * Browser installer capability detection only.
 *
 * There is deliberately no requestPort, flash, erase, or binary download
 * operation in this module. Capability detection cannot mutate a device.
 */
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
  return { locked: true, blockers: [...new Set(blockers)] };
}
