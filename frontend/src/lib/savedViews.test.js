import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

import {
  createSavedViewPayload,
  isSavableStructuredSearch,
  normalizeSavedViewsResponse,
  reorderSavedViewsPayload,
  replaceSavedViewPayload,
  savedViewMatches,
} from './savedViews.js';

const FIRST_ID = '10000000-0000-4000-8000-000000000001';
const SECOND_ID = '20000000-0000-4000-8000-000000000002';

function view(overrides = {}) {
  return {
    id: FIRST_ID,
    create_id: '30000000-0000-4000-8000-000000000003',
    name: 'Leadership mail',
    account_id: 7,
    query: 'from:leader@example.test is:unread',
    revision: 2,
    position: 0,
    created_at: '2026-08-31T12:00:00Z',
    updated_at: '2026-08-31T12:01:00Z',
    ...overrides,
  };
}

test('Saved Views collection normalization is strict, bounded, and position ordered', () => {
  const normalized = normalizeSavedViewsResponse({
    items: [
      view({ id: SECOND_ID, create_id: '40000000-0000-4000-8000-000000000004', name: 'Second', position: 1 }),
      view(),
    ],
    max_views: 12,
  });

  assert.deepEqual(normalized.items.map(item => item.id), [FIRST_ID, SECOND_ID]);
  assert.equal(Object.isFrozen(normalized.items[0]), true);
  assert.throws(() => normalizeSavedViewsResponse({ items: [view()], max_views: 13 }), /max_views/);
  assert.throws(() => normalizeSavedViewsResponse({ items: [view(), view()], max_views: 12 }), /duplicate/);
  assert.throws(() => normalizeSavedViewsResponse({ items: [view({ account_id: '7' })], max_views: 12 }), /account/);
  assert.throws(() => normalizeSavedViewsResponse({ items: [view({ query: 'from:' })], max_views: 12 }), /structured|Search|value/i);
});

test('create, replace, and reorder payloads expose only the frozen API fields', () => {
  assert.deepEqual(createSavedViewPayload({
    createId: FIRST_ID,
    name: '  Leadership   mail ',
    accountId: 7,
    query: ' from:leader@example.test ',
  }), {
    create_id: FIRST_ID,
    name: 'Leadership mail',
    account_id: 7,
    query: 'from:leader@example.test',
  });
  assert.deepEqual(replaceSavedViewPayload({
    revision: 4,
    name: 'Team',
    accountId: null,
    query: 'label:team',
  }), {
    revision: 4,
    name: 'Team',
    account_id: null,
    query: 'label:team',
  });

  const items = [view(), view({ id: SECOND_ID, create_id: '40000000-0000-4000-8000-000000000004', position: 1 })];
  assert.deepEqual(reorderSavedViewsPayload(items, [SECOND_ID, FIRST_ID]), {
    expected_order: [FIRST_ID, SECOND_ID],
    view_ids: [SECOND_ID, FIRST_ID],
  });
  assert.throws(() => reorderSavedViewsPayload(items, [FIRST_ID, FIRST_ID]), /exactly once/);
});

test('active matching is exact account plus exact private query and invalid searches cannot save', () => {
  const item = view();
  assert.equal(savedViewMatches(item, 7, item.query), true);
  assert.equal(savedViewMatches(item, null, item.query), false);
  assert.equal(savedViewMatches(item, 7, 'from:other@example.test'), false);
  assert.equal(isSavableStructuredSearch('from:leader@example.test'), true);
  assert.equal(isSavableStructuredSearch(''), false);
  assert.equal(isSavableStructuredSearch('from:'), false);
});

test('Saved Views surfaces stay in Email navigation, reset with auth, and keep private queries out of URLs', async () => {
  const [sidebar, state, summary, palette, shortcuts, stores, api] = await Promise.all([
    readFile(new URL('../components/layout/Sidebar.svelte', import.meta.url), 'utf8'),
    readFile(new URL('./savedViewState.js', import.meta.url), 'utf8'),
    readFile(new URL('../components/email/EmailSearchSummary.svelte', import.meta.url), 'utf8'),
    readFile(new URL('../components/common/CommandPalette.svelte', import.meta.url), 'utf8'),
    readFile(new URL('./shortcutDefaults.js', import.meta.url), 'utf8'),
    readFile(new URL('./stores.js', import.meta.url), 'utf8'),
    readFile(new URL('./api.js', import.meta.url), 'utf8'),
  ]);
  assert.match(sidebar, /<SavedViews/);
  assert.match(state, /selectedAccountId\.set\(view\.account_id\)[\s\S]*searchQuery\.set\(view\.query\)[\s\S]*currentPage\.set\('inbox'\)/);
  assert.doesNotMatch(state, /URLSearchParams|history\.|location\./);
  assert.match(summary, /Save changes/);
  assert.match(palette, /saved-view:/);
  assert.match(shortcuts, /nav\.savedViews'[\s\S]*key: 'g v'/);
  assert.match(stores, /savedViews\.set\(\[\]\)[\s\S]*savedViewEditorRequest\.set\(null\)/);
  assert.match(api, /listSavedViews:[\s\S]*'GET', '\/saved-views'/);
  assert.match(api, /deleteSavedView:[\s\S]*revision: String\(revision\)/);
});

test('conflict reload closes and clears the stale editor before refreshing authority', async () => {
  const surface = await readFile(
    new URL('../components/email/SavedViews.svelte', import.meta.url),
    'utf8',
  );
  assert.match(surface, /function recoverFromConflict\(\)[\s\S]*closeEditor\(\);[\s\S]*refreshSavedViews\(\)/);
  assert.match(surface, /function closeEditor\(\)[\s\S]*editingId = null;[\s\S]*draftName = '';[\s\S]*draftQuery = '';[\s\S]*confirmingDelete = false;/);
  assert.match(surface, /onclick=\{recoverFromConflict\}>Reload Saved Views/);
  assert.doesNotMatch(surface, /Reload Saved Views<\/button>[\s\S]{0,80}refreshSavedViews/);
});

test('the editor disables its transformed Sidebar containing block while open', async () => {
  const surface = await readFile(
    new URL('../components/email/SavedViews.svelte', import.meta.url),
    'utf8',
  );
  assert.match(surface, /if \(!dialogOpen\) return;[\s\S]*sidebar\.classList\.add\('saved-view-editor-owner'\)/);
  assert.match(surface, /sidebar\.classList\.remove\('saved-view-editor-owner'\)/);
  assert.match(surface, /mail-sidebar\.saved-view-editor-owner[\s\S]*transform: none !important;[\s\S]*pointer-events: auto !important/);
  assert.equal((surface.match(/class="saved-view-layer"/g) || []).length, 1);
});

test('successful delete discards stale positions and revisions before authoritative refresh', async () => {
  const surface = await readFile(
    new URL('../components/email/SavedViews.svelte', import.meta.url),
    'utf8',
  );
  assert.match(surface, /await api\.deleteSavedView[\s\S]*savedViews\.set\(\[\]\);[\s\S]*savedViewsLoaded\.set\(false\);[\s\S]*await refreshSavedViews\(session\)/);
  assert.doesNotMatch(surface, /deleteSavedView[\s\S]{0,300}savedViews\.update\(items => items\.filter/);
});
