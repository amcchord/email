<script>
  import { tick } from 'svelte';
  import {
    DEFAULT_SWIPE_TRIAGE_PREFERENCES,
    SWIPE_TRIAGE_ACTIONS,
    SWIPE_TRIAGE_ACTION_DETAILS,
    normalizeSwipeTriagePreferences,
  } from '../../lib/swipeTriage.js';
  import Icon from '../common/Icon.svelte';

  let {
    open = $bindable(false),
    preferences = DEFAULT_SWIPE_TRIAGE_PREFERENCES,
    disabled = false,
    onsave = null,
    onclose = null,
    onfocusfallback = null,
  } = $props();

  let dialog = $state(null);
  let returnFocus = null;
  let observedOpen = false;
  let rightAction = $state(DEFAULT_SWIPE_TRIAGE_PREFERENCES.right);
  let leftAction = $state(DEFAULT_SWIPE_TRIAGE_PREFERENCES.left);
  let saving = $state(false);
  let error = $state('');

  let rightDetails = $derived(SWIPE_TRIAGE_ACTION_DETAILS[rightAction]);
  let leftDetails = $derived(SWIPE_TRIAGE_ACTION_DETAILS[leftAction]);

  function restoreFocus() {
    if (returnFocus?.isConnected) returnFocus.focus({ preventScroll: true });
    else onfocusfallback?.();
    returnFocus = null;
  }

  async function closeSettings() {
    if (saving) return;
    open = false;
    onclose?.();
  }

  async function saveSettings(event) {
    event?.preventDefault?.();
    if (saving || disabled) return;
    const next = normalizeSwipeTriagePreferences({ right: rightAction, left: leftAction });
    saving = true;
    error = '';
    try {
      const accepted = await onsave?.(next);
      if (accepted === false) return;
      open = false;
      onclose?.();
      await tick();
      restoreFocus();
    } catch (saveError) {
      error = saveError?.message || 'Swipe actions could not be saved. Try again.';
    } finally {
      saving = false;
    }
  }

  function focusableElements() {
    if (!dialog) return [];
    return [...dialog.querySelectorAll(
      'button:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])',
    )].filter(element => !element.hidden && element.offsetParent !== null);
  }

  function handleKeydown(event) {
    event.stopPropagation();
    if (event.key === 'Escape') {
      event.preventDefault();
      void closeSettings();
      return;
    }
    if (event.key !== 'Tab') return;
    const focusable = focusableElements();
    if (!focusable.length) {
      event.preventDefault();
      dialog?.focus();
      return;
    }
    const first = focusable[0];
    const last = focusable.at(-1);
    if (event.shiftKey && (document.activeElement === first || document.activeElement === dialog)) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && (document.activeElement === last || document.activeElement === dialog)) {
      event.preventDefault();
      first.focus();
    }
  }

  $effect(() => {
    const isOpen = open;
    if (isOpen === observedOpen) return;
    observedOpen = isOpen;
    if (!isOpen) {
      if (!saving) void tick().then(restoreFocus);
      return;
    }
    const normalized = normalizeSwipeTriagePreferences(preferences);
    rightAction = normalized.right;
    leftAction = normalized.left;
    error = '';
    returnFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    void tick().then(() => dialog?.focus({ preventScroll: true }));
  });
</script>

