<script>
  import { onMount } from 'svelte';
  import { api } from '../lib/api.js';
  import { createAuthenticatedSessionGuard } from '../lib/stores.js';
  import {
    atAGlanceProfile,
    availableAtAGlanceDesigns,
    availableAtAGlanceProfiles,
    availableAtAGlanceViews,
    defaultAtAGlanceSelection,
    normalizeAtAGlanceExperience,
    selectAtAGlanceDesign,
    selectAtAGlanceProfile,
    selectAtAGlanceView,
    summarizeAtAGlanceDevice,
  } from '../lib/atAGlance.js';

  let experience = $state(null);
  let selection = $state(null);
  let loading = $state(true);
  let loadError = $state('');
  let previewBuster = $state(0);
  let previewLoading = $state(false);
  let previewError = $state(false);
  let sessionGuard = null;
  let loadGeneration = 0;

  let catalogViews = $derived(experience ? availableAtAGlanceViews(experience) : []);
  let catalogProfiles = $derived(
    experience && selection ? availableAtAGlanceProfiles(experience, selection.view) : [],
  );
  let catalogDesigns = $derived(
    experience && selection
      ? availableAtAGlanceDesigns(experience, selection.view, selection.profile)
      : [],
  );
  let selectedProfile = $derived(
    experience && selection ? atAGlanceProfile(experience, selection.profile) : null,
  );
  let previewUrl = $derived(
    selection
      ? api.atAGlancePreviewPngUrl(
          selection.view,
          selection.design,
          selection.profile,
          previewBuster,
        )
      : '',
  );
  let deviceSummaries = $derived(
    (experience?.devices || []).map(device => summarizeAtAGlanceDevice(device)),
  );
  let attentionCount = $derived(deviceSummaries.filter(device => device.needsAttention).length);
  let deviceStatusUnavailable = $derived(
    (experience?.partial_errors || []).some(message => message.includes('Terminal status')),
  );

  function sessionIsCurrent() {
    return Boolean(sessionGuard?.isCurrent());
  }

  onMount(() => {
    sessionGuard = createAuthenticatedSessionGuard();
    void loadExperience();
    return () => {
      loadGeneration += 1;
      sessionGuard?.dispose();
    };
  });

  async function loadExperience() {
    if (!sessionIsCurrent()) return false;
    const requestGeneration = ++loadGeneration;
    loading = true;
    loadError = '';
    try {
      const result = await api.getAtAGlanceExperience();
      if (!sessionIsCurrent() || requestGeneration !== loadGeneration) return false;
      const normalized = normalizeAtAGlanceExperience(result);
      const preferred = selection
        ? { view: selection.view, design: selection.design, profile: selection.profile }
        : { view: 'home' };
      experience = normalized;
      selection = defaultAtAGlanceSelection(normalized, preferred);
      resetPreview();
      return true;
    } catch (error) {
      if (!sessionIsCurrent() || requestGeneration !== loadGeneration) return false;
      loadError = error?.message || 'At a Glance could not be loaded.';
      return false;
    } finally {
      if (sessionIsCurrent() && requestGeneration === loadGeneration) loading = false;
    }
  }

  function resetPreview() {
    previewError = false;
    previewLoading = Boolean(selection);
    previewBuster = Date.now();
  }

  function chooseView(viewKey) {
    if (!experience || !selection) return;
    selection = selectAtAGlanceView(experience, selection, viewKey);
    resetPreview();
  }

  function chooseProfile(profileKey) {
    if (!experience || !selection) return;
    selection = selectAtAGlanceProfile(experience, selection, profileKey);
    resetPreview();
  }

  function chooseDesign(designKey) {
    if (!experience || !selection) return;
    selection = selectAtAGlanceDesign(experience, selection, designKey);
    resetPreview();
  }

  function previewLoaded() {
    previewLoading = false;
    previewError = false;
  }

  function previewFailed() {
    previewLoading = false;
    previewError = true;
  }

  function previewAspect(profile) {
    if (!profile) return '16 / 9';
    return `${profile.aspect_width} / ${profile.aspect_height}`;
  }

  function statusStyle(tone) {
    if (tone === 'danger') {
      return 'background: var(--status-error-bg); border-color: var(--status-error-border); color: var(--status-error-text)';
    }
    if (tone === 'warning') {
      return 'background: var(--status-warning-bg); border-color: var(--status-warning-border); color: var(--status-warning-text)';
    }
    if (tone === 'success') {
      return 'background: var(--status-success-bg); border-color: var(--status-success-border); color: var(--status-success-text)';
    }
    return 'background: var(--bg-tertiary); border-color: var(--border-color); color: var(--text-secondary)';
  }

  function statusLabel(status) {
    const labels = {
      charge_now: 'Charge now',
      charge_soon: 'Charge soon',
      charging: 'Charging',
      possible_charging: 'Checking charge',
      healthy: 'Healthy',
      stable: 'Stable',
      good: 'Good',
      watch: 'Watch battery',
      stale: 'Status stale',
      low: 'Low battery',
      warning: 'Needs attention',
      insufficient_data: 'Learning battery',
      unknown: 'Battery unknown',
    };
    return labels[status] || status.replaceAll('_', ' ');
  }
