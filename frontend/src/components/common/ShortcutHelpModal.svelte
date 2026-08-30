<!--
  ShortcutHelpModal.svelte

  Displays a categorized list of all keyboard shortcuts.
  Triggered by the "?" key (nav.help shortcut).
  Shows user-customized bindings where applicable.
-->
<script>
  import { onMount, tick } from 'svelte';
  import {
    activeShortcuts,
    eventToCombo,
    formatComboForDisplay,
    helpModalOpen,
    normalizeCombo,
    openCommandPalette,
    shortcutsByCategory,
  } from '../../lib/shortcutStore.js';
  import { getCategories } from '../../lib/shortcutDefaults.js';
  import { currentPage } from '../../lib/stores.js';

  let searchFilter = $state('');
  let inputEl = $state(null);
  let dialogEl = $state(null);
  let returnFocusEl = null;
  let wasOpen = false;
  let savedBodyOverflow = '';

  const categories = getCategories();

  let filteredCategories = $derived.by(() => {
    const byCategory = $shortcutsByCategory;
    const query = searchFilter.toLowerCase().trim();

    const result = [];
    for (const cat of categories) {
      const shortcuts = byCategory[cat] || [];
      let filtered = shortcuts;
      if (query) {
        filtered = shortcuts.filter(s =>
          s.label.toLowerCase().includes(query) ||
          s.key.toLowerCase().includes(query) ||
          s.id.toLowerCase().includes(query)
        );
      }
      if (filtered.length > 0) {
        result.push({ name: cat, shortcuts: filtered });
      }
    }
    return result;
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
    returnFocusEl = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    searchFilter = '';
    savedBodyOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    setBackgroundInert(true);
    await tick();
    if ($helpModalOpen) inputEl?.focus();
  }

  function closed() {
    setBackgroundInert(false);
    document.body.style.overflow = savedBodyOverflow;
    const target = returnFocusEl;
    returnFocusEl = null;
    if (target?.isConnected) target.focus();
  }

  onMount(() => {
    const unsubscribe = helpModalOpen.subscribe(open => {
      if (open && !wasOpen) void opened();
      if (!open && wasOpen) closed();
      wasOpen = open;
    });
    return () => {
      unsubscribe();
      if (wasOpen) closed();
    };
  });

  function focusableElements() {
    if (!dialogEl) return [];
    return [...dialogEl.querySelectorAll(
      'button:not([disabled]), input:not([disabled]), [tabindex]:not([tabindex="-1"])',
    )].filter(element => !element.hasAttribute('hidden'));
  }

  function handleKeydown(event) {
    if (!$helpModalOpen || event.isComposing) return;

    const combo = normalizeCombo(eventToCombo(event));
    const helpShortcut = $activeShortcuts['nav.help']?.key;
    if (event.key === 'Escape' || event.key === '?' || (helpShortcut && combo === normalizeCombo(helpShortcut))) {
      event.preventDefault();
      event.stopImmediatePropagation();
      helpModalOpen.set(false);
      return;
    }

    const paletteShortcut = $activeShortcuts['nav.commands']?.key;
    if (paletteShortcut && combo === normalizeCombo(paletteShortcut)) {
      event.preventDefault();
      event.stopImmediatePropagation();
      openCommandPalette();
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

  function handleBackdropClick(e) {
    if (e.target === e.currentTarget) {
      helpModalOpen.set(false);
    }
  }

  function goToSettings() {
    helpModalOpen.set(false);
    // The URL is durable across a cold lazy Admin mount. The event handles the
    // already-mounted case without making first-load navigation timing-based.
    const url = new URL(window.location.href);
    url.searchParams.set('tab', 'preferences');
    window.history.replaceState({}, '', url.toString());
    currentPage.set('admin');
    window.dispatchEvent(new CustomEvent('shortcut-settings-navigate'));
  }
</script>

<svelte:window onkeydown={handleKeydown} />

{#if $helpModalOpen}
  <!-- svelte-ignore a11y_click_events_have_key_events -->
  <!-- svelte-ignore a11y_no_static_element_interactions -->
  <div
    class="modal-backdrop"
    onclick={handleBackdropClick}
  >
    <div
      class="modal-content"
      role="dialog"
      aria-modal="true"
      aria-labelledby="shortcut-help-title"
      bind:this={dialogEl}
    >
      <div class="modal-header">
        <h2 id="shortcut-help-title">Keyboard Shortcuts</h2>
        <div class="modal-header-actions">
          <button class="customize-btn" onclick={goToSettings}>
            Customize
          </button>
          <button class="close-btn" onclick={() => helpModalOpen.set(false)} aria-label="Close">
            <svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M5 5l10 10M15 5l-10 10" />
            </svg>
          </button>
        </div>
      </div>

      <div class="search-bar">
        <input
          type="text"
          aria-label="Search keyboard shortcuts"
          placeholder="Search shortcuts..."
          bind:value={searchFilter}
          bind:this={inputEl}
          class="search-input"
        />
      </div>

      <div class="modal-body">
        {#each filteredCategories as category (category.name)}
          <div class="category">
            <h3 class="category-title">{category.name}</h3>
            <div class="shortcut-list">
              {#each category.shortcuts as shortcut (shortcut.id)}
                <div class="shortcut-row">
                  <span class="shortcut-label">{shortcut.label}</span>
                  <span class="shortcut-keys">
                    {#each shortcut.key.split(' ').filter(k => k) as part, i}
                      {#if i > 0 && !shortcut.key.includes('+')}
                        <span class="key-then">then</span>
                      {/if}
                      {#if shortcut.key.includes('+') && i === 0}
                        {#each shortcut.key.split('+') as mod, j}
                          <kbd class="key-badge">{formatComboForDisplay(mod)}</kbd>
                          {#if j < shortcut.key.split('+').length - 1}
                            <span class="key-plus">+</span>
                          {/if}
                        {/each}
                      {:else}
                        <kbd class="key-badge">{formatComboForDisplay(part)}</kbd>
                      {/if}
                    {/each}
                    {#if shortcut.isCustom}
                      <span class="custom-indicator" title="Customized">*</span>
                    {/if}
                  </span>
                </div>
              {/each}
            </div>
          </div>
        {/each}

        {#if filteredCategories.length === 0}
          <div class="empty-state">
            No shortcuts match "{searchFilter}"
          </div>
        {/if}
      </div>

      <div class="modal-footer">
        <span class="hint">Press <kbd class="key-badge-small">?</kbd> to toggle this dialog</span>
        <span class="hint">Hold <kbd class="key-badge-small">Option</kbd> to see shortcut badges on screen</span>
      </div>
    </div>
  </div>
{/if}

<style>
  .modal-backdrop {
    position: fixed;
    inset: 0;
    z-index: 9999;
    display: flex;
    align-items: center;
    justify-content: center;
    background: rgba(0, 0, 0, 0.5);
    backdrop-filter: blur(2px);
    animation: fade-in 0.15s ease;
  }

  .modal-content {
    width: 90%;
    max-width: 680px;
    max-height: 80vh;
    display: flex;
    flex-direction: column;
    border-radius: 12px;
    overflow: hidden;
    background: var(--bg-elevated);
    border: 1px solid var(--border-color);
    box-shadow: var(--shadow-lg);
    animation: modal-slide-up 0.2s ease;
  }

  .modal-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 16px 20px;
    border-bottom: 1px solid var(--border-color);
  }

  .modal-header h2 {
    margin: 0;
    font-size: 18px;
    font-weight: 600;
    color: var(--text-primary);
  }

  .modal-header-actions {
    display: flex;
    align-items: center;
    gap: 8px;
  }

  .customize-btn {
    min-height: 44px;
    padding: 5px 12px;
    border-radius: 6px;
    border: 1px solid var(--border-color);
    background: var(--bg-secondary);
    color: var(--text-secondary);
    font-size: 12px;
    cursor: pointer;
    transition: all 0.15s;
  }

  .customize-btn:hover {
    background: var(--bg-tertiary, var(--bg-secondary));
    color: var(--text-primary);
  }

  .close-btn {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 44px;
    height: 44px;
    border: none;
    border-radius: 6px;
    background: none;
    color: var(--text-secondary);
    cursor: pointer;
    transition: all 0.15s;
  }

  .close-btn:hover {
    background: var(--bg-secondary);
    color: var(--text-primary);
  }

  .search-bar {
    padding: 12px 20px;
    border-bottom: 1px solid var(--border-color);
  }

  .search-input {
    width: 100%;
    min-height: 44px;
    padding: 8px 12px;
    border-radius: 6px;
    border: 1px solid var(--border-color);
    background: var(--bg-secondary);
    color: var(--text-primary);
    font-size: 14px;
    outline: none;
    transition: border-color 0.15s;
  }

  .search-input:focus {
    border-color: var(--color-accent-500, #3b82f6);
  }

  .search-input::placeholder {
    color: var(--text-tertiary, var(--text-secondary));
  }

  .modal-body {
    flex: 1;
    overflow-y: auto;
    padding: 8px 20px 16px;
  }

  .category {
    margin-top: 16px;
  }

  .category:first-child {
    margin-top: 8px;
  }

  .category-title {
    margin: 0 0 8px 0;
    font-size: 11px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: var(--text-secondary);
  }

  .shortcut-list {
    display: flex;
    flex-direction: column;
  }

  .shortcut-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 6px 0;
    border-bottom: 1px solid var(--border-color);
  }

  .shortcut-row:last-child {
    border-bottom: none;
  }

  .shortcut-label {
    font-size: 13px;
    color: var(--text-primary);
  }

  .shortcut-keys {
    display: flex;
    align-items: center;
    gap: 4px;
    flex-shrink: 0;
    margin-left: 16px;
  }

  .key-badge {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    min-width: 22px;
    height: 22px;
    padding: 0 6px;
    border-radius: 4px;
    font-family: system-ui, -apple-system, sans-serif;
    font-size: 11px;
    font-weight: 600;
    line-height: 1;
    white-space: nowrap;
    color: var(--text-primary);
    background: var(--bg-secondary);
    border: 1px solid var(--border-color);
    box-shadow: 0 1px 2px rgba(0, 0, 0, 0.08);
  }

  .key-then {
    font-size: 10px;
    color: var(--text-secondary);
    margin: 0 2px;
  }

  .key-plus {
    font-size: 10px;
    color: var(--text-secondary);
  }

  .custom-indicator {
    color: var(--color-accent-500, #3b82f6);
    font-size: 12px;
    font-weight: 700;
    margin-left: 2px;
  }

  .empty-state {
    padding: 32px;
    text-align: center;
    color: var(--text-secondary);
    font-size: 14px;
  }

  .modal-footer {
    padding: 12px 20px;
    border-top: 1px solid var(--border-color);
    display: flex;
    justify-content: space-between;
    gap: 16px;
    flex-wrap: wrap;
  }

  .hint {
    font-size: 11px;
    color: var(--text-secondary);
    display: flex;
    align-items: center;
    gap: 4px;
  }

  .key-badge-small {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    min-width: 18px;
    height: 18px;
    padding: 0 4px;
    border-radius: 3px;
    font-family: system-ui, -apple-system, sans-serif;
    font-size: 10px;
    font-weight: 600;
    color: var(--text-primary);
    background: var(--bg-secondary);
    border: 1px solid var(--border-color);
  }

  @keyframes fade-in {
    from { opacity: 0; }
    to { opacity: 1; }
  }

  @keyframes modal-slide-up {
    from {
      opacity: 0;
      transform: translateY(10px) scale(0.98);
    }
    to {
      opacity: 1;
      transform: translateY(0) scale(1);
    }
  }
</style>
