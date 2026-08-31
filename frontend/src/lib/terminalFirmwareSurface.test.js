import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

async function source(relativePath) {
  return readFile(new URL(relativePath, import.meta.url), 'utf8');
}

test('At a Glance wires the isolated Web Serial adapter while independent production gates stay locked', async () => {
  const [app, atAGlance, admin, component, installer, webSerial, firmwareApi, plan, workflow, recovery] = await Promise.all([
    source('../App.svelte'),
    source('../pages/AtAGlance.svelte'),
    source('../pages/Admin.svelte'),
    source('./admin/FirmwareInstaller.svelte'),
    source('./terminalFirmwareInstaller.js'),
    source('./terminalFirmwareWebSerial.js'),
    source('./terminalFirmwareApi.js'),
    source('./terminalFirmwareInstallPlan.js'),
    source('./terminalFirmwareInstallWorkflow.js'),
    source('./terminalFirmwareRecovery.js'),
  ]);

  assert.match(admin, /import FirmwareInstaller from '\.\.\/lib\/admin\/FirmwareInstaller\.svelte';/);
  assert.match(admin, /activeTab === 'terminals'[\s\S]*<FirmwareInstaller \/>/);
  assert.match(atAGlance, /import FirmwareInstaller from '\.\.\/lib\/admin\/FirmwareInstaller\.svelte';/);
  assert.match(atAGlance, /Terminal firmware[\s\S]*<FirmwareInstaller \/>/);
  assert.match(component, /Verify a signed preserve-config package/);
  assert.match(component, /compileTerminalFirmwareInstallPlan/);
  assert.match(component, /loadTerminalFirmwareInstallArtifacts/);
  assert.match(component, /runTerminalFirmwareInstallWorkflow/);
  assert.match(component, /createTerminalFirmwareWebSerialTransports/);
  assert.match(component, /PRODUCTION_TRANSPORT_AVAILABLE = true/);
  assert.match(component, /disabled=\{!canConnectInstall\}/);
  assert.match(component, /!lock\.locked/);
  assert.match(component, /Recovery required|recoveryRequired/);
  assert.match(component, /Disconnect device/);
  assert.match(component, /port selection always requires an explicit click/);
  assert.doesNotMatch(component, /requestPort\s*\(/);
  assert.doesNotMatch(installer, /\.requestPort\s*\(/);
  assert.doesNotMatch(installer, /\.write\s*\(/);
  assert.doesNotMatch(installer, /eraseFlash|writeFlash|flashData/);
  assert.match(webSerial, /await serial\.requestPort\(\)/);
  assert.match(webSerial, /locks\.request/);
  assert.match(webSerial, /writeFlash/);
  assert.match(webSerial, /readFlash/);
  assert.match(webSerial, /after\('hard_reset'\)/);
  assert.match(webSerial, /eraseAll: false/);
  assert.doesNotMatch(webSerial, /eraseFlash|eraseAll: true/);
  assert.match(firmwareApi, /TERMINAL_FIRMWARE_CATALOG_ENDPOINT = '\/terminal\/firmware\/catalog'/);
  assert.match(firmwareApi, /TERMINAL_OTA_CAPABILITIES_ENDPOINT = '\/terminal\/firmware\/ota\/capabilities'/);
  assert.equal(
    (firmwareApi.match(/api\.(get|post|put|patch|delete)\(/g) || []).join(','),
    'api.get(,api.get(',
  );

  const productionSurface = [app, atAGlance, admin, component, installer, firmwareApi].join('\n');
  assert.doesNotMatch(productionSurface, /requestPort\s*\(|navigator\.serial|eraseFlash|writeFlash|flashData/);
  for (const isolatedSource of [plan, workflow, recovery]) {
    assert.doesNotMatch(isolatedSource, /requestPort\s*\(|navigator\.serial|eraseFlash|erase_all\s*:\s*true/);
  }
});
