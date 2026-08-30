import assert from 'node:assert/strict';
import test from 'node:test';

import { terminalEnrollmentRevokeEndpoint } from './terminalEnrollmentApi.js';

test('terminal revocation endpoint is scoped to the encoded public device id', () => {
  assert.equal(
    terminalEnrollmentRevokeEndpoint('52e18b2d-84af-4f3b-a059-f316930c8ef5'),
    '/terminal/enrollment/devices/52e18b2d-84af-4f3b-a059-f316930c8ef5/revoke',
  );
  assert.equal(
    terminalEnrollmentRevokeEndpoint('device/id'),
    '/terminal/enrollment/devices/device%2Fid/revoke',
  );
});

test('terminal revocation endpoint rejects a missing public device id', () => {
  assert.throws(() => terminalEnrollmentRevokeEndpoint(''), /public ID is required/);
  assert.throws(() => terminalEnrollmentRevokeEndpoint('   '), /public ID is required/);
  assert.throws(() => terminalEnrollmentRevokeEndpoint(null), /public ID is required/);
});
