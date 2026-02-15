<script>
  import { currentPage, currentMailbox, sidebarCollapsed, composeOpen, accounts, selectedAccountId, labels as labelsStore, syncStatus, smartFilter, todos, accountColorMap } from '../../lib/stores.js';
  import { api } from '../../lib/api.js';
  import { onMount } from 'svelte';
  import Icon from '../common/Icon.svelte';

  let accountList = $derived($syncStatus.length > 0 ? $syncStatus : $accounts);
  let categoriesExpanded = $state(false);
  let userLabelsExpanded = $state(false);
  let smartViewsExpanded = $state(true);

  let pendingTodoCount = $derived($todos.filter(t => t.status === 'pending').length);

  const aiCategories = [
    { id: 'urgent', label: 'Urgent', color: 'bg-red-500' },
    { id: 'awaiting_reply', label: 'Waiting On', color: 'bg-amber-500' },
    { id: 'fyi', label: 'FYI', color: 'bg-emerald-500' },
    { id: 'can_ignore', label: 'Low Priority', color: 'bg-gray-400' },
  ];

  const emailTypes = [
    { id: 'work', label: 'Work', color: 'bg-purple-500' },
    { id: 'personal', label: 'Personal', color: 'bg-teal-500' },
  ];

  let categoryLabels = $derived(
    $labelsStore.filter(l => l.gmail_label_id && l.gmail_label_id.startsWith('CATEGORY_'))
  );
  let userLabels = $derived(
    $labelsStore.filter(l => l.label_type === 'user')
  );

  const mailboxes = [
    { id: 'INBOX', label: 'Inbox', icon: 'inbox' },
    { id: 'STARRED', label: 'Starred', icon: 'star' },
    { id: 'SENT', label: 'Sent', icon: 'send' },
    { id: 'DRAFTS', label: 'Drafts', icon: 'edit' },
    { id: 'SPAM', label: 'Spam', icon: 'alert-triangle' },
    { id: 'TRASH', label: 'Trash', icon: 'trash-2' },
    { id: 'ALL', label: 'All Mail', icon: 'mail' },
  ];

  function selectMailbox(id) {
    smartFilter.set(null);
    currentMailbox.set(id);
    currentPage.set('inbox');
  }

  function selectLabel(labelId) {
    smartFilter.set(null);
    currentMailbox.set(labelId);
    currentPage.set('inbox');
  }

  function selectSmartFilter(filter) {
    smartFilter.set(filter);
    currentMailbox.set('ALL');
    currentPage.set('inbox');
  }

  function isSmartFilterActive(filter) {
    const sf = $smartFilter;
    if (!sf) return false;
    if (filter.type !== sf.type) return false;
    if (filter.type === 'ai_category' || filter.type === 'ai_email_type') return filter.value === sf.value;
    return true;
  }

  function formatCategoryName(gmailId) {
    // CATEGORY_SOCIAL -> Social, CATEGORY_PROMOTIONS -> Promotions
    return gmailId.replace('CATEGORY_', '').charAt(0) + gmailId.replace('CATEGORY_', '').slice(1).toLowerCase();
  }

  function getAccountSyncState(acct) {
    if (!acct.sync_status) return 'idle';
    return acct.sync_status.status || 'idle';
  }

  onMount(async () => {
    // Only fetch accounts if sync polling hasn't populated them yet
    if (accountList.length === 0) {
      try {
        const fetched = await api.listAccounts();
        accounts.set(fetched);
      } catch {
        // Not authenticated or no accounts yet
      }
    }

    try {
      const fetchedLabels = await api.getLabels();
      labelsStore.set(fetchedLabels);
    } catch {
      // Labels not available
    }
  });
</script>

<aside
  class="h-full flex flex-col border-r shrink-0 transition-all duration-200"
  style="background: var(--bg-secondary); border-color: var(--border-color); width: {$sidebarCollapsed ? '60px' : '240px'}"
