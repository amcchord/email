<script>
  import { onDestroy, onMount, untrack } from 'svelte';
  import { sanitizeHtml } from '../../lib/sanitize.js';
  import { getCachedRichEditor, loadRichEditor } from '../../lib/lazyEditor.js';

  let {
    content = '',
    onUpdate = null,
    onReady = null,
    placeholder = 'Write your message...',
    externalScroll = false,
    autofocus = false,
    ariaLabel = 'Message body',
    surface = 'message',
  } = $props();

  const cachedEditor = getCachedRichEditor();
  let CurrentEditor = $state(cachedEditor);
  let status = $state(cachedEditor ? 'ready' : 'loading');
  let fallbackElement = $state(null);
  let fallbackDirty = $state(false);
  let latestContent = $state(untrack(() => content || ''));
  let observedContent = $state(untrack(() => content || ''));
  let mounted = false;
  let generation = 0;
  let transferFocus = $state(false);

  function focusIsLost() {
    const active = document.activeElement;
    return !active
      || active === document.body
      || active.matches?.('main')
      || !active.isConnected;
  }

  function moveCaretToEnd(node) {
    const selection = window.getSelection?.();
    if (!selection) return;
    const range = document.createRange();
    range.selectNodeContents(node);
    range.collapse(false);
    selection.removeAllRanges();
    selection.addRange(range);
  }

  function initializeFallback(node) {
    fallbackElement = node;
    node.innerHTML = sanitizeHtml(latestContent);
    if (autofocus && focusIsLost()) {
      node.focus({ preventScroll: true });
      moveCaretToEnd(node);
    }
    onReady?.({ mode: 'fallback' });

    return {
      destroy() {
        if (fallbackElement === node) fallbackElement = null;
      },
    };
  }

  function handleFallbackInput(event) {
    const node = event.currentTarget;
    const sanitized = sanitizeHtml(node.innerHTML);
    if (sanitized !== node.innerHTML) {
      node.innerHTML = sanitized;
      moveCaretToEnd(node);
    }
    fallbackDirty = true;
    latestContent = sanitized;
    onUpdate?.(sanitized);
  }

  function handleRichUpdate(html) {
    latestContent = html;
    onUpdate?.(html);
  }

  function handleRichReady() {
    onReady?.({ mode: 'rich' });
  }

  async function openEditor() {
    const requestGeneration = ++generation;
    status = 'loading';

    try {
      const component = await loadRichEditor();
      if (!mounted || requestGeneration !== generation) return;
      transferFocus = Boolean(fallbackElement?.contains(document.activeElement));
      CurrentEditor = component;
      status = 'ready';
    } catch (error) {
      if (!mounted || requestGeneration !== generation) return;
      status = 'error';
    }
  }

  function recoverRichEditor() {
    fallbackElement?.focus({ preventScroll: true });
  }

  onMount(() => {
    mounted = true;
    if (!CurrentEditor) void openEditor();
    return () => {
      mounted = false;
      generation += 1;
    };
  });

  onDestroy(() => {
    mounted = false;
    generation += 1;
  });

  $effect(() => {
    const nextContent = content || '';
    if (nextContent === observedContent) return;
    observedContent = nextContent;
    if (fallbackDirty) return;
    latestContent = nextContent;
    if (fallbackElement) fallbackElement.innerHTML = sanitizeHtml(nextContent);
  });
</script>

<div
  class="deferred-editor flex min-h-[300px] flex-1 flex-col"
  class:external-scroll={externalScroll}
  data-editor-state={status}
  data-editor-surface={surface}
  aria-busy={status === 'loading'}
