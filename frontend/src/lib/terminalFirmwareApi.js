import { api } from './api.js';

export const TERMINAL_FIRMWARE_CATALOG_ENDPOINT = '/terminal/firmware/catalog';

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
