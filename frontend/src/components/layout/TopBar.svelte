<script>
  import { onMount } from 'svelte';
  import { theme } from '../../lib/theme.js';
  import { api } from '../../lib/api.js';
  import { user, sidebarCollapsed, searchQuery, currentPage, currentMailbox, viewMode, overallSyncState, syncStatus, showToast, forceSyncPoll } from '../../lib/stores.js';

  let searchValue = $state('');
  let syncDropdownOpen = $state(false);

  // Keep local searchValue in sync with the store
  onMount(() => {
    const unsub = searchQuery.subscribe(val => {
      searchValue = val;
    });
    return unsub;
  });

  function handleSearch(e) {
    if (e.key === 'Enter') {
      searchQuery.set(searchValue.trim());
    }
  }

  function clearSearch() {
    searchValue = '';
    searchQuery.set('');
  }

  async function handleLogout() {
    try {
      await api.logout();
    } catch {
      // Continue even if API fails
    }
    user.set(null);
  }

  function getPageTitle() {
    if ($currentPage === 'admin') return 'Settings';
    if ($currentPage === 'compose') return 'Compose';
    if ($currentPage === 'stats') return 'Stats';
    if ($currentPage === 'ai-insights') return 'AI Insights';
    const mb = $currentMailbox || 'INBOX';
    // Handle label names like CATEGORY_SOCIAL
    if (mb.startsWith('CATEGORY_')) {
      return mb.replace('CATEGORY_', '').charAt(0) + mb.replace('CATEGORY_', '').slice(1).toLowerCase();
    }
    if (mb.startsWith('Label_')) {
      return mb.replace('Label_', '').replace(/_/g, ' ');
    }
    return mb.charAt(0) + mb.slice(1).toLowerCase();
  }

  function toggleViewMode() {
    viewMode.update(v => {
      const next = v === 'column' ? 'table' : 'column';
      localStorage.setItem('viewMode', next);
      return next;
    });
  }

  function toggleSyncDropdown() {
    syncDropdownOpen = !syncDropdownOpen;
  }

  function closeSyncDropdown() {
    syncDropdownOpen = false;
  }

  async function triggerSync(accountId) {
    try {
      await api.triggerSync(accountId);
      showToast('Sync triggered', 'success');
      // Immediately poll so the UI picks up the syncing state
      setTimeout(forceSyncPoll, 500);
    } catch (err) {
      showToast(err.message, 'error');
    }
  }

  function getSyncProgressText(acct) {
    if (!acct.sync_status) return '';
    const ss = acct.sync_status;
    if (ss.status !== 'syncing') return '';
    if (ss.messages_synced > 0 && ss.total_messages > 0) {
      return `${ss.messages_synced.toLocaleString()} / ${ss.total_messages.toLocaleString()}`;
    }
    if (ss.current_phase) return ss.current_phase;
    return 'Starting...';
  }

  function getOverallProgress() {
    const accts = $overallSyncState.accounts;
    let synced = 0;
    let total = 0;
    for (const a of accts) {
      if (a.sync_status && a.sync_status.status === 'syncing') {
        synced += a.sync_status.messages_synced || 0;
        total += a.sync_status.total_messages || 0;
      }
    }
    if (total > 0) {
      return `${synced.toLocaleString()} / ${total.toLocaleString()}`;
    }
    return '';
  }

  function formatSyncTime(acct) {
    if (!acct.sync_status) return 'Never synced';
    const inc = acct.sync_status.last_incremental_sync;
    const full = acct.sync_status.last_full_sync;
    const latest = inc || full;
    if (!latest) return 'Never synced';
    const ago = Math.round((Date.now() - new Date(latest).getTime()) / 1000);
    if (ago < 60) return 'Just now';
    if (ago < 3600) return `${Math.round(ago / 60)}m ago`;
    return `${Math.round(ago / 3600)}h ago`;
  }

  function getAccountSyncState(acct) {
    if (!acct.sync_status) return 'idle';
    return acct.sync_status.status || 'idle';
  }
</script>

