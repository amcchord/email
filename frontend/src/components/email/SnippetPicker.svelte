<script>
  import { tick } from 'svelte';
  import { api } from '../../lib/api.js';
  import {
    captureAuthenticatedSession,
    isAuthenticatedSessionCurrent,
  } from '../../lib/stores.js';
  import {
    normalizeSnippetList,
    rankPersonalSnippets,
  } from '../../lib/personalSnippets.js';
  import Icon from '../common/Icon.svelte';

  let {
    open = $bindable(false),
    disabled = false,
    shortcutId = null,
    oninsert = null,
    oncapture = null,
    compact = false,
    label = 'Snippets',
  } = $props();

  let trigger = $state(null);
  let dialog = $state(null);
  let searchInput = $state(null);
  let query = $state('');
  let snippets = $state([]);
  let loading = $state(false);
  let error = $state('');
  let selectedIndex = $state(0);
  let observedOpen = false;
  let returnFocus = null;
  let requestGeneration = 0;
  let triggerCaptured = false;

  let results = $derived(rankPersonalSnippets(snippets, query));

  async function loadSnippets() {
    const generation = ++requestGeneration;
    const session = captureAuthenticatedSession();
    loading = true;
    error = '';
    try {
      const response = await api.listPersonalSnippets();
      if (
        generation !== requestGeneration
        || !open
        || !isAuthenticatedSessionCurrent(session)
      ) return;
      snippets = normalizeSnippetList(response);
      selectedIndex = 0;
    } catch (loadError) {
      if (
        generation !== requestGeneration
        || !open
        || !isAuthenticatedSessionCurrent(session)
      ) return;
      error = loadError?.message || 'Snippets could not be loaded';
      snippets = [];
    } finally {
      if (generation === requestGeneration && open) loading = false;
    }
  }

  async function closePicker({ restoreFocus = true } = {}) {
    requestGeneration += 1;
    open = false;
    await tick();
    if (restoreFocus && returnFocus?.isConnected) {
      returnFocus.focus({ preventScroll: true });
    }
    returnFocus = null;
  }

  async function chooseSnippet(snippet) {
    if (!snippet) return;
    try {
      const accepted = await oninsert?.(snippet);
      if (accepted === false) return;
      // Successful insertion owns the final caret/focus restoration. Closing
      // the picker must not move focus back to its toolbar trigger afterward.
      await closePicker({ restoreFocus: false });
    } catch (insertError) {
      error = insertError?.message || 'The snippet could not be inserted';
    }
  }

  function focusableElements() {
    if (!dialog) return [];
    return [...dialog.querySelectorAll(
      'button:not([disabled]), input:not([disabled]), a[href], [tabindex]:not([tabindex="-1"])',
    )].filter(element => !element.hidden && element.offsetParent !== null);
  }

  function handleDialogKeydown(event) {
    // The picker is the active keyboard context. Keep modifier shortcuts from
    // reaching the underlying Compose/Reader/Flow surface while it is open.
    event.stopPropagation();
    if (event.key === 'Escape') {
      event.preventDefault();
      void closePicker();
      return;
    }
    if (event.key === 'ArrowDown' && results.length > 0) {
      event.preventDefault();
      selectedIndex = (selectedIndex + 1) % results.length;
      return;
    }
    if (event.key === 'ArrowUp' && results.length > 0) {
      event.preventDefault();
      selectedIndex = (selectedIndex - 1 + results.length) % results.length;
      return;
    }
    if (event.key === 'Enter' && document.activeElement === searchInput && results.length > 0) {
      event.preventDefault();
      void chooseSnippet(results[selectedIndex]);
      return;
    }
    if (event.key !== 'Tab') return;
    const focusable = focusableElements();
    if (focusable.length === 0) return;
    const first = focusable[0];
    const last = focusable.at(-1);
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }

  $effect(() => {
    const isOpen = open;
    if (isOpen === observedOpen) return;
    observedOpen = isOpen;
    if (!isOpen) return;
    returnFocus = document.activeElement instanceof HTMLElement
      ? document.activeElement
      : trigger;
    query = '';
    selectedIndex = 0;
    void loadSnippets();
    void tick().then(() => searchInput?.focus({ preventScroll: true }));
  });

  $effect(() => {
    query;
    selectedIndex = 0;
  });
</script>

<button
  bind:this={trigger}
  type="button"
  class="snippet-trigger inline-flex min-h-11 items-center justify-center gap-1.5 rounded-lg border px-3 text-xs font-semibold transition-fast disabled:opacity-50"
  class:compact
  style="border-color: var(--border-color); color: var(--text-secondary); background: var(--bg-primary)"
  aria-label="Insert a personal snippet"
  aria-haspopup="dialog"
  aria-expanded={open}
  data-shortcut={shortcutId || undefined}
  {disabled}
  onpointerdown={() => {
    triggerCaptured = Boolean(oncapture?.());
  }}
  onclick={() => {
    if (!triggerCaptured) oncapture?.();
    triggerCaptured = false;
    open = true;
  }}
