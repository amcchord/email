import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

async function source(relativePath) {
  return readFile(new URL(relativePath, import.meta.url), 'utf8');
}

test('terminal Settings owns the OTA control plane while everyday At a Glance stays unchanged', async () => {
  const [admin, atAGlance, component] = await Promise.all([
    source('../pages/Admin.svelte'),
    source('../pages/AtAGlance.svelte'),
    source('./admin/TerminalOtaManager.svelte'),
  ]);

  assert.match(admin, /import TerminalOtaManager from '\.\.\/lib\/admin\/TerminalOtaManager\.svelte';/);
  assert.match(admin, /activeTab === 'terminals'[\s\S]*<TerminalOtaManager devices=\{terminals\}/);
  assert.doesNotMatch(atAGlance, /TerminalOtaManager/);
  assert.match(component, /Owner inspection and rescue controls only/);
  assert.match(component, /never creates an update offer, downloads a firmware artifact, requests a serial port, or writes a device/);
});

test('terminal Settings defaults to routine device work and progressively discloses advanced controls', async () => {
  const admin = await source('../pages/Admin.svelte');

  assert.match(admin, /let terminalSection = \$state\('devices'\)/);
  assert.match(admin, /Devices[\s\S]*Browser displays[\s\S]*General settings[\s\S]*Advanced/);
  assert.match(admin, /Displays &amp; devices/);
  assert.match(admin, /Advanced terminal tools/);
  assert.match(admin, /<details[\s\S]*Install or re-enroll a terminal[\s\S]*<FirmwareInstaller \/>/);
  assert.match(admin, /<details[\s\S]*OTA diagnostics &amp; attempt history[\s\S]*<TerminalOtaManager/);
  assert.match(admin, /terminalSection === 'devices'[\s\S]*xl:grid-cols-2/);
  assert.match(admin, /activeTab === 'terminals' \? 'max-w-6xl' : 'max-w-4xl'/);
});

test('owner OTA surface makes revision, HIL, rollout, history, detail, and cancel boundaries explicit', async () => {
  const [component, otaApi] = await Promise.all([
    source('./admin/TerminalOtaManager.svelte'),
    source('./terminalOtaApi.js'),
  ]);

  assert.match(component, /Confirm printed revision/);
  assert.match(component, /Clear confirmation/);
  assert.match(component, /Physical HIL remains independent/);
  assert.match(component, /Rollout defaults to 0%/);
  assert.match(component, /Attempt history/);
  assert.match(component, /View details/);
  assert.match(component, /canCancelTerminalOtaAttempt\(attempt\)/);
  assert.match(component, /Cancel unstarted offer/);
  assert.match(otaApi, /attempt\.state === 'offered'[\s\S]*attempt\.last_sequence === 0/);
  assert.match(otaApi, /hardware_revision: null/);
  assert.match(otaApi, /reason: 'owner_cancelled'/);
  assert.doesNotMatch(otaApi, /client_request_id|release_id|\/artifacts\//);
  assert.doesNotMatch(component, /navigator\.serial|requestPort\s*\(|writeFlash|eraseFlash/);
});
