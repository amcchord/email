<script>
  import Icon from '../common/Icon.svelte';

  let {
    selectedCount = 0,
    busy = false,
    disabled = false,
    showSnooze = true,
    showLabels = true,
    showMove = true,
    showSwipeSettings = true,
    spamMode = 'hidden',
    trashMode = 'hidden',
    onaction = null,
    onarchive = null,
    onsnooze = null,
    onmarkread = null,
    onmarkunread = null,
    ontogglestar = null,
    onlabel = null,
    onmove = null,
    onclear = null,
    onsettings = null,
  } = $props();

  let count = $derived(Math.max(0, Number(selectedCount) || 0));
  let actionsDisabled = $derived(busy || disabled || count === 0);

  const primaryActions = Object.freeze([
    { id: 'archive', label: 'Archive', icon: 'archive' },
    { id: 'snooze', label: 'Snooze', icon: 'clock' },
    { id: 'mark_read', label: 'Mark read', icon: 'mail' },
    { id: 'mark_unread', label: 'Mark unread', icon: 'mail' },
    { id: 'toggle_star', label: 'Toggle star', icon: 'star' },
  ]);

  function dedicatedCallback(action) {
    if (action === 'archive') return onarchive;
    if (action === 'snooze') return onsnooze;
    if (action === 'mark_read') return onmarkread;
    if (action === 'mark_unread') return onmarkunread;
    if (action === 'toggle_star') return ontogglestar;
    if (action === 'label') return onlabel;
    if (action === 'move') return onmove;
    return null;
  }

  function invoke(action) {
    if (actionsDisabled) return;
    const detail = Object.freeze({ action, selectedCount: count });
    const callback = dedicatedCallback(action);
    if (typeof callback === 'function') callback(detail);
    else onaction?.(detail);
  }
</script>

