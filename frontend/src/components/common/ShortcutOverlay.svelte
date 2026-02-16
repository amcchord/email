<!--
  ShortcutOverlay.svelte

  Shows floating badges next to UI elements when the Option/Alt key is held down.
  Each badge displays the keyboard shortcut that activates that element.

  Target elements are identified by `data-shortcut="action.id"` attributes.
  The overlay queries all matching elements and positions badges relative to them.
-->
<script>
  import { onMount } from 'svelte';
  import {
    overlayVisible,
    activeShortcuts,
    formatComboForDisplay,
  } from '../../lib/shortcutStore.js';
  import { currentPage } from '../../lib/stores.js';

  let badges = $state([]);
  let visible = $state(false);

  // Map page names to shortcut contexts (same as in handler)
  function pageToContext(page) {
    const map = {
      flow: 'flow',
      inbox: 'inbox',
      compose: 'compose',
      calendar: 'calendar',
      todos: 'todos',
      chat: 'chat',
      'ai-insights': 'ai-insights',
      admin: 'admin',
      stats: 'stats',
    };
    return map[page] || 'global';
  }

  function computeBadges() {
    const context = pageToContext($currentPage);
    const shortcuts = $activeShortcuts;
    const newBadges = [];

    // Find all elements with data-shortcut attribute
    const elements = document.querySelectorAll('[data-shortcut]');

    for (const el of elements) {
      const actionId = el.getAttribute('data-shortcut');
      const shortcut = shortcuts[actionId];
      if (!shortcut) continue;

      // Only show shortcuts relevant to current context or global
      if (shortcut.context !== context && shortcut.context !== 'global') continue;

      const rect = el.getBoundingClientRect();
      // Skip if element is not visible
      if (rect.width === 0 || rect.height === 0) continue;
      if (rect.top < 0 || rect.left < 0) continue;

      newBadges.push({
        id: actionId,
        key: formatComboForDisplay(shortcut.key),
        x: rect.left + rect.width / 2,
        y: rect.top + rect.height / 2,
        width: rect.width,
        height: rect.height,
      });
    }

    badges = newBadges;
  }

  // Subscribe to overlay visibility
  const unsubVisible = overlayVisible.subscribe((v) => {
    visible = v;
    if (v) {
      // Small delay to let DOM settle
      requestAnimationFrame(() => computeBadges());
    } else {
      badges = [];
    }
  });

  onMount(() => {
    return () => {
      unsubVisible();
    };
  });
</script>

{#if visible}
  <div class="shortcut-overlay" aria-hidden="true">
    {#each badges as badge (badge.id)}
      <div
        class="shortcut-badge"
        style="left: {badge.x}px; top: {badge.y}px;"
      >
        <span class="shortcut-badge-key">{badge.key}</span>
      </div>
    {/each}
  </div>
{/if}

<style>
  .shortcut-overlay {
    position: fixed;
    inset: 0;
    z-index: 10000;
    pointer-events: none;
    background: rgba(0, 0, 0, 0.08);
    transition: opacity 0.15s ease;
  }

  .shortcut-badge {
    position: fixed;
    transform: translate(-50%, -50%);
    z-index: 10001;
    pointer-events: none;
    animation: badge-pop-in 0.15s ease-out;
  }

  .shortcut-badge-key {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    min-width: 24px;
    height: 26px;
    padding: 0 7px;
    border-radius: 6px;
    font-family: system-ui, -apple-system, sans-serif;
    font-size: 12px;
    font-weight: 700;
    line-height: 1;
    white-space: nowrap;
    color: #fff;
    background: rgba(59, 130, 246, 0.92);
    border: 1.5px solid rgba(255, 255, 255, 0.35);
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.25), 0 0 0 1px rgba(59, 130, 246, 0.5);
    backdrop-filter: blur(4px);
  }

  @keyframes badge-pop-in {
    from {
      opacity: 0;
      transform: translate(-50%, -50%) scale(0.7);
    }
    to {
      opacity: 1;
      transform: translate(-50%, -50%) scale(1);
    }
  }
</style>
