<script>
  import { api } from '../lib/api.js';
  import { user, showToast } from '../lib/stores.js';
  import { theme } from '../lib/theme.js';

  let username = $state('');
  let password = $state('');
  let loading = $state(false);
  let error = $state('');

  async function handleLogin(e) {
    e.preventDefault();
    loading = true;
    error = '';

    try {
      const result = await api.login(username, password);
      user.set(result.user);
    } catch (err) {
      error = err.message || 'Login failed';
    }
    loading = false;
  }
</script>

<div class="min-h-screen flex items-center justify-center p-4" style="background: var(--bg-primary)">
  <div class="w-full max-w-sm">
    <!-- Logo -->
    <div class="text-center mb-8">
      <div class="inline-flex items-center justify-center w-16 h-16 rounded-2xl mb-4 bg-accent-500/10">
        <span class="text-3xl">✉</span>
      </div>
      <h1 class="text-2xl font-bold tracking-tight" style="color: var(--text-primary)">Mail</h1>
      <p class="mt-1 text-sm" style="color: var(--text-secondary)">Sign in to your account</p>
    </div>

    <!-- Form -->
    <form onsubmit={handleLogin} class="rounded-xl border p-6 space-y-4" style="background: var(--bg-secondary); border-color: var(--border-color); box-shadow: var(--shadow-md)">
      {#if error}
        <div class="px-3 py-2 rounded-lg text-sm bg-red-50 text-red-700 dark:bg-red-900/30 dark:text-red-400 border border-red-200 dark:border-red-800">
          {error}
        </div>
      {/if}

      <div class="space-y-1.5">
        <label class="block text-xs font-medium tracking-wide uppercase" style="color: var(--text-secondary)" for="username">Username</label>
        <input
          id="username"
          type="text"
          bind:value={username}
          placeholder="Enter username"
          required
          class="w-full h-10 px-3 rounded-lg text-sm outline-none border transition-fast"
          style="background: var(--bg-primary); border-color: var(--border-color); color: var(--text-primary)"
        />
      </div>

      <div class="space-y-1.5">
        <label class="block text-xs font-medium tracking-wide uppercase" style="color: var(--text-secondary)" for="password">Password</label>
        <input
          id="password"
          type="password"
          bind:value={password}
          placeholder="Enter password"
          required
          class="w-full h-10 px-3 rounded-lg text-sm outline-none border transition-fast"
          style="background: var(--bg-primary); border-color: var(--border-color); color: var(--text-primary)"
        />
      </div>

      <button
        type="submit"
        disabled={loading}
        class="w-full h-10 rounded-lg text-sm font-medium bg-accent-600 text-white hover:bg-accent-700 transition-fast disabled:opacity-50"
      >
        {#if loading}
          <span class="inline-flex items-center gap-2">
            <span class="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin"></span>
            Signing in...
          </span>
        {:else}
          Sign in
        {/if}
      </button>
    </form>

    <!-- Theme toggle -->
    <div class="mt-6 text-center">
      <button
        onclick={() => theme.toggle()}
        class="text-xs transition-fast"
        style="color: var(--text-tertiary)"
      >
        Switch to {$theme === 'dark' ? 'light' : 'dark'} mode
      </button>
    </div>
  </div>
</div>
