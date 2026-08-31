import { api } from './api.js';

export const TERMINAL_OTA_CAPABILITIES_ENDPOINT = '/terminal/firmware/ota/capabilities';
const TERMINAL_OTA_DEVICES_ENDPOINT = '/terminal/devices';
const TERMINAL_OTA_ATTEMPTS_ENDPOINT = '/terminal/ota/attempts';
const HARDWARE_REVISION_PATTERN = /^[A-Za-z0-9._-]{1,64}$/;
const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

function terminalDeviceId(deviceId) {
  const parsed = typeof deviceId === 'string' && /^\d+$/.test(deviceId)
    ? Number(deviceId)
    : deviceId;
  if (!Number.isSafeInteger(parsed) || parsed <= 0) {
    throw new Error('A valid terminal device ID is required');
  }
  return parsed;
}

function terminalAttemptId(attemptId) {
  if (typeof attemptId !== 'string' || !UUID_PATTERN.test(attemptId)) {
    throw new Error('A valid terminal OTA attempt ID is required');
  }
  return attemptId.toLowerCase();
}

export function normalizeTerminalHardwareRevision(value) {
  const revision = typeof value === 'string' ? value.trim() : '';
  if (!HARDWARE_REVISION_PATTERN.test(revision)) {
    throw new Error('Use 1–64 letters, numbers, periods, underscores, or hyphens from the printed revision.');
  }
  return revision;
}

export function canCancelTerminalOtaAttempt(attempt) {
  return Boolean(
    attempt
    && attempt.state === 'offered'
    && attempt.last_sequence === 0,
  );
}

export function getTerminalOtaCapabilities() {
  return api.get(TERMINAL_OTA_CAPABILITIES_ENDPOINT);
}

export function listTerminalOtaAttempts(deviceId) {
  return api.get(`${TERMINAL_OTA_DEVICES_ENDPOINT}/${terminalDeviceId(deviceId)}/ota/attempts`);
}

export function getTerminalOtaAttempt(attemptId) {
  return api.get(`${TERMINAL_OTA_ATTEMPTS_ENDPOINT}/${terminalAttemptId(attemptId)}`);
}

export function confirmTerminalHardwareRevision(deviceId, revision) {
  return api.updateTerminal(terminalDeviceId(deviceId), {
    hardware_revision: normalizeTerminalHardwareRevision(revision),
  });
}

export function clearTerminalHardwareRevision(deviceId) {
  return api.updateTerminal(terminalDeviceId(deviceId), { hardware_revision: null });
}

export function cancelTerminalOtaAttempt(attempt) {
  if (!canCancelTerminalOtaAttempt(attempt)) {
    throw new Error('Only an unstarted OTA offer can be cancelled.');
  }
  return api.post(
    `${TERMINAL_OTA_ATTEMPTS_ENDPOINT}/${terminalAttemptId(attempt.attempt_id)}/cancel`,
    { reason: 'owner_cancelled' },
  );
}
