import { writable, derived } from 'svelte/store';

// Auth state
export const user = writable(null);
export const isAuthenticated = derived(user, ($user) => $user !== null);

// Navigation
export const currentPage = writable('inbox');
export const currentMailbox = writable('INBOX');
export const selectedEmailId = writable(null);
export const selectedThreadId = writable(null);

// Email state
export const emails = writable([]);
export const emailsLoading = writable(false);
export const emailsTotal = writable(0);
export const currentPageNum = writable(1);
export const pageSize = writable(parseInt(localStorage.getItem('pageSize') || '50', 10));

// Accounts
export const accounts = writable([]);
export const selectedAccountId = writable(null);

// Labels
export const labels = writable([]);

// Sync status
export const syncStatus = writable([]);  // Array of account objects with sync_status
let syncPollInterval = null;
let syncPollFn = null;
let syncPollFast = false;  // true when actively syncing (3s), false when idle (30s)

export function startSyncPolling(apiFn) {
  stopSyncPolling();
  syncPollFn = apiFn;

  async function poll() {
    try {
      const accountList = await apiFn();
      syncStatus.set(accountList);
      accounts.set(accountList);

      // Adaptive polling: fast during active sync, slow when idle
      const anySyncing = accountList.some(
        a => a.sync_status && a.sync_status.status === 'syncing'
      );
      if (anySyncing && !syncPollFast) {
        // Switch to fast polling
        syncPollFast = true;
        clearInterval(syncPollInterval);
        syncPollInterval = setInterval(poll, 3000);
      } else if (!anySyncing && syncPollFast) {
        // Switch back to slow polling
        syncPollFast = false;
        clearInterval(syncPollInterval);
        syncPollInterval = setInterval(poll, 30000);
      }
    } catch {
      // Ignore polling errors (e.g. not authenticated)
    }
  }
  poll();
  syncPollInterval = setInterval(poll, 30000);
}

export function stopSyncPolling() {
  if (syncPollInterval) {
    clearInterval(syncPollInterval);
    syncPollInterval = null;
  }
  syncPollFn = null;
  syncPollFast = false;
}

// Force an immediate poll (e.g. after triggering a sync)
export function forceSyncPoll() {
  if (syncPollFn) {
    syncPollFn().then(accountList => {
      syncStatus.set(accountList);
      accounts.set(accountList);
    }).catch(() => {});
  }
}

// Derived sync state for quick access
export const overallSyncState = derived(syncStatus, ($syncStatus) => {
  if (!$syncStatus || $syncStatus.length === 0) {
    return { state: 'idle', message: 'No accounts', accounts: [] };
  }

  const hasSyncing = $syncStatus.some(
    a => a.sync_status && a.sync_status.status === 'syncing'
  );
  const hasError = $syncStatus.some(
    a => a.sync_status && a.sync_status.status === 'error'
  );

  if (hasSyncing) {
    const syncing = $syncStatus.find(a => a.sync_status && a.sync_status.status === 'syncing');
    const phase = syncing.sync_status.current_phase || 'Syncing...';
    return { state: 'syncing', message: phase, accounts: $syncStatus };
  }

  if (hasError) {
    const errored = $syncStatus.find(a => a.sync_status && a.sync_status.status === 'error');
    const errMsg = errored.sync_status.error_message || 'Sync error';
    return { state: 'error', message: errMsg, accounts: $syncStatus };
  }

  // Find the most recent sync time
  let lastSync = null;
  for (const a of $syncStatus) {
    if (!a.sync_status) continue;
    const full = a.sync_status.last_full_sync;
    const inc = a.sync_status.last_incremental_sync;
    const latest = inc || full;
    if (latest) {
      const d = new Date(latest);
      if (!lastSync || d > lastSync) {
        lastSync = d;
      }
    }
  }

  let message = 'Synced';
  if (lastSync) {
    const ago = Math.round((Date.now() - lastSync.getTime()) / 1000);
    if (ago < 60) {
      message = 'Synced just now';
    } else if (ago < 3600) {
      message = `Synced ${Math.round(ago / 60)}m ago`;
    } else {
      message = `Synced ${Math.round(ago / 3600)}h ago`;
    }
  }

  return { state: 'idle', message, accounts: $syncStatus };
});

// UI state
export const sidebarCollapsed = writable(false);
export const composeOpen = writable(false);
export const composeData = writable(null);
export const searchQuery = writable('');
export const toastMessage = writable(null);
export const viewMode = writable(localStorage.getItem('viewMode') || 'column');

// Inline reply draft -- set before navigating to inbox to show an inline reply composer
// Format: { emailId, to, subject, body, threadId }
export const pendingReplyDraft = writable(null);

// Smart filter for AI categories / needs reply in the sidebar
// Format: { type: 'needs_reply' } or { type: 'ai_category', value: 'urgent' } or null
export const smartFilter = writable(null);

// Todos
export const todos = writable([]);

// Chat
export const chatConversations = writable([]);
export const currentConversationId = writable(null);

// Show toast notification
export function showToast(message, type = 'info', duration = 3000) {
  toastMessage.set({ message, type, duration });
  setTimeout(() => {
    toastMessage.set(null);
  }, duration);
}
