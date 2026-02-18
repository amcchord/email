<script>
  import { onMount } from 'svelte';
  import { api } from '../lib/api.js';
  import { user, showToast } from '../lib/stores.js';
  import { theme, getEffectiveMode } from '../lib/theme.js';

  let username = $state('');
  let password = $state('');
  let loading = $state(false);
  let googleLoading = $state(false);
  let error = $state('');
  let showPasswordLogin = $state(false);

  onMount(() => {
    // Check for login errors from OAuth redirect
    const params = new URLSearchParams(window.location.search);
    const loginError = params.get('login_error');
    if (loginError === 'not_allowed') {
      error = 'Your Google account is not authorized to access this system.';
      window.history.replaceState({}, '', '/');
    } else if (loginError === 'no_email') {
      error = 'Could not get email from Google. Please try again.';
      window.history.replaceState({}, '', '/');
    }
  });

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

  async function handleGoogleLogin() {
    googleLoading = true;
    error = '';
    try {
      const result = await api.get('/auth/google/login');
      window.location.href = result.auth_url;
    } catch (err) {
      error = err.message || 'Google login not available';
      googleLoading = false;
    }
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

    <div class="rounded-xl border p-6 space-y-4" style="background: var(--bg-elevated); border-color: var(--border-color); box-shadow: var(--shadow-lg)">
      {#if error}
        <div class="px-3 py-2 rounded-lg text-sm border" style="background: var(--status-error-bg); color: var(--status-error-text); border-color: var(--status-error-border)">
          {error}
        </div>
      {/if}

      <!-- Google Sign In (primary) -->
      <button
        onclick={handleGoogleLogin}
        disabled={googleLoading}
        class="w-full h-11 flex items-center justify-center gap-3 rounded-lg text-sm font-medium border transition-fast disabled:opacity-50"
        style="background: var(--bg-primary); border-color: var(--border-color); color: var(--text-primary)"
      >
        {#if googleLoading}
          <span class="w-4 h-4 border-2 rounded-full animate-spin" style="border-color: var(--border-color); border-top-color: var(--text-primary)"></span>
          Redirecting to Google...
        {:else}
          <svg class="w-5 h-5" viewBox="0 0 24 24">
            <path d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92a5.06 5.06 0 01-2.2 3.32v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.1z" fill="#4285F4"/>
            <path d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" fill="#34A853"/>
            <path d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z" fill="#FBBC05"/>
            <path d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" fill="#EA4335"/>
          </svg>
          Sign in with Google
        {/if}
      </button>

      <!-- Divider -->
      <div class="relative">
        <div class="absolute inset-0 flex items-center">
          <div class="w-full border-t" style="border-color: var(--border-color)"></div>
        </div>
        <div class="relative flex justify-center">
          <button
            onclick={() => showPasswordLogin = !showPasswordLogin}
            class="px-3 text-xs" style="background: var(--bg-secondary); color: var(--text-tertiary)"
          >
            {showPasswordLogin ? 'Hide' : 'Admin'} password login
          </button>
        </div>
      </div>

      <!-- Password login (admin fallback) -->
      {#if showPasswordLogin}
        <form onsubmit={handleLogin} class="space-y-3">
          <div class="space-y-1.5">
            <label class="block text-xs font-medium tracking-wide uppercase" style="color: var(--text-secondary)" for="username">Username</label>
            <input
              id="username"
              type="text"
              bind:value={username}
              placeholder="admin"
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
      {/if}
    </div>

    <!-- Theme toggle -->
    <div class="mt-6 text-center">
      <button
        onclick={() => theme.toggle()}
        class="text-xs transition-fast"
        style="color: var(--text-tertiary)"
      >
        Switch to {getEffectiveMode($theme) === 'dark' ? 'light' : 'dark'} mode
      </button>
    </div>
  </div>
</div>
