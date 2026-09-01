import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const settingsSource = await readFile(
  new URL('../components/email/SwipeActionSettings.svelte', import.meta.url),
  'utf8',
);
const bulkSource = await readFile(
  new URL('../components/email/InboxBulkActionBar.svelte', import.meta.url),
  'utf8',
);
const inboxSource = await readFile(new URL('../pages/Inbox.svelte', import.meta.url), 'utf8');
const listSource = await readFile(
  new URL('../components/email/EmailList.svelte', import.meta.url),
  'utf8',
);
const tableSource = await readFile(
  new URL('../components/email/EmailTable.svelte', import.meta.url),
  'utf8',
);
const shortcutSource = await readFile(new URL('./shortcutDefaults.js', import.meta.url), 'utf8');

test('swipe settings is an accessible callback-only modal with exact defaults', () => {
  for (const contract of [
    'role="dialog"',
    'aria-modal="true"',
    "event.key === 'Escape'",
    "event.key !== 'Tab'",
    'restoreFocus()',
    'Swipe left defaults to Archive; swipe right defaults to Snooze.',
    'onsave?.(next)',
    'min-h-11',
  ]) {
    assert.match(settingsSource, new RegExp(contract.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')));
  }
  assert.doesNotMatch(settingsSource, /from ['"]\.\.\/\.\.\/lib\/api\.js/);
  assert.doesNotMatch(settingsSource, /localStorage|sessionStorage/);
});

test('bulk bar is mobile-sticky, touch-sized, callback-driven, and can hide snooze', () => {
  for (const contract of [
    'role="toolbar"',
    'position: sticky',
    'env(safe-area-inset-bottom)',
    'min-h-11',
    'onaction?.(detail)',
    "showSnooze || action.id !== 'snooze'",
    'onclear?.()',
  ]) {
    assert.match(bulkSource, new RegExp(contract.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')));
  }
  assert.doesNotMatch(bulkSource, /from ['"]\.\.\/\.\.\/lib\/api\.js/);
  assert.doesNotMatch(bulkSource, /localStorage|sessionStorage/);
});

test('Inbox owns one session-scoped selection across list and table layouts', () => {
  for (const contract of [
    'createInboxSelectionModel()',
    'selectedIds={triageSelectedIds}',
    'onToggleSelection={toggleTriageSelection}',
    'onClearSelection={clearTriageSelection}',
    'reconcileTriageSelection(snapshot.key, result.emails)',
    'selectedCount={triageSelectionSnapshot.size}',
  ]) {
    assert.match(inboxSource, new RegExp(contract.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')));
  }
  assert.match(tableSource, /onSelectLoaded\?\.\(\)/);
  assert.match(listSource, /onToggleSelection\?\.\(id, \{ range: Boolean\(event\.shiftKey\) \}\)/);
});

test('touch triage is limited to authoritative Inbox rows with safe visible alternatives', () => {
  for (const contract of [
    '&& swipePreferencesAvailable',
    'swipe_left_action: next.left',
    'swipe_right_action: next.right',
    'showSnooze={false}',
    'onSwipeAction={runSwipeTriageAction}',
    'spamMode={triageSelectedSpamState',
    'trashMode={triageSelectedTrashState',
  ]) {
    assert.ok(inboxSource.includes(contract), contract);
  }
  for (const contract of [
    'data-triage-row-id={email.id}',
    'data-swipe-state="idle"',
    'data-swipe-action="none"',
    'aria-selected={selectedIds.has(email.id)}',
    'data-swipe-surface',
    'aria-label="Actions for {cleanEmailText(email.subject) || \'No subject\'}"',
    'touch-action: pan-y',
  ]) {
    assert.ok(listSource.includes(contract), contract);
  }
  for (const action of ['inbox.toggleSelection', 'inbox.selectLoaded', 'inbox.clearSelection', 'inbox.swipeSettings']) {
    assert.ok(shortcutSource.includes(action), action);
  }
  assert.ok(tableSource.includes('data-triage-row-id={email.id}'));
  assert.ok(tableSource.includes('aria-selected={selectedIds.has(email.id)}'));
  assert.ok(bulkSource.includes('data-triage-bulk-bar'));
});
