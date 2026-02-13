<script>
  import { currentPage, currentMailbox, sidebarCollapsed, composeOpen, accounts, selectedAccountId, labels as labelsStore, syncStatus, smartFilter, todos, accountColorMap } from '../../lib/stores.js';
  import { api } from '../../lib/api.js';
  import { onMount } from 'svelte';

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
    { id: 'DRAFTS', label: 'Drafts', icon: 'draft' },
    { id: 'SPAM', label: 'Spam', icon: 'spam' },
    { id: 'TRASH', label: 'Trash', icon: 'trash' },
    { id: 'ALL', label: 'All Mail', icon: 'all' },
  ];

  const icons = {
    inbox: `<path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M2.25 13.5h3.86a2.25 2.25 0 012.012 1.244l.256.512a2.25 2.25 0 002.013 1.244h3.218a2.25 2.25 0 002.013-1.244l.256-.512a2.25 2.25 0 012.013-1.244h3.859m-19.5.338V18a2.25 2.25 0 002.25 2.25h15A2.25 2.25 0 0021.75 18v-4.162c0-.224-.034-.447-.1-.661L19.24 5.338a2.25 2.25 0 00-2.15-1.588H6.911a2.25 2.25 0 00-2.15 1.588L2.35 13.177a2.25 2.25 0 00-.1.661z"/>`,
    star: `<path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M11.48 3.499a.562.562 0 011.04 0l2.125 5.111a.563.563 0 00.475.345l5.518.442c.499.04.701.663.321.988l-4.204 3.602a.563.563 0 00-.182.557l1.285 5.385a.562.562 0 01-.84.61l-4.725-2.885a.563.563 0 00-.586 0L6.982 20.54a.562.562 0 01-.84-.61l1.285-5.386a.562.562 0 00-.182-.557l-4.204-3.602a.563.563 0 01.321-.988l5.518-.442a.563.563 0 00.475-.345L11.48 3.5z"/>`,
    send: `<path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M6 12L3.269 3.126A59.768 59.768 0 0121.485 12 59.77 59.77 0 013.27 20.876L5.999 12zm0 0h7.5"/>`,
    draft: `<path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M16.862 4.487l1.687-1.688a1.875 1.875 0 112.652 2.652L10.582 16.07a4.5 4.5 0 01-1.897 1.13L6 18l.8-2.685a4.5 4.5 0 011.13-1.897l8.932-8.931zm0 0L19.5 7.125M18 14v4.75A2.25 2.25 0 0115.75 21H5.25A2.25 2.25 0 013 18.75V8.25A2.25 2.25 0 015.25 6H10"/>`,
    spam: `<path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z"/>`,
    trash: `<path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M14.74 9l-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 01-2.244 2.077H8.084a2.25 2.25 0 01-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 00-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 013.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 00-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 00-7.5 0"/>`,
    all: `<path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M21.75 6.75v10.5a2.25 2.25 0 01-2.25 2.25h-15a2.25 2.25 0 01-2.25-2.25V6.75m19.5 0A2.25 2.25 0 0019.5 4.5h-15a2.25 2.25 0 00-2.25 2.25m19.5 0v.243a2.25 2.25 0 01-1.07 1.916l-7.5 4.615a2.25 2.25 0 01-2.36 0L3.32 8.91a2.25 2.25 0 01-1.07-1.916V6.75"/>`,
    label: `<path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M9.568 3H5.25A2.25 2.25 0 003 5.25v4.318c0 .597.237 1.17.659 1.591l9.581 9.581c.699.699 1.78.872 2.607.33a18.095 18.095 0 005.223-5.223c.542-.827.369-1.908-.33-2.607L11.16 3.66A2.25 2.25 0 009.568 3z"/><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M6 6h.008v.008H6V6z"/>`,
    folder: `<path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M2.25 12.75V12A2.25 2.25 0 014.5 9.75h15A2.25 2.25 0 0121.75 12v.75m-8.69-6.44l-2.12-2.12a1.5 1.5 0 00-1.061-.44H4.5A2.25 2.25 0 002.25 6v12a2.25 2.25 0 002.25 2.25h15A2.25 2.25 0 0021.75 18V9a2.25 2.25 0 00-2.25-2.25h-5.379a1.5 1.5 0 01-1.06-.44z"/>`,
    category: `<path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M3.75 6A2.25 2.25 0 016 3.75h2.25A2.25 2.25 0 0110.5 6v2.25a2.25 2.25 0 01-2.25 2.25H6a2.25 2.25 0 01-2.25-2.25V6zM3.75 15.75A2.25 2.25 0 016 13.5h2.25a2.25 2.25 0 012.25 2.25V18a2.25 2.25 0 01-2.25 2.25H6A2.25 2.25 0 013.75 18v-2.25zM13.5 6a2.25 2.25 0 012.25-2.25H18A2.25 2.25 0 0120.25 6v2.25A2.25 2.25 0 0118 10.5h-2.25a2.25 2.25 0 01-2.25-2.25V6zM13.5 15.75a2.25 2.25 0 012.25-2.25H18a2.25 2.25 0 012.25 2.25V18A2.25 2.25 0 0118 20.25h-2.25A2.25 2.25 0 0113.5 18v-2.25z"/>`,
    insights: `<path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M3.75 3v11.25A2.25 2.25 0 006 16.5h2.25M3.75 3h-1.5m1.5 0h16.5m0 0h1.5m-1.5 0v11.25A2.25 2.25 0 0118 16.5h-2.25m-7.5 0h7.5m-7.5 0l-1 3m8.5-3l1 3m0 0l.5 1.5m-.5-1.5h-9.5m0 0l-.5 1.5M9 11.25v1.5M12 9v3.75m3-6v6"/>`,
    stats: `<path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M3 13.125C3 12.504 3.504 12 4.125 12h2.25c.621 0 1.125.504 1.125 1.125v6.75C7.5 20.496 6.996 21 6.375 21h-2.25A1.125 1.125 0 013 19.875v-6.75zM9.75 8.625c0-.621.504-1.125 1.125-1.125h2.25c.621 0 1.125.504 1.125 1.125v11.25c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 01-1.125-1.125V8.625zM16.5 4.125c0-.621.504-1.125 1.125-1.125h2.25C20.496 3 21 3.504 21 4.125v15.75c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 01-1.125-1.125V4.125z"/>`,
  };

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
        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4.5v15m7.5-7.5h-15" />
        </svg>
        Compose
      {:else}
        <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4.5v15m7.5-7.5h-15" />
        </svg>
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
          <svg class="w-[18px] h-[18px] shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            {@html icons[mb.icon]}
          </svg>
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
          <svg class="w-3 h-3 transition-transform duration-200 {smartViewsExpanded ? 'rotate-90' : ''}" style="color: var(--text-tertiary)" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8.25 4.5l7.5 7.5-7.5 7.5" />
          </svg>
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
          <svg class="w-3 h-3 transition-transform duration-200 {categoriesExpanded ? 'rotate-90' : ''}" style="color: var(--text-tertiary)" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8.25 4.5l7.5 7.5-7.5 7.5" />
          </svg>
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
                <svg class="w-[16px] h-[16px] shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  {@html icons.category}
                </svg>
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
          <svg class="w-3 h-3 transition-transform duration-200 {userLabelsExpanded ? 'rotate-90' : ''}" style="color: var(--text-tertiary)" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8.25 4.5l7.5 7.5-7.5 7.5" />
          </svg>
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
                  <svg class="w-[16px] h-[16px] shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    {@html icons.label}
                  </svg>
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
            <svg class="w-3 h-3" style="color: var(--text-tertiary)" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3.75 6A2.25 2.25 0 016 3.75h2.25A2.25 2.25 0 0110.5 6v2.25a2.25 2.25 0 01-2.25 2.25H6a2.25 2.25 0 01-2.25-2.25V6zM13.5 15.75a2.25 2.25 0 012.25-2.25H18a2.25 2.25 0 012.25 2.25V18A2.25 2.25 0 0118 20.25h-2.25A2.25 2.25 0 0113.5 18v-2.25z" />
            </svg>
          </div>
          <span class="truncate">All Accounts</span>
        </button>
      {/if}
      {#each accountList as acct}
        {@const acctColor = $accountColorMap[acct.email]}
        <button
          onclick={() => selectedAccountId.set($selectedAccountId === acct.id ? null : acct.id)}
          class="w-full flex items-center gap-3 px-3 rounded-md text-sm transition-fast"
          style="color: {$selectedAccountId === acct.id ? 'var(--text-primary)' : 'var(--text-secondary)'}; background: {$selectedAccountId === acct.id ? 'var(--bg-hover)' : 'transparent'}; height: {acct.description ? '40px' : '32px'}"
          title={acct.email}
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
            {#if acct.description}
              <span class="text-sm truncate leading-tight">{acct.description}</span>
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
      onclick={() => currentPage.set('chat')}
      class="w-full flex items-center gap-3 px-3 h-8 rounded-md text-sm transition-fast"
      style="color: {$currentPage === 'chat' ? 'var(--text-primary)' : 'var(--text-secondary)'}; background: {$currentPage === 'chat' ? 'var(--bg-hover)' : 'transparent'}"
    >
      <svg class="w-[18px] h-[18px] shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M7.5 8.25h9m-9 3H12m-9.75 1.51c0 1.6 1.123 2.994 2.707 3.227 1.087.16 2.185.283 3.293.369V21l4.076-4.076a1.526 1.526 0 011.037-.443 48.282 48.282 0 005.68-.494c1.584-.233 2.707-1.626 2.707-3.228V6.741c0-1.602-1.123-2.995-2.707-3.228A48.394 48.394 0 0012 3c-2.392 0-4.744.175-7.043.513C3.373 3.746 2.25 5.14 2.25 6.741v6.018z" />
      </svg>
      {#if !$sidebarCollapsed}
        <span>Chat</span>
      {/if}
    </button>
    <button
      onclick={() => currentPage.set('todos')}
      class="w-full flex items-center gap-3 px-3 h-8 rounded-md text-sm transition-fast"
      style="color: {$currentPage === 'todos' ? 'var(--text-primary)' : 'var(--text-secondary)'}; background: {$currentPage === 'todos' ? 'var(--bg-hover)' : 'transparent'}"
    >
      <svg class="w-[18px] h-[18px] shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
      </svg>
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
      <svg class="w-[18px] h-[18px] shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        {@html icons.stats}
      </svg>
      {#if !$sidebarCollapsed}
        <span>Stats</span>
      {/if}
    </button>
    <button
      onclick={() => currentPage.set('ai-insights')}
      class="w-full flex items-center gap-3 px-3 h-8 rounded-md text-sm transition-fast"
      style="color: {$currentPage === 'ai-insights' ? 'var(--text-primary)' : 'var(--text-secondary)'}; background: {$currentPage === 'ai-insights' ? 'var(--bg-hover)' : 'transparent'}"
    >
      <svg class="w-[18px] h-[18px] shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        {@html icons.insights}
      </svg>
      {#if !$sidebarCollapsed}
        <span>AI Insights</span>
      {/if}
    </button>
    <button
      onclick={() => currentPage.set('admin')}
      class="w-full flex items-center gap-3 px-3 h-8 rounded-md text-sm transition-fast"
      style="color: {$currentPage === 'admin' ? 'var(--text-primary)' : 'var(--text-secondary)'}; background: {$currentPage === 'admin' ? 'var(--bg-hover)' : 'transparent'}"
    >
      <svg class="w-[18px] h-[18px] shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M9.594 3.94c.09-.542.56-.94 1.11-.94h2.593c.55 0 1.02.398 1.11.94l.213 1.281c.063.374.313.686.645.87.074.04.147.083.22.127.324.196.72.257 1.075.124l1.217-.456a1.125 1.125 0 011.37.49l1.296 2.247a1.125 1.125 0 01-.26 1.431l-1.003.827c-.293.24-.438.613-.431.992a6.759 6.759 0 010 .255c-.007.378.138.75.43.99l1.005.828c.424.35.534.954.26 1.43l-1.298 2.247a1.125 1.125 0 01-1.369.491l-1.217-.456c-.355-.133-.75-.072-1.076.124a6.57 6.57 0 01-.22.128c-.331.183-.581.495-.644.869l-.213 1.28c-.09.543-.56.941-1.11.941h-2.594c-.55 0-1.02-.398-1.11-.94l-.213-1.281c-.062-.374-.312-.686-.644-.87a6.52 6.52 0 01-.22-.127c-.325-.196-.72-.257-1.076-.124l-1.217.456a1.125 1.125 0 01-1.369-.49l-1.297-2.247a1.125 1.125 0 01.26-1.431l1.004-.827c.292-.24.437-.613.43-.992a6.932 6.932 0 010-.255c.007-.378-.138-.75-.43-.99l-1.004-.828a1.125 1.125 0 01-.26-1.43l1.297-2.247a1.125 1.125 0 011.37-.491l1.216.456c.356.133.751.072 1.076-.124.072-.044.146-.087.22-.128.332-.183.582-.495.644-.869l.214-1.281z"/>
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"/>
      </svg>
      {#if !$sidebarCollapsed}
        <span>Settings</span>
      {/if}
    </button>
  </div>
</aside>
