<script>
  import { onMount, tick } from 'svelte';
  import Icon from '../common/Icon.svelte';

  let {
    viewerState,
    attachments = [],
    returnFocusTarget = null,
    onclose,
    onselect,
    ondownload,
    onretry,
  } = $props();

  let dialogEl = $state(null);
  let closeButton = $state(null);
  let returnFocusEl = null;
  let savedBodyOverflow = '';
  let backgroundState = null;
  let currentIndex = $derived(
    attachments.findIndex(attachment => attachment.id === viewerState?.attachment?.id),
  );

  function portal(node) {
    document.body.appendChild(node);
    return {
      destroy() {
        node.remove();
      },
    };
  }

  function setBackgroundInert(inert) {
    if (inert) {
      const target = document.getElementById('app') || document.querySelector('[data-app-shell]');
      if (!target) return;
      backgroundState = {
        target,
        inert: target.hasAttribute('inert'),
        ariaHidden: target.getAttribute('aria-hidden'),
      };
      target.setAttribute('inert', '');
      target.setAttribute('aria-hidden', 'true');
      return;
    }
    if (!backgroundState) return;
    if (!backgroundState.inert) backgroundState.target.removeAttribute('inert');
    if (backgroundState.ariaHidden === null) backgroundState.target.removeAttribute('aria-hidden');
    else backgroundState.target.setAttribute('aria-hidden', backgroundState.ariaHidden);
    backgroundState = null;
  }

  function focusableElements() {
    if (!dialogEl) return [];
    return [...dialogEl.querySelectorAll(
      'button:not([disabled]), a[href], [tabindex]:not([tabindex="-1"])',
    )].filter(element => !element.hasAttribute('hidden'));
  }

  function selectRelative(delta) {
    if (attachments.length < 2 || currentIndex < 0) return;
    const nextIndex = (currentIndex + delta + attachments.length) % attachments.length;
    onselect?.(attachments[nextIndex]);
  }

  function handleKeydown(event) {
    event.stopPropagation();
    if (event.isComposing) return;
    if (event.key === 'Escape') {
      event.preventDefault();
      event.stopImmediatePropagation();
      onclose?.();
      return;
    }
    if (event.key === 'ArrowLeft' && attachments.length > 1) {
      event.preventDefault();
      selectRelative(-1);
      return;
    }
    if (event.key === 'ArrowRight' && attachments.length > 1) {
      event.preventDefault();
      selectRelative(1);
      return;
    }
    if (event.key !== 'Tab') return;
    const focusable = focusableElements();
    if (focusable.length === 0) {
      event.preventDefault();
      return;
    }
    const current = focusable.indexOf(document.activeElement);
    const next = event.shiftKey
      ? (current <= 0 ? focusable.length - 1 : current - 1)
      : (current === focusable.length - 1 ? 0 : current + 1);
    event.preventDefault();
    focusable[next].focus();
  }

  function handleBackdrop(event) {
    if (event.target === event.currentTarget) onclose?.();
  }

  onMount(() => {
    returnFocusEl = returnFocusTarget?.isConnected
      ? returnFocusTarget
      : (document.activeElement instanceof HTMLElement ? document.activeElement : null);
    savedBodyOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    setBackgroundInert(true);
    void tick().then(() => closeButton?.focus());
    return () => {
      setBackgroundInert(false);
      document.body.style.overflow = savedBodyOverflow;
      const target = returnFocusEl;
      returnFocusEl = null;
      if (target?.isConnected) queueMicrotask(() => target.focus());
    };
  });
</script>

<!-- svelte-ignore a11y_no_static_element_interactions -->
<!-- svelte-ignore a11y_click_events_have_key_events -->
<div
  use:portal
  class="attachment-preview-layer"
  onclick={handleBackdrop}
  data-attachment-preview
