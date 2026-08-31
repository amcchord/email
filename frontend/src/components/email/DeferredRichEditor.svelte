<script>
  import { onDestroy, onMount, untrack } from 'svelte';
  import InlineSnippetMenu from './InlineSnippetMenu.svelte';
  import { findInlineSnippetTrigger } from '../../lib/inlineSnippetExpansion.js';
  import { sanitizeComposeHtml } from '../../lib/sanitize.js';
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
    inlineSnippets = false,
  } = $props();

  const cachedEditor = getCachedRichEditor();
  let CurrentEditor = $state(cachedEditor);
  let status = $state(cachedEditor ? 'ready' : 'loading');
  let fallbackElement = $state(null);
  let fallbackDirty = $state(false);
  let latestContent = $state(untrack(() => sanitizeComposeHtml(content || '')));
  let observedContent = $state(untrack(() => content || ''));
  let mounted = false;
  let generation = 0;
  let transferFocus = $state(false);
  let fallbackInsertionRange = null;
  let fallbackComposing = false;
  let richHandle = $state.raw(null);
  let inlineMenuHandle = $state(null);
  let inlineTrigger = $state(null);
  let inlineA11y = $state({ expanded: false, controls: null, activeDescendant: null });
  let inlineActivation = 0;
  let dismissedInlineSignature = null;

  function inlineSignature(trigger) {
    if (!trigger) return null;
    if (trigger.kind === 'rich') return `${trigger.kind}:${trigger.from}:${trigger.to}:${trigger.token}`;
    return `${trigger.kind}:${trigger.startOffset}:${trigger.endOffset}:${trigger.token}`;
  }

  function sameInlineOrigin(left, right) {
    if (!left || !right || left.kind !== right.kind) return false;
    if (left.kind === 'rich') return left.from === right.from;
    return left.node === right.node && left.startOffset === right.startOffset;
  }

  function setInlineTrigger(next) {
    if (!inlineSnippets || !next) {
      inlineTrigger = null;
      return;
    }
    const signature = inlineSignature(next);
    if (signature === dismissedInlineSignature) {
      inlineTrigger = null;
      return;
    }
    dismissedInlineSignature = null;
    const activation = sameInlineOrigin(inlineTrigger, next)
      ? inlineTrigger.activation
      : ++inlineActivation;
    inlineTrigger = { ...next, activation };
  }

  function dismissInlineTrigger() {
    dismissedInlineSignature = inlineSignature(inlineTrigger);
    inlineTrigger = null;
  }

  function handleInlineSnippetKeydown(event) {
    return inlineMenuHandle?.handleKeydown?.(event) ?? false;
  }

  function inlineSnippetA11yChanged(state) {
    inlineA11y = state || { expanded: false, controls: null, activeDescendant: null };
  }

  function fallbackInlineTrigger(node) {
    if (
      !inlineSnippets
      || fallbackComposing
      || !node
      || typeof document.execCommand !== 'function'
    ) return null;
    const selection = window.getSelection?.();
    if (!selection?.isCollapsed || selection.rangeCount === 0) return null;
    const focusNode = selection.focusNode;
    const focusOffset = selection.focusOffset;
    if (!focusNode || focusNode.nodeType !== Node.TEXT_NODE || !node.contains(focusNode)) return null;
    const blockedParent = focusNode.parentElement?.closest?.('a, code, pre');
    if (blockedParent && node.contains(blockedParent)) return null;
    const parsed = findInlineSnippetTrigger(focusNode.data, focusOffset);
    if (!parsed) return null;
    const range = document.createRange();
    range.setStart(focusNode, parsed.to);
    range.collapse(true);
    const rectangle = range.getBoundingClientRect();
    return {
      ...parsed,
      kind: 'fallback',
      node: focusNode,
      startOffset: parsed.from,
      endOffset: parsed.to,
      anchor: {
        left: rectangle.left,
        top: rectangle.top,
        bottom: rectangle.bottom || rectangle.top + 20,
      },
    };
  }

  function publishFallbackInlineTrigger(node = fallbackElement) {
    setInlineTrigger(fallbackInlineTrigger(node));
  }

  function replaceFallbackInlineSnippet(trigger, html) {
    const node = fallbackElement;
    const current = fallbackInlineTrigger(node);
    if (
      !node
      || trigger?.kind !== 'fallback'
      || !current
      || current.node !== trigger.node
      || current.startOffset !== trigger.startOffset
      || current.endOffset !== trigger.endOffset
      || current.token !== trigger.token
    ) return false;
    const safeHtml = sanitizeComposeHtml(String(html || ''));
    if (!safeHtml) return false;
    const range = document.createRange();
    range.setStart(trigger.node, trigger.startOffset);
    range.setEnd(trigger.node, trigger.endOffset);
    const selection = window.getSelection?.();
    if (!selection) return false;
    node.focus({ preventScroll: true });
    selection.removeAllRanges();
    selection.addRange(range);
    const inserted = document.execCommand('insertHTML', false, safeHtml);
    // Inline expansion requires a native undo transaction. The existing
    // snippet picker remains available when this compatibility path cannot
    // provide one.
    if (!inserted) return false;
    const sanitized = sanitizeComposeHtml(node.innerHTML);
    if (sanitized !== node.innerHTML) {
      node.innerHTML = sanitized;
      moveCaretToEnd(node);
    }
    fallbackDirty = true;
    latestContent = sanitized;
    onUpdate?.(sanitized);
    setInlineTrigger(null);
    return true;
  }

  function chooseInlineSnippet(snippet) {
    const trigger = inlineTrigger;
    if (!trigger) return false;
    const inserted = trigger.kind === 'rich'
      ? richHandle?.replaceInlineSnippet?.(trigger, snippet?.body_html)
      : replaceFallbackInlineSnippet(trigger, snippet?.body_html);
    if (inserted) setInlineTrigger(null);
    return Boolean(inserted);
  }

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

  function insertFallbackHtml(node, html) {
    const safeHtml = sanitizeComposeHtml(String(html || ''));
    if (!safeHtml) return false;
    node.focus({ preventScroll: true });
    const selection = window.getSelection?.();
    if (!selection) return false;
    let range = fallbackInsertionRange?.cloneRange()
      || (selection.rangeCount > 0 ? selection.getRangeAt(0).cloneRange() : null);
    fallbackInsertionRange = null;
    if (!range || !node.contains(range.commonAncestorContainer)) {
      range = document.createRange();
      range.selectNodeContents(node);
      range.collapse(false);
    } else {
      // Preserve selected draft content and insert at its trailing boundary.
      range.collapse(false);
    }
    const fragment = range.createContextualFragment(safeHtml);
    const lastNode = fragment.lastChild;
    range.insertNode(fragment);
    if (lastNode) {
      range.setStartAfter(lastNode);
      range.collapse(true);
      selection.removeAllRanges();
      selection.addRange(range);
    }
    const sanitized = sanitizeComposeHtml(node.innerHTML);
    if (sanitized !== node.innerHTML) {
      node.innerHTML = sanitized;
      moveCaretToEnd(node);
    }
    fallbackDirty = true;
    latestContent = sanitized;
    onUpdate?.(sanitized);
    return true;
  }

  function initializeFallback(node) {
    fallbackElement = node;
    node.innerHTML = sanitizeComposeHtml(latestContent);
    if (autofocus && focusIsLost()) {
      node.focus({ preventScroll: true });
      moveCaretToEnd(node);
    }
    onReady?.({
      mode: 'fallback',
      insertHtml: html => insertFallbackHtml(node, html),
      rememberSelection: () => {
        const selection = window.getSelection?.();
        if (!selection?.rangeCount) return false;
        const range = selection.getRangeAt(0);
        if (!node.contains(range.commonAncestorContainer)) return false;
        fallbackInsertionRange = range.cloneRange();
        return true;
      },
      focus: () => node.focus({ preventScroll: true }),
    });

    return {
      destroy() {
        if (fallbackElement === node) fallbackElement = null;
      },
    };
  }

  function handleFallbackInput(event) {
    const node = event.currentTarget;
    const sanitized = sanitizeComposeHtml(node.innerHTML);
    if (sanitized !== node.innerHTML) {
      node.innerHTML = sanitized;
      moveCaretToEnd(node);
    }
    fallbackDirty = true;
    latestContent = sanitized;
    onUpdate?.(sanitized);
    if (event.isComposing) setInlineTrigger(null);
    else publishFallbackInlineTrigger(node);
  }

  function handleFallbackKeydown(event) {
    if (handleInlineSnippetKeydown(event)) return;
  }

  function handleFallbackCompositionStart() {
    fallbackComposing = true;
    setInlineTrigger(null);
  }

  function handleFallbackCompositionEnd() {
    fallbackComposing = false;
    publishFallbackInlineTrigger();
  }

  function handleRichUpdate(html) {
    const sanitized = sanitizeComposeHtml(html);
    latestContent = sanitized;
    onUpdate?.(sanitized);
  }

  function handleRichReady(handle) {
    richHandle = handle || null;
    onReady?.(handle || { mode: 'rich' });
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
    setInlineTrigger(null);
    mounted = false;
    generation += 1;
  });

  $effect(() => {
    const nextContent = sanitizeComposeHtml(content || '');
    if (nextContent === observedContent) return;
    observedContent = nextContent;
    if (fallbackDirty) return;
    latestContent = nextContent;
    if (fallbackElement) fallbackElement.innerHTML = sanitizeComposeHtml(nextContent);
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
      {inlineSnippets}
      inlineSnippetA11y={inlineA11y}
      onInlineSnippetChange={setInlineTrigger}
      onInlineSnippetKeydown={handleInlineSnippetKeydown}
    />
  {:else}
    <div class="basic-toolbar" aria-hidden="true">
      <span>Basic editor</span>
      <span>{status === 'error' ? 'Rich formatting offline' : 'Formatting is loading'}</span>
    </div>
    <!-- svelte-ignore a11y_aria_activedescendant_has_tabindex (contenteditable is natively focusable) -->
    <div
      class="fallback-editor"
      class:external-scroll={externalScroll}
      role={inlineSnippets ? 'combobox' : 'textbox'}
      aria-autocomplete={inlineSnippets ? 'list' : undefined}
      aria-multiline="true"
      aria-label={ariaLabel}
      aria-expanded={inlineA11y.expanded}
      aria-controls={inlineA11y.expanded ? inlineA11y.controls : undefined}
      aria-activedescendant={inlineA11y.expanded ? inlineA11y.activeDescendant : undefined}
      data-placeholder={placeholder}
      contenteditable="true"
      spellcheck="true"
      oninput={handleFallbackInput}
      onkeydown={handleFallbackKeydown}
      onkeyup={() => publishFallbackInlineTrigger()}
      onclick={() => publishFallbackInlineTrigger()}
      onblur={() => setInlineTrigger(null)}
      oncompositionstart={handleFallbackCompositionStart}
      oncompositionend={handleFallbackCompositionEnd}
      use:initializeFallback
    ></div>
  {/if}

  {#if inlineSnippets}
    <InlineSnippetMenu
      bind:this={inlineMenuHandle}
      active={inlineTrigger}
      menuId={`inline-snippets-${surface}`}
      onchoose={chooseInlineSnippet}
      ondismiss={dismissInlineTrigger}
      ona11ychange={inlineSnippetA11yChanged}
    />
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