{#if count > 0}
  <div
    class="inbox-bulk-bar z-40 mx-2 flex min-h-14 items-center gap-2 rounded-2xl border px-2 py-1.5 shadow-lg sm:mx-4 sm:px-3"
    data-triage-bulk-bar
    style="background: var(--bg-elevated); border-color: var(--border-color); box-shadow: var(--shadow-lg)"
    role="toolbar"
    aria-label={`Bulk actions for ${count} selected ${count === 1 ? 'conversation' : 'conversations'}`}
    aria-busy={busy}
  >
    <div class="flex min-w-fit items-center gap-1 border-r pr-2 sm:gap-2 sm:pr-3" style="border-color: var(--border-color)">
      <button
        type="button"
        class="inline-flex min-h-11 min-w-11 items-center justify-center rounded-xl disabled:opacity-50"
        aria-label="Clear selection"
        title="Clear selection"
        disabled={busy}
        onclick={() => onclear?.()}
      >
        <Icon name="x" size={19} />
      </button>
      <span class="min-w-7 text-center text-sm font-semibold tabular-nums" style="color: var(--text-primary)" aria-live="polite">{count}</span>
      <span class="hidden text-xs sm:inline" style="color: var(--text-secondary)">selected</span>
    </div>

    <div class="bulk-actions-scroll flex min-w-0 flex-1 items-center gap-1 overflow-x-auto" aria-label="Message actions">
      {#each primaryActions.filter(action => showSnooze || action.id !== 'snooze') as action (action.id)}
        <button
          type="button"
          class="inline-flex min-h-11 min-w-11 shrink-0 items-center justify-center gap-2 rounded-xl px-2.5 text-sm font-medium disabled:opacity-50 sm:px-3"
          style="color: var(--text-secondary)"
          disabled={actionsDisabled}
          aria-label={`${action.label} ${count} selected ${count === 1 ? 'conversation' : 'conversations'}`}
          title={action.label}
          onclick={() => invoke(action.id)}
        >
          <Icon name={action.icon} size={18} />
          <span class="hidden lg:inline">{action.label}</span>
        </button>
      {/each}

      {#if showLabels}
        <button
          type="button"
          class="inline-flex min-h-11 min-w-11 shrink-0 items-center justify-center gap-2 rounded-xl px-2.5 text-sm font-medium disabled:opacity-50 sm:px-3"
          style="color: var(--text-secondary)"
          disabled={actionsDisabled}
          aria-label={`Label ${count} selected ${count === 1 ? 'conversation' : 'conversations'}`}
          title="Label"
          onclick={() => invoke('label')}
        >
          <Icon name="tag" size={18} />
          <span class="hidden lg:inline">Label</span>
        </button>
      {/if}

      {#if showMove}
        <button
          type="button"
          class="inline-flex min-h-11 min-w-11 shrink-0 items-center justify-center gap-2 rounded-xl px-2.5 text-sm font-medium disabled:opacity-50 sm:px-3"
          style="color: var(--text-secondary)"
          disabled={actionsDisabled}
          aria-label={`Move ${count} selected ${count === 1 ? 'conversation' : 'conversations'}`}
          title="Move"
          onclick={() => invoke('move')}
        >
          <Icon name="folder" size={18} />
          <span class="hidden lg:inline">Move</span>
        </button>
      {/if}

      {#if spamMode !== 'hidden'}
        <button
          type="button"
          class="inline-flex min-h-11 min-w-11 shrink-0 items-center justify-center gap-2 rounded-xl px-2.5 text-sm font-medium disabled:opacity-50 sm:px-3"
          style="color: {spamMode === 'spam' ? 'var(--status-error)' : 'var(--text-secondary)'}"
          disabled={actionsDisabled || spamMode === 'mixed'}
          aria-label={spamMode === 'unspam' ? `Mark ${count} selected as not spam` : (spamMode === 'spam' ? `Report ${count} selected as spam` : 'Selected conversations have mixed spam states')}
          title={spamMode === 'unspam' ? 'Not spam' : (spamMode === 'spam' ? 'Spam' : 'Spam state varies')}
          onclick={() => invoke(spamMode)}
        >
          <Icon name="shield" size={18} />
          <span class="hidden lg:inline">{spamMode === 'unspam' ? 'Not spam' : (spamMode === 'spam' ? 'Spam' : 'Spam varies')}</span>
        </button>
      {/if}

      {#if trashMode !== 'hidden'}
        <button
          type="button"
          class="inline-flex min-h-11 min-w-11 shrink-0 items-center justify-center gap-2 rounded-xl px-2.5 text-sm font-medium disabled:opacity-50 sm:px-3"
          style="color: {trashMode === 'trash' ? 'var(--status-error)' : 'var(--text-secondary)'}"
          disabled={actionsDisabled || trashMode === 'mixed'}
          aria-label={trashMode === 'untrash' ? `Restore ${count} selected from trash` : (trashMode === 'trash' ? `Trash ${count} selected` : 'Selected conversations have mixed trash states')}
          title={trashMode === 'untrash' ? 'Restore' : (trashMode === 'trash' ? 'Trash' : 'Trash state varies')}
          onclick={() => invoke(trashMode)}
        >
          <Icon name={trashMode === 'untrash' ? 'rotate-ccw' : 'trash'} size={18} />
          <span class="hidden lg:inline">{trashMode === 'untrash' ? 'Restore' : (trashMode === 'trash' ? 'Trash' : 'Trash varies')}</span>
        </button>
      {/if}
    </div>

    {#if showSwipeSettings}
      <button
        type="button"
        class="inline-flex min-h-11 min-w-11 shrink-0 items-center justify-center rounded-xl disabled:opacity-50"
        style="color: var(--text-secondary)"
        disabled={busy}
        aria-label="Customize swipe actions"
        title="Customize swipe actions"
        onclick={() => onsettings?.()}
      >
        <Icon name="sliders" size={18} />
      </button>
    {/if}
  </div>
{/if}

<style>
  .inbox-bulk-bar {
    position: sticky;
    bottom: max(0.75rem, env(safe-area-inset-bottom));
  }

  .bulk-actions-scroll {
    scrollbar-width: none;
    overscroll-behavior-x: contain;
  }

  .bulk-actions-scroll::-webkit-scrollbar {
    display: none;
  }

  @media (max-width: 639px) {
    .inbox-bulk-bar {
      margin-bottom: max(0.25rem, env(safe-area-inset-bottom));
      border-radius: 1rem;
    }
  }
</style>
