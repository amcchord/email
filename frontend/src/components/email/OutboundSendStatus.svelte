<script>
  import { onDestroy, onMount } from 'svelte';
  import { api } from '../../lib/api.js';
  import {
    authenticatedSessionGeneration,
    captureAuthenticatedSession,
    currentPage,
    isAuthenticatedSessionCurrent,
    showToast,
  } from '../../lib/stores.js';
  import { outboundSendOperations, outboundSends } from '../../lib/outboundSend.js';
  import { createIndexedDbDraftStorage } from '../../lib/draftStorage.js';
  import { composeDraftHasContent } from '../../lib/composeDraft.js';
  import {
    forgetRetainedOutboundDraft,
    loadRetainedOutboundDraft,
    openPendingOutboundDraft,
    pendingOutboundDraftRecoveries,
    resetOutboundDraftRecoveries,
    restoreOutboundComposeDraft,
  } from '../../lib/outboundDraftRecovery.js';
  import Icon from '../common/Icon.svelte';

  let mounted = false;
  let intervalId = null;
  let unsubscribeGeneration = null;
  let checking = $state(false);
  let dismissedFailures = $state(new Set());
  let durableStorage = null;
  let recoveredRetainedDraftIds = new Set();

  let reconciling = $derived(
    $outboundSendOperations.filter(operation => operation.state === 'reconciling'),
  );
  let failed = $derived(
    $outboundSendOperations.filter(operation => (
      operation.state === 'failed' && !dismissedFailures.has(failureIdentity(operation))
    )),
  );
  let composeOpen = $derived($currentPage === 'compose');

  function failureIdentity(operation) {
    return String(operation?.send_id || operation?.idempotency_key || 'unknown');
  }

  function getDurableStorage() {
    if (durableStorage) return durableStorage;
    try {
      durableStorage = createIndexedDbDraftStorage();
    } catch {
      durableStorage = null;
    }
    return durableStorage;
  }

  async function loadOperations() {
    if (!mounted) return;
    try {
      const operations = await outboundSends.loadRecent(20);
      for (const operation of operations) {
        if (!operation.client_draft_id) continue;
        if (operation.state === 'sent') {
          void forgetRetainedOutboundDraft(
            getDurableStorage(),
            captureAuthenticatedSession().userId,
            operation.client_draft_id,
          );
          continue;
        }
        if (operation.state === 'cancelled' || operation.state === 'failed') {
          void recoverRetainedTerminalDraft(operation, operation.state);
          continue;
        }
        outboundSends.attachCallbacks(operation, {
          onSent: terminalOperation => forgetAcceptedDraft(terminalOperation),
          onRestore: (terminalOperation, reason) => (
            recoverAcceptedDraft(terminalOperation, reason)
          ),
        });
      }
    } catch {
      // The main mail experience does not depend on this monitor. Its next
      // poll or an explicit status check will retry without recurring toasts.
    }
  }

  async function forgetAcceptedDraft(operation) {
    const session = captureAuthenticatedSession();
    await forgetRetainedOutboundDraft(
      getDurableStorage(),
      session.userId,
      operation.client_draft_id,
    );
  }

  async function recoverRetainedTerminalDraft(operation, reason) {
    if (recoveredRetainedDraftIds.has(operation.client_draft_id)) return true;
    const session = captureAuthenticatedSession();
    const localDraft = await loadRetainedOutboundDraft(
      getDurableStorage(),
      session.userId,
      operation.client_draft_id,
    );
    if (!localDraft || !mounted || !isAuthenticatedSessionCurrent(session)) return false;
    const restored = restoreOutboundComposeDraft(localDraft, operation, reason);
    if (restored) recoveredRetainedDraftIds.add(operation.client_draft_id);
    return restored;
  }

  async function recoverAcceptedDraft(operation, reason) {
    const session = captureAuthenticatedSession();
    try {
      const localDraft = await loadRetainedOutboundDraft(
        getDurableStorage(),
        session.userId,
        operation.client_draft_id,
      );
      const draft = localDraft || await api.getComposeDraft(operation.client_draft_id);
      if (!mounted || !isAuthenticatedSessionCurrent(session)) return false;
      if (!composeDraftHasContent(draft)) {
        throw new Error('Send was stopped, but its draft content is no longer available');
      }
      const restored = restoreOutboundComposeDraft(draft, operation, reason);
      if (restored && localDraft) recoveredRetainedDraftIds.add(operation.client_draft_id);
      return restored;
    } catch (error) {
      if (mounted && isAuthenticatedSessionCurrent(session)) {
        showToast(
          error?.message || 'Send was stopped, but the draft could not be reopened automatically',
          'error',
          6000,
        );
      }
      return false;
    }
  }

  async function checkReconciling() {
    if (!mounted || checking) return;
    const session = captureAuthenticatedSession();
    checking = true;
    try {
      await Promise.allSettled(
        reconciling.map(operation => outboundSends.refreshOperation(operation)),
      );
      await loadOperations();
    } finally {
      if (mounted && isAuthenticatedSessionCurrent(session)) checking = false;
    }
  }

  function dismissFailures() {
    dismissedFailures = new Set([
      ...dismissedFailures,
      ...failed.map(failureIdentity),
    ]);
  }

  onMount(() => {
    mounted = true;
    unsubscribeGeneration = authenticatedSessionGeneration.subscribe(() => {
      if (!mounted) return;
      checking = false;
      dismissedFailures = new Set();
      recoveredRetainedDraftIds = new Set();
      resetOutboundDraftRecoveries();
      outboundSends.resetForCurrentSession();
      void loadOperations();
    });
    intervalId = window.setInterval(loadOperations, 15_000);
  });

  onDestroy(() => {
    mounted = false;
    unsubscribeGeneration?.();
    unsubscribeGeneration = null;
    if (intervalId !== null) window.clearInterval(intervalId);
    void durableStorage?.close?.();
    durableStorage = null;
  });
