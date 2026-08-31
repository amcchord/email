import { api } from './api.js';

export const TERMINAL_ENROLLMENT_CAPABILITIES_ENDPOINT = '/terminal/enrollment/capabilities';
export const TERMINAL_ENROLLMENT_DEVICES_ENDPOINT = '/terminal/enrollment/devices';
export const TERMINAL_ENROLLMENT_INTENTS_ENDPOINT = '/terminal/enrollment/intents';
const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/iu;

function terminalEnrollmentAttemptId(attemptId) {
  if (typeof attemptId !== 'string' || !UUID_PATTERN.test(attemptId)) {
    throw new Error('A valid terminal enrollment attempt ID is required');
  }
  return attemptId.toLowerCase();
}

export function terminalEnrollmentRevokeEndpoint(publicId) {
  if (typeof publicId !== 'string' || !publicId.trim()) {
    throw new Error('A terminal public ID is required');
  }
  return `${TERMINAL_ENROLLMENT_DEVICES_ENDPOINT}/${encodeURIComponent(publicId.trim())}/revoke`;
}

/**
 * Read the session-authenticated, fail-closed RET1 enrollment policy.
 *
 * Reading policy never requests a serial port. The separately gated browser
 * adapter may proceed only when this capability response and the signed
 * firmware package both report the same qualified release/model.
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

export function createTerminalEnrollmentIntent(payload) {
  return api.post(TERMINAL_ENROLLMENT_INTENTS_ENDPOINT, payload);
}

export function issueTerminalEnrollmentTicket(attemptId, payload) {
  return api.post(
    `${TERMINAL_ENROLLMENT_INTENTS_ENDPOINT}/${terminalEnrollmentAttemptId(attemptId)}/ticket`,
    payload,
  );
}

export function completeTerminalEnrollmentIntent(attemptId, payload) {
  return api.post(
    `${TERMINAL_ENROLLMENT_INTENTS_ENDPOINT}/${terminalEnrollmentAttemptId(attemptId)}/complete`,
    payload,
  );
}

/**
 * Supersede one owner-scoped attempt before an encrypted configuration write.
 * The caller must reuse the exact client intent id that created the attempt.
 */
export function cancelTerminalEnrollmentIntent(attemptId, payload) {
  return api.post(
    `${TERMINAL_ENROLLMENT_INTENTS_ENDPOINT}/${terminalEnrollmentAttemptId(attemptId)}/cancel`,
    payload,
  );
}

export function getTerminalEnrollmentIntent(attemptId) {
  return api.get(
    `${TERMINAL_ENROLLMENT_INTENTS_ENDPOINT}/${terminalEnrollmentAttemptId(attemptId)}`,
  );
}
