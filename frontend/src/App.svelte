<script>
  import { onMount } from 'svelte';
  import { api, setUnauthorizedHandler } from './lib/api.js';
  import { user, currentPage, showToast, toastMessage } from './lib/stores.js';
  import { theme } from './lib/theme.js';
  import Login from './pages/Login.svelte';
  import Inbox from './pages/Inbox.svelte';
  import Admin from './pages/Admin.svelte';
  import Compose from './pages/Compose.svelte';
  import Layout from './components/layout/Layout.svelte';
  import Toast from './components/common/Toast.svelte';

  let loading = $state(true);

  onMount(async () => {
    setUnauthorizedHandler(() => {
      user.set(null);
    });

    try {
      const me = await api.me();
      user.set(me);
    } catch {
      user.set(null);
    }
    loading = false;

    // Check URL params
    const params = new URLSearchParams(window.location.search);
    if (params.get('page')) {
      currentPage.set(params.get('page'));
    }
    if (params.get('connected') === 'true') {
      showToast('Google account connected successfully', 'success');
      // Clean URL
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
{:else if !$user}
  <Login />
{:else}
  <Layout>
    {#if $currentPage === 'admin'}
      <Admin />
    {:else if $currentPage === 'compose'}
      <Compose />
    {:else}
      <Inbox />
    {/if}
  </Layout>
{/if}

{#if $toastMessage}
  <Toast message={$toastMessage.message} type={$toastMessage.type} />
{/if}
