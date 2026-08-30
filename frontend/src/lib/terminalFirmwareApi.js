import { api } from './api.js';
import { captureAuthEpoch, isAuthEpochCurrent } from './authSession.js';

export const TERMINAL_FIRMWARE_CATALOG_ENDPOINT = '/terminal/firmware/catalog';
export const TERMINAL_OTA_CAPABILITIES_ENDPOINT = '/terminal/firmware/ota/capabilities';
const SHA256_PATTERN = /^[0-9a-f]{64}$/;
const MAX_MANIFEST_BYTES = 512 * 1024;

function authSessionChanged() {
  const error = new Error('Authentication session changed');
  error.name = 'AbortError';
  error.code = 'auth_session_changed';
  return error;
}

async function readExactResponse(response, maximumBytes, label) {
  if (!response?.ok) throw new Error(`${label} is unavailable.`);
  const declaredLength = response.headers?.get?.('content-length');
  if (declaredLength !== null && declaredLength !== undefined) {
    const parsedLength = Number(declaredLength);
    if (!Number.isSafeInteger(parsedLength) || parsedLength < 0 || parsedLength > maximumBytes) {
      throw new Error(`${label} has an unsafe byte length.`);
    }
  }
  const value = new Uint8Array(await response.arrayBuffer());
  if (value.length === 0 || value.length > maximumBytes) {
    throw new Error(`${label} has an unsafe byte length.`);
  }
  return value;
}

/**
 * Read the authenticated, same-origin firmware catalog.
 *
 * This module intentionally exposes no binary download, serial, erase, or
 * write operation. Those operations stay unavailable until browser-side
 * signature verification and device provisioning are qualified.
 */
export function getTerminalFirmwareCatalog() {
  return api.get(TERMINAL_FIRMWARE_CATALOG_ENDPOINT);
}

export function getTerminalOtaCapabilities() {
  return api.get(TERMINAL_OTA_CAPABILITIES_ENDPOINT);
}

/**
 * Fetch only the exact signed metadata bytes for browser-side verification.
 * Artifact binaries and every serial/write operation remain intentionally
 * absent from this module.
 */
export async function getTerminalFirmwareReleaseEvidence(
  releaseId,
  { fetchImpl = globalThis.fetch, signal } = {},
) {
  if (!SHA256_PATTERN.test(releaseId) || typeof fetchImpl !== 'function') {
    throw new Error('Firmware release ID or fetch runtime is invalid.');
  }
  const authEpoch = captureAuthEpoch();
  const base = `/api/terminal/firmware/releases/${releaseId}`;
  const options = { method: 'GET', credentials: 'include', signal };
  const [manifestResponse, signatureResponse] = await Promise.all([
    fetchImpl(`${base}/manifest.json`, options),
    fetchImpl(`${base}/manifest.sig`, options),
  ]);
  if (!isAuthEpochCurrent(authEpoch)) throw authSessionChanged();
  const [manifestBytes, signatureBytes] = await Promise.all([
    readExactResponse(manifestResponse, MAX_MANIFEST_BYTES, 'Firmware manifest'),
    readExactResponse(signatureResponse, 64, 'Firmware signature'),
  ]);
  if (!isAuthEpochCurrent(authEpoch)) throw authSessionChanged();
  if (signatureBytes.length !== 64) throw new Error('Firmware signature is not 64 bytes.');
  return { manifestBytes, signatureBytes };
}
