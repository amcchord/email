<script>
  import { onMount } from 'svelte';
  import Sidebar from './Sidebar.svelte';
  import TopBar from './TopBar.svelte';
  import KeyboardShortcutHandler from '../common/KeyboardShortcutHandler.svelte';
  import ShortcutOverlay from '../common/ShortcutOverlay.svelte';
  import ShortcutHelpModal from '../common/ShortcutHelpModal.svelte';
  import CommandPalette from '../common/CommandPalette.svelte';
  import OutboundSendStatus from '../email/OutboundSendStatus.svelte';
  import { sidebarCollapsed, currentPage, composeData, savedViewFocusRequest, savedViews, savedViewsMax, searchQuery, createAuthenticatedSessionGuard } from '../../lib/stores.js';
  import { newComposeIntent } from '../../lib/composeDraft.js';
  import { getLazyRouteLabel, normalizeAuthenticatedPage, preloadAuthenticatedPage } from '../../lib/lazyRoutes.js';
  import { openCommandPalette, registerActions, toggleShortcutHelp, loadUserShortcuts } from '../../lib/shortcutStore.js';
  import { theme } from '../../lib/theme.js';
  import { isSavableStructuredSearch } from '../../lib/savedViews.js';
  import { refreshSavedViews, requestSavedViewEditor } from '../../lib/savedViewState.js';

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

  function startNewCompose() {
    composeData.set(newComposeIntent());
    currentPage.set('compose');
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

  async function focusSavedViewsWhenReady() {
    currentPage.set('inbox');
    void preloadAuthenticatedPage('inbox');
    sidebarCollapsed.set(false);
    for (let attempt = 0; attempt < 30; attempt += 1) {
      await new Promise(resolve => requestAnimationFrame(resolve));
      const section = document.querySelector('[data-saved-views-focus]');
      if (section) {
        savedViewFocusRequest.update(value => value + 1);
        section.focus();
        return;
      }
    }
  }

  onMount(() => {
    // Load user's custom shortcut overrides from API
    loadUserShortcuts();
    const savedViewsSession = createAuthenticatedSessionGuard();
    void refreshSavedViews(savedViewsSession);

    // Register global navigation shortcuts that work on every page
    const cleanup = registerActions({
      'nav.flow':     () => navigateByShortcut('flow'),
      'nav.inbox':    () => navigateByShortcut('inbox'),
      'nav.savedViews': () => { void focusSavedViewsWhenReady(); },
      'nav.calendar': () => navigateByShortcut('calendar'),
      'nav.glance':   () => navigateByShortcut('at-a-glance'),
      'nav.contacts': () => navigateByShortcut('contacts'),
      'nav.todos':    () => navigateByShortcut('todos'),
      'nav.stats':    () => navigateByShortcut('stats'),
      'nav.insights': () => navigateByShortcut('ai-insights'),
      'nav.chat':     () => navigateByShortcut('chat'),
      'nav.subscriptions': () => navigateByShortcut('subscriptions'),
      'nav.settings': () => navigateByShortcut('admin'),
      'nav.compose':  startNewCompose,
      // Do not return the promise: the command palette must close and remove
      // its inert shell before the delayed task moves focus to search.
      'nav.search':   () => { void focusInboxSearchWhenReady(); },
      'nav.commands': openCommandPalette,
      'nav.help':     toggleShortcutHelp,
      'nav.theme':    () => theme.toggle(),
      'savedViews.saveCurrent': {
        run: () => requestSavedViewEditor({ mode: 'create' }),
        isEnabled: () => $currentPage === 'inbox' && isSavableStructuredSearch($searchQuery) && $savedViews.length < $savedViewsMax,
        disabledReason: () => $savedViews.length >= $savedViewsMax
          ? `Saved Views is full (${ $savedViewsMax }). Manage an existing view first.`
          : 'Open a valid structured email search first.',
      },
    });

    return () => {
      savedViewsSession.dispose();
      cleanup();
    };
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
