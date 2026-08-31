import assert from 'node:assert/strict';
import test from 'node:test';

import {
  commandPaletteOpen,
  dispatchAction,
  eventToCombo,
  getActionState,
  helpModalOpen,
  hasHandler,
  invokeAction,
  normalizeCombo,
  openCommandPalette,
  openShortcutHelp,
  registerActions,
  toggleShortcutHelp,
} from './shortcutStore.js';
import { get } from 'svelte/store';
import { SHORTCUT_DEFAULTS } from './shortcutDefaults.js';

test('nested action registrations restore the previous owner on cleanup', () => {
  const calls = [];
  const cleanupPage = registerActions({
    'test.nested': () => calls.push('page'),
  });
  const cleanupDetail = registerActions({
    'test.nested': () => calls.push('detail'),
  });

  assert.equal(dispatchAction('test.nested'), true);
  cleanupDetail();
  assert.equal(dispatchAction('test.nested'), true);
  cleanupPage();
  assert.equal(dispatchAction('test.nested'), false);
  assert.deepEqual(calls, ['detail', 'page']);
});

test('disabled actions expose a reason and never execute', () => {
  let executions = 0;
  const cleanup = registerActions({
    'test.disabled': {
      run: () => { executions += 1; },
      isEnabled: () => false,
      disabledReason: () => 'Select an email first',
    },
  });

  assert.deepEqual(
    getActionState('test.disabled'),
    {
      registered: true,
      enabled: false,
      disabledReason: 'Select an email first',
      run: getActionState('test.disabled').run,
    },
  );
  assert.equal(dispatchAction('test.disabled'), false);
  assert.equal(invokeAction('test.disabled').started, false);
  assert.equal(executions, 0);
  cleanup();
});

test('invokeAction returns synchronous errors and async results to the palette', async () => {
  const cleanupError = registerActions({
    'test.error': () => { throw new Error('generated command failure'); },
  });
  const failed = invokeAction('test.error');
  assert.equal(failed.started, true);
  assert.match(failed.error.message, /generated command failure/);
  cleanupError();

  const cleanupAsync = registerActions({
    'test.async': async () => 'completed',
  });
  const pending = invokeAction('test.async');
  assert.equal(pending.started, true);
  assert.equal(await pending.result, 'completed');
  cleanupAsync();
});

test('cleanup is idempotent and removes only the registration it owns', () => {
  const cleanup = registerActions({ 'test.cleanup': () => true });
  assert.equal(hasHandler('test.cleanup'), true);
  cleanup();
  cleanup();
  assert.equal(hasHandler('test.cleanup'), false);
});

test('command-surface helpers preserve exclusive modal ownership', () => {
  helpModalOpen.set(false);
  commandPaletteOpen.set(false);

  openShortcutHelp();
  assert.equal(get(helpModalOpen), true);
  assert.equal(get(commandPaletteOpen), false);

  openCommandPalette();
  assert.equal(get(helpModalOpen), false);
  assert.equal(get(commandPaletteOpen), true);

  toggleShortcutHelp();
  assert.equal(get(helpModalOpen), true);
  assert.equal(get(commandPaletteOpen), false);
  toggleShortcutHelp();
  assert.equal(get(helpModalOpen), false);
});

test('keyboard normalization matches shifted letters and printable punctuation', () => {
  const baseEvent = { altKey: false, ctrlKey: false, metaKey: false };

  assert.equal(eventToCombo({ ...baseEvent, key: '?', shiftKey: true }), normalizeCombo('?'));
  assert.equal(eventToCombo({ ...baseEvent, key: '!', shiftKey: true }), normalizeCombo('!'));
  assert.equal(eventToCombo({ ...baseEvent, key: 'I', shiftKey: true }), normalizeCombo('Shift+i'));
});

test('durable send shortcuts remain palette-visible and keep their existing bindings', () => {
  const byId = Object.fromEntries(SHORTCUT_DEFAULTS.map(shortcut => [shortcut.id, shortcut]));

  assert.notEqual(byId['compose.send'].palette, false);
  assert.notEqual(byId['flow.send'].palette, false);
  assert.equal(byId['compose.send'].key, 'Ctrl+Enter');
  assert.equal(byId['compose.sendArchive'].key, 'Ctrl+Shift+Enter');
  assert.equal(byId['inbox.sendArchive'].key, 'Ctrl+Shift+Enter');
  assert.equal(byId['flow.send'].key, 'Ctrl+Enter');
});

test('compose separates safe close from destructive discard', () => {
  const byId = Object.fromEntries(SHORTCUT_DEFAULTS.map(shortcut => [shortcut.id, shortcut]));

  assert.equal(byId['compose.discard'].key, 'Escape');
  assert.match(byId['compose.discard'].label, /keep draft/i);
  assert.equal(byId['compose.deleteDraft'].key, 'Ctrl+Shift+,');
  assert.match(byId['compose.deleteDraft'].label, /discard draft/i);
});

test('At a Glance has a unique global navigation shortcut', () => {
  const shortcut = SHORTCUT_DEFAULTS.find(item => item.id === 'nav.glance');
  assert.deepEqual(shortcut, {
    id: 'nav.glance',
    key: 'g g',
    label: 'Go to At a Glance',
    context: 'global',
    category: 'Navigation',
  });
  assert.equal(
    SHORTCUT_DEFAULTS.filter(item => item.key === shortcut.key && item.context === 'global').length,
    1,
  );
});
