<script>
  import { onDestroy, onMount } from 'svelte';
  import { createAuthenticatedSessionGuard } from '../stores.js';
  import {
    getTerminalFirmwareCatalog,
    getTerminalFirmwareReleaseEvidence,
    getTerminalOtaCapabilities,
  } from '../terminalFirmwareApi.js';
  import { getTerminalInstallerLock, detectTerminalFirmwareSupport } from '../terminalFirmwareInstaller.js';
  import { validateTerminalFirmwareCatalog } from '../terminalFirmwarePolicy.js';
  import { verifyTerminalFirmwareRelease } from '../terminalFirmwareVerifier.js';

  const sessionGuard = createAuthenticatedSessionGuard();

  let loading = $state(true);
  let loadError = $state('');
  let audit = $state({ valid: false, errors: [], catalog: null });
  let releaseVerification = $state({});
  let otaCapabilities = $state({
    state: 'locked',
    effective_offer_enabled: false,
    blockers: ['Device OTA capability has not been checked.'],
  });
  let support = $state({ secureContext: false, webSerial: false, webLocks: false, supported: false, blockers: [] });
  let lock = $derived(getTerminalInstallerLock(audit, support));

  function formatGitSha(value) {
    return typeof value === 'string' ? value.slice(0, 8) : 'unknown';
  }

  function formatReleaseDate(epoch) {
    if (!Number.isSafeInteger(epoch) || epoch <= 0) return 'Unknown build date';
    const date = new Date(epoch * 1000);
    if (Number.isNaN(date.getTime())) return 'Unknown build date';
    return new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' })
      .format(date);
  }

  async function loadCatalog() {
    loading = true;
    loadError = '';
    try {
      const catalog = await getTerminalFirmwareCatalog();
      if (!sessionGuard.isCurrent()) return;
      audit = validateTerminalFirmwareCatalog(catalog);
      if (!audit.valid) return;
      releaseVerification = Object.fromEntries(
        audit.catalog.releases.map(release => [release.release_id, { state: 'checking', errors: [] }]),
      );
      for (const release of audit.catalog.releases) {
        try {
          const evidence = await getTerminalFirmwareReleaseEvidence(release.release_id);
          if (!sessionGuard.isCurrent()) return;
          const verification = await verifyTerminalFirmwareRelease({ release, ...evidence });
          if (!sessionGuard.isCurrent()) return;
          releaseVerification = {
            ...releaseVerification,
            [release.release_id]: {
              state: verification.valid ? 'verified' : 'locked',
              errors: verification.errors,
            },
          };
        } catch (error) {
          if (!sessionGuard.isCurrent()) return;
          releaseVerification = {
            ...releaseVerification,
            [release.release_id]: {
              state: 'locked',
              errors: [error?.message || 'Exact signed metadata is unavailable.'],
            },
          };
        }
      }
    } catch (error) {
      if (!sessionGuard.isCurrent()) return;
      audit = { valid: false, errors: [], catalog: null };
      releaseVerification = {};
      loadError = error?.message || 'Firmware catalog is unavailable.';
    } finally {
      if (sessionGuard.isCurrent()) loading = false;
    }
  }

  async function loadOtaCapabilities() {
    try {
      const capabilities = await getTerminalOtaCapabilities();
      if (!sessionGuard.isCurrent()) return;
      otaCapabilities = capabilities;
    } catch (error) {
      if (!sessionGuard.isCurrent()) return;
      otaCapabilities = {
        state: 'locked',
        effective_offer_enabled: false,
        blockers: [error?.message || 'Device OTA capability is unavailable.'],
      };
    }
  }

  onMount(() => {
    support = detectTerminalFirmwareSupport();
    void loadCatalog();
    void loadOtaCapabilities();
  });

  onDestroy(() => sessionGuard.dispose());
</script>

<section
  class="rounded-xl border p-5"
  style="background: var(--bg-secondary); border-color: var(--border-color)"
  aria-labelledby="browser-firmware-installer-title"
