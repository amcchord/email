<script>
  let { toast, onDismiss = () => {} } = $props();
  let actionRunning = $state(false);
  let actionError = $state('');

  const colors = {
    success: 'bg-emerald-700 text-white',
    error: 'bg-red-700 text-white',
    info: 'bg-surface-800 text-white dark:bg-surface-200 dark:text-surface-900',
    warning: 'bg-amber-700 text-white',
  };

  async function runAction() {
    if (!toast.onAction || actionRunning) return;
    actionRunning = true;
    actionError = '';
    try {
      await toast.onAction();
      onDismiss();
    } catch (error) {
      actionError = error?.message || 'That action could not be completed. Try again.';
    } finally {
      actionRunning = false;
    }
  }
</script>

<div
  class="toast animate-in {colors[toast.type] || colors.info}"
  role={toast.type === 'error' ? 'alert' : 'status'}
  aria-live={toast.type === 'error' ? 'assertive' : 'polite'}
  aria-atomic="true"
>
  <span class="toast-copy">
    <span class="message">{toast.message}</span>
    {#if actionError}
      <span class="action-error" role="alert">{actionError}</span>
    {/if}
  </span>
  {#if toast.actionLabel && toast.onAction}
    <button
      class="action-button"
      type="button"
      disabled={actionRunning}
      aria-busy={actionRunning}
      onclick={runAction}
    >
      {actionRunning ? 'Working…' : toast.actionLabel}
    </button>
  {/if}
  <button
    class="dismiss-button"
    type="button"
    aria-label={toast.dismissLabel}
    onclick={onDismiss}
  >
    <span aria-hidden="true">×</span>
  </button>
</div>

<style>
  .toast {
    pointer-events: auto;
    display: flex;
    min-height: 3.25rem;
    align-items: center;
    gap: 0.75rem;
    border-radius: 0.75rem;
    padding: 0.625rem 0.625rem 0.625rem 1rem;
    box-shadow: 0 14px 35px rgb(0 0 0 / 0.24);
    font-size: 0.875rem;
    font-weight: 600;
  }

  .toast-copy {
    min-width: 0;
    flex: 1;
    display: grid;
    gap: 0.2rem;
  }

  .message {
    display: block;
  }

  .action-error {
    display: block;
    font-size: 0.75rem;
    font-weight: 500;
    line-height: 1.25;
  }

  .action-button,
  .dismiss-button {
    min-width: 2.75rem;
    min-height: 2.75rem;
    border-radius: 0.5rem;
  }

  .action-button {
    padding: 0 0.75rem;
    background: rgb(255 255 255 / 0.18);
    text-decoration: underline;
    text-underline-offset: 2px;
  }

  .action-button:hover,
  .dismiss-button:hover {
    background: rgb(255 255 255 / 0.25);
  }

  .action-button:disabled {
    cursor: wait;
    opacity: 0.75;
  }

  .dismiss-button {
    display: grid;
    place-items: center;
    font-size: 1.5rem;
    font-weight: 400;
  }

  .animate-in {
    animation: slideUp 180ms cubic-bezier(0.4, 0, 0.2, 1);
  }

  @keyframes slideUp {
    from { opacity: 0; transform: translateY(10px); }
    to { opacity: 1; transform: translateY(0); }
  }

  @media (max-width: 767px) {
    .toast {
      width: 100%;
    }
  }
</style>
