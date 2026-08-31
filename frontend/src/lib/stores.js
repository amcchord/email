import { writable, derived } from 'svelte/store';
import { clearToasts } from './toasts.js';
import { clearUnscopedComposeStorage } from './composeDraft.js';
import { resetShortcutSessionState } from './shortcutStore.js';
import { stopRealtime } from './realtime.js';
import {
  captureAuthEpoch,
  isAuthEpochCurrent,
  transitionAuthEpoch,
} from './authSession.js';
export { toastMessages, showToast, dismissToast, clearToasts } from './toasts.js';

// Auth state
export const user = writable(null);
export const isAuthenticated = derived(user, ($user) => $user !== null);
export const authenticatedSessionGeneration = writable(0);

// Navigation
export const currentPage = writable('flow');
export const currentMailbox = writable('INBOX');
export const selectedEmailId = writable(null);
export const selectedThreadId = writable(null);
// One-shot, account-authoritative handoff from Contacts to Inbox. It is
// intentionally session memory only and is cleared on every auth transition.
export const contactConversationIntent = writable(null);
// One-shot, account-authoritative handoff from Attachments to Inbox. It keeps
// private library filters out of URLs and is cleared at every auth transition.
export const attachmentParentIntent = writable(null);
// Session-only Saved Views state. Queries are deliberately never mirrored to
// URLs or browser storage and are purged at every authenticated transition.
export const savedViews = writable([]);
export const savedViewsLoading = writable(false);
export const savedViewsLoaded = writable(false);
export const savedViewsError = writable('');
export const savedViewsMax = writable(12);
export const activeSavedViewId = writable(null);
export const savedViewEditorRequest = writable(null);
export const savedViewFocusRequest = writable(0);

// Email state
export const emails = writable([]);
export const emailsLoading = writable(false);
export const emailsTotal = writable(0);
export const currentPageNum = writable(1);
export const pageSize = writable(parseInt(localStorage.getItem('pageSize') || '50', 10));

// Accounts
export const accounts = writable([]);
export const accountsLoaded = writable(false);
export const accountsLoadError = writable('');
export const selectedAccountId = writable(null);

// Deterministic color palette for distinguishing accounts
export const ACCOUNT_COLORS = [
  { bg: '#3b82f6', light: '#dbeafe', label: 'blue' },
  { bg: '#8b5cf6', light: '#ede9fe', label: 'violet' },
  { bg: '#ec4899', light: '#fce7f3', label: 'pink' },
  { bg: '#f97316', light: '#ffedd5', label: 'orange' },
  { bg: '#10b981', light: '#d1fae5', label: 'emerald' },
  { bg: '#06b6d4', light: '#cffafe', label: 'cyan' },
];

// Derived map: account email/id -> assigned color (stable order by email)
export const accountColorMap = derived(accounts, ($accounts) => {
  const map = {};
  if (!$accounts || $accounts.length === 0) return map;
  const sorted = [...$accounts].sort((a, b) => a.email.localeCompare(b.email));
  sorted.forEach((acct, idx) => {
    const color = ACCOUNT_COLORS[idx % ACCOUNT_COLORS.length];
    map[acct.email] = color;
    map[acct.id] = color;
  });
  return map;
});

// Labels
export const labels = writable([]);

// Sync status
export const syncStatus = writable([]);  // Array of account objects with sync_status
let syncPollInterval = null;
let syncPollFn = null;
let syncPollFast = false;  // true when actively syncing (3s), false when idle (30s)
let syncPollGeneration = 0;

export function startSyncPolling(apiFn) {
  stopSyncPolling({ clearAuthority: false });
  const generation = syncPollGeneration;
  let inFlightPromise = null;
  accountsLoadError.set('');

  function poll() {
    if (inFlightPromise) return inFlightPromise;
    inFlightPromise = (async () => {
      try {
        const accountList = await apiFn();
        if (generation !== syncPollGeneration) return null;
        syncStatus.set(accountList);
        accounts.set(accountList);
        accountsLoaded.set(true);
        accountsLoadError.set('');

        // Adaptive polling: fast during active sync, slow when idle
        const anySyncing = accountList.some(
          a => a.sync_status && a.sync_status.status === 'syncing'
        );
        if (anySyncing && !syncPollFast) {
          syncPollFast = true;
          clearInterval(syncPollInterval);
          syncPollInterval = setInterval(poll, 3000);
        } else if (!anySyncing && syncPollFast) {
          syncPollFast = false;
          clearInterval(syncPollInterval);
          syncPollInterval = setInterval(poll, 30000);
        }
        return accountList;
      } catch (error) {
        if (generation === syncPollGeneration) {
          accountsLoadError.set(error?.message || 'Connected accounts could not be loaded.');
        }
        return null;
      } finally {
        if (generation === syncPollGeneration) inFlightPromise = null;
      }
    })();
    return inFlightPromise;
  }
  syncPollFn = poll;
  void poll();
  syncPollInterval = setInterval(poll, 30000);
}

