<script>
  import { onMount, tick } from 'svelte';
  import { api } from '../lib/api.js';
  import { user } from '../lib/stores.js';

  let userCode = $state('');
  let status = $state('ready');
  let error = $state('');
  let inputEl = $state(null);

  onMount(async () => {
    const params = new URLSearchParams(window.location.search);
    const code = params.get('code');
    if (code) {
      userCode = formatCode(code);
      if ($user && userCode.length === 9) {
        await tick();
        authorize();
      }
    }
    await tick();
    if (inputEl) inputEl.focus();
  });

  function formatCode(raw) {
    let val = raw.toUpperCase().replace(/[^A-Z0-9]/g, '');
    if (val.length > 4) {
      val = val.slice(0, 4) + '-' + val.slice(4);
    }
    if (val.length > 9) {
      val = val.slice(0, 9);
    }
    return val;
  }

  function handleInput(e) {
    userCode = formatCode(e.target.value);
    e.target.value = userCode;
    error = '';

    if (userCode.length === 9 && $user) {
      authorize();
    }
  }

  function handleKeydown(e) {
    if (e.key === 'Enter') {
      e.preventDefault();
      authorize();
    }
  }

  async function authorize() {
    if (!userCode.trim() || userCode.length < 9) {
      error = 'Enter the full 8-character code';
      return;
    }
    if (status === 'authorizing') return;
    status = 'authorizing';
    error = '';
    try {
      await api.deviceAuthorize(userCode.trim().toUpperCase());
      status = 'success';
    } catch (e) {
      error = e.message || 'Invalid or expired code. Check your terminal and try again.';
      status = 'ready';
    }
  }
</script>

<div class="min-h-screen flex items-center justify-center p-4" style="background: var(--bg-primary)">
  <div class="w-full max-w-md rounded-2xl p-8 shadow-lg" style="background: var(--bg-secondary); border: 1px solid var(--border-color)">
    <div class="text-center mb-6">
      <h1 class="text-2xl font-bold mb-1" style="color: var(--text-primary)">Authorize Device</h1>
      <p class="text-sm" style="color: var(--text-secondary)">
        A terminal client is requesting access to your account.
      </p>
    </div>

    {#if !$user}
      <div class="text-center py-4">
        <p class="mb-4" style="color: var(--text-secondary)">You need to be logged in to authorize a device.</p>
        <a href="/" class="px-4 py-2 rounded-lg text-white font-medium" style="background: var(--color-accent-500)">
          Go to Login
        </a>
      </div>
    {:else if status === 'success'}
      <div class="text-center py-6">
        <div class="success-check">
          <svg viewBox="0 0 52 52" class="checkmark">
            <circle class="checkmark-circle" cx="26" cy="26" r="24" fill="none"/>
            <path class="checkmark-path" fill="none" d="M14 27l7.8 7.8L38 17"/>
          </svg>
        </div>
        <h2 class="text-lg font-semibold mb-2" style="color: var(--color-accent-500)">Device Authorized</h2>
        <p style="color: var(--text-secondary)">
          You can close this window and return to your terminal.
        </p>
      </div>
    {:else}
      <div class="space-y-4">
        <div>
          <label class="block text-sm font-medium mb-1" style="color: var(--text-secondary)">
            Device Code
          </label>
          <input
            bind:this={inputEl}
            type="text"
            value={userCode}
            oninput={handleInput}
            onkeydown={handleKeydown}
            placeholder="XXXX-XXXX"
            class="w-full px-3 py-2 rounded-lg text-center text-2xl font-mono tracking-widest"
            style="background: var(--bg-primary); border: 1px solid var(--border-color); color: var(--text-primary)"
            autocomplete="off"
            spellcheck="false"
            disabled={status === 'authorizing'}
          />
        </div>

        {#if error}
          <p class="text-sm text-center" style="color: var(--color-red-500)">{error}</p>
        {/if}

        <button
          onclick={authorize}
          disabled={status === 'authorizing'}
          class="w-full py-2 rounded-lg text-white font-medium transition-colors flex items-center justify-center gap-2"
          style="background: var(--color-accent-500)"
        >
          {#if status === 'authorizing'}
            <span class="pulsing-dot"></span>
            Authorizing…
          {:else}
            Authorize Device
          {/if}
        </button>

        <p class="text-xs text-center" style="color: var(--text-tertiary)">
          Only authorize devices you trust. This will grant the terminal app full access to your account.
        </p>
      </div>
    {/if}
  </div>
</div>

<style>
  .success-check {
    width: 64px;
    height: 64px;
    margin: 0 auto 12px;
  }
  .checkmark {
    width: 64px;
    height: 64px;
  }
  .checkmark-circle {
    stroke: var(--color-accent-500);
    stroke-width: 2.5;
    stroke-dasharray: 151;
    stroke-dashoffset: 151;
    animation: circle-fill 0.4s ease-in-out forwards;
  }
  .checkmark-path {
    stroke: var(--color-accent-500);
    stroke-width: 3;
    stroke-linecap: round;
    stroke-linejoin: round;
    stroke-dasharray: 36;
    stroke-dashoffset: 36;
    animation: check-draw 0.3s 0.35s ease-in-out forwards;
  }
  @keyframes circle-fill {
    to { stroke-dashoffset: 0; }
  }
  @keyframes check-draw {
    to { stroke-dashoffset: 0; }
  }
  .pulsing-dot {
    display: inline-block;
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: white;
    animation: pulse 1s ease-in-out infinite;
  }
  @keyframes pulse {
    0%, 100% { opacity: 1; transform: scale(1); }
    50% { opacity: 0.4; transform: scale(0.75); }
  }
</style>
