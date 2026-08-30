<script>
  import { onDestroy, onMount } from 'svelte';
  import { api } from '../../lib/api.js';
  import { createIndexedDbDraftStorage } from '../../lib/draftStorage.js';
  import {
    accounts,
    composeData,
    createAuthenticatedSessionGuard,
    currentPage,
  } from '../../lib/stores.js';
  import {
    mergeRecentDrafts,
    recentDraftComposeData,
    recentDraftRecipients,
    recentDraftTitle,
  } from '../../lib/recentDrafts.js';
  import Icon from '../common/Icon.svelte';

  let loading = $state(true);
  let refreshing = $state(false);
  let errorMessage = $state('');
  let localOnly = $state(false);
  let localRecords = $state([]);
  let serverRecords = $state([]);
  let storage = null;
  let sessionGuard = null;
  let loadGeneration = 0;

  let rows = $derived(mergeRecentDrafts(localRecords, serverRecords, $accounts));

  function relativeTime(value) {
    const timestamp = Date.parse(value || '');
    if (!Number.isFinite(timestamp)) return '';
    const seconds = Math.max(0, Math.round((Date.now() - timestamp) / 1000));
    if (seconds < 60) return 'now';
    const minutes = Math.round(seconds / 60);
    if (minutes < 60) return `${minutes}m`;
    const hours = Math.round(minutes / 60);
    if (hours < 24) return `${hours}h`;
    return `${Math.round(hours / 24)}d`;
  }

  function stateLabel(row) {
    if (row.sending) return 'Confirming send';
    if (row.conflict) return 'Changed elsewhere';
    if (!row.server) return 'On this device';
    if (row.state === 'synced') return 'Synced';
    if (row.state === 'discard_pending' || row.state === 'discard-pending') return 'Discarded · Undo available';
    if (row.state === 'failed') return 'Needs attention';
    return 'Saving';
  }

  async function loadDrafts({ refresh = false } = {}) {
    if (!sessionGuard?.isCurrent() || !storage) return;
    const generation = ++loadGeneration;
    if (refresh) refreshing = true;
    else loading = true;
    errorMessage = '';
    try {
      const nextLocalRecords = await storage.list(sessionGuard.userId);
      if (!sessionGuard.isCurrent() || generation !== loadGeneration) return;
      localRecords = nextLocalRecords;
      if (navigator.onLine === false) {
        localOnly = true;
        serverRecords = [];
        return;
      }
      try {
        const nextServerRecords = await api.listRecentComposeDrafts(50);
        if (!sessionGuard.isCurrent() || generation !== loadGeneration) return;
        serverRecords = nextServerRecords;
        localOnly = false;
      } catch (error) {
        if (!sessionGuard.isCurrent() || generation !== loadGeneration) return;
        serverRecords = [];
        localOnly = true;
        errorMessage = error?.message || 'Couldn’t refresh cross-device drafts.';
      }
    } catch (error) {
      if (!sessionGuard?.isCurrent() || generation !== loadGeneration) return;
      errorMessage = error?.message || 'Drafts saved on this device are unavailable.';
    } finally {
      if (sessionGuard?.isCurrent() && generation === loadGeneration) {
        loading = false;
        refreshing = false;
      }
    }
  }

  function openDraft(row) {
    if (!row?.client_draft_id || row.sending) return;
    composeData.set(recentDraftComposeData(row));
    currentPage.set('compose');
  }

  onMount(() => {
    sessionGuard = createAuthenticatedSessionGuard();
    try {
      storage = createIndexedDbDraftStorage();
      void loadDrafts();
    } catch (error) {
      loading = false;
      errorMessage = error?.message || 'Draft storage is unavailable.';
    }
    const online = () => void loadDrafts({ refresh: true });
    window.addEventListener('online', online);
    window.addEventListener('offline', online);
    return () => {
      window.removeEventListener('online', online);
      window.removeEventListener('offline', online);
    };
  });

  onDestroy(() => {
    loadGeneration += 1;
    sessionGuard?.dispose();
    sessionGuard = null;
    void storage?.close?.();
  });
</script>

