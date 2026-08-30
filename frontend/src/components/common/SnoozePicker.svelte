<script>
  import { tick } from 'svelte';
  import Icon from './Icon.svelte';
  import {
    browserScheduleTimezone,
    formatSnoozeWake,
    localScheduleInputValue,
    resolveLocalSchedule,
    snoozeQuickChoices,
  } from '../../lib/remindLater.js';

  let {
    open = false,
    email = null,
    mode = 'create',
    onclose = null,
    onsubmit = null,
  } = $props();

  let dialog = $state(null);
  let choices = $state([]);
  let customValue = $state('');
  let customResult = $state(null);
  let condition = $state('always');
  let submitting = $state(false);
  let submitError = $state('');
  let wasOpen = false;
  let returnFocus = null;
  const timezone = browserScheduleTimezone();

  $effect(() => {
    if (open && !wasOpen) {
      wasOpen = true;
      returnFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
      choices = snoozeQuickChoices();
      customValue = localScheduleInputValue(email?.snooze_wake_at || undefined);
      customResult = null;
      condition = email?.snooze_condition || (email?.is_sent ? 'if_no_reply' : 'always');
      submitError = '';
      dialog?.showModal?.();
      void tick().then(() => dialog?.querySelector?.('[data-first-choice]')?.focus?.());
    } else if (!open && wasOpen) {
      wasOpen = false;
      if (dialog?.open) dialog.close();
    }
  });

  function restoreFocus() {
    const target = returnFocus;
    returnFocus = null;
    if (target?.isConnected) void tick().then(() => target.focus());
  }

  function closePicker() {
    if (submitting) return;
    if (dialog?.open) dialog.close();
    onclose?.();
  }

  function handleClose() {
    const shouldNotify = open;
    wasOpen = false;
    restoreFocus();
    if (shouldNotify) onclose?.();
  }

  async function chooseWake(wakeAt) {
    if (!wakeAt || submitting) return;
    submitting = true;
    submitError = '';
    try {
      // Invoke first so the owner captures the exact selected email before
      // closing the controlled picker clears its target prop.
      const submission = onsubmit?.({ wakeAt, timeZone: timezone, condition });
      // Close before the network round trip. The owning surface performs the
      // optimistic removal and owns rollback/Undo feedback.
      if (dialog?.open) dialog.close();
      onclose?.();
      await submission;
    } catch (error) {
      submitError = error?.message || 'This email could not be snoozed.';
    } finally {
      submitting = false;
    }
  }

  function reviewCustom() {
    customResult = resolveLocalSchedule(customValue);
    if (customResult?.candidates?.length === 1) {
      void chooseWake(customResult.candidates[0].iso);
    }
  }

  function handleBackdrop(event) {
    if (event.target === dialog) closePicker();
  }
</script>

<dialog
  bind:this={dialog}
  class="snooze-dialog m-auto w-[min(92vw,31rem)] rounded-2xl border p-0 shadow-2xl backdrop:bg-black/40"
  style="background: var(--bg-primary); border-color: var(--border-color); color: var(--text-primary)"
  aria-labelledby="snooze-picker-title"
  aria-describedby="snooze-picker-description"
  onclick={handleBackdrop}
  onclose={handleClose}
>
  <div class="p-5 sm:p-6">
    <div class="mb-4 flex items-start justify-between gap-4">
      <div class="min-w-0">
        <h2 id="snooze-picker-title" class="text-lg font-semibold">
          {mode === 'reschedule' ? 'Change reminder' : 'Snooze email'}
        </h2>
        <p id="snooze-picker-description" class="mt-1 text-xs" style="color: var(--text-secondary)">
          {mode === 'reschedule' ? 'Choose a new return time' : 'Bring this conversation back when you need it'} · {timezone}
        </p>
        {#if email?.subject}
          <p class="mt-2 truncate text-sm font-medium" title={email.subject}>{email.subject}</p>
        {/if}
      </div>
      <button
        type="button"
        class="inline-flex min-h-11 min-w-11 shrink-0 items-center justify-center rounded-lg hover:opacity-70"
        onclick={closePicker}
        aria-label="Close snooze picker"
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
          onclick={() => chooseWake(choice.iso)}
        >
          <span class="flex items-center gap-3 font-medium">
            <Icon name="clock" size={16} />
            {choice.label}
          </span>
          <span class="text-right text-xs" style="color: var(--text-secondary)">
            {formatSnoozeWake(choice.iso, timezone, { compact: true })}
          </span>
        </button>
      {/each}
    </div>

    {#if mode !== 'reschedule'}
      <fieldset class="mt-4 rounded-xl border p-3" style="border-color: var(--border-color)">
        <legend class="px-1 text-xs font-semibold">Return this email</legend>
        <div class="grid gap-2 sm:grid-cols-2">
          <label class="flex min-h-11 cursor-pointer items-center gap-2 rounded-lg px-2 text-sm">
            <input type="radio" bind:group={condition} value="always" />
            At this time
          </label>
          <label class="flex min-h-11 cursor-pointer items-center gap-2 rounded-lg px-2 text-sm">
            <input type="radio" bind:group={condition} value="if_no_reply" />
            Only if nobody replies
          </label>
        </div>
      </fieldset>
    {:else}
      <p class="mt-4 rounded-xl border px-3 py-2 text-xs" style="border-color: var(--border-color); color: var(--text-secondary)">
        {condition === 'if_no_reply' ? 'Returns only if nobody has replied.' : 'Returns at the reminder time.'}
      </p>
    {/if}

    <div class="my-5 flex items-center gap-3" aria-hidden="true">
      <span class="h-px flex-1" style="background: var(--border-color)"></span>
      <span class="text-[11px] font-semibold uppercase tracking-wider" style="color: var(--text-tertiary)">Custom</span>
      <span class="h-px flex-1" style="background: var(--border-color)"></span>
    </div>

    <div class="flex flex-col gap-3 sm:flex-row sm:items-end">
      <label class="flex-1 text-xs font-medium">
        Local date and time
        <input
          type="datetime-local"
          bind:value={customValue}
          class="mt-1 min-h-11 w-full rounded-lg border px-3 text-sm focus:outline-none focus:ring-2 focus:ring-accent-500/40"
          style="background: var(--bg-secondary); border-color: var(--border-color); color: var(--text-primary)"
          oninput={() => { customResult = null; submitError = ''; }}
        />
      </label>
      <button
        type="button"
        class="min-h-11 rounded-lg bg-accent-600 px-4 text-sm font-semibold text-white hover:bg-accent-700 disabled:opacity-50"
        disabled={submitting}
        onclick={reviewCustom}
      >{mode === 'reschedule' ? 'Update' : 'Snooze'}</button>
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
              onclick={() => chooseWake(candidate.iso)}
            >{formatSnoozeWake(candidate.iso, timezone)} · {candidate.offsetLabel}</button>
          {/each}
        </div>
      </div>
    {/if}

    {#if submitError}
      <p class="mt-3 text-xs text-red-600" role="alert">{submitError}</p>
    {/if}
  </div>
</dialog>

<style>
  .snooze-dialog[open] { animation: snooze-in 120ms ease-out; }
  @keyframes snooze-in {
    from { opacity: 0; transform: translateY(8px) scale(.99); }
    to { opacity: 1; transform: translateY(0) scale(1); }
  }
  @media (max-width: 640px) {
    .snooze-dialog {
      width: 100%;
      max-width: none;
      max-height: min(92dvh, 46rem);
      margin: auto 0 0;
      overflow-y: auto;
      border-radius: 1.25rem 1.25rem 0 0;
    }
  }
</style>
