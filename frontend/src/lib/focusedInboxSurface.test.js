import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';

const source = relative => fs.readFileSync(new URL(relative, import.meta.url), 'utf8');

test('Split Inbox loads two authoritative sections without the legacy exclusion filter', () => {
  const inbox = source('../pages/Inbox.svelte');
  assert.match(inbox, /inbox_placement: 'focused'/);
  assert.match(inbox, /inbox_placement: 'other'/);
  assert.match(inbox, /Promise\.all/);
  assert.match(inbox, /combineInboxSections/);
  assert.doesNotMatch(inbox, /params\.exclude_ai_category/);
});

test('Split Inbox stays explainable and keyboard navigable in both layouts', () => {
  const list = source('../components/email/EmailList.svelte');
  const table = source('../components/email/EmailTable.svelte');
  const inbox = source('../pages/Inbox.svelte');
  for (const component of [list, table]) {
    assert.match(component, /data-inbox-section="focused"/);
    assert.match(component, /data-inbox-section="other"/);
    assert.match(component, /still in Inbox/);
    assert.match(component, /placementReasonLabel/);
  }
  assert.match(inbox, /'inbox\.nextSection'/);
  assert.match(inbox, /'inbox\.prevSection'/);
  assert.match(inbox, /nextInboxSectionFocus/);
});

test('the TopBar control exposes state and never claims to move provider mail', () => {
  const topBar = source('../components/layout/TopBar.svelte');
  assert.match(topBar, /aria-pressed=\{splitInboxActive\}/);
  assert.match(topBar, /No mail is moved in Gmail/);
  assert.match(topBar, /Split Inbox is available in the standard Inbox/);
  assert.match(topBar, /disabled=\{!splitInboxAvailable\}/);
});
