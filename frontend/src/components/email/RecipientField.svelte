<script>
  import { onMount } from 'svelte';
  import {
    commitRecipientInput,
    mailboxIdentity,
    normalizeMailbox,
    normalizeRecipientSuggestions,
    parseMailboxList,
    pendingMailboxHasOpenSyntax,
  } from '../../lib/recipientField.js';

  let {
    id = 'recipient-field',
    field = 'recipients',
    label = 'Recipients',
    recipients = $bindable([]),
    pending = $bindable(false),
    recipientCollections = [],
    accountKey = null,
    loadSuggestions = null,
    onchange = null,
    isDuplicate = null,
    placeholder = 'Add recipients',
    disabled = false,
    required = false,
    debounceMs = 180,
    minQueryLength = 1,
    autocomplete = 'email',
    autofocus = false,
  } = $props();

  let inputElement = $state(null);
  let query = $state('');
  let suggestions = $state([]);
  let loading = $state(false);
  let loadSettled = $state(false);
  let loadError = $state('');
  let feedback = $state('');
  let selectedIndex = $state(0);
  let suppressedQuery = $state('');
  let requestGeneration = 0;
  let observedAccountKey = null;

  const listboxId = $derived(`${id}-suggestions`);
  const feedbackId = $derived(`${id}-feedback`);
  const hintId = $derived(`${id}-hint`);
  let trimmedQuery = $derived(query.trim());
  let menuOpen = $derived(
    !disabled
    && trimmedQuery.length >= Math.max(1, Number(minQueryLength) || 1)
    && trimmedQuery !== suppressedQuery
    && Boolean(loadSuggestions),
  );

  $effect(() => {
    pending = Boolean(trimmedQuery);
    if (!trimmedQuery) feedback = '';
  });

  function optionId(index) {
    return `${id}-suggestion-${index}`;
  }

  export function focus({ force = false, selectPending = false } = {}) {
    if (!inputElement || (disabled && !force)) return false;
    inputElement.focus({ preventScroll: true });
    if (selectPending) inputElement.select();
    return true;
  }

  function describeCommit(result) {
    const messages = [];
    if (result.invalid.length) {
      messages.push(`${result.invalid.length === 1 ? 'This address is' : 'These addresses are'} invalid: ${result.invalid.join(', ')}`);
    }
    if (result.duplicates.length) {
      messages.push(`${result.duplicates.length === 1 ? 'That recipient is' : 'Those recipients are'} already included.`);
    }
    return messages.join(' ');
  }

  function emitChange({ next, added = [], removed = [], duplicates = [] }) {
    recipients = next;
    onchange?.({ recipients: next, added, removed, duplicates, field });
  }

  function commitValue(value = query) {
    const result = commitRecipientInput(value, {
      recipients,
      recipientCollections,
      isDuplicate,
      field,
    });
    if (result.added.length) {
      emitChange({
        next: result.recipients,
        added: result.added,
        duplicates: result.duplicates,
      });
    } else if (result.duplicates.length) {
      onchange?.({
        recipients: [...recipients],
        added: [],
        removed: [],
        duplicates: result.duplicates,
        field,
      });
    }
    query = result.invalid.join(', ');
    feedback = describeCommit(result);
    suppressedQuery = query.trim();
    suggestions = [];
    loadSettled = false;
    selectedIndex = 0;
    return result.added.length > 0 && result.invalid.length === 0;
  }

  function removeRecipient(index) {
    if (disabled || index < 0 || index >= recipients.length) return;
    const removed = recipients[index];
    const next = recipients.filter((_mailbox, itemIndex) => itemIndex !== index);
    feedback = '';
    emitChange({ next, removed: [removed] });
    focus();
  }

  function chooseSuggestion(suggestion) {
    if (!suggestion || disabled) return;
    commitValue(suggestion.mailbox);
    query = '';
    suppressedQuery = '';
    feedback = '';
    focus();
  }

  function dismissSuggestions() {
    suppressedQuery = trimmedQuery;
    suggestions = [];
    loadSettled = false;
    loadError = '';
    loading = false;
    requestGeneration += 1;
    selectedIndex = 0;
  }

  function handleInput(event) {
    query = event.currentTarget.value;
    if (query.trim() !== suppressedQuery) suppressedQuery = '';
    feedback = '';
    selectedIndex = 0;
  }

  function handlePaste(event) {
    if (disabled) return;
    const pasted = event.clipboardData?.getData('text') || '';
    if (!pasted) return;
    const parsed = parseMailboxList(pasted);
    const looksLikeList = /[,;\r\n]/u.test(pasted);
    if (!looksLikeList && (parsed.invalid.length || parsed.mailboxes.length !== 1)) return;
    event.preventDefault();
    const prefix = query.trim();
    commitValue(prefix ? `${prefix}, ${pasted}` : pasted);
  }

  function handleBlur(event) {
    const pendingQuery = event.currentTarget.value.trim();
    query = event.currentTarget.value;
    if (disabled || !pendingQuery) {
      feedback = '';
      return;
    }
    if (normalizeMailbox(pendingQuery)) {
      commitValue();
      return;
    }
    dismissSuggestions();
    feedback = 'Enter a complete email address before leaving this field.';
  }

  function containTrailingKey(event) {
    if (menuOpen && (event.metaKey || event.ctrlKey || event.altKey)) {
      event.stopPropagation();
    }
  }

  function handleKeydown(event) {
    if (menuOpen) event.stopPropagation();
    if (menuOpen && (event.metaKey || event.ctrlKey || event.altKey)) {
      if (event.key === 'Enter') event.preventDefault();
      return;
    }

    if (event.key === 'ArrowDown' && menuOpen && suggestions.length) {
      event.preventDefault();
      selectedIndex = (selectedIndex + 1) % suggestions.length;
      return;
    }
    if (event.key === 'ArrowUp' && menuOpen && suggestions.length) {
      event.preventDefault();
      selectedIndex = (selectedIndex - 1 + suggestions.length) % suggestions.length;
      return;
    }
    if (event.key === 'Escape' && menuOpen) {
      event.preventDefault();
      dismissSuggestions();
      return;
    }
    if (event.key === 'Enter') {
      event.preventDefault();
      if (menuOpen && suggestions[selectedIndex]) chooseSuggestion(suggestions[selectedIndex]);
      else if (trimmedQuery) commitValue();
      return;
    }
    if (event.key === 'Tab' && trimmedQuery) {
      if (menuOpen && suggestions[selectedIndex]) {
        event.preventDefault();
        chooseSuggestion(suggestions[selectedIndex]);
      } else {
        const normalized = normalizeMailbox(trimmedQuery);
        if (normalized) commitValue();
        else {
          event.preventDefault();
          feedback = 'Enter a complete email address before leaving this field.';
        }
      }
      return;
    }
    if ((event.key === ',' || event.key === ';') && trimmedQuery && !pendingMailboxHasOpenSyntax(query)) {
      event.preventDefault();
      commitValue();
      return;
    }
    if (event.key === 'Backspace' && !query && recipients.length) {
      event.preventDefault();
      removeRecipient(recipients.length - 1);
    }
  }

  $effect(() => {
    const nextAccountKey = accountKey;
    if (Object.is(nextAccountKey, observedAccountKey)) return;
    observedAccountKey = nextAccountKey;
    requestGeneration += 1;
    query = '';
    suggestions = [];
    selectedIndex = 0;
    suppressedQuery = '';
    loadSettled = false;
    loadError = '';
    loading = false;
    feedback = '';
  });

  $effect(() => {
    const loader = loadSuggestions;
    const requestedQuery = trimmedQuery;
    const requestedAccount = accountKey;
    const minimum = Math.max(1, Number(minQueryLength) || 1);
    if (
      typeof loader !== 'function'
      || disabled
      || requestedQuery.length < minimum
      || requestedQuery === suppressedQuery
    ) {
      suggestions = [];
      loading = false;
      loadSettled = false;
      loadError = '';
      return;
    }

    const generation = ++requestGeneration;
    const controller = new AbortController();
    const delay = Math.max(0, Number(debounceMs) || 0);
    loading = true;
    loadSettled = false;
    loadError = '';
    const timer = window.setTimeout(async () => {
      try {
        const response = await loader({
          query: requestedQuery,
          accountKey: requestedAccount,
          signal: controller.signal,
        });
        if (
          controller.signal.aborted
          || generation !== requestGeneration
          || requestedQuery !== query.trim()
          || !Object.is(requestedAccount, accountKey)
        ) return;
        suggestions = normalizeRecipientSuggestions(response, {
          recipients,
          recipientCollections,
        });
        selectedIndex = 0;
      } catch (error) {
        if (controller.signal.aborted || generation !== requestGeneration) return;
        suggestions = [];
        loadError = error?.message || 'Suggestions are unavailable.';
      } finally {
        if (!controller.signal.aborted && generation === requestGeneration) {
          loading = false;
          loadSettled = true;
        }
      }
    }, delay);

    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  });

  onMount(() => {
    if (!autofocus) return undefined;
    const frame = requestAnimationFrame(() => {
      const active = document.activeElement;
      const focusIsLost = !active
        || active === document.body
        || active.matches?.('main')
        || !active.isConnected;
      if (focusIsLost) focus();
    });
    return () => cancelAnimationFrame(frame);
  });
