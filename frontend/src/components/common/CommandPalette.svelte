<script>
  import { onMount, tick } from 'svelte';
  import { accounts, currentPage, savedViews } from '../../lib/stores.js';
  import { openSavedView } from '../../lib/savedViewState.js';
  import {
    activeShortcuts,
    actionRegistryVersion,
    commandPaletteOpen,
    eventToCombo,
    formatComboForDisplay,
    getActionState,
    invokeAction,
    normalizeCombo,
  } from '../../lib/shortcutStore.js';
  import { createCommandSessionGuard, getVisibleCommands, moveSelectionIndex } from '../../lib/commandRegistry.js';
  import Icon from './Icon.svelte';

  let query = $state('');
  let selectedIndex = $state(-1);
  let executionError = $state('');
  let executingId = $state(null);
  let inputEl = $state(null);
  let dialogEl = $state(null);
  let returnFocusEl = null;
  let wasOpen = false;
  let savedBodyOverflow = '';
  let activeSession = 0;
  const sessionGuard = createCommandSessionGuard();

  function pageToContext(page) {
    const contexts = {
      flow: 'flow',
      inbox: 'inbox',
      compose: 'compose',
      calendar: 'calendar',
      contacts: 'contacts',
      attachments: 'attachments',
      todos: 'todos',
      chat: 'chat',
      'ai-insights': 'ai-insights',
      admin: 'admin',
      stats: 'stats',
      subscriptions: 'subscriptions',
    };
    return contexts[page] || 'global';
  }

  let commands = $derived.by(() => {
    // Handler registration is not otherwise part of Svelte's dependency
    // graph. Reading the version makes nested mounts/cleanups refresh results.
    void $actionRegistryVersion;
    void $commandPaletteOpen;
    const context = pageToContext($currentPage);
    const registeredCommands = Object.values($activeShortcuts)
      .filter(shortcut => shortcut.id !== 'nav.commands')
      .filter(shortcut => shortcut.palette !== false)
      .filter(shortcut => shortcut.context === 'global' || shortcut.context === context)
      .map(shortcut => {
        const action = getActionState(shortcut.id);
        return {
          ...shortcut,
          shortcut: formatComboForDisplay(shortcut.key),
          registered: action.registered,
          enabled: action.enabled,
          disabledReason: action.disabledReason,
        };
      })
      .filter(command => command.registered);
    const savedViewCommands = $savedViews.map(view => ({
      id: `saved-view:${view.id}`,
      key: '',
      shortcut: '',
      label: `Open ${view.name}`,
      context: 'global',
      category: 'Saved Views',
      keywords: ['saved view', 'custom split', 'search', view.query],
      registered: true,
      enabled: view.account_id === null || $accounts.some(account => account.id === view.account_id),
      disabledReason: 'Reconnect this Saved View account before opening it.',
      run: () => openSavedView(view),
    }));
    return [...registeredCommands, ...savedViewCommands];
  });

  let visibleCommands = $derived(getVisibleCommands(commands, {
    context: pageToContext($currentPage),
    query,
  }));

  function firstResultIndex(list = visibleCommands) {
    return list.length > 0 ? 0 : -1;
  }

  function lastResultIndex(list = visibleCommands) {
    return list.length - 1;
  }

  function moveSelection(delta) {
    selectedIndex = moveSelectionIndex(selectedIndex, delta, visibleCommands.length);
  }

  $effect(() => {
    void query;
    void visibleCommands.length;
    selectedIndex = firstResultIndex();
    executionError = '';
  });

  $effect(() => {
    const activeId = selectedIndex >= 0 ? visibleCommands[selectedIndex]?.id : null;
    if (!$commandPaletteOpen || !activeId) return;
    void tick().then(() => {
      document.getElementById(`command-option-${activeId}`)?.scrollIntoView({ block: 'nearest' });
    });
  });

  function setBackgroundInert(inert) {
    const shell = document.querySelector('[data-app-shell]');
    if (!shell) return;
    if (inert) {
      shell.setAttribute('inert', '');
      shell.setAttribute('aria-hidden', 'true');
    } else {
      shell.removeAttribute('inert');
      shell.removeAttribute('aria-hidden');
    }
  }

  async function opened() {
    const session = sessionGuard.begin();
    activeSession = session;
    returnFocusEl = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    query = '';
    selectedIndex = -1;
    executionError = '';
    executingId = null;
    savedBodyOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    setBackgroundInert(true);
    await tick();
    if (sessionGuard.isCurrent(session) && $commandPaletteOpen) inputEl?.focus();
  }

  function closed() {
    sessionGuard.invalidate();
    activeSession = 0;
    executingId = null;
    setBackgroundInert(false);
    document.body.style.overflow = savedBodyOverflow;
    const target = returnFocusEl;
    returnFocusEl = null;
    if (target?.isConnected) target.focus();
  }

  onMount(() => {
    const unsubscribe = commandPaletteOpen.subscribe(open => {
      if (open && !wasOpen) void opened();
      if (!open && wasOpen) closed();
      wasOpen = open;
    });
    return () => {
      unsubscribe();
      if (wasOpen) closed();
    };
  });

  function closePalette() {
    commandPaletteOpen.set(false);
  }

  async function executeCommand(command) {
    if (!command?.enabled || executingId) return;
    const session = activeSession;
    executionError = '';
    let invocation;
    try {
      invocation = command.run
        ? { started: true, result: command.run(), error: null }
        : invokeAction(command.id);
    } catch (error) {
      invocation = { started: true, result: undefined, error };
    }
    if (!invocation.started) {
      if (sessionGuard.isCurrent(session) && $commandPaletteOpen) {
        executionError = invocation.disabledReason || 'That command is not available right now.';
      }
      return;
    }
    if (invocation.error) {
      if (sessionGuard.isCurrent(session) && $commandPaletteOpen) {
        executionError = invocation.error.message || 'The command could not be completed.';
      }
      return;
    }

    try {
      if (invocation.result && typeof invocation.result.then === 'function') {
        executingId = command.id;
        await invocation.result;
      }
      if (!sessionGuard.isCurrent(session) || !$commandPaletteOpen) return;
      executingId = null;
      commandPaletteOpen.set(false);
    } catch (error) {
      if (!sessionGuard.isCurrent(session) || !$commandPaletteOpen) return;
      executingId = null;
      executionError = error?.message || 'The command could not be completed.';
      await tick();
      inputEl?.focus();
    }
  }

  function focusableElements() {
    if (!dialogEl) return [];
    return [...dialogEl.querySelectorAll(
      'button:not([disabled]), input:not([disabled]), [tabindex]:not([tabindex="-1"])',
    )].filter(element => !element.hasAttribute('hidden'));
  }

  function handleKeydown(event) {
    if (!$commandPaletteOpen || event.isComposing) return;

    const paletteShortcut = $activeShortcuts['nav.commands']?.key;
    if (paletteShortcut && normalizeCombo(eventToCombo(event)) === normalizeCombo(paletteShortcut)) {
      event.preventDefault();
      event.stopImmediatePropagation();
      closePalette();
      return;
    }

    if (event.key === 'Escape') {
      event.preventDefault();
      event.stopImmediatePropagation();
      closePalette();
      return;
    }
    if (event.key === 'ArrowDown') {
      event.preventDefault();
      event.stopImmediatePropagation();
      moveSelection(1);
      return;
    }
    if (event.key === 'ArrowUp') {
      event.preventDefault();
      event.stopImmediatePropagation();
      moveSelection(-1);
      return;
    }
    if (event.key === 'Home') {
      event.preventDefault();
      event.stopImmediatePropagation();
      selectedIndex = firstResultIndex();
      return;
    }
    if (event.key === 'End') {
      event.preventDefault();
      event.stopImmediatePropagation();
      selectedIndex = lastResultIndex();
      return;
    }
    if (event.key === 'Enter') {
      event.preventDefault();
      event.stopImmediatePropagation();
      const command = visibleCommands[selectedIndex];
      if (command) void executeCommand(command);
      return;
    }
    if (event.key === 'Tab') {
      const focusable = focusableElements();
      if (focusable.length === 0) {
        event.preventDefault();
        event.stopImmediatePropagation();
        return;
      }
      const current = focusable.indexOf(document.activeElement);
      const next = event.shiftKey
        ? (current <= 0 ? focusable.length - 1 : current - 1)
        : (current === focusable.length - 1 ? 0 : current + 1);
      event.preventDefault();
      event.stopImmediatePropagation();
      focusable[next].focus();
    }
  }
