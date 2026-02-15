<script>
  import { onMount } from 'svelte';
  import { theme } from '../../lib/theme.js';
  import Icon from '../common/Icon.svelte';
  import { api } from '../../lib/api.js';
  import { user, sidebarCollapsed, searchQuery, currentPage, currentMailbox, viewMode, overallSyncState, syncStatus, showToast, forceSyncPoll, selectedAccountId, accounts, accountColorMap, hideIgnored } from '../../lib/stores.js';

  let searchValue = $state('');
  let syncDropdownOpen = $state(false);

  let selectedAccount = $derived(
    $selectedAccountId ? $accounts.find(a => a.id === $selectedAccountId) : null
  );
  let selectedAccountColor = $derived(
    selectedAccount ? $accountColorMap[selectedAccount.email] : null
  );
  let countdownText = $state('');
  let countdownInterval = null;

  const tabs = [
    { id: 'flow', label: 'Flow', icon: 'sparkles' },
    { id: 'inbox', label: 'Email', icon: 'inbox' },
    { id: 'calendar', label: 'Calendar', icon: 'calendar' },
  ];

  function updateCountdown() {
    const ra = $overallSyncState.retryAfter;
    if (!ra) {
      countdownText = '';
      return;
    }
    const target = new Date(ra);
    const now = Date.now();
    const diff = Math.max(0, Math.ceil((target.getTime() - now) / 1000));
    if (diff <= 0) {
      countdownText = 'Retrying...';
      forceSyncPoll();
    } else {
      const m = Math.floor(diff / 60);
      const s = diff % 60;
      if (m > 0) {
        countdownText = `${m}m ${s}s`;
      } else {
        countdownText = `${s}s`;
      }
    }
  }

  // Keep local searchValue in sync with the store
  onMount(() => {
    const unsub = searchQuery.subscribe(val => {
      searchValue = val;
    });
    countdownInterval = setInterval(updateCountdown, 1000);
    return () => {
      unsub();
      if (countdownInterval) clearInterval(countdownInterval);
    };
  });

  // Also update countdown whenever sync state changes
  $effect(() => {
    void $overallSyncState.retryAfter;
    updateCountdown();
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

  function switchTab(tabId) {
    currentPage.set(tabId);
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

  function getAccountCountdown(acct) {
    if (!acct.sync_status || !acct.sync_status.retry_after) return '';
    const target = new Date(acct.sync_status.retry_after);
    const diff = Math.max(0, Math.ceil((target.getTime() - Date.now()) / 1000));
    if (diff <= 0) return 'Retrying...';
    const m = Math.floor(diff / 60);
    const s = diff % 60;
    if (m > 0) {
      return `Retry in ${m}m ${s}s`;
    }
    return `Retry in ${s}s`;
  }
</script>

<header class="h-14 flex items-center gap-2 px-4 border-b shrink-0" style="background: var(--bg-secondary); border-color: var(--border-color)">
  <!-- Left: Tab navigation -->
  <nav class="flex items-center gap-1 mr-2">
    {#each tabs as tab}
      <button
        onclick={() => switchTab(tab.id)}
        class="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-medium transition-all duration-150"
        class:tab-active={$currentPage === tab.id}
        class:tab-inactive={$currentPage !== tab.id}
        aria-label="{tab.label} tab"
      >
        {#if tab.icon === 'sparkles'}
          <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09zM18.259 8.715L18 9.75l-.259-1.035a3.375 3.375 0 00-2.455-2.456L14.25 6l1.036-.259a3.375 3.375 0 002.455-2.456L18 2.25l.259 1.035a3.375 3.375 0 002.455 2.456L21.75 6l-1.036.259a3.375 3.375 0 00-2.455 2.456zM16.894 20.567L16.5 21.75l-.394-1.183a2.25 2.25 0 00-1.423-1.423L13.5 18.75l1.183-.394a2.25 2.25 0 001.423-1.423l.394-1.183.394 1.183a2.25 2.25 0 001.423 1.423l1.183.394-1.183.394a2.25 2.25 0 00-1.423 1.423z" />
          </svg>
        {:else}
          <Icon name={tab.icon} size={16} />
        {/if}
        {tab.label}
      </button>
    {/each}
  </nav>

  <!-- Center: Contextual content -->
  {#if $currentPage === 'inbox'}
    <!-- Email tab: Focused toggle + search + view mode -->
    <div class="flex items-center gap-2 flex-1 min-w-0">
      <!-- Sidebar toggle (only on email tab) -->
      <button
        onclick={() => sidebarCollapsed.update(v => !v)}
        class="p-1.5 rounded-md transition-fast shrink-0"
        style="color: var(--text-secondary)"
        aria-label="Toggle sidebar"
      >
        <Icon name="menu" size={16} />
      </button>

      <!-- Focused toggle -->
      <button
        onclick={() => hideIgnored.update(v => !v)}
        class="flex items-center gap-1.5 px-2 py-1 rounded-md text-xs font-medium transition-fast shrink-0 {$hideIgnored ? 'bg-accent-500/15' : ''}"
        style="color: {$hideIgnored ? 'var(--color-accent-600)' : 'var(--text-tertiary)'}"
        title="{$hideIgnored ? 'Showing focused emails (hiding low priority)' : 'Click to hide low priority emails'}"
        aria-label="Toggle hide low priority emails"
      >
        <Icon name="filter" size={14} />
        Focused
      </button>

      <!-- Active account filter chip -->
      {#if selectedAccount}
        <div
          class="flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium shrink-0"
          style="background: {selectedAccountColor ? selectedAccountColor.light : 'var(--bg-tertiary)'}; color: {selectedAccountColor ? selectedAccountColor.bg : 'var(--text-secondary)'}"
        >
          <span
            class="w-2 h-2 rounded-full shrink-0"
            style="background: {selectedAccountColor ? selectedAccountColor.bg : 'var(--text-tertiary)'}"
          ></span>
          <span class="truncate max-w-[120px]">{selectedAccount.description || selectedAccount.email}</span>
          <button
            onclick={() => selectedAccountId.set(null)}
            class="ml-0.5 p-0.5 rounded-full transition-fast hover:opacity-70"
            title="Show all accounts"
            aria-label="Clear account filter"
          >
            <Icon name="x" size={12} strokeWidth={2.5} />
          </button>
        </div>
      {/if}

      <!-- Search bar -->
      <div class="flex-1 max-w-md">
        <div class="relative">
          <span class="absolute left-3 top-1/2 -translate-y-1/2" style="color: var(--text-tertiary)">
            <Icon name="search" size={16} />
          </span>
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
              <Icon name="x" size={16} />
            </button>
          {/if}
        </div>
      </div>

      <!-- View mode toggle -->
      <button
        onclick={toggleViewMode}
        class="p-1.5 rounded-md transition-fast shrink-0"
        style="color: var(--text-secondary)"
        aria-label="Toggle view mode"
        title="{$viewMode === 'column' ? 'Switch to table view' : 'Switch to column view'}"
      >
        {#if $viewMode === 'column'}
          <Icon name="columns" size={16} />
        {:else}
          <Icon name="list" size={16} />
        {/if}
      </button>
    </div>
  {:else}
    <!-- Flow / Calendar / other tabs: spacer -->
    <div class="flex-1"></div>
  {/if}

  <!-- Right section: sync, theme, settings gear, user -->
  <div class="flex items-center gap-1.5 shrink-0">
    <!-- Active account filter chip (non-email tabs) -->
    {#if selectedAccount && $currentPage !== 'inbox'}
      <div
        class="flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium"
        style="background: {selectedAccountColor ? selectedAccountColor.light : 'var(--bg-tertiary)'}; color: {selectedAccountColor ? selectedAccountColor.bg : 'var(--text-secondary)'}"
      >
        <span
          class="w-2 h-2 rounded-full shrink-0"
          style="background: {selectedAccountColor ? selectedAccountColor.bg : 'var(--text-tertiary)'}"
        ></span>
        <span class="truncate max-w-[120px]">{selectedAccount.description || selectedAccount.email}</span>
        <button
          onclick={() => selectedAccountId.set(null)}
          class="ml-0.5 p-0.5 rounded-full transition-fast hover:opacity-70"
          title="Show all accounts"
          aria-label="Clear account filter"
        >
          <Icon name="x" size={12} strokeWidth={2.5} />
        </button>
      </div>
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
          <span class="animate-spin" style="color: var(--color-accent-500)">
            <Icon name="refresh-cw" size={16} />
          </span>
          <span class="hidden sm:inline" style="color: var(--color-accent-500)">{getOverallProgress() || $overallSyncState.message}</span>
        {:else if $overallSyncState.state === 'rate_limited'}
          <span style="color: #f59e0b">
            <Icon name="clock" size={16} />
          </span>
          <span class="hidden sm:inline" style="color: #f59e0b">{countdownText || 'Rate limited'}</span>
        {:else if $overallSyncState.state === 'partial'}
          <span class="w-2 h-2 rounded-full shrink-0" style="background: #22c55e"></span>
          <span class="hidden sm:inline">{$overallSyncState.message}</span>
          {#if $overallSyncState.rateLimitedCount > 0}
            <span class="hidden sm:inline text-[10px] px-1 rounded" style="color: #f59e0b">{countdownText}</span>
          {/if}
        {:else if $overallSyncState.state === 'error'}
          <span class="w-2 h-2 rounded-full shrink-0" style="background: #ef4444"></span>
          <span class="hidden sm:inline" style="color: #ef4444">Sync Error</span>
        {:else}
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
                {#if getAccountSyncState(acct) === 'syncing'}
                  <span class="w-2 h-2 rounded-full shrink-0 animate-pulse" style="background: var(--color-accent-500)"></span>
                {:else if getAccountSyncState(acct) === 'rate_limited'}
                  <span class="w-2 h-2 rounded-full shrink-0" style="background: #f59e0b"></span>
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
                  {:else if getAccountSyncState(acct) === 'rate_limited'}
                    <div class="text-[10px]" style="color: #f59e0b">{getAccountCountdown(acct)}</div>
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
                  <Icon name="refresh-cw" size={14} />
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
        <Icon name="sun" size={16} />
      {:else}
        <Icon name="moon" size={16} />
      {/if}
    </button>

    <!-- Settings gear -->
    <button
      onclick={() => currentPage.set('admin')}
      class="p-1.5 rounded-md transition-fast"
      style="color: {$currentPage === 'admin' ? 'var(--color-accent-500)' : 'var(--text-secondary)'}"
      aria-label="Settings"
      title="Settings"
    >
      <Icon name="settings" size={16} />
    </button>

    <!-- User menu -->
    <div class="flex items-center gap-1.5 pl-2 border-l" style="border-color: var(--border-color)">
      <div class="w-6 h-6 rounded-full bg-accent-500/20 flex items-center justify-center text-[10px] font-bold" style="color: var(--color-accent-600)">
        {($user?.display_name || $user?.username || 'U')[0].toUpperCase()}
      </div>
      <button
        onclick={handleLogout}
        class="p-1 rounded-md transition-fast"
        style="color: var(--text-secondary)"
        aria-label="Logout"
        title="Logout"
      >
        <Icon name="log-out" size={14} />
      </button>
    </div>
  </div>
</header>

<style>
  .tab-active {
    background: var(--color-accent-500);
    color: white;
    box-shadow: 0 1px 3px rgba(0, 0, 0, 0.15);
  }
  .tab-inactive {
    color: var(--text-secondary);
    background: transparent;
  }
  .tab-inactive:hover {
    background: var(--bg-tertiary);
    color: var(--text-primary);
  }
</style>
