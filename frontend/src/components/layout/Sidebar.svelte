<script>
  import { currentPage, currentMailbox, sidebarCollapsed, composeOpen, accounts, selectedAccountId } from '../../lib/stores.js';
  import { api } from '../../lib/api.js';
  import { onMount } from 'svelte';

  let labels = $state([]);
  let accountList = $state([]);

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
  };

  function selectMailbox(id) {
    currentMailbox.set(id);
    currentPage.set('inbox');
  }

  onMount(async () => {
    try {
      accountList = await api.listAccounts();
      accounts.set(accountList);
    } catch {
      // Not authenticated or no accounts yet
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

    <!-- Accounts section -->
    {#if accountList.length > 0 && !$sidebarCollapsed}
      <div class="mt-6 mb-2 px-3">
        <span class="text-[11px] font-semibold tracking-wider uppercase" style="color: var(--text-tertiary)">Accounts</span>
      </div>
      {#each accountList as acct}
        <button
          onclick={() => selectedAccountId.set($selectedAccountId === acct.id ? null : acct.id)}
          class="w-full flex items-center gap-3 px-3 h-8 rounded-md text-sm transition-fast"
          style="color: {$selectedAccountId === acct.id ? 'var(--text-primary)' : 'var(--text-secondary)'}; background: {$selectedAccountId === acct.id ? 'var(--bg-hover)' : 'transparent'}"
        >
          <div class="w-[18px] h-[18px] rounded-full bg-accent-500/20 flex items-center justify-center text-[10px] font-bold shrink-0" style="color: var(--color-accent-600)">
            {acct.email[0].toUpperCase()}
          </div>
          <span class="truncate">{acct.email}</span>
        </button>
      {/each}
    {/if}
  </nav>

  <!-- Bottom actions -->
  <div class="p-2 border-t shrink-0" style="border-color: var(--border-color)">
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
