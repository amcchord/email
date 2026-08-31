import { get } from 'svelte/store';
import { api } from './api.js';
import {
  activeSavedViewId,
  accounts,
  createAuthenticatedSessionGuard,
  currentMailbox,
  currentPage,
  savedViewEditorRequest,
  savedViews,
  savedViewsError,
  savedViewsLoaded,
  savedViewsLoading,
  savedViewsMax,
  searchQuery,
  selectedAccountId,
  sidebarCollapsed,
  smartFilter,
} from './stores.js';
import { normalizeSavedViewsResponse } from './savedViews.js';

export async function refreshSavedViews(sessionGuard = createAuthenticatedSessionGuard()) {
  savedViewsLoading.set(true);
  savedViewsError.set('');
  try {
    const normalized = normalizeSavedViewsResponse(await api.listSavedViews());
    if (!sessionGuard.isCurrent()) return false;
    savedViews.set([...normalized.items]);
    savedViewsMax.set(normalized.max_views);
    savedViewsLoaded.set(true);
    return true;
  } catch (error) {
    if (sessionGuard.isCurrent()) {
      savedViewsError.set(error?.message || 'Saved Views could not be loaded.');
      savedViewsLoaded.set(false);
    }
    return false;
  } finally {
    if (sessionGuard.isCurrent()) savedViewsLoading.set(false);
  }
}

export function openSavedView(view) {
  if (!view) return;
  if (view.account_id !== null && !get(accounts).some(account => account.id === view.account_id)) {
    throw new Error('Reconnect this Saved View account before opening it.');
  }
  // Svelte batches these synchronous writes before Inbox effects run. Account,
  // query, and mailbox therefore become one authoritative dataset snapshot.
  activeSavedViewId.set(view.id);
  selectedAccountId.set(view.account_id);
  currentMailbox.set('ALL');
  smartFilter.set(null);
  searchQuery.set(view.query);
  currentPage.set('inbox');
  if (typeof window !== 'undefined' && window.matchMedia('(max-width: 767px)').matches) {
    sidebarCollapsed.set(true);
  }
}

export function requestSavedViewEditor({ mode = 'create', viewId = null, useCurrentSearch = mode === 'create' } = {}) {
  savedViewEditorRequest.set({
    request_id: `${Date.now()}:${Math.random()}`,
    mode,
    view_id: viewId,
    ...(useCurrentSearch ? {
      account_id: get(selectedAccountId),
      query: get(searchQuery),
    } : {}),
  });
}
