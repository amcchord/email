<script>
  import { api } from '../lib/api.js';

  let { code = '' } = $props();

  let userCode = $state(code || '');
  let status = $state('idle');
  let message = $state('');
  let authorizedEmail = $state('');

  async function authorize() {
    if (!userCode.trim()) return;
    status = 'loading';
    message = '';
    try {
      const result = await api.deviceAuthorize(userCode.trim());
      status = 'success';
      message = result.message || 'TUI session authorized!';
      authorizedEmail = result.email || '';
    } catch (err) {
      status = 'error';
      message = err.message || 'Invalid or expired code. Please try again.';
    }
  }
</script>

<div class="min-h-screen flex items-center justify-center p-4" style="background: var(--bg-primary)">
  <div class="w-full max-w-sm">
    <div class="rounded-2xl border p-8 text-center" style="background: var(--bg-secondary); border-color: var(--border-color)">
      <!-- Header -->
      <div class="mb-6">
        <div class="text-2xl font-bold mb-1" style="color: var(--text-primary)">Authorize TUI</div>
        <p class="text-sm" style="color: var(--text-secondary)">
          Enter the code shown in your terminal to link this session.
        </p>
      </div>

      {#if status === 'success'}
        <!-- Success state -->
        <div class="py-6">
          <div class="w-16 h-16 mx-auto mb-4 rounded-full flex items-center justify-center" style="background: rgba(45, 212, 191, 0.1)">
            <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="#2dd4bf" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <polyline points="20 6 9 17 4 12"></polyline>
            </svg>
          </div>
          <p class="text-sm font-medium" style="color: #2dd4bf">{message}</p>
          <p class="text-xs mt-2" style="color: var(--text-tertiary)">You can close this tab and return to your terminal.</p>
        </div>
      {:else}
        <!-- Code input -->
        <div class="mb-4">
          <input
            type="text"
            bind:value={userCode}
            placeholder="XXXX-XXXX"
            maxlength="9"
            class="w-full h-14 px-4 rounded-xl text-center text-2xl font-mono tracking-[0.3em] outline-none border uppercase"
            style="background: var(--bg-primary); border-color: {status === 'error' ? 'var(--status-error)' : 'var(--border-color)'}; color: var(--text-primary)"
            oninput={(e) => {
              let v = e.target.value.replace(/[^a-zA-Z0-9]/g, '').toUpperCase();
              if (v.length > 4) {
                v = v.slice(0, 4) + '-' + v.slice(4, 8);
              }
              userCode = v;
            }}
            onkeydown={(e) => { if (e.key === 'Enter') authorize(); }}
          />
        </div>

        {#if status === 'error'}
          <p class="text-xs mb-4" style="color: var(--status-error)">{message}</p>
        {/if}

        <button
          onclick={authorize}
          disabled={status === 'loading' || userCode.trim().length < 9}
          class="w-full h-11 rounded-xl text-sm font-semibold text-white transition-colors disabled:opacity-50"
          style="background: var(--color-accent-500)"
        >
          {#if status === 'loading'}
            Authorizing...
          {:else}
            Authorize Session
          {/if}
        </button>

        <p class="text-xs mt-4" style="color: var(--text-tertiary)">
          This code expires in 10 minutes.
        </p>
      {/if}
    </div>
  </div>
</div>
