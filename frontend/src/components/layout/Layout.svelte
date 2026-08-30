<script>
  import { onMount } from 'svelte';
  import Sidebar from './Sidebar.svelte';
  import TopBar from './TopBar.svelte';
  import KeyboardShortcutHandler from '../common/KeyboardShortcutHandler.svelte';
  import ShortcutOverlay from '../common/ShortcutOverlay.svelte';
  import ShortcutHelpModal from '../common/ShortcutHelpModal.svelte';
  import CommandPalette from '../common/CommandPalette.svelte';
  import OutboundSendStatus from '../email/OutboundSendStatus.svelte';
  import { sidebarCollapsed, currentPage } from '../../lib/stores.js';
  import { getLazyRouteLabel, normalizeAuthenticatedPage, preloadAuthenticatedPage } from '../../lib/lazyRoutes.js';
  import { openCommandPalette, registerActions, toggleShortcutHelp, loadUserShortcuts } from '../../lib/shortcutStore.js';
  import { theme } from '../../lib/theme.js';

  let { children } = $props();

  let showSidebar = $derived($currentPage === 'inbox');
  let pageLabel = $derived(getLazyRouteLabel(normalizeAuthenticatedPage($currentPage)));

  function focusMainRegion() {
    requestAnimationFrame(() => {
      document.querySelector('main')?.focus({ preventScroll: true });
    });
  }

  function navigateByShortcut(page) {
    currentPage.set(page);
    focusMainRegion();
  }

  async function focusInboxSearchWhenReady() {
    currentPage.set('inbox');
    // Search lives in the eager shell, so focus it immediately while the
    // heavier Inbox screen continues downloading in parallel.
    void preloadAuthenticatedPage('inbox');

    // TopBar reacts on the next render turn. A short animation-frame loop is
    // resilient to both cold chunks and warm revisits.
    for (let attempt = 0; attempt < 30; attempt += 1) {
      await new Promise(resolve => requestAnimationFrame(resolve));
      const searchInput = document.querySelector('[data-shortcut="nav.search"]');
      if (searchInput) {
        searchInput.focus();
        searchInput.select();
        return;
      }
    }
  }

  onMount(() => {
    // Load user's custom shortcut overrides from API
    loadUserShortcuts();

    // Register global navigation shortcuts that work on every page
    const cleanup = registerActions({
      'nav.flow':     () => navigateByShortcut('flow'),
      'nav.inbox':    () => navigateByShortcut('inbox'),
      'nav.calendar': () => navigateByShortcut('calendar'),
      'nav.todos':    () => navigateByShortcut('todos'),
      'nav.stats':    () => navigateByShortcut('stats'),
      'nav.insights': () => navigateByShortcut('ai-insights'),
      'nav.chat':     () => navigateByShortcut('chat'),
      'nav.subscriptions': () => navigateByShortcut('subscriptions'),
      'nav.settings': () => navigateByShortcut('admin'),
      'nav.compose':  () => navigateByShortcut('compose'),
      // Do not return the promise: the command palette must close and remove
      // its inert shell before the delayed task moves focus to search.
      'nav.search':   () => { void focusInboxSearchWhenReady(); },
      'nav.commands': openCommandPalette,
      'nav.help':     toggleShortcutHelp,
      'nav.theme':    () => theme.toggle(),
    });

    return cleanup;
  });
</script>

<KeyboardShortcutHandler />
<ShortcutOverlay />
<ShortcutHelpModal />
<CommandPalette />

<div data-app-shell class="h-screen flex flex-col overflow-hidden" style="background: var(--bg-primary)">
  <!-- TopBar always full-width so tabs stay in the same position -->
  <TopBar />
  <OutboundSendStatus />
  <div class="flex-1 flex overflow-hidden">
    {#if showSidebar}
      {#if !$sidebarCollapsed}
        <button
          class="mail-sidebar-backdrop"
          aria-label="Close mail navigation"
          onclick={() => sidebarCollapsed.set(true)}
        ></button>
      {/if}
      <Sidebar />
    {/if}
    <main class="flex-1 min-w-0 overflow-hidden" aria-label="{pageLabel} content" tabindex="-1">
      {@render children()}
    </main>
  </div>
</div>

<style>
  .mail-sidebar-backdrop {
    display: none;
  }

  @media (max-width: 767px) {
    .mail-sidebar-backdrop {
      display: block;
      position: fixed;
      inset: 0;
      top: 6.25rem;
      z-index: 35;
      border: 0;
      background: rgb(0 0 0 / 0.35);
      backdrop-filter: blur(2px);
    }
  }
</style>
