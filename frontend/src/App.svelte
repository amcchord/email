<script>
  import { onMount } from 'svelte';
  import { api, setUnauthorizedHandler } from './lib/api.js';
  import {
    authenticatedSessionGeneration,
    captureAuthenticatedSession,
    currentPage,
    dismissToast,
    forceSyncPoll,
    isAuthenticatedSessionCurrent,
    showToast,
    startSyncPolling,
    stopSyncPolling,
    threadOrder,
    toastMessages,
    transitionAuthenticatedSession,
    user,
  } from './lib/stores.js';
  import { theme, activeTheme } from './lib/theme.js';
  import { startVersionPolling } from './lib/autoReload.js';
  import { startRealtime, stopRealtime } from './lib/realtime.js';
  import Login from './pages/Login.svelte';
  import DeviceAuth from './pages/DeviceAuth.svelte';
  import Layout from './components/layout/Layout.svelte';
  import OutboundSendStatus from './components/email/OutboundSendStatus.svelte';
  import Toast from './components/common/Toast.svelte';
  import LazyRouteState from './components/common/LazyRouteState.svelte';
  import {
    DEFAULT_AUTHENTICATED_PAGE,
    createLazyRouteCoordinator,
    getLazyRouteLabel,
    normalizeAuthenticatedPage,
  } from './lib/lazyRoutes.js';
  import { accountOAuthOutcome } from './lib/oauthResult.js';

  let loading = $state(true);
  let standaloneEmailId = $state(null);
  let deviceAuthCode = $state(null);
  let historyInitialized = false;
  let historyNavigationPage = null;
  let focusObservedPage = null;
  let routeState = $state({ key: null, status: 'idle', component: null, error: null });

  let authenticatedPage = $derived(normalizeAuthenticatedPage($currentPage));
  let lazyRouteKey = $derived.by(() => {
    if (loading || !$user || deviceAuthCode !== null) return null;
    if (standaloneEmailId !== null) return 'standalone-email';
    return authenticatedPage;
  });
  let lazyRouteLabel = $derived(getLazyRouteLabel(lazyRouteKey));

  const routeCoordinator = createLazyRouteCoordinator({
    onState: nextState => { routeState = nextState; },
  });

  let observedSessionGeneration = null;
  $effect(() => {
    const generation = $authenticatedSessionGeneration;
    const authenticated = Boolean($user);
    if (generation === observedSessionGeneration) return;
    observedSessionGeneration = generation;
    stopSyncPolling();
    stopRealtime();
    if (authenticated) {
      startSyncPolling(() => api.listAccounts());
      startRealtime();
      void loadAuthenticatedPreferences(captureAuthenticatedSession());
    }
  });

  async function loadAuthenticatedPreferences(session) {
    try {
      const uiPrefs = await api.getUIPreferences();
      if (!isAuthenticatedSessionCurrent(session)) return;
      if (uiPrefs.thread_order) {
        threadOrder.set(uiPrefs.thread_order);
      }
      if (uiPrefs.theme) {
        activeTheme.set(uiPrefs.theme);
      }
      if (uiPrefs.color_scheme) {
        theme.set(uiPrefs.color_scheme);
      }
    } catch {
      // Keep this browser's non-sensitive local preferences.
    }
  }

  function parseStandaloneEmailId(params) {
    if (params.get('view') !== 'email' || !params.get('id')) return null;
    const parsed = Number(params.get('id'));
    return Number.isSafeInteger(parsed) && parsed > 0 ? parsed : null;
  }

  function canonicalPageLocation(page) {
    const url = new URL(window.location.href);
    if (page === DEFAULT_AUTHENTICATED_PAGE) url.searchParams.delete('page');
    else url.searchParams.set('page', page);
    if (page !== 'admin') url.searchParams.delete('tab');
    return `${url.pathname}${url.search}${url.hash}`;
  }

  function retryLazyRoute() {
    // Native module import failures remain memoized for this document in
    // Chromium. Reloading preserves the canonical route and fetches the fresh
    // entry graph, including new hashes after a deployment.
    window.location.reload();
  }

  function focusMainRegion() {
    requestAnimationFrame(() => {
      document.querySelector('main')?.focus({ preventScroll: true });
    });
  }

  function focusMainRegionIfLost() {
    requestAnimationFrame(() => {
      const activeElement = document.activeElement;
      if (!activeElement || activeElement === document.body || !activeElement.isConnected) {
        document.querySelector('main')?.focus({ preventScroll: true });
      }
    });
  }

  function goToFlow() {
    currentPage.set(DEFAULT_AUTHENTICATED_PAGE);
    focusMainRegion();
  }

  onMount(async () => {
    setUnauthorizedHandler(() => {
      transitionAuthenticatedSession(null);
    });

    // Check if this is a device auth page or pop-out email view
    const params = new URLSearchParams(window.location.search);
    if (window.location.pathname === '/auth/device') {
      deviceAuthCode = params.get('code') || '';
    }
    standaloneEmailId = parseStandaloneEmailId(params);

    try {
      const me = await api.me();
      transitionAuthenticatedSession(me);
    } catch {
      transitionAuthenticatedSession(null);
    }
    // Poll for build version changes and auto-reload when restart.sh runs
    startVersionPolling();

    if (params.has('page')) currentPage.set(normalizeAuthenticatedPage(params.get('page')));

    const oauthOutcome = accountOAuthOutcome(window.location.href);
    if (oauthOutcome) {
      showToast(oauthOutcome.message, oauthOutcome.type, 6000);
      window.history.replaceState({}, '', oauthOutcome.location);
      if (oauthOutcome.type === 'success') forceSyncPoll();
    }

    loading = false;

    // Listen for Electron menu commands (Cmd+N → compose, Cmd+, → settings)
    if (window.electronAPI?.isElectron) {
      window.addEventListener('electron-navigate', (e) => {
        currentPage.set(normalizeAuthenticatedPage(e.detail?.page));
      });
    }
  });

  onMount(() => {
    const handlePopState = () => {
      const nextParams = new URLSearchParams(window.location.search);
      const nextPage = normalizeAuthenticatedPage(nextParams.get('page') || DEFAULT_AUTHENTICATED_PAGE);
      historyNavigationPage = nextPage;
      currentPage.set(nextPage);
      focusMainRegion();
    };
    window.addEventListener('popstate', handlePopState);
    return () => window.removeEventListener('popstate', handlePopState);
  });

  // Normalize any navigation source before it reaches the route loader.
  $effect(() => {
    if (loading || !$user || deviceAuthCode !== null || standaloneEmailId !== null) return;
    if ($currentPage !== authenticatedPage) currentPage.set(authenticatedPage);
  });

  // Full Compose is the safe recovery surface for standalone replies. Leave
  // the pop-out route in-place (without a reload) when a reply is expanded or
  // restored so its in-memory draft cannot disappear behind the standalone
  // URL branch.
  $effect(() => {
    const page = $currentPage;
    if (
      typeof window === 'undefined'
      || loading
      || !$user
      || standaloneEmailId === null
      || page !== 'compose'
    ) return;
    const url = new URL(window.location.href);
    url.searchParams.delete('view');
    url.searchParams.delete('id');
    url.searchParams.set('page', 'compose');
    window.history.replaceState({ mailPage: 'compose' }, '', `${url.pathname}${url.search}${url.hash}`);
    standaloneEmailId = null;
  });

  // Feature screens also navigate directly (for example Todo → message or
  // Compose → Inbox). Preserve focus on shell controls that survive the route,
  // but recover to the named main region when the focused source was removed.
  $effect(() => {
    const page = authenticatedPage;
    if (loading || !$user || deviceAuthCode !== null || standaloneEmailId !== null) return;
    if (focusObservedPage === null) {
      focusObservedPage = page;
      return;
    }
    if (page === focusObservedPage) return;
    focusObservedPage = page;
    focusMainRegionIfLost();
  });

  // Keep feature navigation deep-linkable. Initial normalization and popstate
  // replace the current entry; user-initiated navigation creates real browser
  // history so Back and Forward move between app sections.
  $effect(() => {
    const page = authenticatedPage;
    if (typeof window === 'undefined' || loading || !$user || deviceAuthCode !== null || standaloneEmailId !== null) return;
    const next = canonicalPageLocation(page);
    const current = `${window.location.pathname}${window.location.search}${window.location.hash}`;
    const fromHistory = historyNavigationPage === page;
    historyNavigationPage = null;

    if (!historyInitialized || fromHistory) {
      historyInitialized = true;
      if (next !== current) window.history.replaceState({ mailPage: page }, '', next);
    } else if (next !== current) {
      window.history.pushState({ mailPage: page }, '', next);
    }
  });

  // Request only the active feature chunk. The coordinator clears the old
  // component immediately and ignores any late result from superseded routes.
  $effect(() => {
    const key = lazyRouteKey;
    if (!key) {
      routeCoordinator.cancel();
      return;
    }
    void routeCoordinator.open(key);
  });
