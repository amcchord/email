import assert from 'node:assert/strict';
import test from 'node:test';

const storageValues = new Map([
  ['pageSize', '50'],
  ['viewMode', 'column'],
  ['hideIgnored', 'false'],
  ['threadOrder', 'newest_first'],
  ['calendarView', 'week'],
  ['composeLocalDraftV1', 'unsafe-v1'],
  ['composeLocalDraftV2:new', 'unsafe-v2'],
  ['composeLastAccountId', '44'],
  ['composeLocalDraftV3:user:401:new', 'safe-v3'],
]);

globalThis.localStorage = {
  get length() { return storageValues.size; },
  getItem(key) { return storageValues.get(key) ?? null; },
  key(index) { return [...storageValues.keys()][index] ?? null; },
  removeItem(key) { storageValues.delete(key); },
  setItem(key, value) { storageValues.set(key, String(value)); },
};

const { get } = await import('svelte/store');
const stores = await import('./stores.js');
const shortcuts = await import('./shortcutStore.js');

test('identity changes clear user-owned state and retain local display preferences', () => {
  stores.transitionAuthenticatedSession(null);
  const firstSession = stores.transitionAuthenticatedSession({ id: 401, username: 'generated-a' });

  stores.currentPage.set('todos');
  stores.currentMailbox.set('SENT');
  stores.selectedEmailId.set(81);
  stores.selectedThreadId.set('thread-a');
  stores.emails.set([{ id: 81, subject: 'Generated A' }]);
  stores.emailsLoading.set(true);
  stores.emailsTotal.set(1);
  stores.currentPageNum.set(4);
  stores.accounts.set([{ id: 91, email: 'generated-a@example.test' }]);
  stores.accountsLoaded.set(true);
  stores.accountsLoadError.set('old failure');
  stores.labels.set([{ id: 61, name: 'Generated A label' }]);
  stores.selectedAccountId.set(91);
  stores.syncStatus.set([{ id: 91 }]);
  stores.composeOpen.set(true);
  stores.composeData.set({ subject: 'Generated A draft' });
  stores.pendingReplyDraft.set({ emailId: 81 });
  stores.searchQuery.set('from:generated-a@example.test');
  stores.smartFilter.set({ type: 'needs_reply' });
  stores.todos.set([{ id: 71, title: 'Generated A todo' }]);
  stores.chatConversations.set([{ id: 72, title: 'Generated A chat' }]);
  stores.currentConversationId.set(72);
  stores.calendarDate.set(new Date('2026-01-02T00:00:00Z'));
  stores.calendarEvents.set([{ id: 73, summary: 'Generated A event' }]);
  stores.calendarLoading.set(true);
  stores.showToast('Generated A toast', 'info', 0);
  shortcuts.userOverrides.set({ 'nav.inbox': 'x' });
  shortcuts.overridesLoaded.set(true);
  shortcuts.overlayVisible.set(true);
  shortcuts.helpModalOpen.set(true);
  shortcuts.commandPaletteOpen.set(true);
  const cleanupAction = shortcuts.registerActions({ 'generated.action': () => true });

  stores.pageSize.set(75);
  stores.viewMode.set('table');
  stores.sidebarCollapsed.set(true);
  stores.hideIgnored.set(true);
  stores.threadOrder.set('oldest_first');
  stores.calendarView.set('month');

  const sameSession = stores.transitionAuthenticatedSession({ id: 401, username: 'generated-a-updated' });
  assert.equal(sameSession.generation, firstSession.generation);
  assert.equal(get(stores.emails).length, 1);

  const oldGuard = stores.createAuthenticatedSessionGuard();
  const secondSession = stores.transitionAuthenticatedSession({ id: 402, username: 'generated-b' });

  assert.equal(secondSession.userId, '402');
  assert.equal(get(stores.user).id, 402);
  assert.equal(oldGuard.isCurrent(), false);
  assert.equal(get(stores.authenticatedSessionGeneration), secondSession.generation);
  assert.equal(get(stores.currentPage), 'flow');
  assert.equal(get(stores.currentMailbox), 'INBOX');
  assert.equal(get(stores.selectedEmailId), null);
  assert.equal(get(stores.selectedThreadId), null);
  assert.deepEqual(get(stores.emails), []);
  assert.equal(get(stores.emailsLoading), false);
  assert.equal(get(stores.emailsTotal), 0);
  assert.equal(get(stores.currentPageNum), 1);
  assert.deepEqual(get(stores.accounts), []);
  assert.equal(get(stores.accountsLoaded), false);
  assert.equal(get(stores.accountsLoadError), '');
  assert.deepEqual(get(stores.labels), []);
  assert.equal(get(stores.selectedAccountId), null);
  assert.deepEqual(get(stores.syncStatus), []);
  assert.equal(get(stores.composeOpen), false);
  assert.equal(get(stores.composeData), null);
  assert.equal(get(stores.pendingReplyDraft), null);
  assert.equal(get(stores.searchQuery), '');
  assert.equal(get(stores.smartFilter), null);
  assert.deepEqual(get(stores.todos), []);
  assert.deepEqual(get(stores.chatConversations), []);
  assert.equal(get(stores.currentConversationId), null);
  assert.deepEqual(get(stores.calendarEvents), []);
  assert.equal(get(stores.calendarLoading), false);
  assert.deepEqual(get(stores.toastMessages), []);
  assert.deepEqual(get(shortcuts.userOverrides), {});
  assert.equal(get(shortcuts.overridesLoaded), false);
  assert.equal(get(shortcuts.overlayVisible), false);
  assert.equal(get(shortcuts.helpModalOpen), false);
  assert.equal(get(shortcuts.commandPaletteOpen), false);
  assert.equal(shortcuts.hasHandler('generated.action'), false);

  assert.equal(get(stores.pageSize), 75);
  assert.equal(get(stores.viewMode), 'table');
  assert.equal(get(stores.sidebarCollapsed), true);
  assert.equal(get(stores.hideIgnored), true);
  assert.equal(get(stores.threadOrder), 'oldest_first');
  assert.equal(get(stores.calendarView), 'month');

  assert.equal(storageValues.has('composeLocalDraftV1'), false);
  assert.equal(storageValues.has('composeLocalDraftV2:new'), false);
  assert.equal(storageValues.has('composeLastAccountId'), false);
  assert.equal(storageValues.get('composeLocalDraftV3:user:401:new'), 'safe-v3');

  cleanupAction();
  stores.transitionAuthenticatedSession(null);
});

test('disposing a current session guard blocks later writes without changing identity', () => {
  stores.transitionAuthenticatedSession({ id: 411, username: 'generated-c' });
  const guard = stores.createAuthenticatedSessionGuard();
  assert.equal(guard.isCurrent(), true);
  guard.dispose();
  assert.equal(guard.isCurrent(), false);
  stores.transitionAuthenticatedSession(null);
});
