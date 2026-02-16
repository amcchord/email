<script>
  import { onMount } from 'svelte';
  import Sidebar from './Sidebar.svelte';
  import TopBar from './TopBar.svelte';
  import KeyboardShortcutHandler from '../common/KeyboardShortcutHandler.svelte';
  import ShortcutOverlay from '../common/ShortcutOverlay.svelte';
  import ShortcutHelpModal from '../common/ShortcutHelpModal.svelte';
  import { sidebarCollapsed, currentPage, composeOpen, searchQuery } from '../../lib/stores.js';
  import { registerActions, helpModalOpen, loadUserShortcuts } from '../../lib/shortcutStore.js';
  import { theme } from '../../lib/theme.js';

  let { children } = $props();

  let showSidebar = $derived($currentPage === 'inbox');

  onMount(() => {
    // Load user's custom shortcut overrides from API
    loadUserShortcuts();

    // Register global navigation shortcuts that work on every page
    const cleanup = registerActions({
      'nav.flow':     () => currentPage.set('flow'),
      'nav.inbox':    () => currentPage.set('inbox'),
      'nav.calendar': () => currentPage.set('calendar'),
      'nav.todos':    () => currentPage.set('todos'),
      'nav.stats':    () => currentPage.set('stats'),
      'nav.insights': () => currentPage.set('ai-insights'),
      'nav.chat':     () => currentPage.set('chat'),
      'nav.settings': () => currentPage.set('admin'),
      'nav.compose':  () => composeOpen.set(true),
      'nav.search':   () => {
        const searchInput = document.querySelector('[data-shortcut="nav.search"]');
        if (searchInput) searchInput.focus();
      },
      'nav.help':     () => helpModalOpen.update(v => !v),
      'nav.theme':    () => theme.toggle(),
    });

    return cleanup;
  });
</script>

<KeyboardShortcutHandler />
<ShortcutOverlay />
<ShortcutHelpModal />

<div class="h-screen flex flex-col overflow-hidden" style="background: var(--bg-primary)">
  <!-- TopBar always full-width so tabs stay in the same position -->
  <TopBar />
  <div class="flex-1 flex overflow-hidden">
    {#if showSidebar}
      <Sidebar />
    {/if}
    <main class="flex-1 overflow-hidden">
      {@render children()}
    </main>
  </div>
</div>
