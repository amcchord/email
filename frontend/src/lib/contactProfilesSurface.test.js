import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const read = relative => readFile(new URL(relative, import.meta.url), 'utf8');

const [page, api, routes, shortcuts, topbar, layout, inbox, stores, palette, keyboard] = await Promise.all([
  read('../pages/Contacts.svelte'),
  read('./api.js'),
  read('./lazyRoutes.js'),
  read('./shortcutDefaults.js'),
  read('../components/layout/TopBar.svelte'),
  read('../components/layout/Layout.svelte'),
  read('../pages/Inbox.svelte'),
  read('./stores.js'),
  read('../components/common/CommandPalette.svelte'),
  read('../components/common/KeyboardShortcutHandler.svelte'),
]);

test('Contacts is first in More, lazy-loaded, and command-palette navigable with G P', () => {
  assert.match(routes, /contacts: Object\.freeze\(\{ label: 'Contacts', load: \(\) => import\('\.\.\/pages\/Contacts\.svelte'\) \}\)/);
  assert.match(topbar, /const secondaryTabs = \[\s*\{ id: 'contacts', label: 'Contacts', icon: 'users' \}/);
  assert.match(layout, /'nav\.contacts': \(\) => navigateByShortcut\('contacts'\)/);
  assert.match(shortcuts, /id: 'nav\.contacts',[^\n]*key: 'g p'/);
  assert.match(palette, /contacts: 'contacts'/);
  assert.match(keyboard, /contacts: 'contacts'/);
});

test('Contacts owns exact account, debounced abortable search, filters, and complete states', () => {
  assert.match(page, /People observed in one connected account's recent synchronized mail/);
  assert.match(page, /Metadata only · no Contacts permission/);
  assert.match(page, /const relationshipOptions = Object\.freeze\(\[[\s\S]*bidirectional[\s\S]*inbound_only[\s\S]*outbound_only/);
  assert.match(page, /const controller = new AbortController\(\)/);
  assert.match(page, /const delay = requestedQuery \? 220 : 0/);
  assert.match(page, /createAuthenticatedSessionGuard\(\)/);
  assert.match(page, /normalizeContactQueryResponse\(response, \{ accountId \}\)/);
  assert.match(page, /No connected account/);
  assert.match(page, /Loading contacts/);
  assert.match(page, /Contacts unavailable/);
  assert.match(page, /No correspondents found/);
  assert.match(page, /older relationships may not appear/);
  assert.doesNotMatch(page, /<img|gravatar|https?:\/\//i);
});

test('Contacts provides list-detail mobile focus, keyboard, Compose, and exact conversation actions', () => {
  for (const action of ['contacts.next', 'contacts.prev', 'contacts.open', 'contacts.email', 'contacts.search', 'contacts.back']) {
    assert.match(page, new RegExp(`'${action.replace('.', '\\.')}'`));
  }
  assert.match(page, /profileRegion\?\.focus\(\{ preventScroll: true \}\)/);
  assert.match(page, /focusRow\(returnIndex\)/);
  assert.match(page, /composeData\.set\(contactComposeIntent\(contactAccountId, contact\)\)/);
  assert.match(page, /contactConversationIntent\.set\(intent\)/);
  assert.match(page, /selectedEmailId\.set\(intent\.anchor_email_id\)/);
  assert.match(page, /class:mobile-hidden=\{showingMobileProfile\}/);
  assert.match(page, /min-h-11|min-h-14|min-h-16/);
});

test('contact API and Inbox handoff stay POST-only, exact-account, off-page, and auth-reset', () => {
  assert.match(api, /queryContacts: \(payload, \{ signal \} = \{\}\) =>\s*request\('POST', '\/contacts\/query', payload, \{ signal \}\)/);
  assert.match(api, /getContactProfile: \(payload, \{ signal \} = \{\}\) =>\s*request\('POST', '\/contacts\/profile', payload, \{ signal \}\)/);
  assert.match(stores, /export const contactConversationIntent = writable\(null\)/);
  assert.equal((stores.match(/contactConversationIntent\.set\(null\)/g) || []).length, 1);
  assert.match(inbox, /exactContactIntent\?\.thread_id[\s\S]*api\.getThread\(exactContactIntent\.thread_id, 'asc', exactContactIntent\.account_id\)/);
  assert.match(inbox, /exactContactIntent[\s\S]*await api\.getEmail\(id\)/);
  assert.match(inbox, /contact conversation did not contain its exact anchor message/i);
  assert.match(inbox, /contactConversationIntent\.set\(null\)/);
  assert.match(inbox, /selectedReaderUsesThread = \$derived\(\s*Array\.isArray\(selectedThread\?\.emails\) && selectedThread\.emails\.length > 0/);
  assert.match(inbox, /selectedReaderConversation = \$derived\([\s\S]*isConversationSummary\(selectedListConversation\)[\s\S]*conversation_scope: false/);
  assert.equal((inbox.match(/\{#if selectedReaderUsesThread\}/g) || []).length, 2);
  assert.equal((inbox.match(/conversation=\{selectedReaderConversation\}/g) || []).length, 2);
});
