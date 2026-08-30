import assert from 'node:assert/strict';
import test from 'node:test';
import { focusEmailRowOrFallback, shouldFocusAdjacentRow } from './emailRowFocus.js';

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

test('row-removing actions focus the Inbox fallback when no adjacent row remains', () => {
  let fallbackFocused = false;
  const container = {
    querySelectorAll: () => [],
    focus: () => { fallbackFocused = true; },
  };

  assert.equal(focusEmailRowOrFallback(container, null), 'fallback');
  assert.equal(fallbackFocused, true);
});

test('row-removing actions prefer the adjacent visible row over fallback', () => {
  let rowFocused = false;
  let fallbackFocused = false;
  const row = {
    dataset: { emailRowId: '42' },
    getClientRects: () => [{}],
    focus: () => { rowFocused = true; },
  };
  const container = {
    querySelectorAll: () => [row],
    focus: () => { fallbackFocused = true; },
  };

  assert.equal(focusEmailRowOrFallback(container, 42), 'row');
  assert.equal(rowFocused, true);
  assert.equal(fallbackFocused, false);
});
