<script>
  import { onMount } from 'svelte';
  import { searchQuery } from '../../lib/stores.js';
  import {
    analyzeEmailSearch,
    getEmailSearchSuggestions,
  } from '../../lib/emailSearch.js';
  import Icon from '../common/Icon.svelte';

  const listboxId = 'email-search-suggestions';
  const errorId = 'email-search-error';

  let searchInput = $state(null);
  let searchValue = $state('');
  let appliedSearch = $state('');
  let suggestionsOpen = $state(false);
  let activeSuggestion = $state(-1);
  let searchError = $state('');
  let blurTimer = null;

  let suggestions = $derived(getEmailSearchSuggestions(
    searchValue,
    searchInput?.selectionStart ?? searchValue.length,
  ).slice(0, 8));
  let activeDescendant = $derived(
    suggestionsOpen && activeSuggestion >= 0
      ? `email-search-option-${activeSuggestion}`
      : undefined
  );

  onMount(() => {
    const unsubscribe = searchQuery.subscribe(value => {
      appliedSearch = value;
      searchValue = value;
      searchError = '';
    });
    return () => {
      unsubscribe();
      if (blurTimer) window.clearTimeout(blurTimer);
    };
  });

  function openSuggestions() {
    suggestionsOpen = true;
    activeSuggestion = -1;
  }

  function closeSuggestions() {
    suggestionsOpen = false;
    activeSuggestion = -1;
  }

  function handleInput() {
    searchError = '';
    suggestionsOpen = true;
    activeSuggestion = -1;
  }

  function submitSearch() {
    const trimmed = searchValue.trim();
    const analysis = analyzeEmailSearch(trimmed);
    if (!analysis.valid) {
      searchError = analysis.error.message;
      closeSuggestions();
      queueMicrotask(() => searchInput?.focus());
      return;
    }

    searchError = '';
    searchValue = analysis.normalizedQuery;
    searchQuery.set(analysis.normalizedQuery);
    closeSuggestions();
  }

  function currentFragmentRange() {
    const cursor = searchInput?.selectionStart ?? searchValue.length;
    const before = searchValue.slice(0, cursor);
    const match = /[^\s]+$/u.exec(before);
    return { start: match ? cursor - match[0].length : cursor, end: cursor, cursor };
  }

  function acceptSuggestion(suggestion) {
    const range = currentFragmentRange();
    const fragment = searchValue.slice(range.start, range.end);
    const negation = fragment.startsWith('-') ? '-' : '';
    let replacement = `${negation}${suggestion.insertText}`;
    if (suggestion.type === 'value') replacement += ' ';
    searchValue = `${searchValue.slice(0, range.start)}${replacement}${searchValue.slice(range.end)}`;
    searchError = '';
    suggestionsOpen = suggestion.type !== 'value';
    activeSuggestion = -1;
    const nextCursor = range.start + replacement.length;
    queueMicrotask(() => {
      searchInput?.focus();
      searchInput?.setSelectionRange(nextCursor, nextCursor);
    });
  }

  function focusFirstResult() {
    const firstResult = document.querySelector('[data-email-row-id]');
    if (firstResult instanceof HTMLElement && firstResult.getClientRects().length > 0) {
      firstResult.focus();
    }
  }

  function handleKeydown(event) {
    if (event.key === 'ArrowDown') {
      event.preventDefault();
      if (!suggestionsOpen) openSuggestions();
      else if (suggestions.length > 0) activeSuggestion = (activeSuggestion + 1) % suggestions.length;
      return;
    }
    if (event.key === 'ArrowUp') {
      event.preventDefault();
      if (!suggestionsOpen) openSuggestions();
      else if (suggestions.length > 0) {
        activeSuggestion = activeSuggestion <= 0 ? suggestions.length - 1 : activeSuggestion - 1;
      }
      return;
    }
    if (event.key === 'Enter') {
      event.preventDefault();
      if (suggestionsOpen && activeSuggestion >= 0 && suggestions[activeSuggestion]) {
        acceptSuggestion(suggestions[activeSuggestion]);
      } else {
        submitSearch();
      }
      return;
    }
    if (event.key === 'Escape') {
      event.preventDefault();
      if (suggestionsOpen) {
        closeSuggestions();
      } else if (searchValue !== appliedSearch) {
        searchValue = appliedSearch;
        searchError = '';
      } else {
        focusFirstResult();
      }
    }
  }

  function handleFocus() {
    if (blurTimer) window.clearTimeout(blurTimer);
    openSuggestions();
  }

  function handleBlur() {
    blurTimer = window.setTimeout(closeSuggestions, 100);
  }

  function clearSearch() {
    searchValue = '';
    searchError = '';
    searchQuery.set('');
    closeSuggestions();
    queueMicrotask(() => searchInput?.focus());
  }