</script>

<svelte:head>
  <title>At a Glance</title>
</svelte:head>

<div class="h-full overflow-y-auto" style="background: var(--bg-primary)">
  <div class="max-w-7xl mx-auto px-4 py-5 sm:px-6 sm:py-7 lg:px-8 space-y-6">
    <header class="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
      <div class="max-w-2xl">
        <p class="text-[11px] font-semibold uppercase tracking-[0.16em]" style="color: var(--color-accent-600)">Everyday displays</p>
        <h1 class="mt-1 text-2xl sm:text-3xl font-bold tracking-tight" style="color: var(--text-primary)">At a Glance</h1>
        <p class="mt-2 text-sm leading-6" style="color: var(--text-secondary)">
          Preview your day, dashboard, or clock for a landscape or portrait display. The same catalog powers browser screens and e-ink terminals.
        </p>
      </div>
      <a
        href="/?page=admin&tab=terminals"
        class="inline-flex min-h-10 shrink-0 items-center justify-center rounded-lg border px-4 text-sm font-medium hover:opacity-80 focus-visible:outline-2 focus-visible:outline-offset-2"
        style="background: var(--bg-secondary); border-color: var(--border-color); color: var(--text-primary)"
      >
        Manage displays &amp; terminals
      </a>
    </header>

    {#if loading && !experience}
      <div class="grid grid-cols-1 gap-5 lg:grid-cols-[18rem_minmax(0,1fr)]" aria-live="polite" aria-label="Loading At a Glance">
        <div class="h-72 rounded-2xl animate-pulse" style="background: var(--bg-secondary)"></div>
        <div class="h-[28rem] rounded-2xl animate-pulse" style="background: var(--bg-secondary)"></div>
      </div>
      <div class="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {#each Array(3) as _}
          <div class="h-36 rounded-xl animate-pulse" style="background: var(--bg-secondary)"></div>
        {/each}
      </div>
    {:else if loadError && !experience}
      <section class="rounded-2xl border p-6 sm:p-8 text-center" style="background: var(--bg-secondary); border-color: var(--status-error-border)" aria-live="assertive">
        <h2 class="text-base font-semibold" style="color: var(--text-primary)">At a Glance is temporarily unavailable</h2>
        <p class="mt-2 text-sm" style="color: var(--text-secondary)">{loadError}</p>
        <button
          type="button"
          onclick={loadExperience}
          class="mt-5 inline-flex min-h-10 items-center justify-center rounded-lg bg-accent-600 px-4 text-sm font-medium text-white hover:bg-accent-700 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent-500"
        >
          Try again
        </button>
      </section>
    {:else if experience}
      {#if experience.partial_errors.length > 0 || loadError}
        <section class="flex flex-col gap-3 rounded-xl border p-4 sm:flex-row sm:items-center sm:justify-between" style="background: var(--status-warning-bg); border-color: var(--status-warning-border)" aria-live="polite">
          <div>
            <h2 class="text-sm font-semibold" style="color: var(--status-warning-text)">Some live status could not be refreshed</h2>
            <p class="mt-0.5 text-xs" style="color: var(--status-warning-text)">{[loadError, ...experience.partial_errors].filter(Boolean).join(' ')}</p>
          </div>
          <button
            type="button"
            onclick={loadExperience}
            disabled={loading}
            class="inline-flex min-h-9 shrink-0 items-center justify-center rounded-lg border px-3 text-xs font-medium disabled:opacity-50"
            style="background: var(--bg-secondary); border-color: var(--status-warning-border); color: var(--status-warning-text)"
          >
            {loading ? 'Retrying…' : 'Retry'}
          </button>
        </section>
      {/if}

      {#if !selection}
        <section class="rounded-2xl border p-6 sm:p-8 text-center" style="background: var(--bg-secondary); border-color: var(--border-color)">
          <h2 class="text-base font-semibold" style="color: var(--text-primary)">No display views are available yet</h2>
          <p class="mt-2 text-sm" style="color: var(--text-secondary)">The display catalog is empty. You can still review terminal setup and display management in Settings.</p>
          <a href="/?page=admin&tab=terminals" class="mt-5 inline-flex min-h-10 items-center justify-center rounded-lg bg-accent-600 px-4 text-sm font-medium text-white hover:bg-accent-700">Open display settings</a>
        </section>
      {:else}
        <section class="grid grid-cols-1 gap-5 lg:grid-cols-[18rem_minmax(0,1fr)]" aria-label="Display preview chooser">
          <div class="rounded-2xl border p-4 sm:p-5" style="background: var(--bg-secondary); border-color: var(--border-color); box-shadow: var(--shadow-sm)">
            <div>
              <h2 class="text-sm font-semibold" style="color: var(--text-primary)">Choose a view</h2>
              <p class="mt-1 text-xs" style="color: var(--text-tertiary)">Options adapt to the display catalog.</p>
            </div>

            <div class="mt-4 grid grid-cols-1 gap-2" aria-label="At a Glance view">
              {#each catalogViews as view (view.key)}
                <button
                  type="button"
                  onclick={() => chooseView(view.key)}
                  aria-pressed={selection.view === view.key}
                  class="min-h-11 rounded-lg border px-3 py-2 text-left text-sm font-medium transition-colors focus-visible:outline-2 focus-visible:outline-offset-2"
                  style={selection.view === view.key
                    ? 'background: var(--color-accent-50); border-color: var(--color-accent-400); color: var(--color-accent-900)'
                    : 'background: var(--bg-primary); border-color: var(--border-color); color: var(--text-primary)'}
                >
                  {view.label}
                </button>
              {/each}
            </div>

            <div class="mt-5 space-y-4">
              <label class="block" for="at-a-glance-profile">
                <span class="block text-xs font-medium" style="color: var(--text-secondary)">Display format</span>
                <select
                  id="at-a-glance-profile"
                  value={selection.profile}
                  onchange={(event) => chooseProfile(event.currentTarget.value)}
                  class="mt-1.5 h-11 w-full rounded-lg border px-3 text-sm outline-none focus-visible:outline-2 focus-visible:outline-offset-2"
                  style="background: var(--bg-primary); border-color: var(--border-color); color: var(--text-primary)"
                >
                  {#each catalogProfiles as profile (profile.key)}
                    <option value={profile.key}>{profile.label}</option>
                  {/each}
                </select>
              </label>

              {#if catalogDesigns.length > 0}
                <label class="block" for="at-a-glance-design">
                  <span class="block text-xs font-medium" style="color: var(--text-secondary)">Design</span>
                  <select
                    id="at-a-glance-design"
                    value={selection.design || ''}
                    onchange={(event) => chooseDesign(event.currentTarget.value)}
                    class="mt-1.5 h-11 w-full rounded-lg border px-3 text-sm outline-none focus-visible:outline-2 focus-visible:outline-offset-2"
                    style="background: var(--bg-primary); border-color: var(--border-color); color: var(--text-primary)"
                  >
                    {#each catalogDesigns as design (design.key)}
                      <option value={design.key}>{design.label}</option>
                    {/each}
                  </select>
                </label>
              {/if}
            </div>

            <div class="mt-5 rounded-lg border p-3 text-xs leading-5" style="background: var(--bg-primary); border-color: var(--border-color); color: var(--text-secondary)">
              Browser display links and terminal settings stay in the management area, separate from this read-only daily preview.
            </div>
          </div>

          <div class="min-w-0 rounded-2xl border p-3 sm:p-5" style="background: var(--bg-secondary); border-color: var(--border-color); box-shadow: var(--shadow-sm)">
            <div class="mb-4 flex flex-wrap items-center justify-between gap-3">
              <div>
                <h2 class="text-sm font-semibold" style="color: var(--text-primary)">{selection.label}</h2>
                <p class="mt-0.5 text-xs capitalize" style="color: var(--text-tertiary)">
                  {selectedProfile?.orientation || selection.orientation} · {selection.aspect_ratio || selectedProfile?.label}
                </p>
              </div>
              <div class="flex flex-wrap gap-2">
                <button
                  type="button"
                  onclick={resetPreview}
                  class="inline-flex min-h-9 items-center justify-center rounded-lg border px-3 text-xs font-medium hover:opacity-80"
                  style="background: var(--bg-primary); border-color: var(--border-color); color: var(--text-primary)"
                >
                  Refresh
                </button>
                <a
                  href={previewUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  class="inline-flex min-h-9 items-center justify-center rounded-lg bg-accent-600 px-3 text-xs font-medium text-white hover:bg-accent-700 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent-500"
                >
                  Open preview <span class="sr-only">in a new tab</span>
                </a>
                <a
                  href="/?page=admin&tab=terminals"
                  class="inline-flex min-h-9 items-center justify-center rounded-lg border px-3 text-xs font-medium hover:opacity-80 focus-visible:outline-2 focus-visible:outline-offset-2"
                  style="background: var(--bg-primary); border-color: var(--border-color); color: var(--text-primary)"
                >
                  Use on a screen
                </a>
              </div>
            </div>

            <div class="grid min-h-[24rem] place-items-center overflow-hidden rounded-xl border p-3 sm:p-5" style="background: #dedbd2; border-color: var(--border-color)">
              <div
                class={selectedProfile?.orientation === 'portrait' ? 'relative w-full max-w-[19rem]' : 'relative w-full max-w-4xl'}
                style="aspect-ratio: {previewAspect(selectedProfile)}; background: #f5f2e9; box-shadow: 0 16px 45px rgb(0 0 0 / 0.18)"
              >
                {#if previewLoading}
                  <div class="absolute inset-0 z-10 grid place-items-center" style="background: #f5f2e9" aria-live="polite">
                    <span class="text-xs font-medium text-stone-500">Rendering preview…</span>
                  </div>
                {/if}
                {#if previewError}
                  <div class="absolute inset-0 z-20 grid place-items-center p-6 text-center" style="background: #f5f2e9" role="alert">
                    <div>
                      <p class="text-sm font-semibold text-stone-900">Preview could not be rendered</p>
                      <p class="mt-1 text-xs text-stone-600">Your catalog choices are still available.</p>
                      <button type="button" onclick={resetPreview} class="mt-4 min-h-9 rounded-lg bg-stone-900 px-3 text-xs font-medium text-white">Try preview again</button>
                    </div>
                  </div>
                {/if}
                <img
                  src={previewUrl}
                  alt="{selection.label} preview"
                  onload={previewLoaded}
                  onerror={previewFailed}
                  class="block h-full w-full object-contain"
                />
              </div>
            </div>
          </div>
        </section>
      {/if}

      <section class="space-y-3" aria-labelledby="terminal-health-title">
        <div class="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h2 id="terminal-health-title" class="text-base font-semibold" style="color: var(--text-primary)">Terminal health</h2>
            <p class="mt-1 text-xs" style="color: var(--text-tertiary)">A simple check on connection and predicted charging needs.</p>
          </div>
          {#if deviceSummaries.length > 0}
            <p class="text-xs font-medium" style="color: {attentionCount > 0 ? 'var(--status-warning-text)' : 'var(--text-secondary)'}">
              {attentionCount > 0 ? `${attentionCount} need${attentionCount === 1 ? 's' : ''} attention` : 'All reported batteries look good'}
            </p>
          {/if}
        </div>

        {#if deviceStatusUnavailable && deviceSummaries.length === 0}
          <div class="rounded-xl border p-5 text-sm" style="background: var(--bg-secondary); border-color: var(--border-color); color: var(--text-secondary)">
            Terminal status is unavailable right now. Retry above without changing any device settings.
          </div>
        {:else if deviceSummaries.length === 0}
          <div class="rounded-xl border p-5 sm:p-6" style="background: var(--bg-secondary); border-color: var(--border-color)">
            <h3 class="text-sm font-semibold" style="color: var(--text-primary)">No terminals have checked in yet</h3>
            <p class="mt-1 text-xs leading-5" style="color: var(--text-secondary)">Browser previews work without a terminal. When you add an e-ink display, its connection and battery forecast will appear here.</p>
            <a href="/?page=admin&tab=terminals" class="mt-3 inline-flex text-xs font-semibold text-accent-700 hover:underline dark:text-accent-400">Go to terminal setup</a>
          </div>
        {:else}
          <div class="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
            {#each deviceSummaries as device, index (`${device.name}-${index}`)}
              <article class="rounded-xl border p-4" style="background: var(--bg-secondary); border-color: var(--border-color); box-shadow: var(--shadow-sm)">
                <div class="flex items-start justify-between gap-3">
                  <div class="min-w-0">
                    <h3 class="truncate text-sm font-semibold" style="color: var(--text-primary)">{device.name}</h3>
                    <p class="mt-0.5 text-[11px]" style="color: var(--text-tertiary)">{device.model} · {device.enrollment}</p>
                  </div>
                  <span class="shrink-0 rounded-full border px-2 py-1 text-[10px] font-semibold capitalize" style={statusStyle(device.tone)}>{statusLabel(device.status)}</span>
                </div>
                <div class="mt-4">
                  <p class="text-lg font-semibold" style="color: var(--text-primary)">{device.battery}</p>
                  {#if device.forecast}<p class="mt-0.5 text-xs" style="color: var(--text-secondary)">{device.forecast}</p>{/if}
                  {#if device.notice}<p class="mt-2 text-xs font-medium" style="color: {device.needsAttention ? 'var(--status-warning-text)' : 'var(--text-secondary)'}">{device.notice}</p>{/if}
                </div>
                <p class="mt-4 border-t pt-3 text-[11px]" style="border-color: var(--border-subtle); color: var(--text-tertiary)">Last checked in {device.lastSeen}</p>
              </article>
            {/each}
          </div>
        {/if}
      </section>
    {/if}
  </div>
</div>