</script>

{#if loading}
  <div class="h-screen flex items-center justify-center" style="background: var(--bg-primary)" aria-busy="true">
    <div class="flex flex-col items-center gap-3" role="status" aria-live="polite">
      <div class="w-8 h-8 border-2 rounded-full animate-spin" style="border-color: var(--border-color); border-top-color: var(--color-accent-500)"></div>
      <span class="text-sm" style="color: var(--text-secondary)">Opening your mailbox…</span>
    </div>
  </div>
{:else if deviceAuthCode !== null}
  {#key $authenticatedSessionGeneration}
    <DeviceAuth />
  {/key}
{:else if standaloneEmailId !== null}
  <!-- Pop-out email viewer (no layout chrome) -->
  {#if $user}
    {#key $authenticatedSessionGeneration}
      <div class="h-screen min-h-0 flex flex-col" style="background: var(--bg-primary)">
        <OutboundSendStatus />
        <div class="min-h-0 flex-1">
          <LazyRouteState
            expectedKey={lazyRouteKey}
            label={lazyRouteLabel}
            {routeState}
            componentProps={{ emailId: standaloneEmailId }}
            onRetry={retryLazyRoute}
          />
        </div>
      </div>
    {/key}
  {:else}
    <Login />
  {/if}
{:else if !$user}
  <Login />
{:else}
  {#key $authenticatedSessionGeneration}
    <Layout>
      <LazyRouteState
        expectedKey={lazyRouteKey}
        label={lazyRouteLabel}
        {routeState}
        inShell
        canGoHome={lazyRouteKey !== DEFAULT_AUTHENTICATED_PAGE}
        onRetry={retryLazyRoute}
        onGoHome={goToFlow}
      />
    </Layout>
  {/key}
{/if}

{#if $toastMessages.length}
  <div class="toast-stack" aria-label="Notifications">
    {#each $toastMessages as toast (toast.id)}
      <Toast {toast} onDismiss={() => dismissToast(toast.id)} />
    {/each}
  </div>
{/if}

<style>
  .toast-stack {
    position: fixed;
    right: 1.5rem;
    bottom: 1.5rem;
    z-index: 70;
    display: flex;
    width: min(28rem, calc(100vw - 2rem));
    flex-direction: column;
    align-items: stretch;
    gap: 0.625rem;
    pointer-events: none;
  }

  @media (max-width: 767px) {
    .toast-stack {
      right: 1rem;
      bottom: calc(5.25rem + env(safe-area-inset-bottom));
    }
  }
</style>