export function stopSyncPolling({ clearAuthority = true } = {}) {
  syncPollGeneration += 1;
  if (syncPollInterval) {
    clearInterval(syncPollInterval);
    syncPollInterval = null;
  }
  syncPollFn = null;
  syncPollFast = false;
  if (clearAuthority) {
    syncStatus.set([]);
    accounts.set([]);
    accountsLoaded.set(false);
    accountsLoadError.set('');
    selectedAccountId.set(null);
  }
}

// Force an immediate poll (e.g. after triggering a sync)
export function forceSyncPoll() {
  return syncPollFn?.() || Promise.resolve(null);
}

// Derived sync state -- multi-account aware
export const overallSyncState = derived(syncStatus, ($syncStatus) => {
  const empty = { state: 'idle', message: 'No accounts', accounts: [],
    retryAfter: null, syncingCount: 0, rateLimitedCount: 0, errorCount: 0,
    calendarIssueCount: 0, idleCount: 0, totalCount: 0 };
  if (!$syncStatus || $syncStatus.length === 0) return empty;

  const total = $syncStatus.length;
  let syncingCount = 0;
  let rateLimitedCount = 0;
  let errorCount = 0;
  let calendarIssueCount = 0;
  let idleCount = 0;
  let soonestRetry = null;

  for (const a of $syncStatus) {
    const calendar = a.calendar_sync_status;
    if (!a.has_calendar_scope || calendar?.needs_reauth || calendar?.status === 'error') {
      calendarIssueCount++;
    }
    const s = a.sync_status;
    if (!s) { idleCount++; continue; }
    if (s.status === 'syncing') { syncingCount++; }
    else if (s.status === 'rate_limited') {
      rateLimitedCount++;
      if (s.retry_after) {
        const ra = new Date(s.retry_after);
        if (!soonestRetry || ra < soonestRetry) soonestRetry = ra;
      }
    }
    else if (s.status === 'error') { errorCount++; }
    else { idleCount++; }
  }

  const counts = { syncingCount, rateLimitedCount, errorCount, calendarIssueCount, idleCount, totalCount: total };

  // Determine the overall state and message.
  // Priority: syncing > mixed issues > rate_limited > error > idle

  // Any account actively syncing -- that's the primary indicator
  if (syncingCount > 0) {
    let message = 'Syncing';
    if (total > 1) {
      message = `Syncing ${syncingCount} of ${total} accounts`;
    }
    return { state: 'syncing', message, accounts: $syncStatus, retryAfter: null, ...counts };
  }

  // All accounts healthy
  if (rateLimitedCount === 0 && errorCount === 0 && calendarIssueCount === 0) {
    let lastSync = null;
    for (const a of $syncStatus) {
      if (!a.sync_status) continue;
      const inc = a.sync_status.last_incremental_sync;
      const full = a.sync_status.last_full_sync;
      const latest = inc || full;
      if (latest) {
        const d = new Date(latest);
        if (!lastSync || d > lastSync) lastSync = d;
      }
    }
    let message = 'Synced';
    if (lastSync) {
      const ago = Math.round((Date.now() - lastSync.getTime()) / 1000);
      if (ago < 60) { message = 'Synced just now'; }
      else if (ago < 3600) { message = `Synced ${Math.round(ago / 60)}m ago`; }
      else { message = `Synced ${Math.round(ago / 3600)}h ago`; }
    }
    return { state: 'idle', message, accounts: $syncStatus, retryAfter: null, ...counts };
  }

  // Mail can be current while Calendar is disconnected. Surface that as a
  // partial state instead of claiming that the whole app is healthy.
  if (rateLimitedCount === 0 && errorCount === 0 && calendarIssueCount > 0) {
    const message = calendarIssueCount === 1
      ? 'Email synced · Calendar needs attention'
      : `Email synced · ${calendarIssueCount} calendar issues`;
    return { state: 'partial', message, accounts: $syncStatus, retryAfter: null, ...counts };
  }

  // Some accounts have issues but others are fine
  const healthyCount = idleCount;

  if (rateLimitedCount > 0 && healthyCount > 0) {
    // Mixed: some OK, some rate limited
    const message = `${healthyCount} synced, ${rateLimitedCount} rate limited`;
    return { state: 'partial', message, accounts: $syncStatus, retryAfter: soonestRetry, ...counts };
  }

  if (errorCount > 0 && healthyCount > 0) {
    const message = `${healthyCount} synced, ${errorCount} with errors`;
    return { state: 'partial', message, accounts: $syncStatus, retryAfter: null, ...counts };
  }

  // All accounts rate limited
  if (rateLimitedCount > 0 && healthyCount === 0 && errorCount === 0) {
    let message = 'Rate limited';
    if (total > 1) { message = `All ${total} accounts rate limited`; }
    return { state: 'rate_limited', message, accounts: $syncStatus, retryAfter: soonestRetry, ...counts };
  }

  // All accounts errored
  if (errorCount > 0 && healthyCount === 0 && rateLimitedCount === 0) {
    const errored = $syncStatus.find(a => a.sync_status && a.sync_status.status === 'error');
    const errMsg = errored.sync_status.error_message || 'Sync error';
    return { state: 'error', message: errMsg, accounts: $syncStatus, retryAfter: null, ...counts };
  }

  // Mixed errors and rate limits
  const message = `${rateLimitedCount} rate limited, ${errorCount} errors`;
  return { state: 'partial', message, accounts: $syncStatus, retryAfter: soonestRetry, ...counts };
});