>
  <Icon name="file-text" size={15} />
  {#if !compact}<span class="snippet-trigger-label">{label}</span>{/if}
</button>

{#if open}
  <div class="snippet-layer fixed inset-0 z-[70] flex items-center justify-center p-4" role="presentation">
    <button
      type="button"
      class="absolute inset-0 bg-black/45"
      aria-label="Close snippets"
      onclick={() => closePicker()}
    ></button>
    <div
      bind:this={dialog}
      class="snippet-dialog relative flex w-full max-w-xl flex-col overflow-hidden rounded-2xl border shadow-2xl"
      style="background: var(--bg-primary); border-color: var(--border-color)"
      role="dialog"
      tabindex="-1"
      aria-modal="true"
      aria-labelledby="snippet-picker-title"
      onkeydown={handleDialogKeydown}
    >
      <header class="flex items-center gap-3 border-b px-4 py-3" style="border-color: var(--border-color)">
        <div class="min-w-0 flex-1">
          <h2 id="snippet-picker-title" class="text-sm font-semibold" style="color: var(--text-primary)">Insert snippet</h2>
          <p class="text-xs" style="color: var(--text-tertiary)">Search here, or type ; in the message</p>
        </div>
        <button
          type="button"
          class="inline-flex min-h-11 min-w-11 items-center justify-center rounded-lg"
          style="color: var(--text-secondary)"
          aria-label="Close snippets"
          onclick={() => closePicker()}
        ><Icon name="x" size={18} /></button>
      </header>

      <div class="border-b p-3" style="border-color: var(--border-color)">
        <label class="sr-only" for="snippet-search">Search personal snippets</label>
        <div class="flex min-h-11 items-center gap-2 rounded-xl border px-3" style="border-color: var(--border-color); background: var(--bg-secondary)">
          <Icon name="search" size={16} />
          <input
            id="snippet-search"
            bind:this={searchInput}
            bind:value={query}
            class="min-w-0 flex-1 bg-transparent text-sm outline-none"
            style="color: var(--text-primary)"
            placeholder="Type a name or ;shortcut"
            autocomplete="off"
            aria-controls="snippet-results"
            aria-activedescendant={results[selectedIndex] ? `snippet-${results[selectedIndex].snippet_id}` : undefined}
          />
        </div>
      </div>

      <div class="snippet-results min-h-48 overflow-y-auto p-2" id="snippet-results" role="listbox" aria-label="Personal snippets">
        {#if loading}
          <div class="flex min-h-40 items-center justify-center gap-2 text-sm" style="color: var(--text-secondary)" role="status">
            <span class="h-4 w-4 animate-spin rounded-full border-2 border-current border-t-transparent"></span>
            Loading snippets…
          </div>
        {:else if error}
          <div class="flex min-h-40 flex-col items-center justify-center gap-3 px-6 text-center" role="alert">
            <Icon name="alert-circle" size={22} />
            <p class="text-sm" style="color: var(--status-error)">{error}</p>
            <button type="button" class="min-h-11 rounded-lg border px-4 text-sm font-semibold" style="border-color: var(--border-color)" onclick={loadSnippets}>Retry</button>
          </div>
        {:else if results.length === 0}
          <div class="flex min-h-40 flex-col items-center justify-center gap-2 px-6 text-center">
            <Icon name="file-text" size={24} />
            <p class="text-sm font-medium" style="color: var(--text-primary)">{snippets.length ? 'No snippets match' : 'No personal snippets yet'}</p>
            <p class="text-xs" style="color: var(--text-tertiary)">{snippets.length ? 'Try another name, shortcut, or phrase.' : 'Create reusable replies in Settings → Writing.'}</p>
          </div>
        {:else}
          {#each results as snippet, index (snippet.snippet_id)}
            <button
              id="snippet-{snippet.snippet_id}"
              type="button"
              role="option"
              aria-selected={selectedIndex === index}
              class="snippet-option flex min-h-14 w-full items-start gap-3 rounded-xl px-3 py-2.5 text-left"
              class:selected={selectedIndex === index}
              onpointerenter={() => { selectedIndex = index; }}
              onclick={() => chooseSnippet(snippet)}
            >
              <span class="mt-0.5 rounded-md px-2 py-1 font-mono text-[11px]" style="background: var(--bg-tertiary); color: var(--color-accent-700)">;{snippet.shortcut}</span>
              <span class="min-w-0 flex-1">
                <span class="block truncate text-sm font-semibold" style="color: var(--text-primary)">{snippet.name}</span>
                <span class="mt-0.5 block truncate text-xs" style="color: var(--text-tertiary)">{snippet.body_text}</span>
              </span>
              <span class="mt-1 text-[10px]" style="color: var(--text-tertiary)">{selectedIndex === index ? 'Enter' : ''}</span>
            </button>
          {/each}
        {/if}
      </div>

      <footer class="flex items-center justify-between gap-3 border-t px-4 py-3" style="border-color: var(--border-color)">
        <span class="text-[11px]" style="color: var(--text-tertiary)" aria-live="polite">{loading ? 'Loading' : `${results.length} result${results.length === 1 ? '' : 's'}`}</span>
        <a href="/?page=admin&tab=writing" class="inline-flex min-h-11 items-center rounded-lg px-3 text-xs font-semibold" style="color: var(--color-accent-700)">Manage snippets</a>
      </footer>
    </div>
  </div>
{/if}

<style>
  .snippet-option.selected {
    background: var(--bg-hover);
    box-shadow: inset 3px 0 0 var(--color-accent-500);
  }

  .snippet-trigger.compact {
    min-width: 2.75rem;
    padding-inline: 0.625rem;
  }

  @media (max-width: 767px) {
    .snippet-trigger {
      min-width: 2.75rem;
      padding-inline: 0.625rem;
    }

    .snippet-trigger-label {
      display: none;
    }

    .snippet-layer {
      align-items: flex-end;
      padding: 0;
    }

    .snippet-dialog {
      max-height: min(88dvh, 46rem);
      border-radius: 1.25rem 1.25rem 0 0;
      border-bottom: 0;
    }

    .snippet-results {
      min-height: min(48dvh, 24rem);
    }
  }

  @media (prefers-reduced-motion: reduce) {
    .animate-spin { animation: none; }
  }
</style>
