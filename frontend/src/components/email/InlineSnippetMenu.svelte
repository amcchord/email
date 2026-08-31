<script>
  import { onMount } from 'svelte';
  import { api } from '../../lib/api.js';
  import {
    captureAuthenticatedSession,
    isAuthenticatedSessionCurrent,
  } from '../../lib/stores.js';
  import {
    normalizeSnippetList,
    rankPersonalSnippets,
  } from '../../lib/personalSnippets.js';
  import { clampInlineSnippetMenuPosition } from '../../lib/inlineSnippetExpansion.js';

  let {
    active = null,
    menuId = 'inline-snippet-menu',
    onchoose = null,
    ondismiss = null,
    ona11ychange = null,
  } = $props();

  let snippets = $state([]);
  let loading = $state(false);
  let error = $state('');
  let selectedIndex = $state(0);
  let requestGeneration = 0;
  let observedActivation = null;
  let lastA11ySignature = '';
  let position = $state({
    left: 8,
    top: 8,
    width: 0,
    maxHeight: 0,
    placement: 'below',
  });

  let isActive = $derived(Boolean(active));
  let query = $derived(String(active?.query ?? ''));
  let results = $derived(
    isActive && !loading && !error
      ? rankPersonalSnippets(snippets, query)
      : [],
  );

  function activationIdentity(trigger) {
    return trigger?.activation ?? trigger;
  }

  function optionId(snippet) {
    return `${menuId}-option-${snippet.snippet_id}`;
  }

  function currentResult() {
    return results[selectedIndex] || null;
  }

  function loadingStatus() {
    if (!isActive) return '';
    if (loading) return 'Loading personal snippets';
    if (error) return 'Personal snippets are unavailable. The typed shortcut is unchanged.';
    if (results.length === 0) return `No personal snippets match ${query ? `semicolon ${query}` : 'this shortcut'}`;
    return `${results.length} personal snippet${results.length === 1 ? '' : 's'} available`;
  }

  function visualViewportSnapshot() {
    const visual = window.visualViewport;
    return {
      width: visual?.width ?? window.innerWidth,
      height: visual?.height ?? window.innerHeight,
      offsetLeft: visual?.offsetLeft ?? 0,
      offsetTop: visual?.offsetTop ?? 0,
    };
  }

  function updatePosition() {
    if (!active || typeof window === 'undefined') return;
    position = clampInlineSnippetMenuPosition(
      active.anchor,
      visualViewportSnapshot(),
    );
  }

  async function loadSnippets(trigger, activation) {
    const generation = ++requestGeneration;
    const session = captureAuthenticatedSession();
    // Every activation begins without data from a prior editor/session.
    snippets = [];
    selectedIndex = 0;
    error = '';
    loading = true;
    try {
      const response = await api.listPersonalSnippets();
      if (
        generation !== requestGeneration
        || !active
        || !Object.is(activationIdentity(active), activation)
        || !Object.is(active, trigger) && active.activation == null
        || !isAuthenticatedSessionCurrent(session)
      ) return;
      snippets = normalizeSnippetList(response);
    } catch (loadError) {
      if (
        generation !== requestGeneration
        || !active
        || !Object.is(activationIdentity(active), activation)
        || !isAuthenticatedSessionCurrent(session)
      ) return;
      error = loadError?.message || 'Personal snippets could not be loaded';
      snippets = [];
    } finally {
      if (
        generation === requestGeneration
        && active
        && Object.is(activationIdentity(active), activation)
        && isAuthenticatedSessionCurrent(session)
      ) loading = false;
    }
  }

  function chooseSnippet(snippet) {
    if (!isActive || !snippet || typeof onchoose !== 'function') return false;
    onchoose(snippet, active);
    return true;
  }

  function dismiss(reason = 'escape') {
    if (!isActive) return false;
    requestGeneration += 1;
    ondismiss?.({ reason, trigger: active });
    return true;
  }

  export function handleKeydown(event) {
    if (!isActive || !event) return false;

    // Modifier chords belong wholly to this active suggestion context so an
    // underlying editor cannot turn one into Send or another global action.
    if (event.metaKey || event.ctrlKey || event.altKey) {
      event.preventDefault();
      event.stopPropagation();
      return true;
    }

    if (event.key === 'Escape') {
      event.preventDefault();
      event.stopPropagation();
      return dismiss('escape');
    }
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault();
      event.stopPropagation();
      if (results.length > 0) {
        const direction = event.key === 'ArrowDown' ? 1 : -1;
        selectedIndex = (selectedIndex + direction + results.length) % results.length;
      }
      return true;
    }
    if ((event.key === 'Enter' || event.key === 'Tab') && currentResult()) {
      event.preventDefault();
      event.stopPropagation();
      return chooseSnippet(currentResult());
    }
    return false;
  }

  function handleOptionPointerDown(event, snippet) {
    // The editor must retain its captured caret/focus while the caller replaces
    // the exact trigger range.
    event.preventDefault();
    event.stopPropagation();
    chooseSnippet(snippet);
  }

  function handleOptionClick(event, snippet) {
    event.preventDefault();
    event.stopPropagation();
    // Virtual accessibility clicks do not have a preceding pointer event.
    if (event.detail === 0) chooseSnippet(snippet);
  }

  $effect(() => {
    const trigger = active;
    const activation = activationIdentity(trigger);
    if (!trigger) {
      if (observedActivation !== null) requestGeneration += 1;
      observedActivation = null;
      snippets = [];
      loading = false;
      error = '';
      selectedIndex = 0;
      return;
    }
    if (Object.is(activation, observedActivation)) return;
    observedActivation = activation;
    updatePosition();
    void loadSnippets(trigger, activation);
  });

  $effect(() => {
    query;
    selectedIndex = 0;
  });

  $effect(() => {
    const rect = active?.anchor;
    rect?.left;
    rect?.top;
    rect?.bottom;
    if (active) updatePosition();
  });

  $effect(() => {
    const selected = currentResult();
    const payload = {
      expanded: isActive,
      controls: isActive ? menuId : undefined,
      activeDescendant: isActive && selected ? optionId(selected) : undefined,
      status: loadingStatus(),
    };
    const signature = JSON.stringify(payload);
    if (signature === lastA11ySignature) return;
    lastA11ySignature = signature;
    ona11ychange?.(payload);
  });

  onMount(() => {
    const reposition = () => updatePosition();
    window.addEventListener('resize', reposition, { passive: true });
    window.addEventListener('scroll', reposition, { passive: true, capture: true });
    window.visualViewport?.addEventListener('resize', reposition, { passive: true });
    window.visualViewport?.addEventListener('scroll', reposition, { passive: true });
    return () => {
      requestGeneration += 1;
      window.removeEventListener('resize', reposition);
      window.removeEventListener('scroll', reposition, true);
      window.visualViewport?.removeEventListener('resize', reposition);
      window.visualViewport?.removeEventListener('scroll', reposition);
    };
  });