>
  {#if status === 'loading'}
    <div class="editor-status loading" role="status" aria-live="polite" aria-atomic="true">
      <span class="spinner" aria-hidden="true"></span>
      <span>Loading rich formatting… You can start typing now.</span>
    </div>
  {:else if status === 'error'}
    <div class="editor-status error" role="alert" aria-live="assertive" aria-atomic="true">
      <span class="min-w-0">
        <strong>Rich formatting is unavailable.</strong>
        Your draft is still here and basic editing remains available.
      </span>
      <button type="button" onclick={recoverRichEditor}>
        Continue in basic editor
      </button>
    </div>
  {:else}
    <span class="sr-only" role="status" aria-live="polite" aria-atomic="true">Rich formatting ready</span>
  {/if}

  {#if CurrentEditor && status === 'ready'}
    <CurrentEditor
      content={latestContent}
      onUpdate={handleRichUpdate}
      onReady={handleRichReady}
      {placeholder}
      {externalScroll}
      autofocus={autofocus && (transferFocus || focusIsLost())}
      {ariaLabel}
      {surface}
    />
  {:else}
    <div class="basic-toolbar" aria-hidden="true">
      <span>Basic editor</span>
      <span>{status === 'error' ? 'Rich formatting offline' : 'Formatting is loading'}</span>
    </div>
    <div
      class="fallback-editor"
      class:external-scroll={externalScroll}
      role="textbox"
      aria-multiline="true"
      aria-label={ariaLabel}
      data-placeholder={placeholder}
      contenteditable="true"
      spellcheck="true"
      oninput={handleFallbackInput}
      use:initializeFallback
    ></div>
  {/if}
</div>

<style>
  .deferred-editor {
    min-width: 0;
    background: var(--bg-secondary);
  }

  .editor-status {
    display: flex;
    min-height: 2.75rem;
    align-items: center;
    gap: 0.625rem;
    border-bottom: 1px solid var(--border-color);
    padding: 0.5rem 1rem;
    color: var(--text-secondary);
    font-size: 0.75rem;
  }

  .editor-status.loading {
    opacity: 0;
    animation: reveal-status 1ms linear 140ms forwards;
  }

  .editor-status.error {
    flex-wrap: wrap;
    justify-content: space-between;
    border-color: color-mix(in srgb, var(--status-error) 35%, var(--border-color));
    background: color-mix(in srgb, var(--status-error) 7%, var(--bg-secondary));
    color: var(--status-error);
  }

  .editor-status button {
    min-height: 2.75rem;
    flex: 0 0 auto;
    border: 1px solid currentColor;
    border-radius: 0.5rem;
    padding: 0.5rem 0.75rem;
    font-weight: 650;
  }

  .spinner {
    width: 0.875rem;
    height: 0.875rem;
    flex: 0 0 auto;
    border: 2px solid var(--border-color);
    border-top-color: var(--color-accent-500);
    border-radius: 999px;
    animation: spin 700ms linear infinite;
  }

  .basic-toolbar {
    display: flex;
    min-height: 2.5rem;
    align-items: center;
    justify-content: space-between;
    gap: 0.75rem;
    border-bottom: 1px solid var(--border-color);
    padding: 0.5rem 1rem;
    color: var(--text-tertiary);
    font-size: 0.6875rem;
    font-weight: 600;
  }

  .fallback-editor {
    min-height: 300px;
    flex: 1;
    overflow-y: auto;
    padding: 1rem 1.5rem;
    color: var(--text-primary);
    font-size: 0.875rem;
    line-height: 1.55;
    outline: none;
  }

  .fallback-editor.external-scroll {
    overflow: visible;
  }

  .fallback-editor:empty::before {
    color: var(--text-tertiary);
    content: attr(data-placeholder);
    pointer-events: none;
  }

  .fallback-editor:focus-visible {
    box-shadow: inset 0 0 0 2px color-mix(in srgb, var(--color-accent-500) 50%, transparent);
  }

  @keyframes reveal-status {
    to { opacity: 1; }
  }

  @keyframes spin {
    to { transform: rotate(360deg); }
  }

  @media (max-width: 767px) {
    .editor-status {
      align-items: flex-start;
      padding-inline: 0.75rem;
    }

    .editor-status.error {
      flex-direction: column;
    }

    .editor-status button {
      width: 100%;
    }

    .fallback-editor {
      padding-inline: 0.75rem;
    }
  }

  @media (prefers-reduced-motion: reduce) {
    .editor-status.loading {
      animation-delay: 0ms;
    }

    .spinner {
      animation: none;
    }
  }
</style>
