<script>
  import { tick } from 'svelte';
  import Icon from './Icon.svelte';
  import {
    browserScheduleTimezone,
    formatScheduledDelivery,
    localScheduleInputValue,
    resolveLocalSchedule,
    scheduledSendQuickChoices,
  } from '../../lib/sendLater.js';

  let {
    disabled = false,
    busy = false,
    label = 'Send',
    busyLabel = 'Sending…',
    compact = false,
    onsend = null,
    onschedule = null,
  } = $props();

  let dialog = $state(null);
  let choices = $state([]);
  let customValue = $state('');
  let customResult = $state(null);
  let submitting = $state(false);
  let dialogOpen = $state(false);
  const timezone = browserScheduleTimezone();

  function openSchedule() {
    if (disabled || busy || submitting) return;
    choices = scheduledSendQuickChoices();
    customValue = localScheduleInputValue();
    customResult = null;
    dialogOpen = true;
    dialog?.showModal?.();
    void tick().then(() => dialog?.querySelector?.('[data-first-choice]')?.focus?.());
  }

  function closeSchedule() {
    if (dialog?.open && !submitting) dialog.close();
    if (!submitting) dialogOpen = false;
  }

  async function chooseSchedule(iso) {
    if (!iso || submitting) return;
    submitting = true;
    try {
      await onschedule?.({ scheduledFor: iso, scheduleTimezone: timezone });
      dialog?.close?.();
      dialogOpen = false;
    } finally {
      submitting = false;
    }
  }

  function reviewCustom() {
    customResult = resolveLocalSchedule(customValue);
    if (customResult?.candidates?.length === 1) {
      void chooseSchedule(customResult.candidates[0].iso);
    }
  }

  function handleBackdrop(event) {
    if (event.target === dialog) closeSchedule();
  }
</script>

<div class="send-split inline-flex min-h-11 shrink-0 overflow-hidden rounded-lg shadow-sm">
  <button
    type="button"
    class="send-primary inline-flex min-h-11 items-center justify-center gap-1.5 bg-accent-600 px-3 font-medium text-white transition-fast hover:bg-accent-700 focus-visible:z-10 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent-500 disabled:cursor-not-allowed disabled:opacity-50"
    class:text-xs={compact}
    disabled={disabled || busy || submitting}
    onclick={() => onsend?.()}
    title="Send now · Command or Control Enter"
  >
    {#if busy || submitting}
      <span class="h-3.5 w-3.5 animate-spin rounded-full border-2 border-white/30 border-t-white" aria-hidden="true"></span>
      {busyLabel}
    {:else}
      <Icon name="send" size={compact ? 12 : 14} />
      {label}
    {/if}
  </button>
  <button
    type="button"
    class="send-options inline-flex min-h-11 min-w-11 items-center justify-center border-l border-white/25 bg-accent-600 px-2 text-white transition-fast hover:bg-accent-700 focus-visible:z-10 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent-500 disabled:cursor-not-allowed disabled:opacity-50"
    disabled={disabled || busy || submitting}
    onclick={openSchedule}
    aria-label="Send options"
    aria-haspopup="dialog"
    aria-expanded={dialogOpen}
  >
    <Icon name="chevron-down" size={compact ? 12 : 14} />
  </button>
</div>

<dialog
  bind:this={dialog}
  class="send-later-dialog m-auto w-[min(92vw,30rem)] rounded-2xl border p-0 shadow-2xl backdrop:bg-black/40"
  style="background: var(--bg-primary); border-color: var(--border-color); color: var(--text-primary)"
  aria-labelledby="send-later-title"
  onclick={handleBackdrop}
  onclose={() => { dialogOpen = false; }}
>
  <div class="p-5 sm:p-6">
    <div class="mb-4 flex items-start justify-between gap-4">
      <div>
        <h2 id="send-later-title" class="text-lg font-semibold">Send later</h2>
        <p class="mt-1 text-xs" style="color: var(--text-secondary)">
          Times use {timezone}. You can cancel or send early from the scheduled-mail bar.
        </p>
      </div>
      <button
        type="button"
        class="inline-flex min-h-11 min-w-11 items-center justify-center rounded-lg hover:opacity-70"
        onclick={closeSchedule}
        aria-label="Close send later"
      >
        <Icon name="x" size={18} />
      </button>
    </div>

    <div class="grid gap-2">
      {#each choices as choice, index}
        <button
          data-first-choice={index === 0 ? '' : undefined}
          type="button"
          class="flex min-h-12 items-center justify-between gap-4 rounded-xl border px-4 py-2.5 text-left transition-fast hover:border-accent-400 hover:bg-accent-50/50 dark:hover:bg-accent-950/20"
          style="border-color: var(--border-color)"
          disabled={submitting}
          onclick={() => chooseSchedule(choice.iso)}
        >
          <span class="flex items-center gap-3 font-medium">
            <Icon name="clock" size={16} />
            {choice.label}
          </span>
          <span class="text-xs" style="color: var(--text-secondary)">{formatScheduledDelivery(choice.iso, timezone, { compact: true })}</span>
        </button>
      {/each}
    </div>

    <div class="my-5 flex items-center gap-3" aria-hidden="true">
      <span class="h-px flex-1" style="background: var(--border-color)"></span>
      <span class="text-[11px] font-semibold uppercase tracking-wider" style="color: var(--text-tertiary)">Custom</span>
      <span class="h-px flex-1" style="background: var(--border-color)"></span>
    </div>

    <div class="flex flex-col gap-3 sm:flex-row sm:items-end">
      <label class="flex-1 text-xs font-medium">
        Date and time
        <input
          type="datetime-local"
          bind:value={customValue}
          class="mt-1 min-h-11 w-full rounded-lg border px-3 text-sm focus:outline-none focus:ring-2 focus:ring-accent-500/40"
          style="background: var(--bg-secondary); border-color: var(--border-color); color: var(--text-primary)"
          oninput={() => { customResult = null; }}
        />
      </label>
      <button
        type="button"
        class="min-h-11 rounded-lg bg-accent-600 px-4 text-sm font-semibold text-white hover:bg-accent-700 disabled:opacity-50"
        disabled={submitting}
        onclick={reviewCustom}
      >Schedule</button>
    </div>

    {#if customResult?.error}
      <p class="mt-2 text-xs text-red-600" role="alert">{customResult.error}</p>
    {:else if customResult?.candidates?.length > 1}
      <div class="mt-3 rounded-xl border p-3" style="border-color: var(--border-color)">
        <p class="mb-2 text-xs font-medium">The clock repeats this time. Choose the exact occurrence:</p>
        <div class="grid gap-2 sm:grid-cols-2">
          {#each customResult.candidates as candidate}
            <button
              type="button"
              class="min-h-11 rounded-lg border px-3 text-xs font-semibold hover:border-accent-400"
              style="border-color: var(--border-color)"
              onclick={() => chooseSchedule(candidate.iso)}
            >{formatScheduledDelivery(candidate.iso, timezone)} · {candidate.offsetLabel}</button>
          {/each}
        </div>
      </div>
    {/if}
  </div>
</dialog>

<style>
  .send-later-dialog[open] { animation: send-later-in 120ms ease-out; }
  @keyframes send-later-in {
    from { opacity: 0; transform: translateY(8px) scale(.99); }
    to { opacity: 1; transform: translateY(0) scale(1); }
  }
  @media (max-width: 640px) {
    .send-later-dialog {
      width: 100%;
      max-width: none;
      margin: auto 0 0;
      border-radius: 1.25rem 1.25rem 0 0;
    }
  }
</style>
