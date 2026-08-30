import assert from 'node:assert/strict';
import test from 'node:test';
import { shouldFocusAdjacentRow } from './emailRowFocus.js';

test('focus follows selection when the previously selected row was removed', () => {
  assert.equal(shouldFocusAdjacentRow({
    previousSelectedId: 2,
    selectedId: 3,
    previousEmailIds: [1, 2, 3],
    emailIds: [1, 3],
  }), true);
});

test('ordinary selection changes do not steal DOM focus', () => {
  assert.equal(shouldFocusAdjacentRow({
    previousSelectedId: 1,
    selectedId: 2,
    previousEmailIds: [1, 2, 3],
    emailIds: [1, 2, 3],
  }), false);
});

test('focus does not move when a removed selection has no adjacent row', () => {
  assert.equal(shouldFocusAdjacentRow({
    previousSelectedId: 1,
    selectedId: null,
    previousEmailIds: [1],
    emailIds: [],
  }), false);
});
