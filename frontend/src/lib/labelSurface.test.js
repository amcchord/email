import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';

const read = path => fs.readFileSync(new URL(path, import.meta.url), 'utf8');

test('labels and move are discoverable in commands, bulk surfaces, and reader', () => {
  const inbox = read('../pages/Inbox.svelte');
  const list = read('../components/email/EmailList.svelte');
  const table = read('../components/email/EmailTable.svelte');
  const reader = read('../components/email/EmailView.svelte');
  const shortcuts = read('./shortcutDefaults.js');
  const status = read('../components/email/MailActionStatus.svelte');

  assert.match(shortcuts, /id: 'inbox\.label',\s+key: 'l'/);
  assert.match(shortcuts, /id: 'inbox\.move',\s+key: 'v'/);
  assert.match(inbox, /<LabelPicker/);
  assert.match(inbox, /expandVisibleLabelTargets/);
  assert.match(inbox, /submitMailAction\(uniqueIds, action, requestKey, context\.labelId, context\.scope\)/);
  assert.match(list, /openBulkLabels\('apply'\)/);
  assert.match(list, /openBulkLabels\('move'\)/);
  assert.match(table, /openBulkLabels\('apply'\)/);
  assert.match(table, /openBulkLabels\('move'\)/);
  assert.match(reader, /Apply or remove label · L/);
  assert.match(reader, /Move out of Inbox to label · V/);
  assert.match(status, /move_to_label: 'move to label'/);
});

test('picker provides account-safe modal behavior and complete states', () => {
  const picker = read('../components/email/LabelPicker.svelte');
  const workflow = read('./labelWorkflows.js');
  assert.match(picker, /showModal/);
  assert.match(picker, /restoreFocus/);
  assert.match(picker, /oncancel=\{handleCancel\}/);
  assert.match(picker, /Search existing labels/);
  assert.match(picker, /Applies to all existing messages in the selected conversation/);
  assert.match(workflow, /Labels belong to one Gmail account/);
  assert.match(picker, /Loading labels/);
  assert.match(picker, /No user labels/);
  assert.match(picker, /Try again/);
  assert.match(picker, /max-height: 94dvh/);
  assert.match(picker, /claimLabelPickerKeyEvent/);
  assert.match(picker, /onkeyup=\{handleTrailingKeyEvent\}/);
  assert.match(picker, /onkeypress=\{handleTrailingKeyEvent\}/);
  assert.doesNotMatch(picker, /role=\{mode === 'move' \? 'radio'/);
  assert.doesNotMatch(picker, /radiogroup/);
});

test('mobile reader keeps actions in one scrollable rail with Close first', () => {
  const reader = read('../components/email/EmailView.svelte');
  assert.match(reader, /email-reader-header/);
  assert.match(reader, /email-reader-actions/);
  assert.match(reader, /overflow-x: auto/);
  assert.match(reader, /reader-close-action[\s\S]*order: -1/);
});

test('Move is rendered and accepted only for the active Inbox mailbox', () => {
  const inbox = read('../pages/Inbox.svelte');
  const list = read('../components/email/EmailList.svelte');
  const table = read('../components/email/EmailTable.svelte');
  const reader = read('../components/email/EmailView.svelte');
  const picker = read('../components/email/LabelPicker.svelte');

  assert.match(inbox, /moveAvailable = \$derived\([\s\S]*!\$searchQuery[\s\S]*!\$smartFilter[\s\S]*\$currentMailbox === 'INBOX'/);
  assert.match(inbox, /mode === 'move' && !moveAvailable/);
  assert.match(inbox, /if \(!moveAvailable\) return undefined;[\s\S]*registerActions\(\{[\s\S]*'inbox\.move'/);
  assert.match(inbox, /allowMove=\{moveAvailable\}/);
  assert.match(list, /\{#if allowMove\}[\s\S]*openBulkLabels\('move'\)/);
  assert.match(table, /\{#if allowMove\}[\s\S]*openBulkLabels\('move'\)/);
  assert.match(reader, /\{#if allowMove\}[\s\S]*Move out of Inbox to label/);
  assert.match(picker, /removes every current message[\s\S]*from Inbox/);
});

test('row-removing label actions have a selected-row or Inbox-root focus fallback', () => {
  const inbox = read('../pages/Inbox.svelte');
  const picker = read('../components/email/LabelPicker.svelte');
  assert.match(inbox, /optimistic\.removed[\s\S]*queueMicrotask\(focusInboxSelection\)/);
  assert.match(inbox, /focusEmailRowOrFallback\(inboxRoot, focusedEmailId \|\| get\(selectedEmailId\), inboxRoot\)/);
  assert.match(inbox, /onfocusfallback=\{focusInboxSelection\}/);
  assert.match(picker, /else onfocusfallback\?\.\(\)/);
});
