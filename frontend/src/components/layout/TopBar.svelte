<script>
  import { onMount } from 'svelte';
  import { theme, getEffectiveMode } from '../../lib/theme.js';
  import Icon from '../common/Icon.svelte';
  import { activeShortcuts, formatComboForDisplay, openCommandPalette } from '../../lib/shortcutStore.js';
  import { api } from '../../lib/api.js';
  import { preloadAuthenticatedPage } from '../../lib/lazyRoutes.js';
  import { sidebarCollapsed, currentPage, currentMailbox, viewMode, overallSyncState, syncStatus, showToast, forceSyncPoll, selectedAccountId, accounts, accountColorMap, hideIgnored, transitionAuthenticatedSession, createAuthenticatedSessionGuard, user } from '../../lib/stores.js';
  import EmailSearchBox from '../email/EmailSearchBox.svelte';

  let syncDropdownOpen = $state(false);
  let moreMenuOpen = $state(false);
  let moreButton = $state(null);
  let moreMenu = $state(null);
  let observedPage = $currentPage;
  let commandShortcut = $derived(
    formatComboForDisplay($activeShortcuts['nav.commands']?.key || 'Ctrl+k')
  );

  let selectedAccount = $derived(
    $selectedAccountId ? $accounts.find(a => a.id === $selectedAccountId) : null
  );
  let selectedAccountColor = $derived(
    selectedAccount ? $accountColorMap[selectedAccount.email] : null
  );
  let countdownText = $state('');
  let countdownInterval = null;
  let sessionGuard = null;
  let logoutInProgress = $state(false);

  const tabs = [
    { id: 'flow', label: 'Flow', icon: 'sparkles', shortcut: 'nav.flow' },
    { id: 'inbox', label: 'Email', icon: 'inbox', shortcut: 'nav.inbox' },
    { id: 'calendar', label: 'Calendar', icon: 'calendar', shortcut: 'nav.calendar' },
    { id: 'at-a-glance', label: 'At a Glance', icon: 'monitor', shortcut: 'nav.glance' },
  ];

  const secondaryTabs = [
    { id: 'ai-insights', label: 'AI Insights', icon: 'activity' },
    { id: 'chat', label: 'Chat', icon: 'message-square' },
    { id: 'subscriptions', label: 'Subscriptions', icon: 'bell-off' },
    { id: 'todos', label: 'Todos', icon: 'check-circle' },
    { id: 'stats', label: 'Stats', icon: 'bar-chart-2' },
  ];
  const settingsTab = { id: 'admin', label: 'Settings', icon: 'settings' };

  let activeSecondaryTab = $derived(
    secondaryTabs.find(tab => tab.id === $currentPage)
      || ($currentPage === settingsTab.id ? settingsTab : null)
  );
  let secondaryPageActive = $derived(Boolean(activeSecondaryTab));

  function warmRoute(page) {
    void preloadAuthenticatedPage(page);
  }

  function closeMoreMenu({ restoreFocus = false } = {}) {
    if (!moreMenuOpen) return;
    moreMenuOpen = false;
    if (restoreFocus) {
      requestAnimationFrame(() => moreButton?.focus({ preventScroll: true }));
    }
  }

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

  onMount(() => {
    sessionGuard = createAuthenticatedSessionGuard();
    countdownInterval = setInterval(updateCountdown, 1000);
    const handleEscape = event => {
      if (event.key !== 'Escape' || !moreMenuOpen) return;
      event.preventDefault();
      event.stopPropagation();
      closeMoreMenu({ restoreFocus: true });
    };
    window.addEventListener('keydown', handleEscape, true);
    return () => {
      if (countdownInterval) clearInterval(countdownInterval);
      window.removeEventListener('keydown', handleEscape, true);
      sessionGuard?.dispose();
      sessionGuard = null;
    };
  });

  // Keyboard navigation can replace a focused menu item. Close the popover
  // and return focus to its persistent trigger instead of dropping to body.
  $effect(() => {
    const page = $currentPage;
    if (page === observedPage) return;
    const focusWasInMenu = Boolean(moreMenu?.contains(document.activeElement));
    observedPage = page;
    closeMoreMenu({ restoreFocus: focusWasInMenu });
  });

  // Also update countdown whenever sync state changes
  $effect(() => {
    void $overallSyncState.retryAfter;
    updateCountdown();
  });

  async function handleLogout() {
    if (logoutInProgress) return;
    logoutInProgress = true;
    closeMoreMenu();
    syncDropdownOpen = false;
    try {
      await api.logout();
    } catch {
      // Continue even if API fails
    }
    if (!sessionGuard?.isCurrent()) return;
    transitionAuthenticatedSession(null);
  }

  function switchTab(tabId, { restoreMoreFocus = false } = {}) {
    currentPage.set(tabId);
    closeMoreMenu({ restoreFocus: restoreMoreFocus });
    syncDropdownOpen = false;
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
      if (!sessionGuard?.isCurrent()) return;
      showToast('Sync triggered', 'success');
      // Immediately poll so the UI picks up the syncing state
      setTimeout(() => {
        if (sessionGuard?.isCurrent()) forceSyncPoll();
      }, 500);
    } catch (err) {
      if (sessionGuard?.isCurrent()) showToast(err.message, 'error');
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
    const mailState = acct.sync_status?.status || 'idle';
    if (mailState !== 'idle' && mailState !== 'completed') return mailState;
    if (calendarNeedsAttention(acct)) return 'warning';
    return mailState;
  }

  function calendarNeedsAttention(acct) {
    return !acct.has_calendar_scope || acct.calendar_sync_status?.needs_reauth || acct.calendar_sync_status?.status === 'error';
  }

  function getCalendarHealthText(acct) {
    if (!acct.has_calendar_scope) return 'Calendar access not granted';
    if (acct.calendar_sync_status?.needs_reauth) return 'Calendar needs reconnection';
    if (acct.calendar_sync_status?.status === 'error') return acct.calendar_sync_status.error_message || 'Calendar sync error';
    return '';
  }

  async function reauthorizeAccount(accountId) {
    try {
      const result = await api.reauthorizeAccount(accountId);
      if (!sessionGuard?.isCurrent()) return;
      window.location.href = result.auth_url;
    } catch (err) {
      if (sessionGuard?.isCurrent()) {
        showToast(err.message || 'Could not start reconnection', 'error');
      }
    }
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

<header class="app-topbar min-h-14 flex items-center gap-2 px-4 border-b shrink-0" style="background: var(--bg-secondary); border-color: var(--border-color)">
  <!-- Left: Tab navigation -->
  <nav class="primary-nav relative flex items-center gap-1 mr-2" aria-label="Primary navigation">
    {#each tabs as tab}
      <button
        onclick={() => switchTab(tab.id)}
        onpointerenter={() => warmRoute(tab.id)}
        onfocus={() => warmRoute(tab.id)}
        class="min-h-11 flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-medium transition-all duration-150"
        class:tab-active={$currentPage === tab.id}
        class:tab-inactive={$currentPage !== tab.id}
        aria-label="{tab.label} tab"
        aria-current={$currentPage === tab.id ? 'page' : undefined}
        data-shortcut={tab.shortcut}
      >
        {#if tab.icon === 'sparkles'}
          <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09zM18.259 8.715L18 9.75l-.259-1.035a3.375 3.375 0 00-2.455-2.456L14.25 6l1.036-.259a3.375 3.375 0 002.455-2.456L18 2.25l.259 1.035a3.375 3.375 0 002.455 2.456L21.75 6l-1.036.259a3.375 3.375 0 00-2.455 2.456zM16.894 20.567L16.5 21.75l-.394-1.183a2.25 2.25 0 00-1.423-1.423L13.5 18.75l1.183-.394a2.25 2.25 0 001.423-1.423l.394-1.183.394 1.183a2.25 2.25 0 001.423 1.423l1.183.394-1.183.394a2.25 2.25 0 00-1.423 1.423z" />
          </svg>
        {:else}
          <Icon name={tab.icon} size={16} />
        {/if}
        <span class="primary-tab-label">{tab.label}</span>
      </button>
    {/each}
    <div class="more-trigger relative flex items-center shrink-0">
      <button
        bind:this={moreButton}
        onclick={() => moreMenuOpen ? closeMoreMenu() : moreMenuOpen = true}
        class="more-button min-h-11 flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-medium transition-all duration-150"
        class:tab-active={secondaryPageActive}
        class:tab-inactive={!secondaryPageActive}
        aria-label={activeSecondaryTab ? `More app sections, current: ${activeSecondaryTab.label}` : 'More app sections'}
        aria-expanded={moreMenuOpen}
        aria-controls="more-app-sections-menu"
        aria-current={secondaryPageActive ? 'page' : undefined}
      >
        <Icon name="more-horizontal" size={16} />
        <span class="primary-tab-label">More</span>
      </button>
      {#if moreMenuOpen}
        <button
          class="topbar-backdrop fixed inset-0 z-40 cursor-default"
          onclick={() => closeMoreMenu({ restoreFocus: true })}
          tabindex="-1"
          aria-hidden="true"
        ></button>
        <div bind:this={moreMenu} id="more-app-sections-menu" class="more-menu absolute left-0 top-full mt-2 z-50 w-56 rounded-xl border p-1.5 shadow-xl" style="background: var(--bg-secondary); border-color: var(--border-color)">
          {#each secondaryTabs as tab}
            <button
              onclick={() => switchTab(tab.id, { restoreMoreFocus: true })}
              onpointerenter={() => warmRoute(tab.id)}
              onfocus={() => warmRoute(tab.id)}
              class="min-h-11 w-full flex items-center gap-2.5 px-3 py-2 rounded-lg text-sm text-left"
              class:menu-item-active={$currentPage === tab.id}
              aria-current={$currentPage === tab.id ? 'page' : undefined}
            >
              <Icon name={tab.icon} size={16} />
              {tab.label}
            </button>
          {/each}
          <div class="mobile-menu-utilities border-t mt-1 pt-1" style="border-color: var(--border-color)">
            <button
              onclick={() => switchTab('admin', { restoreMoreFocus: true })}
              onpointerenter={() => warmRoute('admin')}
              onfocus={() => warmRoute('admin')}
              class="min-h-11 w-full flex items-center gap-2.5 px-3 py-2 rounded-lg text-sm text-left"
              class:menu-item-active={$currentPage === 'admin'}
              aria-current={$currentPage === 'admin' ? 'page' : undefined}
            >
              <Icon name="settings" size={16} /> Settings
            </button>
            <button onclick={() => { theme.toggle(); closeMoreMenu({ restoreFocus: true }); }} class="min-h-11 w-full flex items-center gap-2.5 px-3 py-2 rounded-lg text-sm text-left">
              <Icon name={getEffectiveMode($theme) === 'dark' ? 'sun' : 'moon'} size={16} />
              {getEffectiveMode($theme) === 'dark' ? 'Light theme' : 'Dark theme'}
            </button>
            <button
              onclick={handleLogout}
              disabled={logoutInProgress}
              class="min-h-11 w-full flex items-center gap-2.5 px-3 py-2 rounded-lg text-sm text-left disabled:opacity-50"
            >
              <Icon name="log-out" size={16} /> Log out
            </button>
          </div>
        </div>
      {/if}
    </div>
  </nav>

  <!-- Center: Contextual content -->
  {#if $currentPage === 'inbox'}
    <!-- Email tab: Focused toggle + search + view mode -->
    <div class="inbox-tools flex items-center gap-2 flex-1 min-w-0">
      <!-- Sidebar toggle (only on email tab) -->
      <button
        onclick={() => sidebarCollapsed.update(v => !v)}
        class="sidebar-toggle min-w-11 min-h-11 inline-flex items-center justify-center rounded-md transition-fast shrink-0"
        style="color: var(--text-secondary)"
        aria-label="Toggle sidebar"
      >
        <Icon name="menu" size={16} />
      </button>

      <!-- Focused toggle -->
      <button
        onclick={() => hideIgnored.update(v => !v)}
        class="focused-toggle min-h-11 flex items-center gap-1.5 px-2 py-1 rounded-md text-xs font-medium transition-fast shrink-0 {$hideIgnored ? 'bg-accent-500/15' : ''}"
        style="color: {$hideIgnored ? 'var(--color-accent-600)' : 'var(--text-tertiary)'}"
        title="{$hideIgnored ? 'Showing focused emails (hiding low priority)' : 'Click to hide low priority emails'}"
        aria-label="Toggle hide low priority emails"
      >
        <Icon name="filter" size={14} />
        <span class="focused-label">Focused</span>
      </button>

      <!-- Active account filter chip -->
      {#if selectedAccount}
        <div
          class="active-account-chip flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium shrink-0"
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
      <div class="email-search-slot flex-1 max-w-xl">
        <EmailSearchBox />
      </div>

      <!-- View mode toggle -->
      <button
        onclick={toggleViewMode}
        class="hidden md:inline-flex p-1.5 rounded-md transition-fast shrink-0"
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
  <div class="topbar-utilities flex items-center gap-1.5 shrink-0">
    <button
      onclick={openCommandPalette}
      class="command-trigger min-w-11 min-h-11 inline-flex items-center justify-center gap-2 px-2.5 rounded-lg border"
      style="color: var(--text-secondary); border-color: var(--border-color); background: var(--bg-primary)"
      aria-label="Open command palette"
      title="Open command palette"
      data-shortcut="nav.commands"
    >
      <Icon name="command" size={16} />
      <span class="command-trigger-label text-xs font-medium">Commands</span>
      <kbd class="command-trigger-key">{commandShortcut}</kbd>
    </button>

    <!-- Active account filter chip (non-email tabs) -->
    {#if selectedAccount && $currentPage !== 'inbox'}
      <div
        class="active-account-chip flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium"
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
          <span style="color: var(--status-warning)">
            <Icon name="clock" size={16} />
          </span>
          <span class="hidden sm:inline" style="color: var(--status-warning)">{countdownText || 'Rate limited'}</span>
        {:else if $overallSyncState.state === 'partial'}
          <span class="w-2 h-2 rounded-full shrink-0" style="background: var(--status-warning)"></span>
          <span class="hidden sm:inline" style="color: var(--status-warning)">{$overallSyncState.message}</span>
          {#if $overallSyncState.rateLimitedCount > 0}
            <span class="hidden sm:inline text-[10px] px-1 rounded" style="color: var(--status-warning)">{countdownText}</span>
          {/if}
        {:else if $overallSyncState.state === 'error'}
          <span class="w-2 h-2 rounded-full shrink-0" style="background: var(--status-error)"></span>
          <span class="hidden sm:inline" style="color: var(--status-error)">Sync Error</span>
        {:else}
          <span class="w-2 h-2 rounded-full shrink-0" style="background: var(--status-success)"></span>
          <span class="hidden sm:inline">{$overallSyncState.message}</span>
        {/if}
      </button>

      {#if syncDropdownOpen}
        <!-- svelte-ignore a11y_no_static_element_interactions a11y_click_events_have_key_events -->
        <button
          class="topbar-backdrop fixed inset-0 z-40"
          onclick={closeSyncDropdown}
          aria-label="Close sync status"
        ></button>
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
                  <span class="w-2 h-2 rounded-full shrink-0" style="background: var(--status-warning)"></span>
                {:else if getAccountSyncState(acct) === 'error'}
                  <span class="w-2 h-2 rounded-full shrink-0" style="background: var(--status-error)"></span>
                {:else if getAccountSyncState(acct) === 'warning'}
                  <span class="w-2 h-2 rounded-full shrink-0" style="background: var(--status-warning)"></span>
                {:else}
                  <span class="w-2 h-2 rounded-full shrink-0" style="background: var(--status-success)"></span>
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
                    <div class="text-[10px]" style="color: var(--status-warning)">{getAccountCountdown(acct)}</div>
                  {:else if getAccountSyncState(acct) === 'error' && acct.sync_status.error_message}
                    <div class="text-[10px] truncate" style="color: var(--status-error)" title={acct.sync_status.error_message}>{acct.sync_status.error_message}</div>
                  {:else}
                    <div class="text-[10px]" style="color: var(--text-tertiary)">{formatSyncTime(acct)}{#if acct.sync_status && acct.sync_status.messages_synced} -- {acct.sync_status.messages_synced.toLocaleString()} emails{/if}</div>
                  {/if}
                  {#if calendarNeedsAttention(acct)}
                    <button
                      onclick={() => reauthorizeAccount(acct.id)}
                      class="mt-1 text-[10px] font-medium text-left"
                      style="color: var(--status-warning)"
                      title={getCalendarHealthText(acct)}
                    >
                      {getCalendarHealthText(acct)} · Reconnect
                    </button>
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
      class="desktop-utility p-1.5 rounded-md transition-fast"
      style="color: var(--text-secondary)"
      aria-label="Toggle theme"
      data-shortcut="nav.theme"
    >
      {#if getEffectiveMode($theme) === 'dark'}
        <Icon name="sun" size={16} />
      {:else}
        <Icon name="moon" size={16} />
      {/if}
    </button>

    <!-- Settings gear -->
    <button
      onclick={() => currentPage.set('admin')}
      onpointerenter={() => warmRoute('admin')}
      onfocus={() => warmRoute('admin')}
      class="desktop-utility p-1.5 rounded-md transition-fast"
      style="color: {$currentPage === 'admin' ? 'var(--color-accent-500)' : 'var(--text-secondary)'}"
      aria-label="Settings"
      aria-current={$currentPage === 'admin' ? 'page' : undefined}
      title="Settings"
      data-shortcut="nav.settings"
    >
      <Icon name="settings" size={16} />
    </button>

    <!-- User menu -->
    <div class="desktop-utility flex items-center gap-1.5 pl-2 border-l" style="border-color: var(--border-color)">
      <div class="w-6 h-6 rounded-full bg-accent-500/20 flex items-center justify-center text-[10px] font-bold" style="color: var(--color-accent-600)">
        {($user?.display_name || $user?.username || 'U')[0].toUpperCase()}
      </div>
      <button
        onclick={handleLogout}
        disabled={logoutInProgress}
        class="p-1 rounded-md transition-fast disabled:opacity-50"
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
  /* Hover states for icon buttons */
  header button:not(.topbar-backdrop):not(.tab-active):not(.tab-inactive) {
    transition: all 150ms cubic-bezier(0.4, 0, 0.2, 1);
  }
  header button:not(.topbar-backdrop):not(.tab-active):not(.tab-inactive):hover {
    background: var(--bg-hover);
    color: var(--text-primary);
  }
  .topbar-backdrop,
  .topbar-backdrop:hover {
    border: 0;
    background: transparent;
  }
  .menu-item-active {
    color: var(--color-accent-600);
    background: color-mix(in srgb, var(--color-accent-500) 14%, transparent);
  }
  .mobile-menu-utilities {
    display: none;
  }
  .command-trigger-label,
  .command-trigger-key {
    display: none;
  }

  @media (max-width: 767px) {
    .app-topbar {
      padding: 0.5rem;
      gap: 0.25rem;
      flex-wrap: wrap;
    }
    .primary-nav {
      margin-right: 0;
      flex: 1 1 auto;
    }
    .primary-nav > button:not(.fixed),
    .primary-nav > .more-trigger > .more-button {
      padding-left: 0.65rem;
      padding-right: 0.65rem;
    }
    .primary-tab-label,
    .desktop-utility,
    .active-account-chip,
    .focused-label {
      display: none;
    }
    .command-trigger-label,
    .command-trigger-key {
      display: none;
    }
    .mobile-menu-utilities {
      display: block;
    }
    .more-menu {
      position: fixed;
      top: 3.25rem;
      left: 0.5rem;
      right: 0.5rem;
      width: auto;
      max-height: calc(100dvh - 3.75rem - env(safe-area-inset-bottom));
      overflow-y: auto;
      overscroll-behavior: contain;
    }
    .topbar-utilities {
      margin-left: auto;
    }
    .inbox-tools {
      order: 3;
      flex-basis: 100%;
    }
    .email-search-slot {
      max-width: none;
      min-width: 0;
    }
    .app-topbar:has(.inbox-tools) {
      min-height: 6.75rem;
    }
  }

  @media (min-width: 768px) and (max-width: 1023px) {
    .primary-tab-label {
      display: none;
    }
    .primary-nav > button:not(.fixed),
    .primary-nav > .more-trigger > .more-button {
      padding-left: 0.65rem;
      padding-right: 0.65rem;
    }
  }

  .command-trigger-key {
    padding: 0.15rem 0.35rem;
    border: 1px solid var(--border-color);
    border-radius: 0.3rem;
    background: var(--bg-secondary);
    color: var(--text-tertiary);
    font: 600 0.625rem/1 system-ui, sans-serif;
  }

  @media (min-width: 1100px) {
    .command-trigger-label,
    .command-trigger-key {
      display: inline-flex;
    }
  }
</style>
