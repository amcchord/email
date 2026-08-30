import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';

const read = path => fs.readFileSync(new URL(path, import.meta.url), 'utf8');

test('universal snooze is discoverable across sidebar, inbox rows, reader, Flow, and commands', () => {
  const sidebar = read('../components/layout/Sidebar.svelte');
  const inbox = read('../pages/Inbox.svelte');
  const list = read('../components/email/EmailList.svelte');
  const table = read('../components/email/EmailTable.svelte');
  const reader = read('../components/email/EmailView.svelte');
  const flow = read('../pages/Flow.svelte');
  const shortcuts = read('./shortcutDefaults.js');

  assert.match(sidebar, /label: 'Snoozed'/);
  assert.match(sidebar, /aria-label=\{mb\.label\}/);
  assert.match(inbox, /<SnoozePicker/);
  assert.match(inbox, /actionLabel: 'Undo'/);
  assert.match(inbox, /Return now/);
  assert.match(inbox, /Cancel reminder/);
  assert.match(list, /onSnooze\(email\)/);
  assert.match(table, /Snooze conversation/);
  assert.match(reader, /Snooze email and remind me later/);
  assert.match(flow, /api\.listSnoozes\(\{ state: 'active'/);
  assert.match(flow, /<SnoozePicker/);
  assert.match(shortcuts, /id: 'inbox\.snooze',\s+key: 'h'/);
  assert.match(shortcuts, /id: 'flow\.snooze',\s+key: 'h'/);
});

test('picker provides modal focus, Escape/native close, DST-safe custom time, and narrow layout', () => {
  const picker = read('../components/common/SnoozePicker.svelte');
  assert.match(picker, /showModal/);
  assert.match(picker, /data-first-choice/);
  assert.match(picker, /onclose=\{handleClose\}/);
  assert.match(picker, /resolveLocalSchedule/);
  assert.match(picker, /Only if nobody replies/);
  assert.match(picker, /max-height: min\(92dvh/);
  assert.match(picker, /role="alert"/);
});