</script>

<div class="recipient-field relative w-full min-w-0" data-recipient-field={field}>
  <div
    class="recipient-shell flex min-h-11 w-full min-w-0 flex-wrap items-center gap-1.5 rounded-xl border px-2 py-1.5 focus-within:ring-2 focus-within:ring-accent-500/40"
    class:recipient-error={Boolean(feedback)}
    style="background: var(--bg-secondary); border-color: {feedback ? 'var(--status-error)' : 'var(--border-color)'}"
  >
    <label for={id} class="shrink-0 px-1 text-xs font-semibold" style="color: var(--text-secondary)">{label}</label>
    <div class="recipient-chips contents" role="list" aria-label={`${label} recipients`}>
      {#each recipients as mailbox, index (`${mailbox}-${index}`)}
        <span class="recipient-chip inline-flex min-h-11 max-w-full min-w-0 items-center rounded-lg" role="listitem" style="background: var(--bg-tertiary); color: var(--text-primary)">
          <span class="min-w-0 truncate pl-2.5 text-sm" title={mailbox}>{mailbox}</span>
          <button
            type="button"
            class="inline-flex min-h-11 min-w-11 shrink-0 items-center justify-center rounded-lg text-lg leading-none disabled:opacity-50"
            aria-label={`Remove ${mailbox}`}
            {disabled}
            onclick={() => removeRecipient(index)}
          >×</button>
        </span>
      {/each}
    </div>
    <input
      bind:this={inputElement}
      bind:value={query}
      {id}
      type="text"
      class="recipient-query min-h-11 min-w-32 flex-1 bg-transparent px-1 text-sm outline-none disabled:opacity-50"
      style="color: var(--text-primary)"
      {placeholder}
      {disabled}
      required={required && recipients.length === 0}
      {autocomplete}
      inputmode="email"
      autocapitalize="none"
      spellcheck="false"
      role="combobox"
      aria-autocomplete="list"
      aria-expanded={menuOpen}
      aria-controls={menuOpen ? listboxId : undefined}
      aria-activedescendant={menuOpen && suggestions[selectedIndex] ? optionId(selectedIndex) : undefined}
      aria-describedby={`${hintId}${feedback ? ` ${feedbackId}` : ''}`}
      aria-invalid={Boolean(feedback)}
      aria-required={required}
      oninput={handleInput}
      onblur={handleBlur}
      onpaste={handlePaste}
      onkeydown={handleKeydown}
      onkeyup={containTrailingKey}
      onkeypress={containTrailingKey}
    />
  </div>

  <p id={hintId} class="sr-only">Enter a complete email address, then press Enter or Tab. Paste comma, semicolon, or line-separated address lists.</p>
  {#if feedback}
    <p id={feedbackId} class="mt-1 px-1 text-xs" style="color: var(--status-error)" role="alert">{feedback}</p>
  {/if}

  {#if menuOpen}
    <div
      id={listboxId}
      class="recipient-suggestions absolute left-0 right-0 z-[65] mt-1 max-h-72 min-w-0 overflow-y-auto overflow-x-hidden rounded-xl border p-1 shadow-xl"
      style="background: var(--bg-primary); border-color: var(--border-color)"
      role="listbox"
      aria-label={`${label} suggestions`}
      aria-busy={loading}
    >
      {#if loading && suggestions.length === 0}
        <div class="flex min-h-11 items-center px-3 text-sm" role="status" style="color: var(--text-secondary)">Finding recipients…</div>
      {:else if loadError}
        <div class="min-h-11 px-3 py-2 text-sm" role="status" style="color: var(--text-secondary)">
          {loadError} Type a complete address and press Enter.
        </div>
      {:else if suggestions.length === 0}
        <div class="min-h-11 px-3 py-2 text-sm" role="status" style="color: var(--text-secondary)">
          No suggestions. Type a complete address and press Enter.
        </div>
      {:else}
        {#each suggestions as suggestion, index (suggestion.identity)}
          <button
            type="button"
            id={optionId(index)}
            class="recipient-option flex min-h-11 w-full min-w-0 items-center justify-between gap-3 rounded-lg px-3 py-2 text-left"
            class:selected={index === selectedIndex}
            style="background: {index === selectedIndex ? 'var(--bg-tertiary)' : 'transparent'}; color: var(--text-primary)"
            role="option"
            aria-selected={index === selectedIndex}
            onpointerdown={(event) => event.preventDefault()}
            onclick={() => chooseSuggestion(suggestion)}
            onmouseenter={() => { selectedIndex = index; }}
          >
            <span class="min-w-0 truncate text-sm font-medium">{suggestion.label}</span>
            {#if suggestion.detail}<span class="min-w-0 truncate text-xs" style="color: var(--text-tertiary)">{suggestion.detail}</span>{/if}
          </button>
        {/each}
      {/if}
    </div>
  {/if}
</div>

<style>
  .recipient-field,
  .recipient-shell,
  .recipient-suggestions {
    max-width: 100%;
  }

  .recipient-chip {
    flex: 0 1 auto;
  }

  .recipient-query {
    width: 10rem;
    max-width: 100%;
  }

  .recipient-option.selected {
    outline: 2px solid color-mix(in srgb, var(--color-accent-500) 42%, transparent);
    outline-offset: -2px;
  }

  @media (max-width: 767px) {
    .recipient-shell {
      padding-inline: 0.375rem;
    }

    .recipient-chip {
      width: min(100%, 24rem);
    }

    .recipient-query {
      min-width: min(9rem, 55vw);
    }
  }
</style>