>
  <!-- Logo -->
  <div class="h-14 flex items-center px-4 border-b shrink-0" style="border-color: var(--border-color)">
    {#if !$sidebarCollapsed}
      <span class="text-lg font-bold tracking-tight" style="color: var(--text-primary)">
        <span style="color: var(--color-accent-500)">&#9993;</span> Mail
      </span>
    {:else}
      <span class="text-lg mx-auto" style="color: var(--color-accent-500)">&#9993;</span>
    {/if}
  </div>

  <!-- Compose Button -->
  <div class="p-3">
    <button
      onclick={() => { composeOpen.set(true); currentPage.set('compose'); }}
      class="w-full h-9 flex items-center justify-center gap-2 rounded-lg text-sm font-medium bg-accent-600 text-white hover:bg-accent-700 transition-fast"
    >
      {#if !$sidebarCollapsed}
        <Icon name="plus" size={16} />
        Compose
      {:else}
        <Icon name="plus" size={20} />
      {/if}
    </button>
  </div>

  <!-- Mailboxes -->
  <nav class="flex-1 overflow-y-auto px-2 py-1">
    <div class="space-y-0.5">
      {#each mailboxes as mb}
        <button
          onclick={() => selectMailbox(mb.id)}
          class="w-full flex items-center gap-3 px-3 h-8 rounded-md text-sm transition-fast"
          class:font-medium={$currentMailbox === mb.id}
          style="color: {$currentMailbox === mb.id ? 'var(--text-primary)' : 'var(--text-secondary)'}; background: {$currentMailbox === mb.id ? 'var(--bg-hover)' : 'transparent'}"
        >
          <Icon name={mb.icon} size={18} class="shrink-0" />
          {#if !$sidebarCollapsed}
            <span class="truncate">{mb.label}</span>
          {/if}
        </button>
      {/each}
    </div>

    <!-- Smart Views (AI) section -->
    {#if !$sidebarCollapsed}
      <div class="mt-4">
        <button
          onclick={() => smartViewsExpanded = !smartViewsExpanded}
          class="w-full flex items-center gap-2 px-3 mb-1"
        >
          <Icon name="chevron-right" size={12} class="transition-transform duration-200 {smartViewsExpanded ? 'rotate-90' : ''}" />
          <span class="text-[11px] font-semibold tracking-wider uppercase" style="color: var(--text-tertiary)">Smart Views</span>
        </button>
        {#if smartViewsExpanded}
          <div class="space-y-0.5">
            <!-- Needs Reply -->
            <button
              onclick={() => selectSmartFilter({ type: 'needs_reply' })}
              class="w-full flex items-center gap-3 px-3 h-7 rounded-md text-sm transition-fast"
              class:font-medium={isSmartFilterActive({ type: 'needs_reply' })}
              style="color: {isSmartFilterActive({ type: 'needs_reply' }) ? 'var(--text-primary)' : 'var(--text-secondary)'}; background: {isSmartFilterActive({ type: 'needs_reply' }) ? 'var(--bg-hover)' : 'transparent'}"
            >
              <span class="w-[16px] h-[16px] flex items-center justify-center shrink-0">
                <span class="w-2.5 h-2.5 rounded-full bg-blue-500"></span>
              </span>
              <span class="truncate">Needs Reply</span>
            </button>
            <!-- AI Categories -->
            {#each aiCategories as cat}
              <button
                onclick={() => selectSmartFilter({ type: 'ai_category', value: cat.id })}
                class="w-full flex items-center gap-3 px-3 h-7 rounded-md text-sm transition-fast"
                class:font-medium={isSmartFilterActive({ type: 'ai_category', value: cat.id })}
                style="color: {isSmartFilterActive({ type: 'ai_category', value: cat.id }) ? 'var(--text-primary)' : 'var(--text-secondary)'}; background: {isSmartFilterActive({ type: 'ai_category', value: cat.id }) ? 'var(--bg-hover)' : 'transparent'}"
              >
                <span class="w-[16px] h-[16px] flex items-center justify-center shrink-0">
                  <span class="w-2.5 h-2.5 rounded-full {cat.color}"></span>
                </span>
                <span class="truncate">{cat.label}</span>
              </button>
            {/each}
            <!-- Email Type (Work / Personal) -->
            {#each emailTypes as et}
              <button
                onclick={() => selectSmartFilter({ type: 'ai_email_type', value: et.id })}
                class="w-full flex items-center gap-3 px-3 h-7 rounded-md text-sm transition-fast"
                class:font-medium={isSmartFilterActive({ type: 'ai_email_type', value: et.id })}
                style="color: {isSmartFilterActive({ type: 'ai_email_type', value: et.id }) ? 'var(--text-primary)' : 'var(--text-secondary)'}; background: {isSmartFilterActive({ type: 'ai_email_type', value: et.id }) ? 'var(--bg-hover)' : 'transparent'}"
              >
                <span class="w-[16px] h-[16px] flex items-center justify-center shrink-0">
                  <span class="w-2.5 h-2.5 rounded-full {et.color}"></span>
                </span>
                <span class="truncate">{et.label}</span>
              </button>
            {/each}
          </div>
        {/if}
      </div>
    {/if}

    <!-- Categories section -->
    {#if categoryLabels.length > 0 && !$sidebarCollapsed}
      <div class="mt-4">
        <button
          onclick={() => categoriesExpanded = !categoriesExpanded}
          class="w-full flex items-center gap-2 px-3 mb-1"
        >
          <Icon name="chevron-right" size={12} class="transition-transform duration-200 {categoriesExpanded ? 'rotate-90' : ''}" />
          <span class="text-[11px] font-semibold tracking-wider uppercase" style="color: var(--text-tertiary)">Categories</span>
        </button>
        {#if categoriesExpanded}
          <div class="space-y-0.5">
            {#each categoryLabels as cl}
              <button
                onclick={() => selectLabel(cl.gmail_label_id)}
                class="w-full flex items-center gap-3 px-3 h-7 rounded-md text-sm transition-fast"
                class:font-medium={$currentMailbox === cl.gmail_label_id}
                style="color: {$currentMailbox === cl.gmail_label_id ? 'var(--text-primary)' : 'var(--text-secondary)'}; background: {$currentMailbox === cl.gmail_label_id ? 'var(--bg-hover)' : 'transparent'}"
              >
                <Icon name="grid" size={16} class="shrink-0" />
                <span class="truncate">{formatCategoryName(cl.gmail_label_id)}</span>
                {#if cl.messages_unread > 0}
                  <span class="ml-auto text-[10px] font-medium px-1.5 rounded-full bg-accent-500/20" style="color: var(--color-accent-600)">{cl.messages_unread}</span>
                {/if}
              </button>
            {/each}
          </div>
        {/if}
      </div>
    {/if}

    <!-- User Labels section -->
    {#if userLabels.length > 0 && !$sidebarCollapsed}
      <div class="mt-4">
        <button
          onclick={() => userLabelsExpanded = !userLabelsExpanded}
          class="w-full flex items-center gap-2 px-3 mb-1"
        >
          <Icon name="chevron-right" size={12} class="transition-transform duration-200 {userLabelsExpanded ? 'rotate-90' : ''}" />
          <span class="text-[11px] font-semibold tracking-wider uppercase" style="color: var(--text-tertiary)">Labels</span>
        </button>
        {#if userLabelsExpanded}
          <div class="space-y-0.5">
            {#each userLabels as ul}
              <button
                onclick={() => selectLabel(ul.gmail_label_id)}
                class="w-full flex items-center gap-3 px-3 h-7 rounded-md text-sm transition-fast"
                class:font-medium={$currentMailbox === ul.gmail_label_id}
                style="color: {$currentMailbox === ul.gmail_label_id ? 'var(--text-primary)' : 'var(--text-secondary)'}; background: {$currentMailbox === ul.gmail_label_id ? 'var(--bg-hover)' : 'transparent'}"
              >
                {#if ul.color_bg}
                  <span class="w-3 h-3 rounded-full shrink-0" style="background: {ul.color_bg}"></span>
                {:else}
                  <Icon name="tag" size={16} class="shrink-0" />
                {/if}
                <span class="truncate">{ul.name}</span>
                {#if ul.messages_unread > 0}
                  <span class="ml-auto text-[10px] font-medium px-1.5 rounded-full bg-accent-500/20" style="color: var(--color-accent-600)">{ul.messages_unread}</span>
                {/if}
              </button>
            {/each}
          </div>
        {/if}
      </div>
    {/if}

    <!-- Accounts section -->
    {#if accountList.length > 0 && !$sidebarCollapsed}
      <div class="mt-6 mb-2 px-3 flex items-center justify-between">
        <span class="text-[11px] font-semibold tracking-wider uppercase" style="color: var(--text-tertiary)">Accounts</span>
      </div>
      <!-- All Accounts button (shown when filtering by a single account) -->
      {#if $selectedAccountId !== null}
        <button
          onclick={() => selectedAccountId.set(null)}
          class="w-full flex items-center gap-3 px-3 h-8 rounded-md text-sm transition-fast mb-0.5"
          style="color: var(--text-secondary); background: transparent"
        >
          <div class="w-[18px] h-[18px] rounded-full flex items-center justify-center shrink-0" style="background: var(--bg-tertiary)">
            <Icon name="grid" size={12} />
          </div>
          <span class="truncate">All Accounts</span>
        </button>
      {/if}
      {#each accountList as acct}
        {@const acctColor = $accountColorMap[acct.email]}
        <button
          onclick={() => selectedAccountId.set($selectedAccountId === acct.id ? null : acct.id)}
          class="w-full flex items-center gap-3 px-3 rounded-md text-sm transition-fast"
          style="color: {$selectedAccountId === acct.id ? 'var(--text-primary)' : 'var(--text-secondary)'}; background: {$selectedAccountId === acct.id ? 'var(--bg-hover)' : 'transparent'}; height: {acct.short_label || acct.description ? '40px' : '32px'}"
          title={acct.description || acct.email}
        >
          <div class="relative w-[18px] h-[18px] shrink-0">
            <div class="w-[18px] h-[18px] rounded-full flex items-center justify-center text-[10px] font-bold text-white" style="background: {acctColor ? acctColor.bg : 'var(--color-accent-500)'}">
              {acct.email[0].toUpperCase()}
            </div>
            <!-- Sync status dot -->
            {#if getAccountSyncState(acct) === 'syncing'}
              <span class="absolute -bottom-0.5 -right-0.5 w-2 h-2 rounded-full animate-pulse" style="background: var(--color-accent-500); box-shadow: 0 0 0 1.5px var(--bg-secondary)"></span>
            {:else if getAccountSyncState(acct) === 'rate_limited'}
              <span class="absolute -bottom-0.5 -right-0.5 w-2 h-2 rounded-full" style="background: #f59e0b; box-shadow: 0 0 0 1.5px var(--bg-secondary)"></span>
            {:else if getAccountSyncState(acct) === 'error'}
              <span class="absolute -bottom-0.5 -right-0.5 w-2 h-2 rounded-full" style="background: #ef4444; box-shadow: 0 0 0 1.5px var(--bg-secondary)"></span>
            {:else}
              <span class="absolute -bottom-0.5 -right-0.5 w-2 h-2 rounded-full" style="background: #22c55e; box-shadow: 0 0 0 1.5px var(--bg-secondary)"></span>
            {/if}
          </div>
          <div class="flex flex-col min-w-0 text-left">
            {#if acct.short_label || acct.description}
              <span class="text-sm truncate leading-tight">{acct.short_label || acct.description}</span>
              <span class="text-[10px] truncate leading-tight" style="color: var(--text-tertiary)">{acct.email}</span>
            {:else}
              <span class="truncate">{acct.email}</span>
            {/if}
          </div>
        </button>
      {/each}
    {/if}

    <!-- Collapsed sidebar: account color dots -->
    {#if accountList.length > 1 && $sidebarCollapsed}
      <div class="mt-4 flex flex-col items-center gap-1.5 px-2">
        {#each accountList as acct}
          {@const acctColor = $accountColorMap[acct.email]}
          <button
            onclick={() => selectedAccountId.set($selectedAccountId === acct.id ? null : acct.id)}
            class="w-6 h-6 rounded-full flex items-center justify-center text-[9px] font-bold text-white transition-fast"
            style="background: {acctColor ? acctColor.bg : 'var(--color-accent-500)'}; opacity: {$selectedAccountId === null || $selectedAccountId === acct.id ? 1 : 0.4}; box-shadow: {$selectedAccountId === acct.id ? '0 0 0 2px var(--bg-secondary), 0 0 0 3px ' + (acctColor ? acctColor.bg : 'var(--color-accent-500)') : 'none'}"
            title={acct.description || acct.email}
          >
            {acct.email[0].toUpperCase()}
          </button>
        {/each}
      </div>
    {/if}
  </nav>

  <!-- Bottom actions -->
  <div class="p-2 border-t shrink-0 space-y-0.5" style="border-color: var(--border-color)">
    <button
      onclick={() => currentPage.set('todos')}
      class="w-full flex items-center gap-3 px-3 h-8 rounded-md text-sm transition-fast"
      style="color: {$currentPage === 'todos' ? 'var(--text-primary)' : 'var(--text-secondary)'}; background: {$currentPage === 'todos' ? 'var(--bg-hover)' : 'transparent'}"
    >
      <Icon name="check-circle" size={18} class="shrink-0" />
      {#if !$sidebarCollapsed}
        <span>Todos</span>
        {#if pendingTodoCount > 0}
          <span class="ml-auto text-[10px] font-medium px-1.5 rounded-full bg-accent-500/20" style="color: var(--color-accent-600)">{pendingTodoCount}</span>
        {/if}
      {/if}
    </button>
    <button
      onclick={() => currentPage.set('stats')}
      class="w-full flex items-center gap-3 px-3 h-8 rounded-md text-sm transition-fast"
      style="color: {$currentPage === 'stats' ? 'var(--text-primary)' : 'var(--text-secondary)'}; background: {$currentPage === 'stats' ? 'var(--bg-hover)' : 'transparent'}"
    >
      <Icon name="bar-chart-2" size={18} class="shrink-0" />
      {#if !$sidebarCollapsed}
        <span>Stats</span>
      {/if}
    </button>
  </div>
</aside>