</script>

<svelte:window onkeydown={handleKeydown} />

{#if $commandPaletteOpen}
  <div class="command-layer">
    <button class="command-backdrop" onclick={closePalette} aria-label="Close command palette"></button>
    <div
      class="command-dialog"
      role="dialog"
      aria-modal="true"
      aria-labelledby="command-palette-title"
      bind:this={dialogEl}
    >
      <div class="command-search-row">
        <Icon name="search" size={20} />
        <label id="command-palette-title" class="sr-only" for="command-palette-input">Commands</label>
        <input
          id="command-palette-input"
          bind:this={inputEl}
          bind:value={query}
          role="combobox"
          aria-autocomplete="list"
          aria-expanded="true"
          aria-controls="command-palette-results"
          aria-activedescendant={selectedIndex >= 0 ? `command-option-${visibleCommands[selectedIndex]?.id}` : undefined}
          autocomplete="off"
          spellcheck="false"
          placeholder="Type a command or action…"
        />
        <button class="command-close" onclick={closePalette} aria-label="Close command palette">
          <Icon name="x" size={18} />
        </button>
      </div>

      <div class="command-result-summary sr-only" aria-live="polite">
        {visibleCommands.length} {visibleCommands.length === 1 ? 'command' : 'commands'} available
      </div>

      {#if executionError}
        <div class="command-error" role="alert">
          <Icon name="alert-circle" size={16} />
          <span>{executionError}</span>
        </div>
      {/if}

      <div id="command-palette-results" class="command-results" role="listbox" aria-label="Available commands">
        {#each visibleCommands as command, index (command.id)}
          <button
            id={`command-option-${command.id}`}
            class="command-option"
            class:command-option-active={index === selectedIndex}
            class:command-option-disabled={!command.enabled}
            role="option"
            tabindex="-1"
            aria-selected={index === selectedIndex}
            aria-disabled={!command.enabled || Boolean(executingId)}
            aria-describedby={!command.enabled ? `command-option-reason-${command.id}` : undefined}
            disabled={Boolean(executingId)}
            onpointermove={() => selectedIndex = index}
            onclick={() => executeCommand(command)}
          >
            <span class="command-icon" aria-hidden="true">
              <Icon name={command.category === 'Inbox' ? 'mail' : command.category === 'Saved Views' ? 'bookmark' : 'arrow-right'} size={16} />
            </span>
            <span class="command-copy">
              <span class="command-label">{command.label}</span>
              <span
                class="command-meta"
                id={!command.enabled ? `command-option-reason-${command.id}` : undefined}
              >
                {command.enabled ? command.category : command.disabledReason}
              </span>
            </span>
            {#if executingId === command.id}
              <span class="command-spinner" aria-label="Running"></span>
            {:else if command.shortcut}
              <kbd>{command.shortcut}</kbd>
            {/if}
          </button>
        {/each}

        {#if visibleCommands.length === 0}
          <div class="command-empty" role="status">
            <Icon name="search" size={22} />
            <strong>No commands match</strong>
            <span>Try an action such as “compose,” “archive,” or “settings.”</span>
          </div>
        {/if}
      </div>

      <footer class="command-footer" aria-hidden="true">
        <span><kbd>↑</kbd><kbd>↓</kbd> Navigate</span>
        <span><kbd>↩</kbd> Run</span>
        <span><kbd>Esc</kbd> Close</span>
      </footer>
    </div>
  </div>
{/if}

<style>
  .command-layer {
    position: fixed;
    inset: 0;
    z-index: 10020;
    display: flex;
    align-items: flex-start;
    justify-content: center;
    padding: min(14vh, 8rem) 1rem 1rem;
  }

  .command-backdrop {
    position: absolute;
    inset: 0;
    border: 0;
    background: rgb(15 23 42 / 0.46);
    backdrop-filter: blur(4px);
  }

  .command-dialog {
    position: relative;
    z-index: 1;
    width: min(42rem, 100%);
    max-height: min(38rem, calc(100vh - 2rem));
    display: flex;
    flex-direction: column;
    overflow: hidden;
    border: 1px solid var(--border-color);
    border-radius: 1rem;
    background: var(--bg-elevated);
    color: var(--text-primary);
    box-shadow: 0 24px 70px rgb(15 23 42 / 0.32);
  }

  .command-search-row {
    min-height: 3.75rem;
    display: flex;
    align-items: center;
    gap: 0.75rem;
    padding: 0.5rem 0.625rem 0.5rem 1rem;
    border-bottom: 1px solid var(--border-color);
    color: var(--text-tertiary);
  }

  .command-search-row input {
    min-width: 0;
    flex: 1;
    border: 0;
    outline: 0;
    background: transparent;
    color: var(--text-primary);
    font-size: 1rem;
  }

  .command-search-row input::placeholder { color: var(--text-tertiary); }

  .command-close {
    width: 2.75rem;
    height: 2.75rem;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    border: 0;
    border-radius: 0.75rem;
    color: var(--text-secondary);
    background: transparent;
  }

  .command-close:hover,
  .command-close:focus-visible { background: var(--bg-hover); color: var(--text-primary); }

  .command-error {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    padding: 0.75rem 1rem;
    border-bottom: 1px solid color-mix(in srgb, var(--status-error) 35%, var(--border-color));
    color: var(--status-error);
    background: color-mix(in srgb, var(--status-error) 9%, transparent);
    font-size: 0.8125rem;
  }

  .command-results {
    min-height: 8rem;
    overflow-y: auto;
    overscroll-behavior: contain;
    padding: 0.5rem;
  }

  .command-option {
    width: 100%;
    min-height: 3.25rem;
    display: flex;
    align-items: center;
    gap: 0.75rem;
    padding: 0.5rem 0.75rem;
    border: 0;
    border-radius: 0.75rem;
    background: transparent;
    color: var(--text-primary);
    text-align: left;
  }

  .command-option-active { background: color-mix(in srgb, var(--color-accent-500) 14%, transparent); }
  .command-option-disabled { opacity: 0.58; }

  .command-icon {
    width: 2rem;
    height: 2rem;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    flex: 0 0 auto;
    border-radius: 0.625rem;
    color: var(--color-accent-600);
    background: color-mix(in srgb, var(--color-accent-500) 12%, var(--bg-secondary));
  }

  .command-copy { min-width: 0; flex: 1; display: flex; flex-direction: column; gap: 0.125rem; }
  .command-label { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 0.875rem; font-weight: 600; }
  .command-meta { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--text-tertiary); font-size: 0.6875rem; }

  .command-option kbd,
  .command-footer kbd {
    min-width: 1.6rem;
    min-height: 1.5rem;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    padding: 0 0.4rem;
    border: 1px solid var(--border-color);
    border-radius: 0.375rem;
    background: var(--bg-secondary);
    color: var(--text-secondary);
    font: 600 0.6875rem/1 system-ui, sans-serif;
  }

  .command-spinner {
    width: 1rem;
    height: 1rem;
    border: 2px solid var(--border-color);
    border-top-color: var(--color-accent-500);
    border-radius: 999px;
    animation: command-spin 0.7s linear infinite;
  }

  .command-empty {
    min-height: 12rem;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 0.4rem;
    padding: 2rem;
    color: var(--text-tertiary);
    text-align: center;
  }

  .command-empty strong { color: var(--text-primary); font-size: 0.9rem; }
  .command-empty span { font-size: 0.75rem; }

  .command-footer {
    min-height: 2.5rem;
    display: flex;
    align-items: center;
    justify-content: flex-end;
    gap: 1rem;
    padding: 0.4rem 0.75rem;
    border-top: 1px solid var(--border-color);
    color: var(--text-tertiary);
    font-size: 0.6875rem;
  }

  .command-footer span { display: inline-flex; align-items: center; gap: 0.3rem; }

  @keyframes command-spin { to { transform: rotate(360deg); } }

  @media (max-width: 767px) {
    .command-layer {
      align-items: flex-end;
      padding: 0.5rem 0.5rem max(0.5rem, env(safe-area-inset-bottom));
    }

    .command-dialog {
      width: 100%;
      max-height: min(78vh, calc(100dvh - 1rem - env(safe-area-inset-bottom)));
      border-radius: 1rem;
    }

    .command-option { min-height: 3.5rem; }
    .command-footer { justify-content: flex-start; overflow: hidden; }
    .command-footer span:nth-child(2),
    .command-footer span:nth-child(3) { display: none; }
  }

  @media (prefers-reduced-motion: reduce) {
    .command-spinner { animation-duration: 1.4s; }
  }
</style>
