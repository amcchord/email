import assert from 'node:assert/strict';
import test from 'node:test';
import { claimLabelPickerKeyEvent } from './labelPickerKeys.js';

function keyEvent(key) {
  return {
    key,
    stopped: false,
    prevented: false,
    stopPropagation() { this.stopped = true; },
    preventDefault() { this.prevented = true; },
  };
}

test('picker claims printable key events without preventing search input', () => {
  const event = keyEvent('l');
  assert.equal(claimLabelPickerKeyEvent(event, { preventEscape: true }), 'l');
  assert.equal(event.stopped, true);
  assert.equal(event.prevented, false);
});

test('picker claims and prevents Escape so only the controlled modal closes', () => {
  const event = keyEvent('Escape');
  claimLabelPickerKeyEvent(event, { preventEscape: true });
  assert.equal(event.stopped, true);
  assert.equal(event.prevented, true);
});

test('picker claims keyup and keypress events without changing defaults', () => {
  for (const key of ['v', 'ArrowDown', 'Escape']) {
    const event = keyEvent(key);
    claimLabelPickerKeyEvent(event);
    assert.equal(event.stopped, true);
    assert.equal(event.prevented, false);
  }
});