</script>

<div class="email-search" role="search" aria-label="Email search">
  <label class="sr-only" for="email-search-input">Search email</label>
  <div class="search-input-wrap">
    <span class="search-icon" aria-hidden="true">
      <Icon name="search" size={17} />
    </span>
    <input
      id="email-search-input"
      bind:this={searchInput}
      bind:value={searchValue}
      oninput={handleInput}
      onfocus={handleFocus}
      onblur={handleBlur}
      onkeydown={handleKeydown}
      type="search"
      role="combobox"
      aria-label="Search email"
      aria-autocomplete="list"
      aria-expanded={suggestionsOpen}
      aria-controls={listboxId}
      aria-activedescendant={activeDescendant}
      aria-invalid={searchError ? 'true' : 'false'}
      aria-describedby={searchError ? errorId : undefined}
      autocomplete="off"
      autocapitalize="none"
      autocorrect="off"
      spellcheck="false"
      enterkeyhint="search"
      placeholder="Search all mail…"
      maxlength="512"
      data-shortcut="nav.search"
    />
    {#if searchValue}
      <button
        type="button"
        onclick={clearSearch}
        class="clear-search"
        aria-label="Clear search"
        title="Clear search"
      >
        <Icon name="x" size={17} />
      </button>
    {:else}
      <kbd class="search-shortcut" aria-hidden="true">/</kbd>
    {/if}
  </div>

  {#if searchError}
    <p id={errorId} class="search-error" role="alert">{searchError}</p>
  {/if}

  {#if suggestionsOpen}
    <div class="suggestion-popover">
      <div class="suggestion-heading">
        <span>{suggestions.length > 0 ? 'Search filters' : 'Email search'}</span>
        <span class="suggestion-hint">Quotes · OR · −exclude</span>
      </div>
      <div id={listboxId} role="listbox" aria-label="Email search filters">
        {#if suggestions.length > 0}
          {#each suggestions as suggestion, index (`${suggestion.syntax}-${index}`)}
            <button
              id={`email-search-option-${index}`}
              type="button"
              role="option"
              aria-selected={activeSuggestion === index}
              class:active={activeSuggestion === index}
              onpointerdown={(event) => event.preventDefault()}
              onclick={() => acceptSuggestion(suggestion)}
              onmouseenter={() => activeSuggestion = index}
            >
              <span class="suggestion-copy">
                <strong>{suggestion.syntax}</strong>
                <span>{suggestion.description}</span>
              </span>
              <span class="suggestion-enter" aria-hidden="true">↵</span>
            </button>
          {/each}
        {:else}
          <p class="suggestion-empty">Press Enter to search. Use quotes for an exact phrase.</p>
        {/if}
      </div>
    </div>
  {/if}
</div>

<style>
  .email-search {
    position: relative;
    width: 100%;
  }
  .search-input-wrap {
    position: relative;
  }
  .search-icon {
    position: absolute;
    left: 0.8rem;
    top: 50%;
    z-index: 1;
    display: inline-flex;
    transform: translateY(-50%);
    color: var(--text-tertiary);
    pointer-events: none;
  }
  input {
    width: 100%;
    height: 2.75rem;
    padding: 0 2.8rem 0 2.45rem;
    border: 1px solid var(--border-color);
    border-radius: 0.75rem;
    outline: none;
    background: var(--bg-primary);
    color: var(--text-primary);
    font-size: 1rem;
    line-height: 1.25rem;
    transition: border-color 120ms ease, box-shadow 120ms ease, background 120ms ease;
  }
  input:focus {
    border-color: var(--color-accent-500);
    box-shadow: 0 0 0 3px color-mix(in srgb, var(--color-accent-500) 18%, transparent);
  }
  input[aria-invalid="true"] {
    border-color: var(--status-error, #dc2626);
  }
  input::-webkit-search-cancel-button {
    display: none;
  }
  .clear-search {
    position: absolute;
    right: 0;
    top: 0;
    display: inline-flex;
    width: 2.75rem;
    height: 2.75rem;
    align-items: center;
    justify-content: center;
    border-radius: 0.7rem;
    color: var(--text-tertiary);
  }
  .search-shortcut {
    position: absolute;
    right: 0.75rem;
    top: 50%;
    transform: translateY(-50%);
    min-width: 1.35rem;
    padding: 0.12rem 0.35rem;
    border: 1px solid var(--border-color);
    border-radius: 0.35rem;
    background: var(--bg-secondary);
    color: var(--text-tertiary);
    font: 600 0.68rem/1.2 system-ui, sans-serif;
    text-align: center;
  }
  .search-error {
    position: absolute;
    top: calc(100% + 0.3rem);
    left: 0.45rem;
    z-index: 72;
    max-width: calc(100vw - 1rem);
    margin: 0;
    padding: 0.4rem 0.6rem;
    border-radius: 0.45rem;
    background: var(--status-error, #b91c1c);
    color: white;
    font-size: 0.75rem;
    font-weight: 600;
    box-shadow: 0 5px 18px rgb(0 0 0 / 0.16);
  }
  .suggestion-popover {
    position: absolute;
    top: calc(100% + 0.45rem);
    left: 0;
    right: 0;
    z-index: 70;
    max-height: min(50dvh, 22rem);
    overflow: auto;
    border: 1px solid var(--border-color);
    border-radius: 0.85rem;
    background: var(--bg-secondary);
    box-shadow: 0 18px 45px rgb(0 0 0 / 0.18), 0 2px 8px rgb(0 0 0 / 0.08);
  }
  .suggestion-heading {
    position: sticky;
    top: 0;
    z-index: 1;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 0.75rem;
    padding: 0.65rem 0.8rem 0.45rem;
    background: var(--bg-secondary);
    color: var(--text-tertiary);
    font-size: 0.7rem;
    font-weight: 700;
    letter-spacing: 0.04em;
    text-transform: uppercase;
  }
  .suggestion-hint {
    font-weight: 500;
    letter-spacing: 0;
    text-transform: none;
  }
  [role="option"] {
    display: flex;
    width: calc(100% - 0.5rem);
    min-height: 2.75rem;
    margin: 0.1rem 0.25rem;
    padding: 0.55rem 0.65rem;
    align-items: center;
    justify-content: space-between;
    gap: 0.75rem;
    border-radius: 0.6rem;
    color: var(--text-primary);
    text-align: left;
  }
  [role="option"].active,
  [role="option"]:hover {
    background: color-mix(in srgb, var(--color-accent-500) 13%, var(--bg-tertiary));
  }
  .suggestion-copy {
    display: flex;
    min-width: 0;
    flex-direction: column;
    gap: 0.1rem;
  }
  .suggestion-copy strong {
    color: var(--color-accent-600);
    font: 700 0.8rem/1.2 ui-monospace, SFMono-Regular, Menlo, monospace;
  }
  .suggestion-copy span {
    overflow: hidden;
    color: var(--text-secondary);
    font-size: 0.75rem;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .suggestion-enter {
    color: var(--text-tertiary);
    font-size: 0.75rem;
  }
  .suggestion-empty {
    margin: 0;
    padding: 0.9rem;
    color: var(--text-secondary);
    font-size: 0.78rem;
  }

  @media (min-width: 768px) {
    input {
      height: 2.5rem;
      font-size: 0.875rem;
    }
    .clear-search {
      width: 2.5rem;
      height: 2.5rem;
    }
  }

  @media (max-width: 767px) {
    .suggestion-popover {
      position: fixed;
      top: 6.6rem;
      left: 0.5rem;
      right: 0.5rem;
    }
    .suggestion-heading {
      align-items: flex-start;
      flex-direction: column;
      gap: 0.15rem;
    }
  }
</style>