</script>

{#if reconciling.length > 0}
  <section
    class="flex flex-wrap items-center gap-3 px-4 py-2 border-b shrink-0 bg-amber-50/90 dark:bg-amber-950/30"
    style="border-color: var(--border-color); color: var(--text-primary)"
    role="status"
    aria-live="polite"
  >
    <span class="shrink-0 text-amber-600 dark:text-amber-400" aria-hidden="true">
      <Icon name="refresh-cw" size={17} />
    </span>
    <div class="min-w-48 flex-1">
      <p class="text-xs font-semibold">
        {reconciling.length === 1
          ? 'Confirming 1 email send'
          : `Confirming ${reconciling.length} email sends`}
      </p>
      <p class="text-xs mt-0.5" style="color: var(--text-secondary)">
        The server may already have this message. Do not resend while its status is being confirmed.
      </p>
    </div>
    <button
      type="button"
      class="min-h-11 px-3 rounded-lg border text-xs font-semibold disabled:opacity-60"
      style="border-color: var(--border-color); background: var(--bg-primary); color: var(--color-accent-600)"
      disabled={checking}
      aria-busy={checking}
      onclick={checkReconciling}
    >
      {checking ? 'Checking…' : 'Check now'}
    </button>
  </section>
{/if}

{#if $pendingOutboundDraftRecoveries.length > 0}
  <section
    class="flex flex-wrap items-center gap-3 px-4 py-2 border-b shrink-0 bg-blue-50/90 dark:bg-blue-950/30"
    style="border-color: var(--border-color); color: var(--text-primary)"
    role="status"
    aria-live="polite"
  >
    <span class="shrink-0 text-blue-600 dark:text-blue-400" aria-hidden="true">
      <Icon name="file-text" size={17} />
    </span>
    <div class="min-w-48 flex-1">
      <p class="text-xs font-semibold">
        {$pendingOutboundDraftRecoveries.length === 1
          ? 'A recovered draft is ready'
          : `${$pendingOutboundDraftRecoveries.length} recovered drafts are ready`}
      </p>
      <p class="text-xs mt-0.5" style="color: var(--text-secondary)">
        {composeOpen
          ? 'Finish or leave your current draft before reviewing it.'
          : 'Review the message before choosing Send again.'}
      </p>
    </div>
    <button
      type="button"
      class="min-h-11 px-3 rounded-lg border text-xs font-semibold disabled:opacity-60"
      style="border-color: var(--border-color); background: var(--bg-primary); color: var(--color-accent-600)"
      disabled={composeOpen}
      onclick={() => openPendingOutboundDraft($pendingOutboundDraftRecoveries[0].id)}
    >
      Review draft
    </button>
  </section>
{/if}

{#if failed.length > 0}
  <section
    class="flex flex-wrap items-center gap-3 px-4 py-2 border-b shrink-0 bg-red-50/80 dark:bg-red-950/30"
    style="border-color: var(--border-color); color: var(--text-primary)"
    role="alert"
    aria-live="assertive"
  >
    <span class="shrink-0 text-red-600 dark:text-red-400" aria-hidden="true">
      <Icon name="alert-triangle" size={17} />
    </span>
    <div class="min-w-48 flex-1">
      <p class="text-xs font-semibold">
        {failed.length === 1 ? '1 email was not sent' : `${failed.length} emails were not sent`}
      </p>
      <p class="text-xs mt-0.5" style="color: var(--text-secondary)">
        The draft was restored when possible. Review it before choosing Send again.
      </p>
    </div>
    <button
      type="button"
      class="min-h-11 px-3 rounded-lg border text-xs font-semibold"
      style="border-color: var(--border-color); background: var(--bg-primary); color: var(--text-secondary)"
      onclick={dismissFailures}
    >
      Dismiss
    </button>
  </section>
{/if}
