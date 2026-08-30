<script>
  import { onDestroy, onMount } from 'svelte';
  import { createAuthenticatedSessionGuard } from '../stores.js';
  import { getTerminalEnrollmentCapabilities } from '../terminalEnrollmentApi.js';

  const sessionGuard = createAuthenticatedSessionGuard();

  let loading = $state(true);
  let loadError = $state('');
  let capabilities = $state(null);

  async function loadCapabilities() {
    loading = true;
    loadError = '';
    try {
      const result = await getTerminalEnrollmentCapabilities();
      if (!sessionGuard.isCurrent()) return;
      capabilities = result;
    } catch (error) {
      if (!sessionGuard.isCurrent()) return;
      capabilities = null;
      loadError = error?.message || 'Enrollment policy is unavailable.';
    } finally {
      if (sessionGuard.isCurrent()) loading = false;
    }
  }

  export async function refresh() {
    await loadCapabilities();
  }

  onMount(() => void loadCapabilities());
  onDestroy(() => sessionGuard.dispose());
</script>

<section
  class="rounded-xl border p-5"
  style="background: var(--bg-secondary); border-color: var(--border-color)"
  aria-labelledby="terminal-enrollment-title"
>
  <div class="flex flex-wrap items-start justify-between gap-3">
    <div>
      <h4 id="terminal-enrollment-title" class="text-sm font-semibold" style="color: var(--text-primary)">
        Secure terminal enrollment
      </h4>
      <p class="text-[11px] mt-0.5 max-w-3xl" style="color: var(--text-tertiary)">
        RET1 authorizes one owner and one revocable device URL from a browser-observed physical serial session. This is physical-cable-only provisioning, not hardware attestation or proof of cryptographic hardware identity. The browser transport stays locked until interrupted-write, recovery, Wi-Fi, and check-in tests pass on physical E1001 and E1002 hardware.
      </p>
    </div>
    <span
      class="inline-flex items-center rounded-full border px-2.5 py-1 text-[10px] font-semibold uppercase tracking-wider"
      style="background: var(--status-warning-bg); border-color: var(--status-warning-border); color: var(--status-warning-text)"
    >{capabilities?.state === 'ready' ? 'Server ready · browser locked' : 'Locked'}</span>
  </div>

  {#if loading}
    <p class="mt-4 text-xs" style="color: var(--text-tertiary)" role="status">Checking enrollment policy…</p>
  {:else if loadError}
    <div class="mt-4 rounded-lg border px-3 py-2 text-xs" style="background: var(--status-warning-bg); border-color: var(--status-warning-border); color: var(--status-warning-text)" role="status">
      Enrollment policy unavailable: {loadError}
    </div>
  {:else if capabilities}
    <div class="mt-4 grid grid-cols-1 sm:grid-cols-3 gap-2" aria-label="Enrollment guarantees">
      <div class="rounded-lg border px-3 py-2 text-xs" style="background: var(--bg-primary); border-color: var(--border-color)">
        <div class="font-semibold" style="color: var(--text-secondary)">Protocol</div>
        <div class="mt-0.5" style="color: var(--text-tertiary)">{capabilities.protocol || 'RET1'}</div>
      </div>
      <div class="rounded-lg border px-3 py-2 text-xs" style="background: var(--bg-primary); border-color: var(--border-color)">
        <div class="font-semibold" style="color: var(--text-secondary)">Observed session</div>
        <div class="mt-0.5" style="color: var(--text-tertiary)">Physical serial cable · no hardware attestation</div>
      </div>
      <div class="rounded-lg border px-3 py-2 text-xs" style="background: var(--bg-primary); border-color: var(--border-color)">
        <div class="font-semibold" style="color: var(--text-secondary)">Activation</div>
        <div class="mt-0.5" style="color: var(--text-tertiary)">First scoped HTTPS check-in</div>
      </div>
    </div>

    {#if (capabilities.qualified_releases || []).length > 0}
      <div class="mt-4">
        <h5 class="text-xs font-semibold" style="color: var(--text-primary)">Server-qualified firmware</h5>
        <div class="mt-2 flex flex-wrap gap-1.5">
          {#each capabilities.qualified_releases as release (release.release_id)}
            <span class="inline-flex rounded-full border px-2 py-1 text-[10px]" style="border-color: var(--border-color); color: var(--text-secondary)">
              {release.firmware_version} · {(release.models || []).join(', ')}
            </span>
          {/each}
        </div>
      </div>
    {/if}

    <div class="mt-4 rounded-lg border px-3 py-3 text-xs" style="background: var(--bg-primary); border-color: var(--border-color)">
      <p class="font-semibold" style="color: var(--text-secondary)">Current gates</p>
      <ul class="mt-1.5 space-y-1 list-disc pl-4" style="color: var(--text-tertiary)">
        {#each (capabilities.blockers || ['Physical hardware qualification has not enabled browser enrollment.']) as blocker}
          <li>{blocker}</li>
        {/each}
      </ul>
      <p class="mt-2 text-[10px] font-medium" style="color: var(--text-secondary)">
        This screen never requests a serial port and cannot send Wi-Fi credentials, write configuration, flash, or erase a terminal.
      </p>
    </div>
  {/if}
</section>
