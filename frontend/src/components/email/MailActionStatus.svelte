<script>
  import { onDestroy, onMount } from 'svelte';
  import { api } from '../../lib/api.js';
  import { showToast } from '../../lib/stores.js';
  import { lastEvent } from '../../lib/realtime.js';
  import Icon from '../common/Icon.svelte';

  let operations = $state([]);
  let retrying = $state(new Set());
  let mounted = false;
  let intervalId = null;
  let observedEvent = null;

  let failedOperations = $derived(operations.filter(operation =>
    operation.state === 'failed' || operation.items?.some(item => item.state === 'failed')
  ));
  let failedCount = $derived(failedOperations.reduce(
    (count, operation) => count + operation.items.filter(item => item.state === 'failed').length,
    0,
  ));

  const actionLabels = {
    archive: 'archive',
    trash: 'move to trash',
    untrash: 'restore',
    spam: 'mark as spam',
    unspam: 'mark as not spam',
    mark_read: 'mark as read',
    mark_unread: 'mark as unread',
    star: 'star',
    unstar: 'unstar',
  };

  async function loadOperations() {
    try {
      const result = await api.listRecentMailActions(20);
      if (mounted) operations = Array.isArray(result) ? result : (result.operations || []);
    } catch {
      // This banner is an enhancement over the normal inbox path. A polling
      // failure must not interrupt reading mail or generate recurring toasts.
    }
  }

  async function retry(operation) {
    if (retrying.has(operation.request_id)) return;
    retrying = new Set(retrying).add(operation.request_id);
    try {
      await api.retryMailAction(operation.request_id);
      operations = operations.filter(item => item.request_id !== operation.request_id);
      showToast('Email action queued to retry', 'success');
    } catch (err) {
      showToast(err.message || 'Could not retry this email action', 'error');
    } finally {
      const next = new Set(retrying);
      next.delete(operation.request_id);
      retrying = next;
    }
  }

  $effect(() => {
    const event = $lastEvent;
    if (!mounted || !event || event === observedEvent) return;
    observedEvent = event;
    void loadOperations();
  });

  onMount(() => {
    mounted = true;
    void loadOperations();
    intervalId = window.setInterval(loadOperations, 15_000);
  });

  onDestroy(() => {
    mounted = false;
    if (intervalId !== null) window.clearInterval(intervalId);
  });
</script>

{#if failedOperations.length > 0}
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
        {failedCount === 1 ? '1 email action needs attention' : `${failedCount} email actions need attention`}
      </p>
      <p class="text-xs mt-0.5" style="color: var(--text-secondary)">
        The intended inbox state is saved. Retry the Gmail update when you’re ready.
      </p>
    </div>
    <div class="flex flex-wrap gap-2">
      {#each failedOperations.slice(0, 3) as operation (operation.request_id)}
        <button
          type="button"
          class="min-h-11 px-3 rounded-lg border text-xs font-semibold disabled:opacity-60"
          style="border-color: var(--border-color); background: var(--bg-primary); color: var(--color-accent-600)"
          disabled={retrying.has(operation.request_id)}
          aria-busy={retrying.has(operation.request_id)}
          onclick={() => retry(operation)}
        >
          {retrying.has(operation.request_id)
            ? 'Retrying…'
            : `Retry ${actionLabels[operation.action] || 'update'}`}
        </button>
      {/each}
    </div>
  </section>
{/if}