>
  <div class="flex flex-wrap items-start justify-between gap-3">
    <div>
      <h4 id="browser-firmware-installer-title" class="text-sm font-semibold" style="color: var(--text-primary)">
        Browser firmware installer
      </h4>
      <p class="text-[11px] mt-0.5 max-w-3xl" style="color: var(--text-tertiary)">
        Firmware catalog inspection is available now. Device connection, download, erase, and flash operations remain disabled until browser signature verification, secure provisioning, and hardware recovery tests are qualified.
      </p>
    </div>
    <span
      class="inline-flex items-center rounded-full border px-2.5 py-1 text-[10px] font-semibold uppercase tracking-wider"
      style="background: var(--status-warning-bg); border-color: var(--status-warning-border); color: var(--status-warning-text)"
    >Locked</span>
  </div>

  <div class="mt-4 grid grid-cols-1 sm:grid-cols-3 gap-2" aria-label="Browser firmware prerequisites">
    {#each [
      { label: 'Secure HTTPS context', ready: support.secureContext },
      { label: 'Web Serial available', ready: support.webSerial },
      { label: 'Web Locks available', ready: support.webLocks },
    ] as item (item.label)}
      <div class="rounded-lg border px-3 py-2 text-xs" style="background: var(--bg-primary); border-color: var(--border-color)">
        <span aria-hidden="true" style="color: {item.ready ? 'var(--status-success, #10b981)' : 'var(--text-tertiary)'}">{item.ready ? '●' : '○'}</span>
        <span class="ml-1" style="color: var(--text-secondary)">{item.label}</span>
      </div>
    {/each}
  </div>

  <div
    class="mt-4 rounded-lg border px-3 py-3 text-xs"
    style="background: var(--bg-primary); border-color: var(--border-color)"
    aria-label="Device OTA capability"
  >
    <div class="flex flex-wrap items-baseline justify-between gap-2">
      <p class="font-semibold" style="color: var(--text-secondary)">Device OTA</p>
      <span class="text-[10px] font-semibold uppercase tracking-wider" style="color: var(--text-tertiary)">
        {otaCapabilities?.effective_offer_enabled ? 'Ready' : 'Locked'}
      </span>
    </div>
    {#if !otaCapabilities?.effective_offer_enabled}
      <ul class="mt-1.5 space-y-1 list-disc pl-4" style="color: var(--text-tertiary)">
        {#each (otaCapabilities?.blockers || []).slice(0, 4) as blocker}
          <li>{blocker}</li>
        {/each}
      </ul>
    {/if}
    <p class="mt-2 text-[10px]" style="color: var(--text-tertiary)">
      No update offer, firmware download, or device event endpoint is enabled by this status surface.
    </p>
  </div>

  {#if loading}
    <p class="mt-4 text-xs" style="color: var(--text-tertiary)" role="status">Checking the signed firmware catalog…</p>
  {:else if loadError}
    <div class="mt-4 rounded-lg border px-3 py-2 text-xs" style="background: var(--status-warning-bg); border-color: var(--status-warning-border); color: var(--status-warning-text)" role="status">
      Catalog unavailable: {loadError}
    </div>
  {:else if !audit.valid}
    <div class="mt-4 rounded-lg border px-3 py-2 text-xs" style="background: var(--status-error-bg); border-color: var(--status-error-border); color: var(--status-error-text)" role="alert">
      <p class="font-semibold">Catalog metadata failed the browser safety audit.</p>
      {#each audit.errors as error}
        <p class="mt-1">{error}</p>
      {/each}
    </div>
  {:else}
    <div class="mt-4">
      <div class="flex flex-wrap items-baseline justify-between gap-2">
        <h5 class="text-xs font-semibold" style="color: var(--text-primary)">Verified server catalog</h5>
        <span class="text-[10px]" style="color: var(--text-tertiary)">
          {audit.catalog.releases.length} approved {audit.catalog.releases.length === 1 ? 'release' : 'releases'}
        </span>
      </div>

      {#if audit.catalog.releases.length === 0}
        <p class="mt-2 text-xs" style="color: var(--text-tertiary)">No signed release has been staged for browser inspection.</p>
      {:else}
        <div class="mt-2 space-y-2">
          {#each audit.catalog.releases as release (release.release_id)}
            {@const verification = releaseVerification[release.release_id]}
            <article class="rounded-lg border p-3" style="background: var(--bg-primary); border-color: var(--border-color)">
              <div class="flex flex-wrap items-baseline justify-between gap-2">
                <div class="text-xs font-semibold" style="color: var(--text-primary)">{release.firmware_version}</div>
                <div class="text-[10px]" style="color: var(--text-tertiary)">{formatReleaseDate(release.source_date_epoch)}</div>
              </div>
              <div class="mt-1 text-[10px] font-mono break-all" style="color: var(--text-tertiary)">
                Git {formatGitSha(release.git_sha)} · key {release.signing_key_id} · manifest {release.release_id.slice(0, 12)}…
              </div>
              <div
                class="mt-2 rounded-md border px-2.5 py-2 text-[10px]"
                style="background: var(--bg-secondary); border-color: var(--border-color); color: var(--text-secondary)"
                role="status"
              >
                {#if verification?.state === 'checking'}
                  Checking exact manifest bytes and detached signature…
                {:else if verification?.state === 'verified'}
                  Exact manifest bytes and Ed25519 signature verified in this browser. Flashing remains locked.
                {:else}
                  Browser signature preflight locked{verification?.errors?.[0] ? `: ${verification.errors[0]}` : '.'}
                {/if}
              </div>
              <div class="mt-2 flex flex-wrap gap-1.5">
                {#each release.models as model (model.model)}
                  <span
                    class="inline-flex rounded-full border px-2 py-1 text-[10px]"
                    style="border-color: var(--border-color); color: var(--text-secondary)"
                    title={model.blockers.join(' ') || 'Server-qualified release metadata'}
                  >
                    {model.model} · {model.browser_flash_qualified ? 'qualified metadata' : 'not qualified'}
                  </span>
                {/each}
              </div>
            </article>
          {/each}
        </div>
      {/if}
    </div>
  {/if}

  <div class="mt-4 rounded-lg border px-3 py-3 text-xs" style="background: var(--bg-primary); border-color: var(--border-color)">
    <p class="font-semibold" style="color: var(--text-secondary)">Why flashing is locked</p>
    <ul class="mt-1.5 space-y-1 list-disc pl-4" style="color: var(--text-tertiary)">
      {#each lock.blockers as blocker}
        <li>{blocker}</li>
      {/each}
    </ul>
    <p class="mt-2 text-[10px] font-medium" style="color: var(--text-secondary)">
      This screen never requests a serial port and cannot write or erase a terminal.
    </p>
  </div>
</section>
