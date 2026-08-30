import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const source = relative => readFileSync(new URL(relative, import.meta.url), 'utf8');

test('production enrollment surface is visible but has no serial or provisioning capability', () => {
  const admin = source('../pages/Admin.svelte');
  const component = source('./admin/TerminalEnrollment.svelte');
  const api = source('./terminalEnrollmentApi.js');

  assert.match(admin, /import TerminalEnrollment from '\.\.\/lib\/admin\/TerminalEnrollment\.svelte';/);
  assert.match(admin, /activeTab === 'terminals'[\s\S]*<TerminalEnrollment bind:this=\{terminalEnrollmentPanel\} \/>/);
  assert.match(component, /never requests a serial port/);
  assert.match(component, /browser-observed physical serial session/);
  assert.match(component, /not hardware attestation or proof of cryptographic hardware identity/);
  assert.match(api, /capabilities/);

  for (const productionSource of [admin, component, api]) {
    assert.doesNotMatch(productionSource, /requestPort\s*\(/);
    assert.doesNotMatch(productionSource, /terminalEnrollmentProtocol/);
    assert.doesNotMatch(productionSource, /\.serial\b/);
  }
});

test('owner can revoke only pending or enrolled secure terminal credentials', () => {
  const admin = source('../pages/Admin.svelte');
  const api = source('./terminalEnrollmentApi.js');

  assert.match(admin, /device\.enrollment_state === 'enrolled' \|\| device\.enrollment_state === 'pending'/);
  assert.match(admin, /Revoke secure access for/);
  assert.match(admin, /private device URL will stop working/);
  assert.match(admin, /labeled by their reported MAC/);
  assert.match(admin, /loadTerminals\(\),[\s\S]*terminalEnrollmentPanel\?\.refresh\?\.\(\)/);
  assert.match(api, /api\.post\(terminalEnrollmentRevokeEndpoint\(publicId\), \{\}\)/);
});
