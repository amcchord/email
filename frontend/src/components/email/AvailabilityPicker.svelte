<script>
  import { tick } from 'svelte';
  import { api } from '../../lib/api.js';
  import {
    captureAuthenticatedSession,
    isAuthenticatedSessionCurrent,
  } from '../../lib/stores.js';
  import {
    AVAILABILITY_DURATIONS,
    AVAILABILITY_RANGES,
    availabilityCoverageMessage,
    browserAvailabilityTimeZone,
    buildAvailabilityRequest,
    calendarScopedAvailabilityAccounts,
    defaultAvailabilityAccountIds,
    formatAvailabilitySnapshot,
    groupAvailabilitySlots,
    normalizeAvailabilityResponse,
    senderCanShareAvailability,
  } from '../../lib/shareAvailability.js';
  import Icon from '../common/Icon.svelte';

  let {
    open = $bindable(false),
    accounts = [],
    senderAccountId = null,
    disabled = false,
    shortcutId = null,
    oninsert = null,
    oncapture = null,
    compact = false,
  } = $props();

  let trigger = $state(null);
  let dialog = $state(null);
  let returnFocus = null;
  let observedOpen = false;
  let observedSenderId = null;
  let senderObserved = false;
  let triggerCaptured = false;
  let requestGeneration = 0;
  let requestController = null;
  let configurationGeneration = 0;

  let selectedAccountIds = $state([]);
  let durationMinutes = $state(30);
  let rangeDays = $state(7);
  let dayStart = $state('09:00');
  let dayEnd = $state('17:00');
  let includeWeekends = $state(false);
  let timeZone = $state(browserAvailabilityTimeZone());
  let loading = $state(false);
  let error = $state('');
  let result = $state.raw(null);
  let selectedSlotKeys = $state([]);

  let scopedAccounts = $derived(calendarScopedAvailabilityAccounts(accounts));
  let senderId = $derived(Number(senderAccountId) || null);
  let senderReady = $derived(senderCanShareAvailability(accounts, senderId));
  let triggerDisabled = $derived(disabled || !senderReady);
  let selectedSlots = $derived(
    (result?.slots || []).filter(slot => selectedSlotKeys.includes(slotKey(slot))),
  );
  let groupedSlots = $derived(result ? groupAvailabilitySlots(result.slots, result.timezone) : []);

  function accountLabel(account) {
    return account?.short_label || account?.description || account?.email || `Account ${account?.id}`;
  }

  function slotKey(slot) {
    return `${slot?.start || ''}|${slot?.end || ''}`;
  }

  function abortRequest() {
    requestGeneration += 1;
    requestController?.abort();
    requestController = null;
    loading = false;
  }

  function resetPicker() {
    abortRequest();
    selectedAccountIds = defaultAvailabilityAccountIds(accounts, senderId);
    durationMinutes = 30;
    rangeDays = 7;
    dayStart = '09:00';
    dayEnd = '17:00';
    includeWeekends = false;
    timeZone = browserAvailabilityTimeZone();
    error = '';
    result = null;
    selectedSlotKeys = [];
    configurationGeneration += 1;
  }

  function invalidateResult() {
    abortRequest();
    configurationGeneration += 1;
    error = '';
    result = null;
    selectedSlotKeys = [];
  }

  async function closePicker({ restoreFocus = true } = {}) {
    abortRequest();
    open = false;
    result = null;
    error = '';
    selectedSlotKeys = [];
    await tick();
    if (restoreFocus && returnFocus?.isConnected) {
      returnFocus.focus({ preventScroll: true });
    }
    returnFocus = null;
  }

  function selectedScopeIsCurrent(accountIds) {
    const availableIds = new Set(scopedAccounts.map(account => Number(account.id)));
    return senderReady
      && accountIds.includes(senderId)
      && accountIds.length === selectedAccountIds.length
      && accountIds.every(id => selectedAccountIds.includes(id) && availableIds.has(id));
  }

  async function checkAvailability() {
    let payload;
    try {
      payload = buildAvailabilityRequest({
        accountIds: selectedAccountIds,
        senderAccountId: senderId,
        durationMinutes,
        rangeDays,
        dayStart,
        dayEnd,
        includeWeekends,
        timeZone,
      });
    } catch (validationError) {
      error = validationError?.message || 'Review the availability settings.';
      result = null;
      return;
    }

    abortRequest();
    const generation = ++requestGeneration;
    const configurationAtStart = configurationGeneration;
    const senderAtStart = senderId;
    const accountIdsAtStart = [...payload.account_ids];
    const session = captureAuthenticatedSession();
    const controller = new AbortController();
    requestController = controller;
    loading = true;
    error = '';
    result = null;
    selectedSlotKeys = [];
    try {
      const response = await api.getCalendarAvailability(payload, { signal: controller.signal });
      if (
        generation !== requestGeneration
        || configurationAtStart !== configurationGeneration
        || !open
        || senderAtStart !== senderId
        || !selectedScopeIsCurrent(accountIdsAtStart)
        || !isAuthenticatedSessionCurrent(session)
      ) return;
      result = normalizeAvailabilityResponse(response, {
        accountIds: accountIdsAtStart,
        timeZone: payload.timezone,
        durationMinutes: payload.duration_minutes,
      });
    } catch (loadError) {
      if (
        generation !== requestGeneration
        || controller.signal.aborted
        || !open
        || !isAuthenticatedSessionCurrent(session)
      ) return;
      error = loadError?.message || 'Availability snapshot could not be checked.';
      result = null;
    } finally {
      if (generation === requestGeneration) {
        requestController = null;
        loading = false;
      }
    }
  }

  function toggleAccount(accountId, checked) {
    const id = Number(accountId);
    if (id === senderId) return;
    selectedAccountIds = checked
      ? [...new Set([...selectedAccountIds, id])]
      : selectedAccountIds.filter(candidate => candidate !== id);
    invalidateResult();
  }

  function toggleSlot(slot, checked) {
    const key = slotKey(slot);
    selectedSlotKeys = checked
      ? [...new Set([...selectedSlotKeys, key])]
      : selectedSlotKeys.filter(candidate => candidate !== key);
  }

  async function insertSelection() {
    if (!result?.ready || selectedSlots.length === 0) return;
    try {
      const snapshot = formatAvailabilitySnapshot(result, selectedSlots);
      const accepted = await oninsert?.(snapshot);
      if (accepted === false) return;
      await closePicker({ restoreFocus: false });
    } catch (insertError) {
      error = insertError?.message || 'The availability snapshot could not be inserted.';
    }
  }

  function focusableElements() {
    if (!dialog) return [];
    return [...dialog.querySelectorAll(
      'button:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])',
    )].filter(element => !element.hidden && element.offsetParent !== null);
  }

  function handleDialogKeydown(event) {
    event.stopPropagation();
    if (event.key === 'Escape') {
      event.preventDefault();
      void closePicker();
      return;
    }
    if (event.key !== 'Tab') return;
    const focusable = focusableElements();
    if (focusable.length === 0) {
      event.preventDefault();
      dialog?.focus();
      return;
    }
    const first = focusable[0];
    const last = focusable.at(-1);
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }

  $effect(() => {
    const currentSenderId = senderId;
    if (!senderObserved) {
      observedSenderId = currentSenderId;
      senderObserved = true;
      return;
    }
    if (currentSenderId === observedSenderId) return;
    observedSenderId = currentSenderId;
    resetPicker();
    if (open) void closePicker();
  });

  $effect(() => {
    const isOpen = open;
    if (isOpen === observedOpen) return;
    observedOpen = isOpen;
    if (!isOpen) {
      abortRequest();
      return;
    }
    if (triggerDisabled) {
      open = false;
      return;
    }
    returnFocus = document.activeElement instanceof HTMLElement
      ? document.activeElement
      : trigger;
    resetPicker();
    void tick().then(() => {
      const first = dialog?.querySelector('input:not([disabled]), button:not([disabled])');
      if (first instanceof HTMLElement) first.focus({ preventScroll: true });
      else dialog?.focus({ preventScroll: true });
    });
  });
