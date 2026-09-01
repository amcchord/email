import assert from 'node:assert/strict';
import test from 'node:test';

import {
  DEFAULT_SWIPE_TRIAGE_PREFERENCES,
  SWIPE_TRIAGE_ACTIONS,
  createSwipeTriageController,
  isInteractiveSwipeTarget,
  normalizeSwipeTriagePreferences,
} from './swipeTriage.js';

function pointer(overrides = {}) {
  return {
    pointerId: 4,
    pointerType: 'touch',
    isPrimary: true,
    button: 0,
    clientX: 20,
    clientY: 20,
    target: { closest: () => null },
    preventDefault() {},
    ...overrides,
  };
}

test('preference contract is closed to non-destructive triage actions', () => {
  assert.deepEqual(SWIPE_TRIAGE_ACTIONS, [
    'archive', 'snooze', 'toggle_read', 'toggle_star', 'none',
  ]);
  for (const forbidden of ['trash', 'spam', 'move']) {
    assert.equal(SWIPE_TRIAGE_ACTIONS.includes(forbidden), false);
  }
  assert.deepEqual(normalizeSwipeTriagePreferences({ right: 'trash', left: 'toggle_star' }), {
    right: DEFAULT_SWIPE_TRIAGE_PREFERENCES.right,
    left: 'toggle_star',
  });
});

test('interactive descendants, mouse, non-primary, and multi-touch starts are ignored', () => {
  const controller = createSwipeTriageController();
  assert.equal(controller.pointerDown(pointer({ pointerType: 'mouse' })), false);
  assert.equal(controller.pointerDown(pointer({ isPrimary: false })), false);
  assert.equal(controller.pointerDown(pointer({ touches: [{}, {}] })), false);
  assert.equal(controller.pointerDown(pointer({ target: { closest: () => ({ tagName: 'BUTTON' }) } })), false);
  assert.equal(controller.getState().tracking, false);
  assert.equal(isInteractiveSwipeTarget({ tagName: 'INPUT', parentNode: null }), true);

  assert.equal(controller.pointerDown(pointer({ pointerId: 8 })), true);
  assert.equal(controller.pointerDown(pointer({ pointerId: 9, isPrimary: false })), false);
  assert.equal(controller.getState().cancelReason, 'multi-touch');
});

test('vertical movement wins before horizontal intent and does not prevent scrolling', () => {
  let prevented = false;
  const controller = createSwipeTriageController({ intentDistance: 8, axisDominance: 1.4 });
  assert.equal(controller.pointerDown(pointer()), true);
  const state = controller.pointerMove(pointer({
    clientX: 24,
    clientY: 48,
    preventDefault() { prevented = true; },
  }));
  assert.equal(prevented, false);
  assert.equal(state.tracking, false);
  assert.equal(state.cancelReason, 'vertical-scroll');
});

test('clear horizontal intent exposes transform, reveal, action, and armed state', () => {
  let prevented = false;
  const controller = createSwipeTriageController({ threshold: 60, maxTranslation: 80 });
  controller.pointerDown(pointer());
  const state = controller.pointerMove(pointer({
    clientX: 92,
    clientY: 23,
    preventDefault() { prevented = true; },
  }));
  assert.equal(prevented, true);
  assert.equal(state.phase, 'swiping');
  assert.equal(state.direction, 'right');
  assert.equal(state.action, 'snooze');
  assert.equal(state.deltaX, 72);
  assert.equal(state.transformX, 72);
  assert.equal(state.reveal, 1);
  assert.equal(state.armed, true);
});

test('threshold is configurable, disabled directions never arm, and commit happens once on pointerup', () => {
  const commits = [];
  const controller = createSwipeTriageController({
    threshold: 50,
    preferences: { right: 'none', left: 'toggle_read' },
    onCommit: commit => commits.push(commit),
  });
  controller.pointerDown(pointer());
  controller.pointerMove(pointer({ clientX: 90 }));
  assert.equal(controller.getState().armed, false);
  assert.equal(controller.pointerUp(pointer({ clientX: 90 })), null);

  controller.pointerDown(pointer({ pointerId: 7 }));
  controller.pointerMove(pointer({ pointerId: 7, clientX: -40 }));
  const commit = controller.pointerUp(pointer({ pointerId: 7, clientX: -40 }));
  assert.equal(commit.action, 'toggle_read');
  assert.equal(commit.direction, 'left');
  assert.equal(controller.pointerUp(pointer({ pointerId: 7, clientX: -40 })), null);
  assert.equal(commits.length, 1);
  assert.equal(controller.getState().phase, 'idle');
});

test('pointer cancellation, lost capture, disabled state, and generation changes cancel safely', () => {
  const controller = createSwipeTriageController({ generation: 'account-1:inbox:1' });
  controller.pointerDown(pointer());
  controller.pointerCancel(pointer());
  assert.equal(controller.getState().cancelReason, 'pointer-cancel');

  controller.pointerDown(pointer());
  controller.lostPointerCapture(pointer());
  assert.equal(controller.getState().cancelReason, 'lost-pointer-capture');

  controller.pointerDown(pointer());
  controller.updateContext({ disabled: true });
  assert.equal(controller.getState().cancelReason, 'disabled');

  controller.updateContext({ disabled: false, generation: 'account-1:inbox:2' });
  controller.pointerDown(pointer());
  controller.updateContext({ generation: 'account-2:inbox:1' });
  assert.equal(controller.getState().cancelReason, 'generation-changed');
});

test('a getter-backed generation change is rechecked before move and commit', () => {
  let generation = 1;
  const commits = [];
  const controller = createSwipeTriageController({
    threshold: 40,
    getGeneration: () => generation,
    onCommit: commit => commits.push(commit),
  });
  controller.pointerDown(pointer());
  controller.pointerMove(pointer({ clientX: 80 }));
  generation = 2;
  assert.equal(controller.pointerUp(pointer({ clientX: 80 })), null);
  assert.equal(controller.getState().cancelReason, 'generation-changed');
  assert.equal(commits.length, 0);
});
