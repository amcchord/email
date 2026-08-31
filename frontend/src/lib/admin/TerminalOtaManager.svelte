<script>
  import { onDestroy, onMount } from 'svelte';
  import Button from '../../components/common/Button.svelte';
  import { createAuthenticatedSessionGuard } from '../stores.js';
  import {
    canCancelTerminalOtaAttempt,
    cancelTerminalOtaAttempt,
    clearTerminalHardwareRevision,
    confirmTerminalHardwareRevision,
    getTerminalOtaAttempt,
    getTerminalOtaCapabilities,
    listTerminalOtaAttempts,
    normalizeTerminalHardwareRevision,
  } from '../terminalOtaApi.js';

  let { devices = [], onDeviceUpdated = () => {} } = $props();

  const sessionGuard = createAuthenticatedSessionGuard();
  const requestedDeviceIds = new Set();
  const ACTIVE_ATTEMPT_STATES = new Set([
    'offered',
    'downloading',
    'staged',
    'booted_pending_validation',
  ]);

  let capabilities = $state(null);
  let capabilityLoading = $state(true);
  let capabilityError = $state('');
  let refreshing = $state(false);
  let attemptsByDevice = $state({});
  let attemptsLoading = $state({});
  let attemptsError = $state({});
  let detailByAttempt = $state({});
  let detailLoading = $state({});
  let detailError = $state({});
  let expandedAttemptId = $state(null);
  let revisionDrafts = $state({});
  let revisionSaving = $state({});
  let cancellationSaving = $state({});
  let actionMessage = $state('');
  let actionError = $state('');
  let loadGeneration = 0;

  $effect(() => {
    for (const device of devices) {
      if (requestedDeviceIds.has(device.id)) continue;
      requestedDeviceIds.add(device.id);
      void loadAttempts(device.id);
    }
  });

  onMount(() => {
    void loadCapabilities();
  });

  onDestroy(() => {
    loadGeneration += 1;
    sessionGuard.dispose();
  });

  function sessionIsCurrent() {
    return sessionGuard.isCurrent();
  }

  async function loadCapabilities() {
    const generation = ++loadGeneration;
    capabilityLoading = true;
    capabilityError = '';
    try {
      const result = await getTerminalOtaCapabilities();
      if (!sessionIsCurrent() || generation !== loadGeneration) return;
      capabilities = result;
    } catch (error) {
      if (!sessionIsCurrent() || generation !== loadGeneration) return;
      capabilityError = error?.message || 'OTA capability status is unavailable.';
    } finally {
      if (sessionIsCurrent() && generation === loadGeneration) capabilityLoading = false;
    }
  }

  async function loadAttempts(deviceId) {
    attemptsLoading = { ...attemptsLoading, [deviceId]: true };
    attemptsError = { ...attemptsError, [deviceId]: '' };
    try {
      const result = await listTerminalOtaAttempts(deviceId);
      if (!sessionIsCurrent()) return;
      attemptsByDevice = {
        ...attemptsByDevice,
        [deviceId]: Array.isArray(result) ? result : [],
      };
    } catch (error) {
      if (!sessionIsCurrent()) return;
      attemptsError = {
        ...attemptsError,
        [deviceId]: error?.message || 'Attempt history is unavailable.',
      };
    } finally {
      if (sessionIsCurrent()) {
        attemptsLoading = { ...attemptsLoading, [deviceId]: false };
      }
    }
  }

  async function refreshOtaStatus() {
    refreshing = true;
    actionMessage = '';
    actionError = '';
    await Promise.all([
      loadCapabilities(),
      ...devices.map(device => loadAttempts(device.id)),
    ]);
    if (sessionIsCurrent()) refreshing = false;
  }

  function revisionDraft(device) {
    if (Object.prototype.hasOwnProperty.call(revisionDrafts, device.id)) {
      return revisionDrafts[device.id];
    }
    return device.hardware_revision || '';
  }

  function setRevisionDraft(deviceId, value) {
    revisionDrafts = { ...revisionDrafts, [deviceId]: value };
    actionMessage = '';
    actionError = '';
  }

  function revisionIsValid(value) {
    try {
      normalizeTerminalHardwareRevision(value);
      return true;
    } catch {
      return false;
    }
  }

  function activeAttempt(deviceId) {
    return (attemptsByDevice[deviceId] || []).find(attempt => (
      ACTIVE_ATTEMPT_STATES.has(attempt.state)
    ));
  }

  async function confirmRevision(device) {
    let revision;
    try {
      revision = normalizeTerminalHardwareRevision(revisionDraft(device));
    } catch (error) {
      actionError = error.message;
      return;
    }
    const label = device.name || device.mac || `terminal ${device.id}`;
    if (!confirm(
      `Confirm that "${revision}" is printed on ${label}? `
      + 'This owner claim can qualify a future OTA offer, but it is not inferred hardware identity or HIL evidence.',
    )) return;

    revisionSaving = { ...revisionSaving, [device.id]: true };
    actionMessage = '';
    actionError = '';
    try {
      const updated = await confirmTerminalHardwareRevision(device.id, revision);
      if (!sessionIsCurrent()) return;
      revisionDrafts = { ...revisionDrafts, [device.id]: updated.hardware_revision || '' };
      onDeviceUpdated(updated);
      actionMessage = `${label}: printed hardware revision confirmed.`;
    } catch (error) {
      if (sessionIsCurrent()) actionError = error?.message || 'Hardware revision could not be confirmed.';
    } finally {
      if (sessionIsCurrent()) revisionSaving = { ...revisionSaving, [device.id]: false };
    }
  }

  async function clearRevision(device) {
    if (!device.hardware_revision) return;
    const label = device.name || device.mac || `terminal ${device.id}`;
    if (!confirm(
      `Clear the confirmed revision "${device.hardware_revision}" from ${label}? `
      + 'The terminal will be ineligible for a new OTA offer until an exact printed revision is confirmed again.',
    )) return;

    revisionSaving = { ...revisionSaving, [device.id]: true };
    actionMessage = '';
    actionError = '';
    try {
      const updated = await clearTerminalHardwareRevision(device.id);
      if (!sessionIsCurrent()) return;
      revisionDrafts = { ...revisionDrafts, [device.id]: '' };
      onDeviceUpdated(updated);
      actionMessage = `${label}: hardware revision confirmation cleared.`;
    } catch (error) {
      if (sessionIsCurrent()) actionError = error?.message || 'Hardware revision could not be cleared.';
    } finally {
      if (sessionIsCurrent()) revisionSaving = { ...revisionSaving, [device.id]: false };
    }
  }

  async function toggleAttemptDetails(attempt) {
    if (expandedAttemptId === attempt.attempt_id) {
      expandedAttemptId = null;
      return;
    }
    expandedAttemptId = attempt.attempt_id;
    if (detailByAttempt[attempt.attempt_id]) return;

    detailLoading = { ...detailLoading, [attempt.attempt_id]: true };
    detailError = { ...detailError, [attempt.attempt_id]: '' };
    try {
      const detail = await getTerminalOtaAttempt(attempt.attempt_id);
      if (!sessionIsCurrent() || expandedAttemptId !== attempt.attempt_id) return;
      detailByAttempt = { ...detailByAttempt, [attempt.attempt_id]: detail };
    } catch (error) {
      if (!sessionIsCurrent()) return;
      detailError = {
        ...detailError,
        [attempt.attempt_id]: error?.message || 'Attempt details are unavailable.',
      };
    } finally {
      if (sessionIsCurrent()) {
        detailLoading = { ...detailLoading, [attempt.attempt_id]: false };
      }
    }
  }

  async function cancelAttempt(device, attempt) {
    if (!canCancelTerminalOtaAttempt(attempt)) return;
    const label = device.name || device.mac || `terminal ${device.id}`;
    if (!confirm(
      `Cancel the unstarted OTA offer for ${label}? `
      + 'Cancellation is allowed only before the device accepts sequence 1.',
    )) return;

    cancellationSaving = { ...cancellationSaving, [attempt.attempt_id]: true };
    actionMessage = '';
    actionError = '';
    try {
      const updated = await cancelTerminalOtaAttempt(attempt);
      if (!sessionIsCurrent()) return;
      attemptsByDevice = {
        ...attemptsByDevice,
        [device.id]: (attemptsByDevice[device.id] || []).map(item => (
          item.attempt_id === updated.attempt_id ? updated : item
        )),
      };
      detailByAttempt = { ...detailByAttempt, [updated.attempt_id]: updated };
      actionMessage = `${label}: unstarted OTA offer cancelled.`;
    } catch (error) {
      if (sessionIsCurrent()) actionError = error?.message || 'The OTA offer could not be cancelled.';
    } finally {
      if (sessionIsCurrent()) {
        cancellationSaving = { ...cancellationSaving, [attempt.attempt_id]: false };
      }
    }
  }

  function stateLabel(state) {
    const labels = {
      offered: 'Offered · not started',
      downloading: 'Downloading',
      staged: 'Staged',
      booted_pending_validation: 'Booted · validating',
      succeeded: 'Succeeded',
      failed: 'Failed',
      rolled_back: 'Rolled back',
      recovery_required: 'Recovery required',
      cancelled: 'Cancelled',
      expired: 'Expired',
    };
    return labels[state] || String(state || 'unknown').replaceAll('_', ' ');
  }

  function stateStyle(state) {
    if (state === 'succeeded') {
      return 'background: var(--status-success-bg); border-color: var(--status-success-border); color: var(--status-success-text)';
    }
    if (state === 'failed' || state === 'recovery_required') {
      return 'background: var(--status-error-bg); border-color: var(--status-error-border); color: var(--status-error-text)';
    }
    if (ACTIVE_ATTEMPT_STATES.has(state)) {
      return 'background: var(--status-warning-bg); border-color: var(--status-warning-border); color: var(--status-warning-text)';
    }
    return 'background: var(--bg-tertiary); border-color: var(--border-color); color: var(--text-secondary)';
  }

  function formatTimestamp(value) {
    if (!value) return '—';
    const parsed = new Date(value);
    if (Number.isNaN(parsed.getTime())) return '—';
    return new Intl.DateTimeFormat(undefined, {
      dateStyle: 'medium',
      timeStyle: 'short',
    }).format(parsed);
  }

  function shortIdentity(value, length = 12) {
    if (typeof value !== 'string' || !value) return '—';
    return value.length > length ? `${value.slice(0, length)}…` : value;
  }
