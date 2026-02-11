<script>
  import { theme } from '../../lib/theme.js';
  import { api } from '../../lib/api.js';
  import { user, sidebarCollapsed, searchQuery, currentPage, currentMailbox } from '../../lib/stores.js';

  let searchValue = $state('');

  function handleSearch(e) {
    if (e.key === 'Enter') {
      searchQuery.set(searchValue);
    }
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
    return $currentMailbox.charAt(0) + $currentMailbox.slice(1).toLowerCase();
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
        class="w-full h-8 pl-9 pr-3 rounded-lg text-sm outline-none border"
        style="background: var(--bg-primary); border-color: var(--border-color); color: var(--text-primary)"
      />
    </div>
  </div>

  <div class="flex items-center gap-2">
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
