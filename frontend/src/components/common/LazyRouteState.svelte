<script>
  let {
    expectedKey,
    label,
    routeState,
    componentProps = {},
    inShell = false,
    canGoHome = false,
    onRetry,
    onGoHome,
  } = $props();

  let status = $derived(routeState?.key === expectedKey ? routeState.status : 'loading');
  let CurrentComponent = $derived(status === 'ready' ? routeState.component : null);

  function reloadApp() {
    window.location.reload();
  }

  function focusRecoveryIfLost(node) {
    const frame = requestAnimationFrame(() => {
      const activeElement = document.activeElement;
      if (!activeElement || activeElement === document.body || !activeElement.isConnected) {
        node.querySelector('.primary-action')?.focus({ preventScroll: true });
      }
    });
    return { destroy: () => cancelAnimationFrame(frame) };
  }
</script>

{#snippet errorPanel(primaryAction, primaryLabel, copy, showReload = true)}
  <section
    class:in-shell={inShell}
    class:standalone={!inShell}
    class="route-state route-error"
    data-route-state="error"
    data-route-key={expectedKey}
    role="alert"
    aria-live="assertive"
    use:focusRecoveryIfLost
  >
    <div class="route-error-card">
      <div class="route-error-icon" aria-hidden="true">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
          <path d="M12 8v4m0 4h.01M10.3 3.7 2.6 17a2 2 0 0 0 1.7 3h15.4a2 2 0 0 0 1.7-3L13.7 3.7a2 2 0 0 0-3.4 0Z" />
        </svg>
      </div>
      <p class="route-eyebrow">{label}</p>
      <h1>{label} couldn’t load</h1>
      <p class="route-error-copy">{copy}</p>
      <div class="route-error-actions">
        <button class="primary-action" type="button" onclick={primaryAction}>{primaryLabel}</button>
        {#if showReload}
          <button class="secondary-action" type="button" onclick={reloadApp}>Reload app</button>
        {/if}
        {#if canGoHome}
          <button class="text-action" type="button" onclick={onGoHome}>Go to Flow</button>
        {/if}
      </div>
    </div>
  </section>
{/snippet}

{#if CurrentComponent}
  <span class="route-ready-announcement" role="status" aria-live="polite" aria-atomic="true">
    {label} loaded
  </span>
  {#key expectedKey}
    <svelte:boundary>
      <CurrentComponent {...componentProps} />
      {#snippet failed(_error, reset)}
        {@render errorPanel(
          reset,
          'Try again',
          'This screen stopped unexpectedly. Try it again, or reload the app if the problem continues.',
        )}
      {/snippet}
    </svelte:boundary>
  {/key}
{:else if status === 'error'}
  {@render errorPanel(
    onRetry,
    'Reload and retry',
    'We couldn’t download this screen. Check your connection, then reload to request a fresh copy. Your current route will be preserved.',
    false,
  )}
{:else}
  <section
    class:in-shell={inShell}
    class:standalone={!inShell}
    class="route-state route-loading"
    data-route-state="loading"
    data-route-key={expectedKey}
    aria-busy="true"
  >
    <div class="route-loading-content">
      <div class="loading-announcement" role="status" aria-live="polite" aria-atomic="true">
        <span class="route-spinner" aria-hidden="true"></span>
        <span>Loading {label}…</span>
      </div>
      <div class="route-skeleton" aria-hidden="true">
        <span class="skeleton-line skeleton-title"></span>
        <span class="skeleton-line skeleton-subtitle"></span>
        <div class="skeleton-grid">
          <span></span>
          <span></span>
          <span></span>
        </div>
      </div>
    </div>
  </section>
{/if}

<style>
  .route-ready-announcement {
    position: absolute;
    width: 1px;
    height: 1px;
    padding: 0;
    margin: -1px;
    overflow: hidden;
    clip: rect(0, 0, 0, 0);
    white-space: nowrap;
    border: 0;
  }

  .route-state {
    display: grid;
    width: 100%;
    min-width: 0;
    place-items: center;
    overflow: auto;
    background:
      radial-gradient(circle at 50% 15%, color-mix(in srgb, var(--color-accent-500) 8%, transparent), transparent 34rem),
      var(--bg-primary);
    color: var(--text-primary);
  }

  .in-shell {
    height: 100%;
    min-height: 18rem;
  }

  .standalone {
    min-height: 100vh;
  }

  .route-loading-content {
    width: min(42rem, calc(100% - 2rem));
    opacity: 0;
    animation: reveal-loading 1ms linear 140ms forwards;
  }

  .loading-announcement {
    display: flex;
    min-height: 2.75rem;
    align-items: center;
    justify-content: center;
    gap: 0.625rem;
    color: var(--text-secondary);
    font-size: 0.875rem;
    font-weight: 600;
  }

  .route-spinner {
    width: 1rem;
    height: 1rem;
    border: 2px solid var(--border-color);
    border-top-color: var(--color-accent-500);
    border-radius: 999px;
    animation: spin 700ms linear infinite;
  }

  .route-skeleton {
    margin-top: 1.25rem;
    padding: 1.5rem;
    border: 1px solid var(--border-color);
    border-radius: 1rem;
    background: color-mix(in srgb, var(--bg-secondary) 92%, transparent);
    box-shadow: 0 14px 36px rgb(15 23 42 / 0.06);
  }

  .skeleton-line,
  .skeleton-grid span {
    display: block;
    border-radius: 999px;
    background: linear-gradient(90deg, var(--bg-tertiary), color-mix(in srgb, var(--bg-tertiary) 55%, var(--bg-secondary)), var(--bg-tertiary));
    background-size: 220% 100%;
    animation: shimmer 1.4s ease-in-out infinite;
  }

  .skeleton-title {
    width: 34%;
    height: 0.875rem;
  }

  .skeleton-subtitle {
    width: 58%;
    height: 0.625rem;
    margin-top: 0.75rem;
  }

  .skeleton-grid {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 0.75rem;
    margin-top: 1.5rem;
  }

  .skeleton-grid span {
    height: 5.5rem;
    border-radius: 0.75rem;
  }

  .route-error-card {
    width: min(34rem, calc(100% - 2rem));
    padding: clamp(1.5rem, 4vw, 2.25rem);
    border: 1px solid var(--border-color);
    border-radius: 1.25rem;
    background: var(--bg-secondary);
    box-shadow: 0 20px 52px rgb(15 23 42 / 0.12);
    text-align: center;
  }

  .route-error-icon {
    display: grid;
    width: 3rem;
    height: 3rem;
    margin: 0 auto 1rem;
    place-items: center;
    border-radius: 1rem;
    background: color-mix(in srgb, #ef4444 13%, var(--bg-secondary));
    color: #dc2626;
  }

  .route-error-icon svg {
    width: 1.5rem;
    height: 1.5rem;
    stroke-linecap: round;
    stroke-linejoin: round;
    stroke-width: 1.8;
  }

  .route-eyebrow {
    margin: 0 0 0.4rem;
    color: var(--text-tertiary);
    font-size: 0.6875rem;
    font-weight: 700;
    letter-spacing: 0.12em;
    text-transform: uppercase;
  }

  h1 {
    margin: 0;
    font-size: clamp(1.25rem, 3vw, 1.625rem);
    font-weight: 700;
    letter-spacing: -0.025em;
  }

  .route-error-copy {
    max-width: 28rem;
    margin: 0.75rem auto 0;
    color: var(--text-secondary);
    font-size: 0.875rem;
    line-height: 1.55;
  }

  .route-error-actions {
    display: flex;
    flex-wrap: wrap;
    justify-content: center;
    gap: 0.625rem;
    margin-top: 1.4rem;
  }

  .route-error-actions button {
    min-height: 2.75rem;
    padding: 0.65rem 1rem;
    border: 1px solid transparent;
    border-radius: 0.75rem;
    font-size: 0.875rem;
    font-weight: 650;
    transition: transform 120ms ease, border-color 120ms ease, background 120ms ease;
  }

  .route-error-actions button:hover {
    transform: translateY(-1px);
  }

  .route-error-actions button:focus-visible {
    outline: 3px solid color-mix(in srgb, var(--color-accent-500) 32%, transparent);
    outline-offset: 2px;
  }

  .primary-action {
    background: var(--color-accent-500);
    color: white;
  }

  .secondary-action {
    border-color: var(--border-color) !important;
    background: var(--bg-primary);
    color: var(--text-primary);
  }

  .text-action {
    background: transparent;
    color: var(--color-accent-600);
  }

  @keyframes reveal-loading {
    to { opacity: 1; }
  }

  @keyframes spin {
    to { transform: rotate(360deg); }
  }

  @keyframes shimmer {
    0% { background-position: 100% 0; }
    100% { background-position: -120% 0; }
  }

  @media (max-width: 520px) {
    .route-loading-content {
      width: min(100% - 1.25rem, 32rem);
    }

    .route-skeleton {
      padding: 1rem;
    }

    .skeleton-grid {
      grid-template-columns: 1fr;
    }

    .skeleton-grid span:not(:first-child) {
      display: none;
    }

    .route-error-card {
      width: min(100% - 1.25rem, 32rem);
    }

    .route-error-actions {
      flex-direction: column;
    }

    .route-error-actions button {
      width: 100%;
    }
  }

  @media (prefers-reduced-motion: reduce) {
    .route-loading-content {
      animation-delay: 0ms;
    }

    .route-spinner,
    .skeleton-line,
    .skeleton-grid span {
      animation: none;
    }

    .route-error-actions button {
      transition: none;
    }
  }
</style>
