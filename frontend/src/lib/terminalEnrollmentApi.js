import { api } from './api.js';

export const TERMINAL_ENROLLMENT_CAPABILITIES_ENDPOINT = '/terminal/enrollment/capabilities';
export const TERMINAL_ENROLLMENT_DEVICES_ENDPOINT = '/terminal/enrollment/devices';

export function terminalEnrollmentRevokeEndpoint(publicId) {
  if (typeof publicId !== 'string' || !publicId.trim()) {
    throw new Error('A terminal public ID is required');
  }
  return `${TERMINAL_ENROLLMENT_DEVICES_ENDPOINT}/${encodeURIComponent(publicId.trim())}/revoke`;
}

/**
 * Read the session-authenticated, fail-closed RET1 enrollment policy.
 *
 * Serial transport is intentionally absent. The production surface may show
 * qualification evidence, but it cannot request a port or provision a device
 * until the physical HIL milestone enables a separate transport adapter.
 */
export function getTerminalEnrollmentCapabilities() {
  return api.get(TERMINAL_ENROLLMENT_CAPABILITIES_ENDPOINT);
}

/**
 * Revoke every credential generation for one owner-scoped secure terminal.
 * The terminal must be physically enrolled again before it can check in.
 */
export function revokeTerminalEnrollment(publicId) {
  return api.post(terminalEnrollmentRevokeEndpoint(publicId), {});
}
