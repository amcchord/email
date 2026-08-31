<script>
  import { tick } from 'svelte';
  import { api } from '../../lib/api.js';
  import {
    captureAuthenticatedSession,
    isAuthenticatedSessionCurrent,
  } from '../../lib/stores.js';
  import {
    createInboxRulePayload,
    inboxPlacementLabel,
    inboxRuleFutureEffect,
    isInboxRuleConflict,
    newInboxRuleCreateId,
    normalizeInboxRuleCandidate,
    normalizeInboxRuleMutation,
  } from '../../lib/inboxPlacementRules.js';
  import Icon from '../common/Icon.svelte';

  let {
    open = $bindable(false),
    email = null,
    onmutated = null,
    onconflict = null,
    onfocusfallback = null,
  } = $props();

  let dialog = $state(null);
  let returnFocus = null;
  let observedOpen = false;
  let observedEmailId = null;
  let requestGeneration = 0;
  let requestController = null;
  let mutationGeneration = 0;
  let loading = $state(false);
  let saving = $state(false);
  let error = $state('');
  let conflict = $state(false);
  let state = $state.raw(null);
  let selectedScope = $state('');
  let placement = $state('focused');
  let createId = null;

  let selectedScopeCandidate = $derived(
    state?.scopes?.find(item => item.scope === selectedScope) || null,
  );

  function abortRequests() {
    requestGeneration += 1;
    mutationGeneration += 1;
    requestController?.abort();
    requestController = null;
    loading = false;
    saving = false;
  }

  async function closePicker({ restoreFocus = true, force = false } = {}) {
    if (saving && !force) return;
    abortRequests();
    open = false;
    state = null;
    error = '';
    conflict = false;
    await tick();
    if (restoreFocus && returnFocus?.isConnected) {
      returnFocus.focus({ preventScroll: true });
    } else {
      onfocusfallback?.();
    }
    returnFocus = null;
  }

  async function reloadLatestChoices() {
    if (loading || saving) return;
    await onconflict?.();
    if (open) await loadCandidate();
  }

  async function loadCandidate() {
    const emailId = Number(email?.id);
    if (!open || !Number.isInteger(emailId) || emailId < 1) return;
    requestController?.abort();
    const generation = ++requestGeneration;
    const session = captureAuthenticatedSession();
    const controller = new AbortController();
    requestController = controller;
    loading = true;
    error = '';
    conflict = false;
    state = null;
    createId = null;
    try {
      const accountId = Number(email?.account_id);
      if (!Number.isInteger(accountId) || accountId < 1) throw new Error('This conversation has no exact account context.');
      const response = await api.getInboxPlacementRuleCandidate(accountId, emailId, {
        signal: controller.signal,
      });
      if (
        generation !== requestGeneration
        || controller.signal.aborted
        || !open
        || Number(email?.id) !== emailId
        || !isAuthenticatedSessionCurrent(session)
      ) return;
      const normalized = normalizeInboxRuleCandidate(response);
      state = normalized;
      selectedScope = normalized.scopes[0].scope;
      placement = email?.inbox_placement === 'focused' ? 'other' : 'focused';
    } catch (loadError) {
      if (
        generation !== requestGeneration
        || controller.signal.aborted
        || !open
        || !isAuthenticatedSessionCurrent(session)
      ) return;
      error = loadError?.message || 'The Split Inbox choices could not be loaded.';
    } finally {
      if (generation === requestGeneration) {
        requestController = null;
        loading = false;
      }
    }
  }

  async function applyRule() {
    if (!state || !selectedScopeCandidate || saving) return;
    let payload;
    try {
      const requestCreateId = createId || newInboxRuleCreateId();
      createId = requestCreateId;
      payload = createInboxRulePayload({
        createId: requestCreateId,
        accountId: state.candidate.account_id,
        anchorEmailId: state.candidate.anchor_email_id,
        scope: selectedScope,
        placement,
        currentRule: selectedScopeCandidate.current_rule,
      });
    } catch (validationError) {
      error = validationError?.message || 'Review this rule.';
      return;
    }

    const generation = ++mutationGeneration;
    const session = captureAuthenticatedSession();
    const emailId = Number(email?.id);
    saving = true;
    error = '';
    conflict = false;
    try {
      const mutation = normalizeInboxRuleMutation(
        await api.createInboxPlacementRule(payload),
        selectedScopeCandidate.current_rule,
      );
      if (
        generation !== mutationGeneration
        || !open
        || Number(email?.id) !== emailId
        || !isAuthenticatedSessionCurrent(session)
      ) return;
      const accepted = await onmutated?.({
        kind: 'teach',
        mutation,
        candidate: state.candidate,
      });
      if (accepted === false) return;
      await closePicker({ restoreFocus: false, force: true });
    } catch (saveError) {
      if (
        generation !== mutationGeneration
        || !open
        || !isAuthenticatedSessionCurrent(session)
      ) return;
      conflict = isInboxRuleConflict(saveError);
      error = conflict
        ? 'This rule changed in another session. Reload the latest choices before trying again.'
        : (saveError?.message || 'The Split Inbox rule could not be saved.');
    } finally {
      if (generation === mutationGeneration) saving = false;
    }
  }

  function resetCreateAttempt() {
    createId = null;
    error = '';
    conflict = false;
  }

  function focusableElements() {
    if (!dialog) return [];
    return [...dialog.querySelectorAll(
      'button:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])',
    )].filter(element => !element.hidden && element.offsetParent !== null);
  }

  function handleKeydown(event) {
    event.stopPropagation();
    if (event.key === 'Escape') {
      event.preventDefault();
      void closePicker();
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
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }

  $effect(() => {
    const emailId = Number(email?.id) || null;
    if (open && observedOpen && emailId !== observedEmailId) {
      observedEmailId = emailId;
      void loadCandidate();
      return;
    }
    if (open === observedOpen) return;
    observedOpen = open;
    observedEmailId = emailId;
    if (!open) {
      abortRequests();
      return;
    }
    returnFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    void loadCandidate();
    void tick().then(() => dialog?.focus({ preventScroll: true }));
  });
</script>

{#if open}
  <div class="inbox-rule-layer fixed inset-0 z-[74] flex items-center justify-center p-4" role="presentation">
    <button
      type="button"
      class="absolute inset-0 bg-black/45"
      aria-label="Close Teach Split Inbox"
      onclick={() => closePicker()}
    ></button>
    <div
      bind:this={dialog}
      class="inbox-rule-dialog relative flex max-h-[92dvh] w-full max-w-xl flex-col overflow-hidden rounded-2xl border shadow-2xl"
      style="background: var(--bg-primary); border-color: var(--border-color)"
      role="dialog"
      tabindex="-1"
      aria-busy={saving}
      aria-modal="true"
      aria-labelledby="inbox-rule-picker-title"
      aria-describedby="inbox-rule-picker-description"
      onkeydown={handleKeydown}
    >
      <header class="flex items-start gap-3 border-b px-5 py-4" style="border-color: var(--border-color)">
        <div class="min-w-0 flex-1">
          <h2 id="inbox-rule-picker-title" class="text-base font-semibold" style="color: var(--text-primary)">Teach Split Inbox</h2>
          <p id="inbox-rule-picker-description" class="mt-1 text-xs leading-relaxed" style="color: var(--text-secondary)">
            Create a personal rule for future Inbox conversations. This changes your local Inbox view only; Gmail is unchanged.
          </p>
        </div>
        <button type="button" class="inline-flex min-h-11 min-w-11 items-center justify-center rounded-lg disabled:opacity-50" disabled={saving} aria-label="Close Teach Split Inbox" onclick={() => closePicker()}>
          <Icon name="x" size={19} />
        </button>
      </header>

      <div class="flex-1 overflow-y-auto p-5">
        {#if loading}
          <div class="flex min-h-52 flex-col items-center justify-center gap-3" role="status">
            <span class="h-6 w-6 animate-spin rounded-full border-2" style="border-color: var(--border-color); border-top-color: var(--color-accent-500)"></span>
            <span class="text-sm" style="color: var(--text-secondary)">Loading safe rule choices…</span>
          </div>
        {:else if error && !state}
          <div class="rounded-xl border p-4" style="border-color: var(--status-error); background: var(--status-error-bg)" role="alert">
            <p class="text-sm font-medium" style="color: var(--status-error)">{error}</p>
            <button type="button" class="mt-3 min-h-11 rounded-lg border px-4 text-sm font-semibold" style="border-color: var(--border-color); color: var(--text-primary)" onclick={conflict ? reloadLatestChoices : loadCandidate}>
              {conflict ? 'Reload latest choices' : 'Try again'}
            </button>
          </div>
        {:else if state}
          <div class="rounded-xl border p-4" style="border-color: var(--border-color); background: var(--bg-secondary)">
            <p class="text-xs font-semibold uppercase tracking-wide" style="color: var(--text-tertiary)">Exact account</p>
            <p class="mt-1 break-all text-sm font-medium" style="color: var(--text-primary)">{state.candidate.account_email}</p>
            <p class="mt-2 text-xs" style="color: var(--text-secondary)">
              Currently in <strong>{inboxPlacementLabel(email?.inbox_placement)}</strong>. Rules never cross connected accounts.
            </p>
          </div>

          <fieldset class="mt-5">
            <legend class="text-sm font-semibold" style="color: var(--text-primary)">What should this rule match?</legend>
            <div class="mt-2 space-y-2">
              {#each state.scopes as scope (scope.scope)}
                <label class="flex min-h-11 cursor-pointer items-start gap-3 rounded-xl border px-3 py-3" style="border-color: {selectedScope === scope.scope ? 'var(--color-accent-500)' : 'var(--border-color)'}">
                  <input type="radio" name="inbox-rule-scope" value={scope.scope} bind:group={selectedScope} disabled={saving} onchange={resetCreateAttempt} />
                  <span class="min-w-0 flex-1">
                    <span class="block text-sm font-medium" style="color: var(--text-primary)">{scope.display_label}</span>
                    <span class="mt-0.5 block text-xs" style="color: var(--text-secondary)">{inboxRuleFutureEffect(scope.scope)}</span>
                    {#if scope.current_rule}
                      <span class="mt-1 block text-[11px] font-medium" style="color: var(--color-accent-700)">Existing rule: {inboxPlacementLabel(scope.current_rule.placement)}{scope.current_rule.enabled ? '' : ' · off'}</span>
                    {/if}
                  </span>
                </label>
              {/each}
            </div>
          </fieldset>

          <fieldset class="mt-5">
            <legend class="text-sm font-semibold" style="color: var(--text-primary)">Place future matches in</legend>
            <div class="mt-2 grid grid-cols-2 gap-2">
              {#each ['focused', 'other'] as target}
                <label class="flex min-h-11 cursor-pointer items-center gap-2 rounded-xl border px-3" style="border-color: {placement === target ? 'var(--color-accent-500)' : 'var(--border-color)'}">
                  <input type="radio" name="inbox-rule-placement" value={target} bind:group={placement} disabled={saving} onchange={resetCreateAttempt} />
                  <span class="text-sm font-semibold" style="color: var(--text-primary)">{inboxPlacementLabel(target)}</span>
                </label>
              {/each}
            </div>
          </fieldset>

          {#if selectedScopeCandidate}
            <p class="mt-4 rounded-lg px-3 py-2 text-xs leading-relaxed" style="background: var(--bg-tertiary); color: var(--text-secondary)">
              {inboxRuleFutureEffect(selectedScopeCandidate.scope)} Existing messages are re-evaluated only when the full Split Inbox refreshes.
            </p>
          {/if}

          {#if error}
            <div class="mt-4 rounded-lg border p-3" style="border-color: var(--status-error); background: var(--status-error-bg)" role="alert">
              <p class="text-xs font-medium" style="color: var(--status-error)">{error}</p>
              {#if conflict}
                <button type="button" class="mt-2 min-h-11 rounded-lg border px-3 text-xs font-semibold" style="border-color: var(--border-color); color: var(--text-primary)" onclick={reloadLatestChoices}>Reload latest choices</button>
              {/if}
            </div>
          {/if}
        {/if}
      </div>

      <footer class="flex flex-wrap-reverse justify-end gap-2 border-t px-5 py-4" style="border-color: var(--border-color)">
        <button type="button" class="min-h-11 rounded-lg border px-4 text-sm font-semibold disabled:opacity-50" style="border-color: var(--border-color); color: var(--text-secondary)" disabled={saving} onclick={() => closePicker()}>Cancel</button>
        <button type="button" class="min-h-11 rounded-lg bg-accent-600 px-4 text-sm font-semibold text-white disabled:opacity-50" disabled={!state || loading || saving || conflict} onclick={applyRule}>
          {saving ? 'Refreshing Split Inbox…' : 'Save rule'}
        </button>
      </footer>
    </div>
  </div>
{/if}

<style>
  @media (max-width: 639px) {
    .inbox-rule-layer {
      align-items: flex-end;
      padding: 0;
    }
    .inbox-rule-dialog {
      max-height: min(92dvh, 760px);
      border-radius: 1.25rem 1.25rem 0 0;
      border-bottom: 0;
    }
  }
</style>