<section class="working-drafts border-b" style="border-color: var(--border-color)" aria-labelledby="working-drafts-title" data-working-drafts>
  <div class="flex items-center gap-3 px-4 py-3">
    <div class="min-w-0 flex-1">
      <h2 id="working-drafts-title" class="text-sm font-semibold" style="color: var(--text-primary)">Continue writing</h2>
      <p class="text-xs" style="color: var(--text-tertiary)">Replies and messages saved across this device and your signed-in accounts.</p>
    </div>
    <button
      type="button"
      onclick={() => loadDrafts({ refresh: true })}
      disabled={refreshing}
      class="inline-flex min-h-11 items-center gap-2 rounded-lg border px-3 text-xs font-medium disabled:opacity-50"
      style="border-color: var(--border-color); color: var(--text-secondary)"
      aria-label="Refresh working drafts"
    >
      <Icon name="refresh-cw" size={14} class={refreshing ? 'animate-spin' : ''} />
      <span class="hidden sm:inline">Refresh</span>
    </button>
  </div>

  {#if localOnly}
    <p class="px-4 pb-2 text-xs" style="color: var(--status-warning, #b45309)" role="status">
      {errorMessage ? 'Couldn’t refresh cross-device drafts. Showing safe copies from this device.' : 'Only drafts saved on this device are available offline.'}
    </p>
  {:else if errorMessage}
    <p class="px-4 pb-2 text-xs" style="color: var(--status-error)" role="alert">{errorMessage}</p>
  {/if}

  {#if loading}
    <div class="grid gap-2 px-4 pb-4 sm:grid-cols-2" aria-label="Loading drafts">
      <div class="h-20 animate-pulse rounded-xl" style="background: var(--bg-tertiary)"></div>
      <div class="h-20 animate-pulse rounded-xl" style="background: var(--bg-tertiary)"></div>
    </div>
  {:else if rows.length === 0}
    <div class="px-4 pb-4">
      <div class="rounded-xl border border-dashed px-4 py-5 text-center" style="border-color: var(--border-color)">
        <p class="text-sm font-medium" style="color: var(--text-primary)">No drafts in progress</p>
        <p class="mt-1 text-xs" style="color: var(--text-tertiary)">Start a reply or compose a message and it will appear here.</p>
      </div>
    </div>
  {:else}
    <div class="draft-grid grid gap-2 overflow-y-auto px-4 pb-4 sm:grid-cols-2" data-working-draft-list>
      {#each rows as row (row.client_draft_id)}
        <button
          type="button"
          onclick={() => openDraft(row)}
          disabled={row.sending}
          class="draft-card min-w-0 rounded-xl border p-3 text-left transition-fast disabled:cursor-not-allowed disabled:opacity-70"
          class:attention={row.conflict}
          style="border-color: {row.conflict ? 'var(--status-warning, #b45309)' : 'var(--border-color)'}; background: var(--bg-primary)"
          data-client-draft-id={row.client_draft_id}
        >
          <span class="flex items-start gap-2">
            <span class="min-w-0 flex-1">
              <span class="block truncate text-sm font-semibold" style="color: var(--text-primary)">{recentDraftTitle(row)}</span>
              <span class="mt-0.5 block truncate text-xs" style="color: var(--text-secondary)">{recentDraftRecipients(row)}</span>
            </span>
            <span class="shrink-0 text-[11px]" style="color: var(--text-tertiary)">{relativeTime(row.updated_at)}</span>
          </span>
          {#if row.body_preview}
            <span class="mt-2 block truncate text-xs" style="color: var(--text-tertiary)">{row.body_preview}</span>
          {/if}
          <span class="mt-2 flex items-center gap-2 text-[11px] font-medium" style="color: {row.conflict ? 'var(--status-warning, #b45309)' : 'var(--color-accent-600)'}">
            {#if row.account?.color}<span class="h-2 w-2 rounded-full" style="background: {row.account.color}"></span>{/if}
            <span class="truncate">{row.account?.email || `Account ${row.account_id}`}</span>
            <span aria-hidden="true">·</span>
            <span>{stateLabel(row)}</span>
          </span>
        </button>
      {/each}
    </div>
  {/if}
</section>

<style>
  .working-drafts {
    flex: 0 0 auto;
    background: var(--bg-secondary);
  }
  .draft-grid { max-height: 13rem; }
  .draft-card:hover:not(:disabled) { background: var(--bg-hover) !important; }
  .draft-card:focus-visible { outline: 2px solid var(--color-accent-500); outline-offset: 2px; }
  @media (max-width: 767px) {
    .draft-grid { max-height: min(38dvh, 19rem); grid-template-columns: 1fr; }
  }
</style>
