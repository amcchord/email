<script>
  import { tick } from 'svelte';
  import { api } from '../../lib/api.js';
  import {
    labelActionForMode,
    labelMembership,
    normalizeUserLabels,
    resolveLabelAccount,
    safeLabelColor,
  } from '../../lib/labelWorkflows.js';
  import Icon from '../common/Icon.svelte';
  import { claimLabelPickerKeyEvent } from '../../lib/labelPickerKeys.js';

  let {
    open = false,
    mode = 'apply',
    emails = [],
    accounts = [],
    catalog = [],
    onclose = null,
    oncatalog = null,
    onsubmit = null,
    onfocusfallback = null,
  } = $props();

  let dialog = $state(null);
  let searchInput = $state(null);
  let query = $state('');
  let pickerLabels = $state([]);
  let loading = $state(false);
  let loadError = $state('');
  let submitError = $state('');
  let submittingId = $state(null);
  let wasOpen = false;
  let returnFocus = null;
  let loadGeneration = 0;

  let account = $derived(resolveLabelAccount(emails, accounts));
  let filteredLabels = $derived(
    pickerLabels.filter(label => label.name.toLowerCase().includes(query.trim().toLowerCase())),
  );
  let title = $derived(mode === 'move' ? 'Move to label' : 'Apply label');

  $effect(() => {
    if (open && !wasOpen) {
      wasOpen = true;
      returnFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
      query = '';
      loadError = '';
      submitError = '';
      pickerLabels = account.state === 'single'
        ? normalizeUserLabels(catalog, account.accountId)
        : [];
      dialog?.showModal?.();
      void tick().then(() => searchInput?.focus?.());
      if (account.state === 'single') void loadLabels(account.accountId);
    } else if (!open && wasOpen) {
      wasOpen = false;
      loadGeneration += 1;
      if (dialog?.open) dialog.close();
    }
  });

  async function loadLabels(accountId) {
    const generation = ++loadGeneration;
    loading = true;
    loadError = '';
    try {
      const fetched = await api.getLabels(accountId);
      if (generation !== loadGeneration || !open) return;
      pickerLabels = normalizeUserLabels(fetched, accountId);
      oncatalog?.(fetched, accountId);
    } catch (error) {
      if (generation !== loadGeneration || !open) return;
      loadError = error?.message || 'Labels could not be loaded.';
    } finally {
      if (generation === loadGeneration) loading = false;
    }
  }

  function restoreFocus() {
    const target = returnFocus;
    returnFocus = null;
    void tick().then(() => {
      if (target?.isConnected) target.focus();
      else onfocusfallback?.();
    });
  }

  function closePicker() {
    if (submittingId !== null) return;
    if (dialog?.open) dialog.close();
    else onclose?.();
  }

  function handleClose() {
    const shouldNotify = open;
    wasOpen = false;
    loadGeneration += 1;
    restoreFocus();
    if (shouldNotify) onclose?.();
  }

  function handleCancel(event) {
    event.preventDefault();
    closePicker();
  }

  function handleBackdrop(event) {
    if (event.target === dialog) closePicker();
  }

  function optionButtons() {
    return [...dialog.querySelectorAll('[data-label-option]:not(:disabled)')];
  }

  function navigateOptions(event) {
    if (!['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) return;
    const buttons = optionButtons();
    if (!buttons.length) return;
    event.preventDefault();
    const current = buttons.indexOf(document.activeElement);
    let index = event.key === 'Home' ? 0 : event.key === 'End' ? buttons.length - 1 : current;
    if (event.key === 'ArrowDown') index = current < 0 ? 0 : Math.min(buttons.length - 1, current + 1);
    if (event.key === 'ArrowUp') index = current < 0 ? buttons.length - 1 : Math.max(0, current - 1);
    buttons[index]?.focus();
  }

  function handleKeydown(event) {
    claimLabelPickerKeyEvent(event, { preventEscape: true });
    if (event.key === 'Escape') {
      closePicker();
      return;
    }
    navigateOptions(event);
  }

  function handleTrailingKeyEvent(event) {
    claimLabelPickerKeyEvent(event);
  }

  async function chooseLabel(label) {
    if (submittingId !== null || account.state !== 'single') return;
    const membership = labelMembership(emails, label.gmail_label_id);
    const action = labelActionForMode(mode, membership);
    submittingId = label.id;
    submitError = '';
    try {
      const accepted = await onsubmit?.({
        action,
        labelId: label.id,
        gmailLabelId: label.gmail_label_id,
        labelName: label.name,
      });
      if (accepted !== false) {
        submittingId = null;
        closePicker();
        return;
      }
      submitError = 'The label change was not accepted. Try again.';
    } catch (error) {
      submitError = error?.message || 'The label change could not be completed.';
    } finally {
      submittingId = null;
    }
  }
</script>

<dialog
  bind:this={dialog}
  class="label-dialog m-auto w-[min(92vw,32rem)] rounded-2xl border p-0 shadow-2xl backdrop:bg-black/40"
  style="background: var(--bg-primary); border-color: var(--border-color); color: var(--text-primary)"
  aria-labelledby="label-picker-title"
  aria-describedby="label-picker-description"
  onclick={handleBackdrop}
  oncancel={handleCancel}
  onclose={handleClose}
  onkeydown={handleKeydown}
  onkeyup={handleTrailingKeyEvent}
  onkeypress={handleTrailingKeyEvent}
>
  <div class="flex max-h-[82dvh] flex-col">
    <div class="shrink-0 border-b p-5" style="border-color: var(--border-color)">
      <div class="flex items-start justify-between gap-4">
        <div class="min-w-0">
          <h2 id="label-picker-title" class="text-lg font-semibold">{title}</h2>
          <p id="label-picker-description" class="mt-1 text-xs" style="color: var(--text-secondary)">
            {emails.length === 1 ? '1 email' : `${emails.length} emails`}
            {#if account.accountEmail} · {account.accountEmail}{/if}
          </p>
          <p class="mt-1 text-xs" style="color: var(--text-tertiary)">
            {#if mode === 'move'}
              Applies the destination label and removes every current message in the selected conversation{emails.length === 1 ? '' : 's'} from Inbox.
            {:else}
              Applies to all existing messages in the selected conversation{emails.length === 1 ? '' : 's'}.
            {/if}
          </p>
        </div>
        <button
          type="button"
          class="inline-flex min-h-11 min-w-11 shrink-0 items-center justify-center rounded-lg hover:opacity-70 disabled:opacity-50"
          disabled={submittingId !== null}
          onclick={closePicker}
          aria-label={`Close ${title.toLowerCase()}`}
        ><Icon name="x" size={18} /></button>
      </div>

      {#if account.state === 'single'}
        <label class="relative mt-4 block">
          <span class="sr-only">Search labels</span>
          <span class="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2" style="color: var(--text-tertiary)">
            <Icon name="search" size={16} />
          </span>
          <input
            bind:this={searchInput}
            bind:value={query}
            type="search"
            class="min-h-11 w-full rounded-xl border py-2 pl-10 pr-3 text-sm focus:outline-none focus:ring-2 focus:ring-accent-500/40"
            style="background: var(--bg-secondary); border-color: var(--border-color); color: var(--text-primary)"
            placeholder="Search existing labels"
            autocomplete="off"
          />
        </label>
      {/if}
    </div>

    <div class="min-h-32 flex-1 overflow-y-auto p-3" aria-busy={loading}>
      {#if account.state !== 'single'}
        <div class="m-2 rounded-xl border p-4 text-sm" role="status" style="border-color: var(--border-color); background: var(--bg-secondary)">
          <div class="mb-2 flex items-center gap-2 font-semibold"><Icon name="alert-circle" size={17} /> Account-specific labels</div>
          <p style="color: var(--text-secondary)">{account.message}</p>
        </div>
      {:else if loading && pickerLabels.length === 0}
        <div class="flex min-h-28 items-center justify-center gap-2 text-sm" role="status" style="color: var(--text-secondary)">
          <span class="h-4 w-4 animate-spin rounded-full border-2 border-current border-t-transparent"></span>
          Loading labels
        </div>
      {:else if loadError && pickerLabels.length === 0}
        <div class="m-2 rounded-xl border p-4 text-sm" role="alert" style="border-color: var(--status-error); color: var(--status-error)">
          <p>{loadError}</p>
          <button type="button" class="mt-3 min-h-11 rounded-lg border px-4 font-semibold" onclick={() => loadLabels(account.accountId)}>Try again</button>
        </div>
      {:else if pickerLabels.length === 0}
        <div class="flex min-h-28 flex-col items-center justify-center p-4 text-center">
          <Icon name="tag" size={24} />
          <p class="mt-2 text-sm font-semibold">No user labels</p>
          <p class="mt-1 text-xs" style="color: var(--text-secondary)">Create a label in Gmail, then refresh this list.</p>
        </div>
      {:else if filteredLabels.length === 0}
        <div class="flex min-h-28 items-center justify-center p-4 text-center text-sm" style="color: var(--text-secondary)">
          No labels match “{query}”
        </div>
      {:else}
        {#if loadError}
          <p class="mx-2 mb-2 rounded-lg px-3 py-2 text-xs" role="status" style="background: var(--bg-tertiary); color: var(--text-secondary)">
            Showing saved labels. Refresh failed: {loadError}
          </p>
        {/if}
        <div class="grid gap-1">
          {#each filteredLabels as label}
            {@const membership = labelMembership(emails, label.gmail_label_id)}
            {@const removes = mode === 'apply' && membership === 'all'}
            <button
              type="button"
              data-label-option
              class="flex min-h-12 w-full items-center gap-3 rounded-xl px-3 py-2 text-left hover:bg-accent-50 disabled:opacity-50 dark:hover:bg-accent-950/20"
              disabled={submittingId !== null}
              role={mode === 'apply' ? 'checkbox' : undefined}
              aria-checked={mode === 'apply' ? (membership === 'some' ? 'mixed' : membership === 'all') : undefined}
              onclick={() => chooseLabel(label)}
            >
              <span
                class="inline-flex h-5 w-5 shrink-0 items-center justify-center rounded border"
                style="background: {membership === 'none' ? 'transparent' : safeLabelColor(label.color_bg, 'var(--color-accent-500)')}; border-color: {safeLabelColor(label.color_bg, 'var(--border-color)')}; color: {safeLabelColor(label.color_text, '#ffffff')}"
                aria-hidden="true"
              >
                {#if membership === 'all'}<Icon name="check" size={13} strokeWidth={3} />
                {:else if membership === 'some'}<Icon name="minus" size={13} strokeWidth={3} />{/if}
              </span>
              <span class="min-w-0 flex-1 truncate font-medium">{label.name}</span>
              <span class="shrink-0 text-xs" style="color: var(--text-secondary)">
                {#if submittingId === label.id}Working…
                {:else if mode === 'move'}Move
                {:else if removes}Remove
                {:else if membership === 'some'}Apply to all
                {:else}Apply{/if}
              </span>
            </button>
          {/each}
        </div>
      {/if}
      {#if submitError}<p class="m-2 text-xs" role="alert" style="color: var(--status-error)">{submitError}</p>{/if}
    </div>
  </div>
</dialog>

<style>
  .label-dialog[open] { animation: label-in 120ms ease-out; }
  @keyframes label-in {
    from { opacity: 0; transform: translateY(8px) scale(.99); }
    to { opacity: 1; transform: translateY(0) scale(1); }
  }
  @media (max-width: 640px) {
    .label-dialog {
      width: 100%;
      max-width: none;
      max-height: 94dvh;
      margin: auto 0 0;
      border-radius: 1.25rem 1.25rem 0 0;
    }
  }
</style>
