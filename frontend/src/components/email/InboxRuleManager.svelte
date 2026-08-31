<script>
  import { tick } from 'svelte';
  import { api } from '../../lib/api.js';
  import {
    captureAuthenticatedSession,
    isAuthenticatedSessionCurrent,
  } from '../../lib/stores.js';
  import {
    inboxPlacementLabel,
    inboxRuleScopeLabel,
    isInboxRuleConflict,
    normalizeInboxRuleMutation,
    normalizeInboxRulesResponse,
    updateInboxRulePayload,
  } from '../../lib/inboxPlacementRules.js';
  import Icon from '../common/Icon.svelte';

  let {
    open = $bindable(false),
    accounts = [],
    initialAccountId = null,
    refreshToken = 0,
    onmutated = null,
    ondeleted = null,
    onconflict = null,
    onfocusfallback = null,
  } = $props();

  let dialog = $state(null);
  let returnFocus = null;
  let observedOpen = false;
  let observedRefreshToken = null;
  let requestGeneration = 0;
  let requestController = null;
  let mutationGeneration = 0;
  let loading = $state(false);
  let error = $state('');
  let conflict = $state(false);
  let status = $state('');
  let response = $state.raw(null);
  let accountFilter = $state('');
  let drafts = $state({});
  let busyRuleId = $state(null);
  let confirmingDeleteId = $state(null);

  function accountName(account) {
    return account?.short_label || account?.description || account?.email || `Account ${account?.id}`;
  }

  function initializeDrafts(items) {
    drafts = Object.fromEntries(items.map(rule => [rule.id, {
      placement: rule.placement,
      enabled: rule.enabled,
    }]));
  }

  function setDraft(ruleId, changes) {
    drafts = {
      ...drafts,
      [ruleId]: { ...drafts[ruleId], ...changes },
    };
    confirmingDeleteId = null;
  }

  function draftChanged(rule) {
    const draft = drafts[rule.id];
    return Boolean(draft && (
      draft.placement !== rule.placement || draft.enabled !== rule.enabled
    ));
  }

  function abortRequests() {
    requestGeneration += 1;
    mutationGeneration += 1;
    requestController?.abort();
    requestController = null;
    loading = false;
    busyRuleId = null;
  }

  async function closeManager() {
    if (busyRuleId) return;
    abortRequests();
    open = false;
    response = null;
    error = '';
    conflict = false;
    confirmingDeleteId = null;
    await tick();
    if (returnFocus?.isConnected) {
      returnFocus.focus({ preventScroll: true });
    } else {
      onfocusfallback?.();
    }
    returnFocus = null;
  }

  async function reloadLatestRules() {
    if (loading || busyRuleId) return;
    await onconflict?.();
    if (open) await loadRules();
  }

  async function loadRules() {
    if (!open) return;
    requestController?.abort();
    const generation = ++requestGeneration;
    const filterAtStart = accountFilter;
    const session = captureAuthenticatedSession();
    const controller = new AbortController();
    requestController = controller;
    loading = true;
    error = '';
    conflict = false;
    try {
      const raw = await api.listInboxPlacementRules(
        filterAtStart ? Number(filterAtStart) : null,
        { signal: controller.signal },
      );
      if (
        generation !== requestGeneration
        || controller.signal.aborted
        || !open
        || accountFilter !== filterAtStart
        || !isAuthenticatedSessionCurrent(session)
      ) return;
      response = normalizeInboxRulesResponse(raw);
      initializeDrafts(response.items);
      confirmingDeleteId = null;
    } catch (loadError) {
      if (
        generation !== requestGeneration
        || controller.signal.aborted
        || !open
        || !isAuthenticatedSessionCurrent(session)
      ) return;
      error = loadError?.message || 'Split Inbox rules could not be loaded.';
    } finally {
      if (generation === requestGeneration) {
        requestController = null;
        loading = false;
      }
    }
  }

  async function saveRule(rule) {
    const draft = drafts[rule.id];
    if (!draft || !draftChanged(rule) || busyRuleId) return;
    const generation = ++mutationGeneration;
    const session = captureAuthenticatedSession();
    busyRuleId = rule.id;
    error = '';
    conflict = false;
    status = '';
    try {
      const mutation = normalizeInboxRuleMutation(
        await api.updateInboxPlacementRule(
          rule.id,
          updateInboxRulePayload({ ...draft, revision: rule.revision }),
        ),
        rule,
      );
      if (
        generation !== mutationGeneration
        || !open
        || busyRuleId !== rule.id
        || !isAuthenticatedSessionCurrent(session)
      ) return;
      const accepted = await onmutated?.({ kind: 'update', mutation });
      if (accepted === false) return;
      status = `Rule updated for ${mutation.rule.account_email}. Split Inbox refreshed.`;
      await loadRules();
    } catch (saveError) {
      if (
        generation !== mutationGeneration
        || !open
        || !isAuthenticatedSessionCurrent(session)
      ) return;
      conflict = isInboxRuleConflict(saveError);
      error = conflict
        ? 'This rule changed in another session. Reload the latest rules before trying again.'
        : (saveError?.message || 'The rule could not be updated. Try again.');
    } finally {
      if (generation === mutationGeneration) busyRuleId = null;
    }
  }

  async function deleteRule(rule) {
    if (busyRuleId || confirmingDeleteId !== rule.id) return;
    const generation = ++mutationGeneration;
    const session = captureAuthenticatedSession();
    busyRuleId = rule.id;
    error = '';
    conflict = false;
    status = '';
    try {
      await api.deleteInboxPlacementRule(rule.id, rule.revision);
      if (
        generation !== mutationGeneration
        || !open
        || busyRuleId !== rule.id
        || !isAuthenticatedSessionCurrent(session)
      ) return;
      const accepted = await ondeleted?.({ kind: 'delete', rule });
      if (accepted === false) return;
      status = `Rule deleted for ${rule.account_email}. Split Inbox refreshed.`;
      await loadRules();
    } catch (deleteError) {
      if (
        generation !== mutationGeneration
        || !open
        || !isAuthenticatedSessionCurrent(session)
      ) return;
      conflict = isInboxRuleConflict(deleteError);
      error = conflict
        ? 'This rule changed in another session. Reload the latest rules before deleting it.'
        : (deleteError?.message || 'The rule could not be deleted. Try again.');
    } finally {
      if (generation === mutationGeneration) busyRuleId = null;
    }
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
      void closeManager();
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
    const nextRefreshToken = refreshToken;
    if (open && observedOpen && nextRefreshToken !== observedRefreshToken) {
      observedRefreshToken = nextRefreshToken;
      void loadRules();
      return;
    }
    if (open === observedOpen) return;
    observedOpen = open;
    observedRefreshToken = nextRefreshToken;
    if (!open) {
      abortRequests();
      return;
    }
    returnFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    accountFilter = initialAccountId ? String(initialAccountId) : '';
    status = '';
    void loadRules();
    void tick().then(() => dialog?.focus({ preventScroll: true }));
  });