>
  <!-- svelte-ignore a11y_click_events_have_key_events -->
  <div class="attachment-preview-backdrop" aria-hidden="true" onclick={() => onclose?.()}></div>
  <div
    class="attachment-preview-dialog"
    role="dialog"
    aria-modal="true"
    aria-labelledby="attachment-preview-title"
    aria-describedby="attachment-preview-description"
    aria-busy={viewerState?.mode === 'loading'}
    tabindex="-1"
    bind:this={dialogEl}
    onkeydown={handleKeydown}
  >
    <header class="attachment-preview-header">
      <div class="attachment-preview-heading">
        <h2 id="attachment-preview-title" title={viewerState.displayName}>{viewerState.displayName}</h2>
        <p id="attachment-preview-description">
          {viewerState.typeLabel} · {viewerState.sizeLabel}
          {#if attachments.length > 1 && currentIndex >= 0}
            · {currentIndex + 1} of {attachments.length}
          {/if}
        </p>
      </div>
      <div class="attachment-preview-header-actions">
        {#if viewerState.mode !== 'confirm'}
          <button
            type="button"
            class="preview-icon-button"
            aria-label={viewerState.downloadMode === 'loading'
              ? `Downloading ${viewerState.displayName}`
              : `Download ${viewerState.displayName}`}
            title="Download"
            disabled={viewerState.mode === 'loading' || viewerState.downloadMode === 'loading'}
            aria-busy={viewerState.downloadMode === 'loading'}
            onclick={() => ondownload?.(viewerState.attachment)}
          >
            <span class:animate-spin={viewerState.downloadMode === 'loading'}>
              <Icon name={viewerState.downloadMode === 'loading' ? 'loader' : 'download'} size={18} />
            </span>
          </button>
        {/if}
        <button
          type="button"
          class="preview-icon-button"
          aria-label="Close attachment preview"
          title="Close"
          bind:this={closeButton}
          onclick={() => onclose?.()}
        >
          <Icon name="x" size={20} />
        </button>
      </div>
    </header>

    {#if attachments.length > 1}
      <div class="attachment-preview-navigation" aria-label="Attachment navigation">
        <button type="button" onclick={() => selectRelative(-1)} aria-label="Previous attachment">
          <Icon name="chevron-left" size={18} />
          <span>Previous</span>
        </button>
        <span aria-live="polite">{currentIndex + 1} of {attachments.length}</span>
        <button type="button" onclick={() => selectRelative(1)} aria-label="Next attachment">
          <span>Next</span>
          <Icon name="chevron-right" size={18} />
        </button>
      </div>
    {/if}

    <div class="attachment-preview-body">
      {#if viewerState.mode === 'loading'}
        <div class="preview-centered" role="status" aria-live="polite">
          <span class="preview-spinner" aria-hidden="true"></span>
          <strong>Preparing preview…</strong>
          <span>Preparing a constrained browser preview.</span>
        </div>
      {:else if viewerState.mode === 'error'}
        <div class="preview-centered preview-error" role="alert">
          <Icon name="alert-circle" size={28} />
          <strong>Preview unavailable</strong>
          <span>{viewerState.error.message}</span>
          {#if viewerState.error.retryable}
            <button type="button" class="preview-primary-button" onclick={() => onretry?.(viewerState.attachment)}>
              Retry preview
            </button>
          {/if}
        </div>
      {:else if viewerState.mode === 'unsupported'}
        <div class="preview-centered preview-notice" role="status">
          <Icon name={viewerState.notice?.tone === 'danger' ? 'alert-triangle' : 'file'} size={32} />
          <strong>{viewerState.notice?.label || 'Preview unavailable'}</strong>
          <span>{viewerState.notice?.detail || 'Download this file to view it.'}</span>
        </div>
      {:else if viewerState.mode === 'confirm'}
        <div class="preview-centered preview-warning" role="alert">
          <Icon name="alert-triangle" size={32} />
          <strong>{viewerState.notice.label}</strong>
          <span>{viewerState.notice.detail}</span>
          <span class="preview-confirm-copy">Downloading does not scan or verify this file.</span>
          {#if viewerState.downloadError}
            <span class="preview-download-error" role="alert">{viewerState.downloadError}</span>
          {/if}
          <div class="preview-confirm-actions">
            <button type="button" class="preview-secondary-button" onclick={() => onclose?.()}>
              {viewerState.downloadMode === 'loading' ? 'Close' : 'Cancel'}
            </button>
            <button
              type="button"
              class="preview-danger-button"
              disabled={viewerState.downloadMode === 'loading'}
              aria-busy={viewerState.downloadMode === 'loading'}
              onclick={() => ondownload?.(viewerState.attachment, true)}
            >{viewerState.downloadMode === 'loading' ? 'Downloading…' : 'Download anyway'}</button>
          </div>
        </div>
      {:else if viewerState.preview?.kind === 'image'}
        <div class="preview-media-frame">
          <img src={viewerState.preview.objectUrl} alt="Preview of {viewerState.displayName}" />
        </div>
      {:else if viewerState.preview?.kind === 'pdf'}
        <div class="preview-centered preview-pdf-ready">
          <Icon name="file-text" size={36} />
          <strong>PDF preview is ready</strong>
          <span>Basic checks passed. Open the untrusted document in your browser’s separate PDF viewer.</span>
          <a
            class="preview-primary-button"
            href={viewerState.preview.sourceUrl}
            target="_blank"
            rel="noopener noreferrer"
          >
            <Icon name="external-link" size={16} />
            Open PDF preview
          </a>
        </div>
      {:else if viewerState.preview?.kind === 'text'}
        <!-- svelte-ignore a11y_no_noninteractive_tabindex -->
        <div
          class="preview-text-frame"
          role="region"
          tabindex="0"
          aria-label="Text preview of {viewerState.displayName}"
        >
          {#if viewerState.preview.truncated}
            <div class="preview-truncated" role="status">
              Showing the first 1 MB. Download the file to view the rest.
            </div>
          {/if}
          <pre>{viewerState.preview.text}</pre>
        </div>
      {/if}
    </div>

    <footer
      class="attachment-preview-footer"
      class:attachment-preview-footer-status={Boolean(viewerState.downloadError || viewerState.downloadMode)}
    >
      <div class:preview-footer-idle={!viewerState.downloadError && !viewerState.downloadMode}>
        {#if viewerState.downloadError}
          <Icon name="alert-circle" size={15} />
          <span role="alert">{viewerState.downloadError}</span>
        {:else if viewerState.downloadMode === 'loading'}
          <span class="preview-spinner preview-spinner-small" aria-hidden="true"></span>
          <span role="status">Downloading the original attachment…</span>
        {:else if viewerState.downloadMode === 'success'}
          <Icon name="check" size={15} />
          <span role="status">Original download started.</span>
        {:else}
          <Icon name="shield" size={15} />
          <span>Previewing does not prove a file is safe. Download and open only files you trust.</span>
        {/if}
      </div>
      {#if viewerState.mode !== 'confirm'}
        <button
          type="button"
          class="preview-primary-button"
          disabled={viewerState.mode === 'loading' || viewerState.downloadMode === 'loading'}
          aria-busy={viewerState.downloadMode === 'loading'}
          onclick={() => ondownload?.(viewerState.attachment)}
        >
          <Icon name={viewerState.downloadMode === 'loading' ? 'loader' : 'download'} size={16} />
          {viewerState.downloadMode === 'loading' ? 'Downloading…' : 'Download'}
        </button>
      {/if}
    </footer>
  </div>
</div>

<style>
  .attachment-preview-layer {
    position: fixed;
    inset: 0;
    z-index: 80;
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 24px;
  }
  .attachment-preview-backdrop {
    position: absolute;
    inset: 0;
    background: rgb(15 23 42 / 0.72);
    backdrop-filter: blur(3px);
  }
  .attachment-preview-dialog {
    position: relative;
    width: min(1100px, 100%);
    height: min(820px, calc(100dvh - 48px));
    min-height: 360px;
    display: grid;
    grid-template-rows: auto auto minmax(0, 1fr) auto;
    overflow: hidden;
    border: 1px solid var(--border-color);
    border-radius: 16px;
    background: var(--bg-elevated);
    color: var(--text-primary);
    box-shadow: 0 30px 90px rgb(0 0 0 / 0.38);
  }
  .attachment-preview-header,
  .attachment-preview-footer,
  .attachment-preview-navigation {
    position: relative;
    z-index: 1;
    display: flex;
    align-items: center;
    border-color: var(--border-color);
    background: var(--bg-elevated);
  }
  .attachment-preview-header {
    justify-content: space-between;
    gap: 16px;
    min-width: 0;
    padding: 14px 16px;
    border-bottom: 1px solid var(--border-color);
  }
  .attachment-preview-heading {
    min-width: 0;
  }
  .attachment-preview-heading h2 {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    font-size: 15px;
    font-weight: 650;
  }
  .attachment-preview-heading p {
    margin-top: 2px;
    font-size: 12px;
    color: var(--text-secondary);
  }
  .attachment-preview-header-actions {
    display: flex;
    gap: 4px;
    flex: none;
  }
  .preview-icon-button,
  .attachment-preview-navigation button {
    min-width: 44px;
    min-height: 44px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 6px;
    border-radius: 9px;
    color: var(--text-secondary);
  }
  .preview-icon-button:hover,
  .attachment-preview-navigation button:hover {
    background: var(--bg-tertiary);
    color: var(--text-primary);
  }
  .attachment-preview-navigation {
    justify-content: space-between;
    padding: 4px 12px;
    border-bottom: 1px solid var(--border-color);
    font-size: 12px;
    color: var(--text-secondary);
  }
  .attachment-preview-navigation button {
    padding-inline: 10px;
    font-size: 12px;
    font-weight: 600;
  }
  .attachment-preview-body {
    min-height: 0;
    overflow: auto;
    background: var(--bg-secondary);
  }
  .preview-centered {
    width: 100%;
    min-height: 100%;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 10px;
    padding: 28px;
    text-align: center;
    color: var(--text-secondary);
  }
  .preview-centered strong {
    color: var(--text-primary);
    font-size: 16px;
  }
  .preview-centered > span {
    max-width: 520px;
    font-size: 13px;
    line-height: 1.5;
  }
  .preview-error { color: var(--status-error); }
  .preview-warning { color: var(--status-warning-text); }
  .preview-spinner {
    width: 28px;
    height: 28px;
    border: 3px solid var(--border-color);
    border-top-color: var(--color-accent-500);
    border-radius: 999px;
    animation: attachment-preview-spin 0.8s linear infinite;
  }
  .preview-spinner-small {
    width: 15px;
    height: 15px;
    border-width: 2px;
    flex: none;
  }
  .preview-download-error {
    color: var(--status-error);
  }
  .preview-media-frame {
    width: 100%;
    height: 100%;
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 24px;
    overflow: auto;
  }
  .preview-media-frame img {
    max-width: 100%;
    max-height: 100%;
    object-fit: contain;
    border-radius: 8px;
    box-shadow: 0 12px 36px rgb(0 0 0 / 0.18);
  }
  .preview-pdf-ready { color: var(--text-secondary); }
  .preview-text-frame {
    width: 100%;
    height: 100%;
    overflow: auto;
    padding: 20px;
  }
  .preview-text-frame pre {
    width: min(860px, 100%);
    min-height: 100%;
    margin: 0 auto;
    padding: 20px;
    overflow-wrap: anywhere;
    white-space: pre-wrap;
    border: 1px solid var(--border-color);
    border-radius: 10px;
    background: var(--bg-primary);
    color: var(--text-primary);
    font: 13px/1.6 ui-monospace, SFMono-Regular, Menlo, monospace;
  }
  .preview-truncated {
    width: min(860px, 100%);
    margin: 0 auto 10px;
    padding: 9px 12px;
    border: 1px solid var(--color-accent-500);
    border-radius: 8px;
    color: var(--text-secondary);
    font-size: 12px;
  }
  .attachment-preview-footer {
    justify-content: space-between;
    gap: 16px;
    padding: 10px 16px;
    border-top: 1px solid var(--border-color);
  }
  .attachment-preview-footer > div {
    min-width: 0;
    display: flex;
    align-items: center;
    gap: 7px;
    color: var(--text-secondary);
    font-size: 12px;
  }
  .preview-primary-button,
  .preview-secondary-button,
  .preview-danger-button {
    min-height: 44px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 7px;
    padding: 0 16px;
    border-radius: 9px;
    font-size: 13px;
    font-weight: 650;
    text-decoration: none;
  }
  .preview-primary-button {
    background: var(--color-accent-700);
    color: white;
  }
  .preview-secondary-button {
    border: 1px solid var(--border-color);
    color: var(--text-primary);
  }
  .preview-danger-button {
    background: #b91c1c;
    color: white;
  }
  .preview-confirm-copy {
    font-weight: 600;
  }
  .preview-confirm-actions {
    display: flex;
    flex-wrap: wrap;
    justify-content: center;
    gap: 10px;
    margin-top: 8px;
  }
  button:focus-visible,
  .preview-text-frame:focus-visible {
    outline: 2px solid var(--text-primary);
    outline-offset: 2px;
  }
  button:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }
  @keyframes attachment-preview-spin {
    to { transform: rotate(360deg); }
  }
  @media (max-width: 640px) {
    .attachment-preview-layer {
      padding: 0;
      align-items: stretch;
    }
    .attachment-preview-dialog {
      width: 100%;
      height: 100dvh;
      min-height: 0;
      border: 0;
      border-radius: 0;
      padding-top: env(safe-area-inset-top);
      padding-bottom: env(safe-area-inset-bottom);
    }
    .attachment-preview-header {
      padding: 8px 10px;
    }
    .attachment-preview-navigation button span {
      display: none;
    }
    .preview-media-frame,
    .preview-text-frame {
      padding: 12px;
    }
    .preview-text-frame pre {
      padding: 14px;
      font-size: 12px;
    }
    .attachment-preview-footer {
      padding: 8px 10px;
    }
    .attachment-preview-footer > .preview-footer-idle {
      display: none;
    }
    .attachment-preview-footer-status {
      flex-direction: column;
      align-items: stretch;
    }
    .attachment-preview-footer .preview-primary-button {
      width: 100%;
    }
  }
  @media (prefers-reduced-motion: reduce) {
    .preview-spinner { animation-duration: 1.6s; }
  }
</style>
