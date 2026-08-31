import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';

const source = relative => fs.readFileSync(new URL(relative, import.meta.url), 'utf8');

test('regular Inbox and search use server-paginated conversations', () => {
  const inbox = source('../pages/Inbox.svelte');
  assert.match(inbox, /api\.listConversations\(params\)/);
  assert.match(inbox, /normalizeConversationList/);
  assert.match(inbox, /snapshot\.mailbox !== 'DRAFTS'/);
  assert.match(inbox, /api\.getThread\(threadId, 'asc', summary\.account_id\)/);
  assert.match(inbox, /context\.scope/);
  assert.match(inbox, /String\(summary\?\.gmail_thread_id \|\| ''\)\.trim\(\)/);
  assert.match(inbox, /activeSnoozesExcludedByServer/);
  assert.match(inbox, /listRequests\.invalidate\(\)[\s\S]*currentPageNum\.set\(1\)/);
  assert.match(inbox, /requireActionReconciliation\(context\.datasetKey, context\.optimistic\.removed\)/);
});

test('list and table expose one aggregate conversation row with conversation bulk copy', () => {
  for (const relative of ['../components/email/EmailList.svelte', '../components/email/EmailTable.svelte']) {
    const component = source(relative);
    assert.match(component, /email\.member_count/);
    assert.match(component, /email\.star_state === 'some'/);
    assert.match(component, /label\.coverage === 'some'/);
    assert.match(component, /conversations selected/);
    assert.match(component, /!email\.conversation_scope && email\.thread_digest_type/);
  }
});

test('conversation reader is chronological, account-safe, and keeps message controls touch sized', () => {
  const reader = source('../components/email/ConversationView.svelte');
  assert.match(reader, /chronological/);
  assert.match(reader, /min-h-11/);
  assert.match(reader, /defaultThreadMessageId/);
  assert.match(reader, /onAction\?\.\(action, \[conversation\.id\]\)/);
});

test('Inbox distinguishes row focus from opening and restores focus on close', () => {
  const inbox = source('../pages/Inbox.svelte');
  assert.match(inbox, /let focusedEmailId = \$state\(null\)/);
  assert.match(inbox, /openFocusedEmail/);
  assert.match(inbox, /handleRowFocus/);
  assert.match(inbox, /focusEmailRow\(document\.querySelector\('\.inbox-page'\), returnId\)/);
});