{#if open}
  <div class="swipe-settings-layer fixed inset-0 z-[76] flex items-center justify-center p-4" role="presentation">
    <button
      type="button"
      class="absolute inset-0 bg-black/45"
      aria-label="Close swipe action settings"
      disabled={saving}
      onclick={() => closeSettings()}
    ></button>
    <div
      bind:this={dialog}
      class="swipe-settings-dialog relative flex max-h-[92dvh] w-full max-w-lg flex-col overflow-hidden rounded-2xl border shadow-2xl"
      style="background: var(--bg-primary); border-color: var(--border-color)"
      role="dialog"
      tabindex="-1"
      aria-modal="true"
      aria-busy={saving}
      aria-labelledby="swipe-settings-title"
      aria-describedby="swipe-settings-description"
      onkeydown={handleKeydown}
    >
      <form class="contents" onsubmit={saveSettings}>
        <header class="flex items-start gap-3 border-b px-5 py-4" style="border-color: var(--border-color)">
        <div class="min-w-0 flex-1">
          <h2 id="swipe-settings-title" class="text-base font-semibold" style="color: var(--text-primary)">Swipe actions</h2>
          <p id="swipe-settings-description" class="mt-1 text-xs leading-relaxed" style="color: var(--text-secondary)">
            Choose what a deliberate horizontal swipe does in Inbox. Swipe left defaults to Archive; swipe right defaults to Snooze.
          </p>
        </div>
        <button
          type="button"
          class="inline-flex min-h-11 min-w-11 items-center justify-center rounded-lg disabled:opacity-50"
          disabled={saving}
          aria-label="Close swipe action settings"
          onclick={() => closeSettings()}
        >
          <Icon name="x" size={19} />
        </button>
        </header>

        <div class="flex-1 space-y-5 overflow-y-auto p-5">
        <div class="rounded-xl border p-4 text-xs leading-relaxed" style="border-color: var(--border-color); background: var(--bg-secondary); color: var(--text-secondary)">
          Swipe actions use the same account-safe Inbox action and Undo path as the toolbar. Snooze asks for a return time. “No action” disables that direction. Trash, spam, and move are never swipe choices.
        </div>

        <label class="block" for="swipe-action-right">
          <span class="flex items-center gap-2 text-sm font-semibold" style="color: var(--text-primary)">
            <Icon name="arrow-right" size={17} />
            Swipe right
          </span>
          <select
            id="swipe-action-right"
            class="mt-2 min-h-11 w-full rounded-xl border px-3 text-sm outline-none focus-visible:ring-2"
            style="background: var(--bg-primary); border-color: var(--border-color); color: var(--text-primary)"
            bind:value={rightAction}
            disabled={saving || disabled}
          >
            {#each SWIPE_TRIAGE_ACTIONS as action}
              <option value={action}>{SWIPE_TRIAGE_ACTION_DETAILS[action].label}</option>
            {/each}
          </select>
          <span class="mt-2 flex items-start gap-2 rounded-lg px-3 py-2 text-xs leading-relaxed" style="background: var(--bg-tertiary); color: var(--text-secondary)">
            <Icon name={rightDetails.icon} size={16} class="mt-0.5 shrink-0" />
            {rightDetails.effect}
          </span>
        </label>

        <label class="block" for="swipe-action-left">
          <span class="flex items-center gap-2 text-sm font-semibold" style="color: var(--text-primary)">
            <Icon name="arrow-left" size={17} />
            Swipe left
          </span>
          <select
            id="swipe-action-left"
            class="mt-2 min-h-11 w-full rounded-xl border px-3 text-sm outline-none focus-visible:ring-2"
            style="background: var(--bg-primary); border-color: var(--border-color); color: var(--text-primary)"
            bind:value={leftAction}
            disabled={saving || disabled}
          >
            {#each SWIPE_TRIAGE_ACTIONS as action}
              <option value={action}>{SWIPE_TRIAGE_ACTION_DETAILS[action].label}</option>
            {/each}
          </select>
          <span class="mt-2 flex items-start gap-2 rounded-lg px-3 py-2 text-xs leading-relaxed" style="background: var(--bg-tertiary); color: var(--text-secondary)">
            <Icon name={leftDetails.icon} size={16} class="mt-0.5 shrink-0" />
            {leftDetails.effect}
          </span>
        </label>

        {#if error}
          <div class="rounded-lg border p-3 text-sm font-medium" style="border-color: var(--status-error); background: var(--status-error-bg); color: var(--status-error)" role="alert">
            {error}
          </div>
        {/if}
        </div>

        <footer class="flex flex-wrap-reverse justify-end gap-2 border-t px-5 py-4" style="border-color: var(--border-color)">
        <button
          type="button"
          class="min-h-11 rounded-lg border px-4 text-sm font-semibold disabled:opacity-50"
          style="border-color: var(--border-color); color: var(--text-secondary)"
          disabled={saving}
          onclick={() => closeSettings()}
        >Cancel</button>
        <button
          type="submit"
          class="min-h-11 rounded-lg bg-accent-600 px-4 text-sm font-semibold text-white disabled:opacity-50"
          disabled={saving || disabled}
        >{saving ? 'Saving…' : 'Save swipe actions'}</button>
        </footer>
      </form>
    </div>
  </div>
{/if}

<style>
  @media (max-width: 639px) {
    .swipe-settings-layer {
      align-items: flex-end;
      padding: 0;
    }
    .swipe-settings-dialog {
      max-height: min(92dvh, 760px);
      border-radius: 1.25rem 1.25rem 0 0;
      border-bottom: 0;
      padding-bottom: env(safe-area-inset-bottom);
    }
  }
</style>
