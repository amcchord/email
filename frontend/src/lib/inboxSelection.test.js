import assert from 'node:assert/strict';
import test from 'node:test';

import { createInboxSelectionModel } from './inboxSelection.js';

test('toggle, range selection, select loaded, and clear are deterministic', () => {
  const model = createInboxSelectionModel({ sessionKey: 'user:2', datasetKey: 'inbox:focused' });
  model.toggle(2);
  assert.deepEqual(model.snapshot().selectedIds, [2]);
  model.selectRange(5, [1, 2, 3, 4, 5]);
  assert.deepEqual(model.snapshot().selectedIds, [2, 3, 4, 5]);
  model.toggle(3);
  assert.deepEqual(model.snapshot().selectedIds, [2, 4, 5]);
  model.selectLoaded([8, 8, 9, null]);
  assert.deepEqual(model.snapshot().selectedIds, [8, 9]);
  assert.equal(model.snapshot().anchorId, 9);
  model.clear();
  assert.equal(model.snapshot().size, 0);
});

test('same-dataset refresh and list/table toggles preserve selection', () => {
  const model = createInboxSelectionModel({ sessionKey: 'user:2', datasetKey: 'inbox:all' });
  model.selectLoaded([11, 12]);
  assert.equal(model.setScope({ sessionKey: 'user:2', datasetKey: 'inbox:all' }), false);
  model.prune([11, 12, 13]);
  assert.deepEqual(model.snapshot().selectedIds, [11, 12]);
});

test('authoritative refresh prunes vanished rows but partial/error refresh does not', () => {
  const model = createInboxSelectionModel({ sessionKey: 'user:2', datasetKey: 'saved:9' });
  model.selectLoaded([4, 5, 6]);
  model.prune([4], { authoritative: false });
  assert.deepEqual(model.snapshot().selectedIds, [4, 5, 6]);
  model.prune([4, 6, 7]);
  assert.deepEqual(model.snapshot().selectedIds, [4, 6]);
  assert.equal(model.snapshot().anchorId, 6);
});

test('dataset and authenticated-session changes clear selection immediately', () => {
  const model = createInboxSelectionModel({ sessionKey: 'user:2', datasetKey: 'inbox:focused' });
  model.toggle(21);
  assert.equal(model.setScope({ sessionKey: 'user:2', datasetKey: 'inbox:other' }), true);
  assert.equal(model.snapshot().size, 0);
  model.toggle(22);
  assert.equal(model.setScope({ sessionKey: 'user:3', datasetKey: 'inbox:other' }), true);
  assert.equal(model.snapshot().size, 0);
});

test('range selection is bounded to authoritative ordered IDs and supports replacement', () => {
  const model = createInboxSelectionModel({ sessionKey: 'user:2', datasetKey: 'inbox' });
  model.toggle('mail-a');
  model.selectRange('mail-c', ['mail-a', 'mail-b', 'mail-c']);
  assert.deepEqual(model.snapshot().selectedIds, ['mail-a', 'mail-b', 'mail-c']);
  model.selectRange('missing', ['mail-a', 'mail-b']);
  assert.deepEqual(model.snapshot().selectedIds, ['mail-a', 'mail-b', 'mail-c']);
  model.selectRange('mail-b', ['mail-a', 'mail-b', 'mail-c'], { replace: true });
  assert.deepEqual(model.snapshot().selectedIds, ['mail-b', 'mail-c']);
});