</script>

{#if open}
  <div class="inbox-rules-layer fixed inset-0 z-[74] flex items-center justify-center p-4" role="presentation">
    <button type="button" class="absolute inset-0 bg-black/45" aria-label="Close Split Inbox rules" onclick={closeManager}></button>
    <div
      bind:this={dialog}
      class="inbox-rules-dialog relative flex max-h-[92dvh] w-full max-w-3xl flex-col overflow-hidden rounded-2xl border shadow-2xl"
      style="background: var(--bg-primary); border-color: var(--border-color)"
      role="dialog"
      tabindex="-1"
      aria-busy={Boolean(busyRuleId)}
      aria-modal="true"
      aria-labelledby="inbox-rule-manager-title"
      aria-describedby="inbox-rule-manager-description"
      onkeydown={handleKeydown}
    >
      <header class="flex items-start gap-3 border-b px-5 py-4" style="border-color: var(--border-color)">
        <div class="min-w-0 flex-1">
          <h2 id="inbox-rule-manager-title" class="text-base font-semibold" style="color: var(--text-primary)">Split Inbox rules</h2>
          <p id="inbox-rule-manager-description" class="mt-1 text-xs leading-relaxed" style="color: var(--text-secondary)">
            Review personal Focused and Other rules. They affect your local Inbox view only; Gmail is unchanged.
          </p>
        </div>
        <button type="button" class="inline-flex min-h-11 min-w-11 items-center justify-center rounded-lg disabled:opacity-50" disabled={Boolean(busyRuleId)} aria-label="Close Split Inbox rules" onclick={closeManager}>
          <Icon name="x" size={19} />
        </button>
      </header>

      <div class="border-b px-5 py-3" style="border-color: var(--border-color)">
        <label class="block text-xs font-semibold" style="color: var(--text-secondary)">
          Filter rules by account
          <select
            class="mt-1 min-h-11 w-full rounded-lg border px-3 text-sm sm:max-w-sm"
            style="background: var(--bg-primary); border-color: var(--border-color); color: var(--text-primary)"
            bind:value={accountFilter}
            disabled={loading || Boolean(busyRuleId)}
            onchange={loadRules}
          >
            <option value="">All connected accounts</option>
            {#each accounts as account (account.id)}
              <option value={String(account.id)}>{accountName(account)} · {account.email}</option>
            {/each}
          </select>
        </label>
      </div>

      <div class="flex-1 overflow-y-auto p-5">
        <p class="sr-only" aria-live="polite">{status}</p>
        {#if loading}
          <div class="flex min-h-52 flex-col items-center justify-center gap-3" role="status">
            <span class="h-6 w-6 animate-spin rounded-full border-2" style="border-color: var(--border-color); border-top-color: var(--color-accent-500)"></span>
            <span class="text-sm" style="color: var(--text-secondary)">Loading Split Inbox rules…</span>
          </div>
        {:else if error && !response}
          <div class="rounded-xl border p-4" style="border-color: var(--status-error); background: var(--status-error-bg)" role="alert">
            <p class="text-sm font-medium" style="color: var(--status-error)">{error}</p>
            <button type="button" class="mt-3 min-h-11 rounded-lg border px-4 text-sm font-semibold" style="border-color: var(--border-color)" onclick={conflict ? reloadLatestRules : loadRules}>{conflict ? 'Reload latest rules' : 'Try again'}</button>
          </div>
        {:else if response?.items.length === 0}
          <div class="flex min-h-52 flex-col items-center justify-center rounded-xl border p-6 text-center" style="border-color: var(--border-color); background: var(--bg-secondary)">
            <Icon name="inbox" size={28} />
            <h3 class="mt-3 text-sm font-semibold" style="color: var(--text-primary)">No personal rules for this account filter</h3>
            <p class="mt-1 max-w-md text-xs" style="color: var(--text-secondary)">Use Teach on an Inbox row to create one from server-approved choices.</p>
          </div>
        {:else if response}
          <div class="space-y-3">
            <div class="flex items-center justify-between gap-3">
              <p class="text-xs" style="color: var(--text-tertiary)">{response.items.length} {response.items.length === 1 ? 'rule' : 'rules'}</p>
              {#if response.max_rules_per_account}
                <p class="text-[11px]" style="color: var(--text-tertiary)">Up to {response.max_rules_per_account} per account</p>
              {/if}
            </div>
            {#each response.items as rule (rule.id)}
              <article class="rounded-xl border p-4" style="border-color: var(--border-color); background: var(--bg-secondary)">
                <div class="flex flex-col gap-3 sm:flex-row sm:items-start">
                  <div class="min-w-0 flex-1">
                    <p class="break-all text-xs font-semibold" style="color: var(--text-tertiary)">{rule.account_email}</p>
                    <h3 class="mt-1 break-words text-sm font-semibold" style="color: var(--text-primary)">{rule.display_value}</h3>
                    <p class="mt-1 text-xs" style="color: var(--text-secondary)">{inboxRuleScopeLabel(rule.scope)} · exact account only</p>
                  </div>
                  <label class="flex min-h-11 items-center gap-2 rounded-lg border px-3 text-xs font-semibold" style="border-color: var(--border-color)">
                    <input type="checkbox" checked={drafts[rule.id]?.enabled} disabled={Boolean(busyRuleId) || conflict} onchange={event => setDraft(rule.id, { enabled: event.currentTarget.checked })} />
                    Rule enabled
                  </label>
                </div>

                <label class="mt-3 block text-xs font-semibold" style="color: var(--text-secondary)">
                  Place future matches in
                  <select class="mt-1 min-h-11 w-full rounded-lg border px-3 text-sm sm:max-w-xs" style="background: var(--bg-primary); border-color: var(--border-color); color: var(--text-primary)" value={drafts[rule.id]?.placement} disabled={Boolean(busyRuleId) || conflict} onchange={event => setDraft(rule.id, { placement: event.currentTarget.value })}>
                    <option value="focused">{inboxPlacementLabel('focused')}</option>
                    <option value="other">{inboxPlacementLabel('other')}</option>
                  </select>
                </label>

                {#if error && busyRuleId === rule.id}
                  <p class="mt-3 text-xs font-medium" style="color: var(--status-error)" role="alert">{error}</p>
                {/if}

                <div class="mt-3 flex flex-wrap items-center justify-end gap-2">
                  {#if confirmingDeleteId === rule.id}
                    <span class="mr-auto text-xs font-medium" style="color: var(--status-error)">Delete this exact-account rule?</span>
                    <button type="button" class="min-h-11 rounded-lg border px-3 text-xs font-semibold" style="border-color: var(--border-color)" disabled={Boolean(busyRuleId)} onclick={() => { confirmingDeleteId = null; }}>Cancel delete</button>
                    <button type="button" class="min-h-11 rounded-lg px-3 text-xs font-semibold text-white disabled:opacity-50" style="background: var(--status-error)" disabled={Boolean(busyRuleId) || conflict} onclick={() => deleteRule(rule)}>{busyRuleId === rule.id ? 'Deleting…' : 'Delete rule'}</button>
                  {:else}
                    <button type="button" class="mr-auto min-h-11 rounded-lg px-3 text-xs font-semibold disabled:opacity-50" style="color: var(--status-error)" disabled={Boolean(busyRuleId) || conflict} onclick={() => { confirmingDeleteId = rule.id; }}><Icon name="trash-2" size={14} /> Delete</button>
                    <button type="button" class="min-h-11 rounded-lg bg-accent-600 px-4 text-xs font-semibold text-white disabled:opacity-50" disabled={!draftChanged(rule) || Boolean(busyRuleId) || conflict} onclick={() => saveRule(rule)}>{busyRuleId === rule.id ? 'Refreshing…' : 'Save changes'}</button>
                  {/if}
                </div>
              </article>
            {/each}
          </div>

          {#if error}
            <div class="mt-4 rounded-lg border p-3" style="border-color: var(--status-error); background: var(--status-error-bg)" role="alert">
              <p class="text-xs font-medium" style="color: var(--status-error)">{error}</p>
              {#if conflict}<button type="button" class="mt-2 min-h-11 rounded-lg border px-3 text-xs font-semibold" style="border-color: var(--border-color)" onclick={reloadLatestRules}>Reload latest rules</button>{/if}
            </div>
          {/if}
        {/if}
      </div>

      <footer class="flex justify-end border-t px-5 py-4" style="border-color: var(--border-color)">
        <button type="button" class="min-h-11 rounded-lg border px-4 text-sm font-semibold disabled:opacity-50" style="border-color: var(--border-color); color: var(--text-primary)" disabled={Boolean(busyRuleId)} onclick={closeManager}>Done</button>
      </footer>
    </div>
  </div>
{/if}

<style>
  @media (max-width: 639px) {
    .inbox-rules-layer {
      align-items: flex-end;
      padding: 0;
    }
    .inbox-rules-dialog {
      max-height: min(92dvh, 780px);
      border-radius: 1.25rem 1.25rem 0 0;
      border-bottom: 0;
    }
  }
</style>