</script>

<section
  class="rounded-xl border p-5"
  style="background: var(--bg-secondary); border-color: var(--border-color)"
  aria-labelledby="terminal-ota-owner-title"
>
  <div class="flex flex-wrap items-start justify-between gap-3">
    <div class="max-w-2xl">
      <h4 id="terminal-ota-owner-title" class="text-sm font-semibold" style="color: var(--text-primary)">Device OTA control plane</h4>
      <p class="mt-1 text-[11px] leading-5" style="color: var(--text-tertiary)">
        Owner inspection and rescue controls only. This page never creates an update offer, downloads a firmware artifact, requests a serial port, or writes a device.
      </p>
    </div>
    <Button size="sm" onclick={refreshOtaStatus} disabled={refreshing}>
      {refreshing ? 'Refreshing…' : 'Refresh OTA status'}
    </Button>
  </div>

  <div class="mt-4 rounded-lg border p-4" style="background: var(--bg-primary); border-color: var(--border-color)" aria-label="Read-only OTA capability status">
    {#if capabilityLoading && !capabilities}
      <p class="text-xs" style="color: var(--text-tertiary)" role="status">Checking the read-only OTA gates…</p>
    {:else if capabilityError && !capabilities}
      <div role="alert">
        <p class="text-xs font-semibold" style="color: var(--status-error-text)">OTA gate status is unavailable</p>
        <p class="mt-1 text-[11px]" style="color: var(--text-tertiary)">{capabilityError}</p>
      </div>
    {:else if capabilities}
      <div class="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p class="text-xs font-semibold" style="color: var(--text-primary)">Effective offers</p>
          <p class="mt-0.5 text-[11px]" style="color: var(--text-tertiary)">Protocol {capabilities.protocol || 'OTA1'} · read only</p>
        </div>
        <span
          class="rounded-full border px-2.5 py-1 text-[10px] font-semibold uppercase tracking-wider"
          style={capabilities.effective_offer_enabled
            ? 'background: var(--status-success-bg); border-color: var(--status-success-border); color: var(--status-success-text)'
            : 'background: var(--status-warning-bg); border-color: var(--status-warning-border); color: var(--status-warning-text)'}
        >
          {capabilities.effective_offer_enabled ? 'Eligible' : 'Locked'}
        </span>
      </div>

      <div class="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-3">
        <div class="rounded-md border px-3 py-2 text-[11px]" style="border-color: var(--border-color); color: var(--text-secondary)">
          <span class="font-semibold">Server switch</span><br />{capabilities.enabled ? 'Enabled' : 'Disabled'}
        </div>
        <div class="rounded-md border px-3 py-2 text-[11px]" style="border-color: var(--border-color); color: var(--text-secondary)">
          <span class="font-semibold">Durable event ledger</span><br />{capabilities.event_persistence_ready ? 'Installed' : 'Unavailable'}
        </div>
        <div class="rounded-md border px-3 py-2 text-[11px]" style="border-color: var(--border-color); color: var(--text-secondary)">
          <span class="font-semibold">Exact HIL-qualified releases</span><br />{(capabilities.qualified_releases || []).length}
        </div>
      </div>

      {#if !capabilities.effective_offer_enabled}
        <ul class="mt-3 list-disc space-y-1 pl-5 text-[11px]" style="color: var(--text-tertiary)">
          {#each (capabilities.blockers || ['The OTA control plane is locked.']) as blocker}
            <li>{blocker}</li>
          {/each}
        </ul>
      {/if}
    {/if}

    <div class="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-2">
      <p class="rounded-md border px-3 py-2 text-[11px] leading-5" style="border-color: var(--border-color); color: var(--text-secondary)">
        <span class="font-semibold">Physical HIL remains independent.</span> Qualification must match the exact descriptor, signed parent release, model, and printed revision. A revision confirmation below is only an owner claim.
      </p>
      <p class="rounded-md border px-3 py-2 text-[11px] leading-5" style="border-color: var(--border-color); color: var(--text-secondary)">
        <span class="font-semibold">Rollout defaults to 0%.</span> This surface has no rollout or enablement control. Cohort percentage is snapshotted only in an already-created attempt.
      </p>
    </div>
  </div>

  {#if actionMessage}
    <p class="mt-3 rounded-lg border px-3 py-2 text-xs" style="background: var(--status-success-bg); border-color: var(--status-success-border); color: var(--status-success-text)" role="status">{actionMessage}</p>
  {/if}
  {#if actionError}
    <p class="mt-3 rounded-lg border px-3 py-2 text-xs" style="background: var(--status-error-bg); border-color: var(--status-error-border); color: var(--status-error-text)" role="alert">{actionError}</p>
  {/if}

  {#if devices.length === 0}
    <p class="mt-4 text-xs" style="color: var(--text-tertiary)">No checked-in terminal is available for revision confirmation or OTA history.</p>
  {:else}
    <div class="mt-4 space-y-4">
      {#each devices as device (device.id)}
        {@const attempts = attemptsByDevice[device.id] || []}
        {@const active = activeAttempt(device.id)}
        {@const draft = revisionDraft(device)}
        {@const savingRevision = !!revisionSaving[device.id]}
        <article class="rounded-lg border p-4" style="background: var(--bg-primary); border-color: var(--border-color)">
          <div class="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h5 class="text-xs font-semibold" style="color: var(--text-primary)">{device.name || device.mac || `Terminal ${device.id}`}</h5>
              <p class="mt-0.5 text-[11px]" style="color: var(--text-tertiary)">
                {device.hardware_model || 'unknown model'} · {device.enrollment_state || 'unknown enrollment'} · owner-scoped device {device.id}
              </p>
            </div>
            {#if active}
              <span class="rounded-full border px-2 py-1 text-[10px] font-semibold" style={stateStyle(active.state)}>{stateLabel(active.state)}</span>
            {/if}
          </div>

          <div class="mt-3 rounded-md border p-3" style="border-color: var(--border-color)">
            <div class="flex flex-wrap items-baseline justify-between gap-2">
              <div>
                <p class="text-[11px] font-semibold" style="color: var(--text-secondary)">Printed hardware revision</p>
                <p class="mt-0.5 text-[10px]" style="color: var(--text-tertiary)">
                  Enter the exact label; USB, model, and running firmware do not infer it.
                </p>
              </div>
              {#if device.hardware_revision_confirmed_at}
                <span class="text-[10px]" style="color: var(--text-tertiary)">Confirmed {formatTimestamp(device.hardware_revision_confirmed_at)}</span>
              {/if}
            </div>
            <div class="mt-2 flex flex-col gap-2 sm:flex-row sm:items-center">
              <input
                id="terminal-hardware-revision-{device.id}"
                type="text"
                value={draft}
                oninput={(event) => setRevisionDraft(device.id, event.currentTarget.value)}
                maxlength="64"
                spellcheck="false"
                autocomplete="off"
                aria-label="Printed hardware revision for {device.name || device.mac || `terminal ${device.id}`}"
                placeholder="e.g. V1.0"
                disabled={savingRevision || !!active}
                class="h-9 min-w-0 flex-1 rounded-lg border px-3 text-xs outline-none disabled:opacity-60"
                style="background: var(--bg-secondary); border-color: var(--border-color); color: var(--text-primary)"
              />
              <Button
                size="sm"
                variant="primary"
                onclick={() => confirmRevision(device)}
                disabled={savingRevision || !!active || !revisionIsValid(draft) || draft.trim() === (device.hardware_revision || '')}
              >
                {savingRevision ? 'Saving…' : 'Confirm printed revision'}
              </Button>
              {#if device.hardware_revision}
                <Button size="sm" variant="danger" onclick={() => clearRevision(device)} disabled={savingRevision || !!active}>
                  Clear confirmation
                </Button>
              {/if}
            </div>
            {#if active}
              <p class="mt-2 text-[10px]" style="color: var(--status-warning-text)">
                Revision changes are locked while attempt {shortIdentity(active.attempt_id, 8)} is active. An unstarted offer may be cancelled below; a started attempt cannot be cancelled here.
              </p>
            {:else if device.hardware_revision}
              <p class="mt-2 text-[10px]" style="color: var(--text-tertiary)">
                Confirmed value: <code>{device.hardware_revision}</code>. This alone does not enable OTA or satisfy physical HIL.
              </p>
            {/if}
          </div>

          <div class="mt-3">
            <div class="flex items-center justify-between gap-2">
              <h6 class="text-[11px] font-semibold" style="color: var(--text-secondary)">Attempt history</h6>
              <button type="button" onclick={() => loadAttempts(device.id)} disabled={attemptsLoading[device.id]} class="text-[10px] font-semibold hover:underline disabled:opacity-50" style="color: var(--color-accent-600)">
                {attemptsLoading[device.id] ? 'Refreshing…' : 'Refresh history'}
              </button>
            </div>

            {#if attemptsLoading[device.id] && attempts.length === 0}
              <p class="mt-2 text-[11px]" style="color: var(--text-tertiary)" role="status">Loading attempt history…</p>
            {:else if attemptsError[device.id] && attempts.length === 0}
              <p class="mt-2 text-[11px]" style="color: var(--status-error-text)" role="alert">{attemptsError[device.id]}</p>
            {:else if attempts.length === 0}
              <p class="mt-2 text-[11px]" style="color: var(--text-tertiary)">No OTA attempt has been created for this terminal.</p>
            {:else}
              <div class="mt-2 space-y-2">
                {#each attempts as attempt (attempt.attempt_id)}
                  {@const detail = detailByAttempt[attempt.attempt_id] || attempt}
                  <div class="rounded-md border px-3 py-2" style="border-color: var(--border-color)">
                    <div class="flex flex-wrap items-center justify-between gap-2">
                      <div>
                        <span class="rounded-full border px-2 py-0.5 text-[10px] font-semibold" style={stateStyle(attempt.state)}>{stateLabel(attempt.state)}</span>
                        <span class="ml-2 text-[10px]" style="color: var(--text-tertiary)">{formatTimestamp(attempt.created_at)}</span>
                      </div>
                      <div class="flex flex-wrap gap-2">
                        <button type="button" onclick={() => toggleAttemptDetails(attempt)} class="min-h-8 rounded-md border px-2.5 text-[10px] font-semibold" style="border-color: var(--border-color); color: var(--text-secondary)">
                          {expandedAttemptId === attempt.attempt_id ? 'Hide details' : 'View details'}
                        </button>
                        {#if canCancelTerminalOtaAttempt(attempt)}
                          <button
                            type="button"
                            onclick={() => cancelAttempt(device, attempt)}
                            disabled={cancellationSaving[attempt.attempt_id]}
                            class="min-h-8 rounded-md border px-2.5 text-[10px] font-semibold disabled:opacity-50"
                            style="border-color: var(--status-error-border); color: var(--status-error-text)"
                          >
                            {cancellationSaving[attempt.attempt_id] ? 'Cancelling…' : 'Cancel unstarted offer'}
                          </button>
                        {/if}
                      </div>
                    </div>
                    <p class="mt-1.5 text-[10px]" style="color: var(--text-tertiary)">
                      {attempt.source_version || 'unknown source'} → {attempt.target_version || 'unknown target'} · {attempt.device_model || 'unknown model'} / {attempt.hardware_revision || 'unconfirmed revision'}
                    </p>

                    {#if expandedAttemptId === attempt.attempt_id}
                      <div class="mt-3 border-t pt-3" style="border-color: var(--border-color)">
                        {#if detailLoading[attempt.attempt_id] && !detailByAttempt[attempt.attempt_id]}
                          <p class="text-[10px]" style="color: var(--text-tertiary)" role="status">Loading authoritative attempt details…</p>
                        {:else if detailError[attempt.attempt_id]}
                          <p class="text-[10px]" style="color: var(--status-error-text)" role="alert">{detailError[attempt.attempt_id]}</p>
                        {:else}
                          <dl class="grid grid-cols-1 gap-x-4 gap-y-2 text-[10px] sm:grid-cols-2">
                            <div><dt style="color: var(--text-tertiary)">Attempt / offer</dt><dd class="font-mono break-all" style="color: var(--text-secondary)">{detail.attempt_id}<br />{detail.offer_id}</dd></div>
                            <div><dt style="color: var(--text-tertiary)">Sequence integrity</dt><dd style="color: var(--text-secondary)">Last {detail.last_sequence ?? 0} · {detail.has_event_gap ? 'event gap detected' : 'no recorded gap'}</dd></div>
                            <div><dt style="color: var(--text-tertiary)">Descriptor / parent</dt><dd class="font-mono" title={detail.release_id} style="color: var(--text-secondary)">{shortIdentity(detail.release_id)} / {shortIdentity(detail.parent_release_id)}</dd></div>
                            <div><dt style="color: var(--text-tertiary)">Signed catalog</dt><dd style="color: var(--text-secondary)">Generation {detail.catalog_generation ?? '—'} · key {detail.signing_key_id || '—'}</dd></div>
                            <div><dt style="color: var(--text-tertiary)">Source runtime</dt><dd style="color: var(--text-secondary)">{detail.source_version || '—'} · {shortIdentity(detail.source_build_id)} · {detail.source_partition || '—'}</dd></div>
                            <div><dt style="color: var(--text-tertiary)">Target runtime</dt><dd style="color: var(--text-secondary)">{detail.target_version || '—'} · {shortIdentity(detail.target_build_id)} · {detail.layout || '—'}</dd></div>
                            <div><dt style="color: var(--text-tertiary)">Rollout snapshot</dt><dd style="color: var(--text-secondary)">{detail.rollout_percentage ?? 0}% · cohort bucket {detail.cohort_bucket ?? '—'}</dd></div>
                            <div><dt style="color: var(--text-tertiary)">Lifecycle</dt><dd style="color: var(--text-secondary)">Expires {formatTimestamp(detail.expires_at)}<br />Terminal {formatTimestamp(detail.terminal_at)}</dd></div>
                          </dl>
                        {/if}
                      </div>
                    {/if}
                  </div>
                {/each}
              </div>
            {/if}
          </div>
        </article>
      {/each}
    </div>
  {/if}
</section>