// UI state
// Start with the mail navigation closed on narrow screens. The sidebar becomes
// an overlay drawer there; keeping the desktop default would leave almost no
// room for the message list on first load.
export const sidebarCollapsed = writable(
  typeof window !== 'undefined' ? window.matchMedia('(max-width: 767px)').matches : false
);
export const composeOpen = writable(false);
export const composeData = writable(null);
export const searchQuery = writable('');
export const viewMode = writable(localStorage.getItem('viewMode') || 'column');

// Inline reply draft -- set before navigating to inbox to show an inline reply composer
// Format: { emailId, to, subject, body, threadId }
export const pendingReplyDraft = writable(null);

// Hide "can_ignore" emails toggle (persisted)
export const hideIgnored = writable(localStorage.getItem('hideIgnored') === 'true');
hideIgnored.subscribe(v => localStorage.setItem('hideIgnored', String(v)));

// Thread message ordering preference (persisted)
export const threadOrder = writable(localStorage.getItem('threadOrder') || 'newest_first');
threadOrder.subscribe(v => localStorage.setItem('threadOrder', String(v)));

// Smart filter for AI categories / needs reply / email type in the sidebar
// Format: { type: 'needs_reply' } or { type: 'ai_category', value: 'urgent' } or { type: 'ai_email_type', value: 'work' } or null
export const smartFilter = writable(null);

// Todos
export const todos = writable([]);

// Chat
export const chatConversations = writable([]);
export const currentConversationId = writable(null);

// Calendar
export const calendarView = writable(localStorage.getItem('calendarView') || 'week');
calendarView.subscribe(v => localStorage.setItem('calendarView', v));
export const calendarDate = writable(new Date());
export const calendarEvents = writable([]);
export const calendarLoading = writable(false);

function resetAuthenticatedSessionState() {
  currentPage.set('flow');
  currentMailbox.set('INBOX');
  selectedEmailId.set(null);
  selectedThreadId.set(null);
  contactConversationIntent.set(null);
  attachmentParentIntent.set(null);
  savedViews.set([]);
  savedViewsLoading.set(false);
  savedViewsLoaded.set(false);
  savedViewsError.set('');
  savedViewsMax.set(12);
  activeSavedViewId.set(null);
  savedViewEditorRequest.set(null);
  savedViewFocusRequest.set(0);

  emails.set([]);
  emailsLoading.set(false);
  emailsTotal.set(0);
  currentPageNum.set(1);

  labels.set([]);
  selectedAccountId.set(null);
  composeOpen.set(false);
  composeData.set(null);
  pendingReplyDraft.set(null);
  searchQuery.set('');
  smartFilter.set(null);

  todos.set([]);
  chatConversations.set([]);
  currentConversationId.set(null);

  calendarDate.set(new Date());
  calendarEvents.set([]);
  calendarLoading.set(false);

  clearToasts();
  resetShortcutSessionState();
}

/**
 * Move the application to one authoritative authenticated identity.
 *
 * Every identity boundary invalidates captured async work before publishing
 * the next user. Non-sensitive browser preferences (theme, layout, page size,
 * calendar view, thread order) intentionally remain outside this reset.
 */
export function transitionAuthenticatedSession(nextUser) {
  const transition = transitionAuthEpoch(nextUser);

  // This also runs for anonymous -> anonymous bootstrap. Old V1/V2 drafts
  // have no provable owner, so an upgraded browser must purge them even when
  // it opens on the signed-out screen.
  clearUnscopedComposeStorage();

  if (transition.changed) {
    stopSyncPolling();
    stopRealtime();
    resetAuthenticatedSessionState();
  }

  user.set(transition.user);
  if (transition.changed) {
    authenticatedSessionGeneration.set(transition.snapshot.generation);
  }
  return captureAuthenticatedSession();
}

export function captureAuthenticatedSession() {
  return captureAuthEpoch();
}

export function isAuthenticatedSessionCurrent(snapshot) {
  return snapshot?.userId !== null && isAuthEpochCurrent(snapshot);
}

export function createAuthenticatedSessionGuard() {
  const snapshot = captureAuthenticatedSession();
  let active = true;
  return Object.freeze({
    snapshot,
    userId: snapshot.userId,
    isCurrent: () => active && isAuthenticatedSessionCurrent(snapshot),
    dispose: () => { active = false; },
  });
}