</script>

{#if isActive}
  <div
    id={menuId}
    class="inline-snippet-menu fixed z-[75] overflow-y-auto overscroll-contain rounded-xl border p-1.5 shadow-2xl"
    class:above={position.placement === 'above'}
    style:left="{position.left}px"
    style:top="{position.top}px"
    style:width="{position.width}px"
    style:max-height="{position.maxHeight}px"
    style:background="var(--bg-primary)"
    style:border-color="var(--border-color)"
    role="listbox"
    aria-label="Personal snippet suggestions"
  >
    {#if loading}
      <div class="flex min-h-11 items-center gap-2 px-3 text-sm" style="color: var(--text-secondary)" role="status">
        <span class="h-3.5 w-3.5 animate-spin rounded-full border-2 border-current border-t-transparent"></span>
        Loading snippets…
      </div>
    {:else if error}
      <div class="flex min-h-11 items-center px-3 py-2 text-sm" style="color: var(--status-error)" role="alert">
        Snippets unavailable. Keep typing to leave ;{query} unchanged.
      </div>
    {:else if results.length === 0}
      <div class="flex min-h-11 items-center px-3 py-2 text-sm" style="color: var(--text-secondary)" role="status">
        No snippets match ;{query}
      </div>
    {:else}
      {#each results as snippet, index (snippet.snippet_id)}
        <button
          id={optionId(snippet)}
          type="button"
          role="option"
          aria-selected={selectedIndex === index}
          tabindex="-1"
          class="snippet-option flex min-h-11 w-full min-w-0 items-center gap-3 rounded-lg px-3 py-2 text-left"
          class:selected={selectedIndex === index}
          onpointerenter={() => { selectedIndex = index; }}
          onpointerdown={(event) => handleOptionPointerDown(event, snippet)}
          onclick={(event) => handleOptionClick(event, snippet)}
        >
          <span class="shrink-0 rounded px-1.5 py-1 font-mono text-[11px]" style="background: var(--bg-tertiary); color: var(--color-accent-700)">
            ;{snippet.shortcut}
          </span>
          <span class="min-w-0 flex-1">
            <span class="block truncate text-sm font-semibold" style="color: var(--text-primary)">{snippet.name}</span>
            <span class="block truncate text-xs" style="color: var(--text-tertiary)">{snippet.body_text}</span>
          </span>
        </button>
      {/each}
    {/if}
  </div>
{/if}

<style>
  .inline-snippet-menu {
    min-width: min(15rem, calc(100vw - 1rem));
    overscroll-behavior: contain;
  }

  .snippet-option:hover,
  .snippet-option.selected {
    background: var(--bg-hover);
    box-shadow: inset 3px 0 0 var(--color-accent-500);
  }

  @media (max-width: 639px) {
    .inline-snippet-menu {
      max-width: calc(100vw - 1rem);
    }
  }

  @media (prefers-reduced-motion: reduce) {
    .animate-spin { animation: none; }
  }
</style>
