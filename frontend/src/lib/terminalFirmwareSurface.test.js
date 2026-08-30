import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

async function source(relativePath) {
  return readFile(new URL(relativePath, import.meta.url), 'utf8');
}

test('At a Glance renders a read-only, write-locked firmware installer', async () => {
  const [app, admin, component, installer, firmwareApi, plan, workflow, recovery] = await Promise.all([
    source('../App.svelte'),
    source('../pages/Admin.svelte'),
    source('./admin/FirmwareInstaller.svelte'),
    source('./terminalFirmwareInstaller.js'),
    source('./terminalFirmwareApi.js'),
    source('./terminalFirmwareInstallPlan.js'),
    source('./terminalFirmwareInstallWorkflow.js'),
    source('./terminalFirmwareRecovery.js'),
  ]);

  assert.match(admin, /import FirmwareInstaller from '\.\.\/lib\/admin\/FirmwareInstaller\.svelte';/);
  assert.match(admin, /activeTab === 'terminals'[\s\S]*<FirmwareInstaller \/>/);
  assert.match(component, /Device connection, download, erase, and flash operations remain disabled/);
  assert.match(component, /never requests a serial port and cannot write or erase a terminal/);
  assert.doesNotMatch(component, /requestPort\s*\(/);
  assert.doesNotMatch(installer, /\.requestPort\s*\(/);
  assert.doesNotMatch(installer, /\.write\s*\(/);
  assert.doesNotMatch(installer, /eraseFlash|writeFlash|flashData/);
  assert.match(firmwareApi, /TERMINAL_FIRMWARE_CATALOG_ENDPOINT = '\/terminal\/firmware\/catalog'/);
  assert.match(firmwareApi, /TERMINAL_OTA_CAPABILITIES_ENDPOINT = '\/terminal\/firmware\/ota\/capabilities'/);
  assert.equal(
    (firmwareApi.match(/api\.(get|post|put|patch|delete)\(/g) || []).join(','),
    'api.get(,api.get(',
  );

  const productionSurface = [app, admin, component, installer, firmwareApi].join('\n');
  for (const isolatedModule of [
    'terminalFirmwareInstallPlan',
    'terminalFirmwareInstallWorkflow',
    'terminalFirmwareRecovery',
  ]) {
    assert.doesNotMatch(productionSurface, new RegExp(isolatedModule));
  }
  for (const isolatedSource of [plan, workflow, recovery]) {
    assert.doesNotMatch(isolatedSource, /requestPort\s*\(|navigator\.serial|eraseFlash|erase_all\s*:\s*true/);
  }
});
