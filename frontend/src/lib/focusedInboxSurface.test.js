import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';

const source = relative => fs.readFileSync(new URL(relative, import.meta.url), 'utf8');

test('Split Inbox loads one coherent two-section response without the legacy exclusion filter', () => {
  const inbox = source('../pages/Inbox.svelte');
  const api = source('./api.js');
  assert.match(inbox, /api\.listConversationSplit/);
  assert.match(api, /emails\/conversations\/split/);
  assert.match(inbox, /combineInboxSections/);
  assert.match(inbox, /totals did not match the coherent response/);
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
    assert.match(component, /placementProvenanceLabel/);
    assert.match(component, /Teach Split Inbox for this conversation/);
    assert.match(component, /onManageSplitRules/);
  }
  assert.match(inbox, /'inbox\.nextSection'/);
  assert.match(inbox, /'inbox\.prevSection'/);
  assert.match(inbox, /nextInboxSectionFocus/);
  assert.match(inbox, /'inbox\.teachSplit'/);
  assert.match(inbox, /'inbox\.manageSplitRules'/);
  assert.match(inbox, /InboxRulePicker/);
  assert.match(inbox, /InboxRuleManager/);
});

test('rule mutations refetch the coherent split and expose typed Undo', () => {
  const inbox = source('../pages/Inbox.svelte');
  const picker = source('../components/email/InboxRulePicker.svelte');
  const manager = source('../components/email/InboxRuleManager.svelte');
  assert.match(inbox, /refreshAfterInboxRuleChange/);
  assert.match(inbox, /inboxRuleManagerRefreshToken \+= 1/);
  assert.match(inbox, /inboxRuleUndoOperation/);
  assert.match(inbox, /Undo rule change/);
  assert.match(inbox, /Focused and Other counts refreshed/);
  for (const dialog of [picker, manager]) {
    assert.match(dialog, /aria-modal="true"/);
    assert.match(dialog, /event\.key === 'Escape'/);
    assert.match(dialog, /event\.key !== 'Tab'/);
    assert.match(dialog, /isAuthenticatedSessionCurrent/);
    assert.match(dialog, /Gmail is unchanged/);
  }
  assert.match(picker, /exact account/i);
  assert.match(picker, /createId \|\| newInboxRuleCreateId/);
  assert.match(picker, /if \(saving && !force\) return/);
  assert.match(picker, /Reload latest choices/);
  assert.match(manager, /Filter rules by account/);
  assert.match(manager, /nextRefreshToken !== observedRefreshToken/);
  assert.match(manager, /if \(busyRuleId\) return/);
  assert.match(manager, /Reload latest rules/);
  assert.match(manager, /Delete this exact-account rule/);
});

test('the TopBar control exposes state and never claims to move provider mail', () => {
  const topBar = source('../components/layout/TopBar.svelte');
  assert.match(topBar, /aria-pressed=\{splitInboxActive\}/);
  assert.match(topBar, /No mail is moved in Gmail/);
  assert.match(topBar, /Split Inbox is available in the standard Inbox/);
  assert.match(topBar, /disabled=\{!splitInboxAvailable\}/);
});
