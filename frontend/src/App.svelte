<script>
  import { onMount } from 'svelte';
  import { api, setUnauthorizedHandler } from './lib/api.js';
  import { user, currentPage, showToast, toastMessage, startSyncPolling, stopSyncPolling } from './lib/stores.js';
  import { theme } from './lib/theme.js';
  import { startVersionPolling } from './lib/autoReload.js';
  import Login from './pages/Login.svelte';
  import Inbox from './pages/Inbox.svelte';
  import Admin from './pages/Admin.svelte';
  import Compose from './pages/Compose.svelte';
  import Stats from './pages/Stats.svelte';
  import AIInsights from './pages/AIInsights.svelte';
  import Todos from './pages/Todos.svelte';
  import Chat from './pages/Chat.svelte';
  import EmailViewStandalone from './pages/EmailViewStandalone.svelte';
  import Layout from './components/layout/Layout.svelte';
  import Toast from './components/common/Toast.svelte';

  let loading = $state(true);
  let standaloneEmailId = $state(null);

  onMount(async () => {
    setUnauthorizedHandler(() => {
      user.set(null);
      stopSyncPolling();
    });

    // Check if this is a pop-out email view
    const params = new URLSearchParams(window.location.search);
    if (params.get('view') === 'email' && params.get('id')) {
      standaloneEmailId = parseInt(params.get('id'));
    }

    try {
      const me = await api.me();
      user.set(me);
      // Start polling sync status once authenticated
      startSyncPolling(() => api.listAccounts());
    } catch {
      user.set(null);
    }
    loading = false;

    // Poll for build version changes and auto-reload when restart.sh runs
    startVersionPolling();

    if (params.get('page')) {
      currentPage.set(params.get('page'));
    }
    if (params.get('connected') === 'true') {
      showToast('Google account connected successfully', 'success');
      window.history.replaceState({}, '', '/');
    }
  });
</script>

{#if loading}
  <div class="h-screen flex items-center justify-center" style="background: var(--bg-primary)">
    <div class="flex flex-col items-center gap-3">
      <div class="w-8 h-8 border-2 rounded-full animate-spin" style="border-color: var(--border-color); border-top-color: var(--color-accent-500)"></div>
      <span class="text-sm" style="color: var(--text-secondary)">Loading...</span>
    </div>
  </div>
{:else if standaloneEmailId}
  <!-- Pop-out email viewer (no layout chrome) -->
  {#if $user}
    <EmailViewStandalone emailId={standaloneEmailId} />
  {:else}
    <Login />
  {/if}
{:else if !$user}
  <Login />
{:else}
  <Layout>
    {#if $currentPage === 'admin'}
      <Admin />
    {:else if $currentPage === 'compose'}
      <Compose />
    {:else if $currentPage === 'stats'}
      <Stats />
    {:else if $currentPage === 'ai-insights'}
      <AIInsights />
    {:else if $currentPage === 'todos'}
      <Todos />
    {:else if $currentPage === 'chat'}
      <Chat />
    {:else}
      <Inbox />
    {/if}
  </Layout>
{/if}

{#if $toastMessage}
  <Toast message={$toastMessage.message} type={$toastMessage.type} />
{/if}
