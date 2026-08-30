import assert from 'node:assert/strict';
import test from 'node:test';

import {
  captureAuthEpoch,
  isAuthEpochCurrent,
  normalizedAuthenticatedUserId,
  transitionAuthEpoch,
} from './authSession.js';

test('authenticated identity transitions invalidate prior generations', () => {
  transitionAuthEpoch(null);
  const anonymous = captureAuthEpoch();
  const first = transitionAuthEpoch({ id: 101, username: 'generated-a' });

  assert.equal(first.changed, true);
  assert.equal(first.snapshot.userId, '101');
  assert.equal(isAuthEpochCurrent(anonymous), false);
  assert.equal(isAuthEpochCurrent(first.snapshot), true);

  const sameIdentity = transitionAuthEpoch({ id: 101, username: 'generated-a-renamed' });
  assert.equal(sameIdentity.changed, false);
  assert.equal(sameIdentity.snapshot.generation, first.snapshot.generation);

  const second = transitionAuthEpoch({ id: 202, username: 'generated-b' });
  assert.equal(second.changed, true);
  assert.equal(isAuthEpochCurrent(first.snapshot), false);
  assert.equal(isAuthEpochCurrent(second.snapshot), true);

  transitionAuthEpoch(null);
});

test('invalid authenticated identities fail closed as anonymous', () => {
  for (const candidate of [null, {}, { id: 0 }, { id: -3 }, { id: '../user' }, { id: 'two users' }]) {
    assert.equal(normalizedAuthenticatedUserId(candidate), null);
  }
});
