<script>
  import {
    analyzeEmailSearch,
    getEmailSearchScopeLabel,
    removeEmailSearchClause,
  } from '../../lib/emailSearch.js';
  import Icon from '../common/Icon.svelte';

  let {
    query = '',
    total = 0,
    updating = false,
    failed = false,
    showingPrevious = false,
    onQueryChange = null,
  } = $props();

  let analysis = $derived(analyzeEmailSearch(query));
  let liveMessage = $derived(
    updating
      ? 'Searching email.'
      : failed
        ? ''
        : `${total.toLocaleString()} ${total === 1 ? 'result' : 'results'}.`
  );
  let scopeLabel = $derived(
    showingPrevious
      ? 'Previous results remain visible'
      : (analysis.valid ? getEmailSearchScopeLabel(analysis.ast) : 'Structured search results')
  );

  function updateQuery(value) {
    if (onQueryChange) onQueryChange(value);
  }

  function removeChip(chip) {
    if (!analysis.valid) return;
    updateQuery(removeEmailSearchClause(analysis.ast, chip.id));
  }

  function focusSearch() {
    const input = document.getElementById('email-search-input');
    if (input instanceof HTMLInputElement) {
      input.focus();
      input.select();
    }
  }
</script>

<section class="search-summary" aria-label="Search results summary">
  <p class="sr-only" aria-live="polite" aria-atomic="true">{liveMessage}</p>
  <div class="summary-lead">
    <span class="summary-icon" aria-hidden="true"><Icon name="search" size={15} /></span>
    <div class="summary-copy">
      <strong>
        {#if updating}
          Searching mail…
        {:else if failed}
          Search interrupted
        {:else}
          {total.toLocaleString()} {total === 1 ? 'result' : 'results'}
        {/if}
      </strong>
      <span>{scopeLabel}</span>
    </div>
  </div>

  {#if analysis.valid && analysis.chips.length > 0}
    <div class="search-chips" aria-label="Applied search filters">
      {#each analysis.chips as chip (chip.id)}
        {#if chip.join}
          <span class:or-join={chip.join === 'or'} class="chip-join" aria-hidden="true">
            {chip.join === 'or' ? 'OR' : '+'}
          </span>
        {/if}
        <button
          type="button"
          class="search-chip"
          onclick={() => removeChip(chip)}
          aria-label={`Remove ${chip.label} filter`}
          title={`Remove ${chip.label}`}
        >
          <span>{chip.label}</span>
          <Icon name="x" size={13} />
        </button>
      {/each}
    </div>
  {:else}
    <span class="raw-query">{query}</span>
  {/if}

  <div class="summary-actions">
    <button type="button" onclick={focusSearch}>Edit</button>
    <button type="button" class="clear-button" onclick={() => updateQuery('')}>Clear</button>
  </div>
</section>

<style>
  .search-summary {
    display: flex;
    min-height: 3.4rem;
    flex: 0 0 auto;
    align-items: center;
    gap: 0.65rem;
    padding: 0.45rem 0.75rem;
    overflow: hidden;
    border-bottom: 1px solid var(--border-color);
    background: color-mix(in srgb, var(--color-accent-500) 6%, var(--bg-secondary));
  }
  .summary-lead {
    display: flex;
    flex: 0 0 auto;
    align-items: center;
    gap: 0.45rem;
  }
  .summary-icon {
    display: inline-flex;
    width: 1.8rem;
    height: 1.8rem;
    align-items: center;
    justify-content: center;
    border-radius: 0.55rem;
    background: color-mix(in srgb, var(--color-accent-500) 16%, transparent);
    color: var(--color-accent-600);
  }
  .summary-copy {
    display: flex;
    flex-direction: column;
    line-height: 1.15;
  }
  .summary-copy strong {
    color: var(--text-primary);
    font-size: 0.76rem;
  }
  .summary-copy span,
  .raw-query {
    color: var(--text-tertiary);
    font-size: 0.68rem;
  }
  .search-chips {
    display: flex;
    min-width: 0;
    flex: 1 1 auto;
    align-items: center;
    gap: 0.3rem;
    overflow-x: auto;
    padding: 0.1rem;
    scrollbar-width: none;
  }
  .search-chips::-webkit-scrollbar {
    display: none;
  }
  .search-chip {
    display: inline-flex;
    min-height: 2.35rem;
    flex: 0 0 auto;
    align-items: center;
    gap: 0.35rem;
    padding: 0.35rem 0.65rem;
    border: 1px solid color-mix(in srgb, var(--color-accent-500) 25%, var(--border-color));
    border-radius: 999px;
    background: var(--bg-primary);
    color: var(--text-secondary);
    font-size: 0.72rem;
    font-weight: 600;
  }
  .search-chip:hover,
  .search-chip:focus-visible {
    border-color: var(--color-accent-500);
    color: var(--text-primary);
  }
  .chip-join {
    flex: 0 0 auto;
    color: var(--text-tertiary);
    font-size: 0.65rem;
    font-weight: 700;
  }
  .chip-join.or-join {
    color: var(--color-accent-600);
  }
  .summary-actions {
    display: flex;
    flex: 0 0 auto;
    align-items: center;
    gap: 0.25rem;
  }
  .summary-actions button {
    min-width: 2.75rem;
    min-height: 2.75rem;
    padding: 0.35rem 0.55rem;
    border-radius: 0.55rem;
    color: var(--text-secondary);
    font-size: 0.72rem;
    font-weight: 700;
  }
  .summary-actions button:hover,
  .summary-actions button:focus-visible {
    background: var(--bg-hover);
    color: var(--text-primary);
  }
  .summary-actions .clear-button {
    color: var(--color-accent-600);
  }
  .raw-query {
    min-width: 0;
    flex: 1 1 auto;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  @media (max-width: 767px) {
    .search-summary {
      min-height: auto;
      flex-wrap: wrap;
      gap: 0.35rem 0.6rem;
      padding: 0.45rem 0.5rem;
    }
    .summary-lead {
      flex: 1 1 auto;
    }
    .search-chips {
      order: 3;
      flex-basis: 100%;
    }
    .search-chip {
      min-height: 2.75rem;
    }
  }
</style>
