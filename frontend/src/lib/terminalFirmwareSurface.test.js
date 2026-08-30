import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

async function source(relativePath) {
  return readFile(new URL(relativePath, import.meta.url), 'utf8');
}

test('At a Glance renders a catalog-only locked firmware installer', async () => {
  const [admin, component, installer, firmwareApi] = await Promise.all([
    source('../pages/Admin.svelte'),
    source('./admin/FirmwareInstaller.svelte'),
    source('./terminalFirmwareInstaller.js'),
    source('./terminalFirmwareApi.js'),
  ]);

  assert.match(admin, /import FirmwareInstaller from '\.\.\/lib\/admin\/FirmwareInstaller\.svelte';/);
  assert.match(admin, /activeTab === 'terminals'[\s\S]*<FirmwareInstaller \/>/);
  assert.match(component, /Device connection, download, erase, and flash operations remain disabled/);
  assert.match(component, /never requests a serial port and cannot write or erase a terminal/);
  assert.doesNotMatch(component, /requestPort\s*\(/);
  assert.doesNotMatch(installer, /\.requestPort\s*\(/);
  assert.doesNotMatch(installer, /\.write\s*\(/);
  assert.doesNotMatch(installer, /eraseFlash|writeFlash|flashData/);
  assert.equal((firmwareApi.match(/api\.(get|post|put|delete)\(/g) || []).join(','), 'api.get(');
});
