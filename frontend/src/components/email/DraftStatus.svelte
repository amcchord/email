<script>
  import { draftStatusView } from '../../lib/draftSession.js';

  let {
    state = { status: 'pristine' },
    onretry = null,
    onundo = null,
    onreview = null,
    compact = false,
  } = $props();

  let view = $derived(draftStatusView(state));
</script>

<div
  class="draft-status"
  class:compact
  class:error={view.tone === 'error'}
  class:warning={view.tone === 'warning'}
  class:success={view.tone === 'success'}
  role={view.role}
  aria-live={view.live}
  aria-atomic="true"
  data-draft-state={state.status || 'pristine'}
>
  <span class="draft-status-message">{view.message}</span>
  {#if view.retry && onretry}
    <button type="button" onclick={onretry}>Retry</button>
  {/if}
  {#if view.undo && onundo}
    <button type="button" onclick={onundo}>Undo</button>
  {/if}
  {#if view.review && onreview}
    <button type="button" onclick={onreview}>Review versions</button>
  {/if}
</div>

<style>
  .draft-status {
    display: inline-flex;
    min-width: 0;
    align-items: center;
    gap: 0.5rem;
    color: var(--text-secondary);
    font-size: 0.75rem;
    line-height: 1.25rem;
  }

  .draft-status.compact {
    font-size: 0.6875rem;
  }

  .draft-status.error {
    color: var(--status-error);
  }

  .draft-status.warning {
    color: var(--status-warning, #b45309);
  }

  .draft-status.success {
    color: var(--status-success, #047857);
  }

  .draft-status-message {
    min-width: 0;
    overflow-wrap: anywhere;
  }

  button {
    min-height: 2.75rem;
    flex: 0 0 auto;
    border: 1px solid currentColor;
    border-radius: 0.5rem;
    padding: 0.5rem 0.75rem;
    font-weight: 650;
  }

  button:focus-visible {
    outline: 2px solid var(--color-accent-500);
    outline-offset: 2px;
  }

  @media (max-width: 767px) {
    .draft-status {
      width: 100%;
      flex-wrap: wrap;
    }

    .draft-status-message {
      flex: 1 1 auto;
    }
  }
</style>