<header class="h-14 flex items-center gap-4 px-4 border-b shrink-0" style="background: var(--bg-secondary); border-color: var(--border-color)">
  <!-- Collapse toggle -->
  <button
    onclick={() => sidebarCollapsed.update(v => !v)}
    class="p-1.5 rounded-md transition-fast"
    style="color: var(--text-secondary)"
    aria-label="Toggle sidebar"
  >
    <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M3.75 6.75h16.5M3.75 12h16.5m-16.5 5.25h16.5" />
    </svg>
  </button>

  <!-- Page title -->
  <h1 class="text-base font-semibold" style="color: var(--text-primary)">{getPageTitle()}</h1>

  <!-- Search -->
  <div class="flex-1 max-w-md mx-auto">
    <div class="relative">
      <svg class="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4" style="color: var(--text-tertiary)" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 5.196a7.5 7.5 0 0010.607 10.607z" />
      </svg>
      <input
        type="text"
        bind:value={searchValue}
        onkeydown={handleSearch}
        placeholder="Search emails..."
        class="w-full h-8 pl-9 pr-8 rounded-lg text-sm outline-none border"
        style="background: var(--bg-primary); border-color: var(--border-color); color: var(--text-primary)"
      />
      {#if searchValue}
        <button
          onclick={clearSearch}
          class="absolute right-2 top-1/2 -translate-y-1/2 p-0.5 rounded transition-fast"
          style="color: var(--text-tertiary)"
          aria-label="Clear search"
        >
          <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      {/if}
    </div>
  </div>

  <div class="flex items-center gap-2">
    <!-- View toggle (only show on inbox/email pages) -->
    {#if $currentPage === 'inbox'}
      <button
        onclick={toggleViewMode}
        class="p-1.5 rounded-md transition-fast"
        style="color: var(--text-secondary)"
        aria-label="Toggle view mode"
        title="{$viewMode === 'column' ? 'Switch to table view' : 'Switch to column view'}"
      >
        {#if $viewMode === 'column'}
          <!-- Table icon -->
          <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M3.375 19.5h17.25m-17.25 0a1.125 1.125 0 01-1.125-1.125M3.375 19.5h7.5c.621 0 1.125-.504 1.125-1.125m-9.75 0V5.625m0 12.75v-1.5c0-.621.504-1.125 1.125-1.125m18.375 2.625V5.625m0 12.75c0 .621-.504 1.125-1.125 1.125m1.125-1.125v-1.5c0-.621-.504-1.125-1.125-1.125m0 3.75h-7.5A1.125 1.125 0 0112 18.375m9.75-12.75c0-.621-.504-1.125-1.125-1.125H3.375c-.621 0-1.125.504-1.125 1.125m19.5 0v1.5c0 .621-.504 1.125-1.125 1.125M2.25 5.625v1.5c0 .621.504 1.125 1.125 1.125m0 0h17.25m-17.25 0h7.5c.621 0 1.125.504 1.125 1.125M3.375 8.25c-.621 0-1.125.504-1.125 1.125v1.5c0 .621.504 1.125 1.125 1.125m17.25-3.75h-7.5c-.621 0-1.125.504-1.125 1.125m8.625-1.125c.621 0 1.125.504 1.125 1.125v1.5c0 .621-.504 1.125-1.125 1.125m-17.25 0h7.5m-7.5 0c-.621 0-1.125.504-1.125 1.125v1.5c0 .621.504 1.125 1.125 1.125M12 10.875v-1.5m0 1.5c0 .621-.504 1.125-1.125 1.125M12 10.875c0 .621.504 1.125 1.125 1.125m-2.25 0c.621 0 1.125.504 1.125 1.125M10.875 12h-7.5m8.625 0h7.5m-8.625 0c.621 0 1.125.504 1.125 1.125v1.5" />
          </svg>
        {:else}
          <!-- List icon -->
          <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M8.25 6.75h12M8.25 12h12m-12 5.25h12M3.75 6.75h.007v.008H3.75V6.75zm.375 0a.375.375 0 11-.75 0 .375.375 0 01.75 0zM3.75 12h.007v.008H3.75V12zm.375 0a.375.375 0 11-.75 0 .375.375 0 01.75 0zm-.375 5.25h.007v.008H3.75v-.008zm.375 0a.375.375 0 11-.75 0 .375.375 0 01.75 0z" />
          </svg>
        {/if}
      </button>
    {/if}

    <!-- Sync status indicator -->
    <div class="relative">
      <button
        onclick={toggleSyncDropdown}
        class="flex items-center gap-1.5 px-2 py-1 rounded-md text-xs transition-fast"
        style="color: var(--text-secondary)"
        aria-label="Sync status"
        title={$overallSyncState.message}
      >
        {#if $overallSyncState.state === 'syncing'}
          <!-- Spinning sync icon -->
          <svg class="w-4 h-4 animate-spin" style="color: var(--color-accent-500)" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0l3.181 3.183a8.25 8.25 0 0013.803-3.7M4.031 9.865a8.25 8.25 0 0113.803-3.7l3.181 3.182M20.017 4.355v4.992" />
          </svg>
          <span class="hidden sm:inline" style="color: var(--color-accent-500)">{getOverallProgress() || 'Syncing...'}</span>
        {:else if $overallSyncState.state === 'error'}
          <!-- Error icon -->
          <span class="w-2 h-2 rounded-full shrink-0" style="background: #ef4444"></span>
          <span class="hidden sm:inline" style="color: #ef4444">Sync Error</span>
        {:else}
          <!-- Idle/completed icon -->
          <span class="w-2 h-2 rounded-full shrink-0" style="background: #22c55e"></span>
          <span class="hidden sm:inline">{$overallSyncState.message}</span>
        {/if}
      </button>

      {#if syncDropdownOpen}
        <!-- svelte-ignore a11y_no_static_element_interactions a11y_click_events_have_key_events -->
        <div
          class="fixed inset-0 z-40"
          onclick={closeSyncDropdown}
        ></div>
        <div
          class="absolute right-0 top-full mt-1 z-50 w-72 rounded-lg border shadow-lg overflow-hidden"
          style="background: var(--bg-secondary); border-color: var(--border-color)"
        >
          <div class="px-3 py-2 border-b" style="border-color: var(--border-color)">
            <span class="text-xs font-semibold uppercase tracking-wider" style="color: var(--text-tertiary)">Sync Status</span>
          </div>
          <div class="max-h-64 overflow-y-auto">
            {#each $overallSyncState.accounts as acct}
              <div class="px-3 py-2 flex items-center gap-2 border-b last:border-b-0" style="border-color: var(--border-color)">
                <!-- Status dot -->
                {#if getAccountSyncState(acct) === 'syncing'}
                  <span class="w-2 h-2 rounded-full shrink-0 animate-pulse" style="background: var(--color-accent-500)"></span>
                {:else if getAccountSyncState(acct) === 'error'}
                  <span class="w-2 h-2 rounded-full shrink-0" style="background: #ef4444"></span>
                {:else}
                  <span class="w-2 h-2 rounded-full shrink-0" style="background: #22c55e"></span>
                {/if}
                <div class="flex-1 min-w-0">
                  <div class="text-xs font-medium truncate" style="color: var(--text-primary)">{acct.email}</div>
                  {#if getAccountSyncState(acct) === 'syncing'}
                    <div class="text-[10px] truncate" style="color: var(--color-accent-500)">{getSyncProgressText(acct)}</div>
                    {#if acct.sync_status.messages_synced > 0 && acct.sync_status.total_messages > 0}
                      <div class="mt-1 h-1 rounded-full overflow-hidden" style="background: var(--border-color)">
                        <div
                          class="h-full rounded-full transition-all duration-500"
                          style="background: var(--color-accent-500); width: {Math.min(100, Math.round(acct.sync_status.messages_synced / acct.sync_status.total_messages * 100))}%"
                        ></div>
                      </div>
                    {/if}
                  {:else if getAccountSyncState(acct) === 'error' && acct.sync_status.error_message}
                    <div class="text-[10px] truncate" style="color: #ef4444" title={acct.sync_status.error_message}>{acct.sync_status.error_message}</div>
                  {:else}
                    <div class="text-[10px]" style="color: var(--text-tertiary)">{formatSyncTime(acct)}{#if acct.sync_status && acct.sync_status.messages_synced} -- {acct.sync_status.messages_synced.toLocaleString()} emails{/if}</div>
                  {/if}
                </div>
                <button
                  onclick={() => triggerSync(acct.id)}
                  class="p-1 rounded transition-fast shrink-0"
                  style="color: var(--text-tertiary)"
                  title="Sync now"
                  aria-label="Sync {acct.email}"
                >
                  <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0l3.181 3.183a8.25 8.25 0 0013.803-3.7M4.031 9.865a8.25 8.25 0 0113.803-3.7l3.181 3.182M20.017 4.355v4.992" />
                  </svg>
                </button>
              </div>
            {/each}
            {#if $overallSyncState.accounts.length === 0}
              <div class="px-3 py-3 text-xs text-center" style="color: var(--text-tertiary)">No accounts connected</div>
            {/if}
          </div>
        </div>
      {/if}
    </div>

    <!-- Theme toggle -->
    <button
      onclick={() => theme.toggle()}
      class="p-1.5 rounded-md transition-fast"
      style="color: var(--text-secondary)"
      aria-label="Toggle theme"
    >
      {#if $theme === 'dark'}
        <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M12 3v2.25m6.364.386l-1.591 1.591M21 12h-2.25m-.386 6.364l-1.591-1.591M12 18.75V21m-4.773-4.227l-1.591 1.591M5.25 12H3m4.227-4.773L5.636 5.636M15.75 12a3.75 3.75 0 11-7.5 0 3.75 3.75 0 017.5 0z" />
        </svg>
      {:else}
        <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M21.752 15.002A9.718 9.718 0 0118 15.75c-5.385 0-9.75-4.365-9.75-9.75 0-1.33.266-2.597.748-3.752A9.753 9.753 0 003 11.25C3 16.635 7.365 21 12.75 21a9.753 9.753 0 009.002-5.998z" />
        </svg>
      {/if}
    </button>

    <!-- User menu -->
    <div class="flex items-center gap-2 pl-2 border-l" style="border-color: var(--border-color)">
      <div class="w-7 h-7 rounded-full bg-accent-500/20 flex items-center justify-center text-xs font-bold" style="color: var(--color-accent-600)">
        {($user?.display_name || $user?.username || 'U')[0].toUpperCase()}
      </div>
      {#if $user}
        <span class="text-sm hidden sm:inline" style="color: var(--text-secondary)">{$user.display_name || $user.username}</span>
      {/if}
      <button
        onclick={handleLogout}
        class="p-1.5 rounded-md transition-fast"
        style="color: var(--text-secondary)"
        aria-label="Logout"
        title="Logout"
      >
        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M15.75 9V5.25A2.25 2.25 0 0013.5 3h-6a2.25 2.25 0 00-2.25 2.25v13.5A2.25 2.25 0 007.5 21h6a2.25 2.25 0 002.25-2.25V15m3 0l3-3m0 0l-3-3m3 3H9" />
        </svg>
      </button>
    </div>
  </div>
</header>