</script>

<button
  bind:this={trigger}
  type="button"
  class="availability-trigger inline-flex min-h-11 items-center justify-center gap-1.5 rounded-lg border px-3 text-xs font-semibold transition-fast disabled:opacity-50"
  class:compact
  style="border-color: var(--border-color); color: var(--text-secondary); background: var(--bg-primary)"
  aria-label="Share availability"
  aria-haspopup="dialog"
  aria-expanded={open}
  data-shortcut={shortcutId || undefined}
  disabled={triggerDisabled}
  title={!senderReady
    ? 'Calendar access is not enabled for the sending account.'
    : 'Share an availability snapshot'}
  onpointerdown={() => {
    triggerCaptured = Boolean(oncapture?.());
  }}
  onclick={() => {
    if (triggerDisabled) return;
    if (!triggerCaptured) oncapture?.();
    triggerCaptured = false;
    open = true;
  }}
>
  <Icon name="calendar" size={15} />
  {#if !compact}<span class="availability-trigger-label">Availability</span>{/if}
</button>

{#if open}
  <div class="availability-layer fixed inset-0 z-[72] flex items-center justify-center p-4" role="presentation">
    <button
      type="button"
      class="absolute inset-0 bg-black/45"
      aria-label="Close availability picker"
      onclick={() => closePicker()}
    ></button>
    <div
      bind:this={dialog}
      class="availability-dialog relative flex max-h-[92dvh] w-full max-w-3xl flex-col overflow-hidden rounded-2xl border shadow-2xl"
      style="background: var(--bg-primary); border-color: var(--border-color)"
      role="dialog"
      tabindex="-1"
      aria-modal="true"
      aria-labelledby="availability-picker-title"
      aria-describedby="availability-picker-description"
      onkeydown={handleDialogKeydown}
    >
      <header class="flex items-start gap-3 border-b px-5 py-4" style="border-color: var(--border-color)">
        <div class="min-w-0 flex-1">
          <h2 id="availability-picker-title" class="text-base font-semibold" style="color: var(--text-primary)">Share availability</h2>
          <p id="availability-picker-description" class="mt-1 text-xs leading-relaxed" style="color: var(--text-tertiary)">
            Check a saved availability snapshot, select times, then insert them into this message.
          </p>
        </div>
        <button
          type="button"
          class="inline-flex min-h-11 min-w-11 items-center justify-center rounded-lg"
          style="color: var(--text-secondary)"
          aria-label="Close availability picker"
          onclick={() => closePicker()}
        ><Icon name="x" size={19} /></button>
      </header>

      <div class="availability-body flex-1 overflow-y-auto p-5">
        <div class="grid gap-5 lg:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]">
          <section class="space-y-5" aria-label="Availability settings">
            <fieldset>
              <legend class="text-sm font-semibold" style="color: var(--text-primary)">Calendars to check</legend>
              <p class="mt-1 text-[11px]" style="color: var(--text-tertiary)">The sending account is required. Other connected calendars are optional.</p>
              <div class="mt-2 space-y-1.5">
                {#each scopedAccounts as account (account.id)}
                  <label class="flex min-h-11 items-center gap-3 rounded-lg border px-3 py-2" style="border-color: var(--border-color)">
                    <input
                      type="checkbox"
                      checked={selectedAccountIds.includes(Number(account.id))}
                      disabled={Number(account.id) === senderId}
                      onchange={event => toggleAccount(account.id, event.currentTarget.checked)}
                    />
                    <span class="min-w-0 flex-1">
                      <span class="block truncate text-sm font-medium" style="color: var(--text-primary)">{accountLabel(account)}</span>
                      <span class="block truncate text-[11px]" style="color: var(--text-tertiary)">{account.email}</span>
                    </span>
                    {#if Number(account.id) === senderId}
                      <span class="shrink-0 text-[10px] font-semibold" style="color: var(--color-accent-700)">Sending account · required</span>
                    {/if}
                  </label>
                {/each}
              </div>
            </fieldset>

            <div class="grid gap-4 sm:grid-cols-2">
              <label class="block text-xs font-semibold" style="color: var(--text-secondary)">
                Date range
                <select bind:value={rangeDays} onchange={invalidateResult} class="mt-1 min-h-11 w-full rounded-lg border px-3 text-sm" style="background: var(--bg-primary); border-color: var(--border-color); color: var(--text-primary)">
                  {#each AVAILABILITY_RANGES as days}
                    <option value={days}>Next {days} days</option>
                  {/each}
                </select>
              </label>
              <label class="block text-xs font-semibold" style="color: var(--text-secondary)">
                Meeting length
                <select bind:value={durationMinutes} onchange={invalidateResult} class="mt-1 min-h-11 w-full rounded-lg border px-3 text-sm" style="background: var(--bg-primary); border-color: var(--border-color); color: var(--text-primary)">
                  {#each AVAILABILITY_DURATIONS as minutes}
                    <option value={minutes}>{minutes} minutes</option>
                  {/each}
                </select>
              </label>
              <label class="block text-xs font-semibold" style="color: var(--text-secondary)">
                Workday starts
                <input type="time" bind:value={dayStart} min="06:00" max="22:00" step="900" onchange={invalidateResult} class="mt-1 min-h-11 w-full rounded-lg border px-3 text-sm" style="background: var(--bg-primary); border-color: var(--border-color); color: var(--text-primary)" />
              </label>
              <label class="block text-xs font-semibold" style="color: var(--text-secondary)">
                Workday ends
                <input type="time" bind:value={dayEnd} min="06:00" max="22:00" step="900" onchange={invalidateResult} class="mt-1 min-h-11 w-full rounded-lg border px-3 text-sm" style="background: var(--bg-primary); border-color: var(--border-color); color: var(--text-primary)" />
              </label>
            </div>

            <label class="flex min-h-11 items-center gap-3 rounded-lg border px-3" style="border-color: var(--border-color)">
              <input type="checkbox" bind:checked={includeWeekends} onchange={invalidateResult} />
              <span class="text-sm font-medium" style="color: var(--text-primary)">Include weekends</span>
            </label>

            <label class="block text-xs font-semibold" style="color: var(--text-secondary)">
              Time zone
              <input bind:value={timeZone} onchange={invalidateResult} autocomplete="off" spellcheck="false" class="mt-1 min-h-11 w-full rounded-lg border px-3 text-sm" style="background: var(--bg-primary); border-color: var(--border-color); color: var(--text-primary)" placeholder="America/New_York" />
            </label>

            <button
              type="button"
              class="inline-flex min-h-11 w-full items-center justify-center gap-2 rounded-lg bg-accent-600 px-4 text-sm font-semibold text-white disabled:opacity-50"
              disabled={loading || selectedAccountIds.length === 0 || !selectedAccountIds.includes(senderId)}
              onclick={checkAvailability}
            >
              {#if loading}<span class="h-4 w-4 animate-spin rounded-full border-2 border-white/40 border-t-white"></span>{/if}
              {loading ? 'Checking…' : 'Check availability'}
            </button>
          </section>

          <section class="min-h-72 rounded-xl border p-4" style="border-color: var(--border-color); background: var(--bg-secondary)" aria-labelledby="available-times-title">
            <div class="flex items-start justify-between gap-3">
              <div>
                <h3 id="available-times-title" class="text-sm font-semibold" style="color: var(--text-primary)">Available times</h3>
                <p class="mt-1 text-[11px]" style="color: var(--text-tertiary)">Showing up to 8 matching times from saved calendar data.</p>
              </div>
              {#if result?.ready}
                <span class="shrink-0 rounded-full px-2 py-1 text-[10px] font-semibold" style="background: var(--status-success-bg); color: var(--status-success)">Snapshot ready</span>
              {/if}
            </div>

            {#if loading}
              <div class="flex min-h-56 items-center justify-center gap-2 text-sm" style="color: var(--text-secondary)" role="status">
                <span class="h-4 w-4 animate-spin rounded-full border-2 border-current border-t-transparent"></span>
                Checking saved calendars…
              </div>
            {:else if error}
              <div class="flex min-h-56 flex-col items-center justify-center gap-3 px-4 text-center" role="alert">
                <Icon name="alert-circle" size={24} />
                <p class="text-sm" style="color: var(--status-error)">{error}</p>
                <button type="button" class="min-h-11 rounded-lg border px-4 text-sm font-semibold" style="border-color: var(--border-color)" onclick={checkAvailability}>Retry</button>
              </div>
            {:else if result}
              <div class="mt-4 space-y-3" aria-label="Calendar coverage">
                {#each result.coverage as coverage (coverage.account_id)}
                  <article class="rounded-lg border px-3 py-2" style="border-color: var(--border-color); background: var(--bg-primary)">
                    <div class="flex items-center justify-between gap-2">
                      <span class="truncate text-xs font-semibold" style="color: var(--text-primary)">{coverage.account_email}</span>
                      <span class="shrink-0 text-[10px] font-semibold" style="color: {coverage.state === 'ready' ? 'var(--status-success)' : 'var(--status-warning)'}">{coverage.state === 'ready' ? 'Ready' : 'Needs attention'}</span>
                    </div>
                    <p class="mt-1 text-[11px] leading-relaxed" style="color: var(--text-tertiary)">{availabilityCoverageMessage(coverage, result.timezone)}</p>
                  </article>
                {/each}
              </div>

              {#if !result.ready}
                <div class="mt-4 rounded-lg border px-4 py-3 text-sm" style="border-color: var(--status-warning-border); background: var(--status-warning-bg); color: var(--status-warning-text)" role="status">
                  Calendar coverage is incomplete. Adjust the selected calendars or reconnect the affected account, then retry.
                </div>
              {:else if result.slots.length === 0}
                <div class="flex min-h-40 flex-col items-center justify-center gap-2 px-4 text-center" role="status">
                  <Icon name="calendar" size={24} />
                  <p class="text-sm font-medium" style="color: var(--text-primary)">No times fit these settings</p>
                  <p class="text-xs" style="color: var(--text-tertiary)">Try a longer date range, wider workday, or another meeting length.</p>
                </div>
              {:else}
                <div class="mt-4 space-y-4">
                  {#each groupedSlots as group (group.label)}
                    <fieldset>
                      <legend class="text-xs font-semibold" style="color: var(--text-secondary)">{group.label}</legend>
                      <div class="mt-2 grid gap-2 sm:grid-cols-2">
                        {#each group.slots as slot (slot.start)}
                          <label class="flex min-h-11 items-center gap-2 rounded-lg border px-3 py-2 text-sm" class:selected={selectedSlotKeys.includes(slotKey(slot))} style="border-color: var(--border-color); background: var(--bg-primary)">
                            <input type="checkbox" checked={selectedSlotKeys.includes(slotKey(slot))} onchange={event => toggleSlot(slot, event.currentTarget.checked)} />
                            <span>{slot.label}</span>
                          </label>
                        {/each}
                      </div>
                    </fieldset>
                  {/each}
                </div>
              {/if}
            {:else}
              <div class="flex min-h-56 flex-col items-center justify-center gap-2 px-4 text-center">
                <Icon name="calendar" size={26} />
                <p class="text-sm font-medium" style="color: var(--text-primary)">Choose how to check your calendars</p>
                <p class="text-xs leading-relaxed" style="color: var(--text-tertiary)">Nothing is inserted until you select times and confirm.</p>
              </div>
            {/if}
          </section>
        </div>
      </div>

      <footer class="flex flex-wrap items-center justify-between gap-3 border-t px-5 py-3" style="border-color: var(--border-color)">
        <span class="text-[11px]" style="color: var(--text-tertiary)" aria-live="polite">
          {selectedSlots.length ? `${selectedSlots.length} time${selectedSlots.length === 1 ? '' : 's'} selected` : 'Select at least one time to insert'}
        </span>
        <div class="flex items-center gap-2">
          <button type="button" class="min-h-11 rounded-lg px-4 text-sm font-semibold" style="color: var(--text-secondary)" onclick={() => closePicker()}>Cancel</button>
          <button
            type="button"
            class="min-h-11 rounded-lg bg-accent-600 px-4 text-sm font-semibold text-white disabled:opacity-50"
            disabled={!result?.ready || selectedSlots.length === 0}
            onclick={insertSelection}
          >Insert selected times</button>
        </div>
      </footer>
    </div>
  </div>
{/if}

<style>
  .availability-trigger.compact {
    min-width: 2.75rem;
    padding-inline: 0.625rem;
  }

  label.selected {
    border-color: var(--color-accent-500) !important;
    box-shadow: inset 0 0 0 1px var(--color-accent-500);
  }

  @media (max-width: 767px) {
    .availability-trigger {
      min-width: 2.75rem;
      padding-inline: 0.625rem;
    }

    .availability-trigger-label {
      display: none;
    }

    .availability-layer {
      align-items: flex-end;
      padding: 0;
    }

    .availability-dialog {
      max-height: 92dvh;
      border-radius: 1.25rem 1.25rem 0 0;
      border-bottom: 0;
    }

    .availability-body {
      padding: 1rem;
    }
  }

  @media (prefers-reduced-motion: reduce) {
    .animate-spin { animation: none; }
  }
</style>
