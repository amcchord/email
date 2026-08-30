import assert from 'node:assert/strict';
import test from 'node:test';
import { get } from 'svelte/store';
import { createToastController } from './toasts.js';

function scheduledController(limit = 4) {
  const callbacks = new Map();
  let nextTimer = 1;
  const controller = createToastController({
    limit,
    schedule(callback) {
      const id = nextTimer++;
      callbacks.set(id, callback);
      return id;
    },
    cancel(id) {
      callbacks.delete(id);
    },
  });
  return { controller, callbacks };
}

test('older toast expiry cannot clear a newer notification', () => {
  const { controller, callbacks } = scheduledController();
  controller.show('First', 'info', 1000);
  controller.show('Second', 'success', 1000);
  const [firstTimer] = callbacks.keys();

  callbacks.get(firstTimer)();

  assert.deepEqual(get(controller).map(item => item.message), ['Second']);
});

test('toast queue is bounded and cancels evicted timers', () => {
  const { controller, callbacks } = scheduledController(2);
  controller.show('One', 'info', 1000);
  controller.show('Two', 'info', 1000);
  controller.show('Three', 'info', 1000);

  assert.deepEqual(get(controller).map(item => item.message), ['Two', 'Three']);
  assert.equal(callbacks.size, 2);
});

test('actionable toasts retain callback and accessible labels', async () => {
  const { controller } = scheduledController();
  let invoked = 0;
  controller.show('Archived', 'success', 10000, {
    actionLabel: 'Undo',
    onAction: async () => { invoked += 1; },
    dismissLabel: 'Dismiss archive notification',
  });

  const [toast] = get(controller);
  await toast.onAction();

  assert.equal(invoked, 1);
  assert.equal(toast.actionLabel, 'Undo');
  assert.equal(toast.dismissLabel, 'Dismiss archive notification');
});
