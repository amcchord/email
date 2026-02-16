<!--
  KeyboardShortcutHandler.svelte

  Renderless component that listens to global keydown events and dispatches
  matching keyboard shortcuts.  Mounted once in Layout.svelte.

  Supports:
    - Single-key shortcuts (e, /, ?, etc.)
    - Modifier combos (Ctrl+Enter, Shift+i, etc.)
    - Multi-key sequences (g f, g i — press first key then second within 1s)
    - Input-awareness: plain letter shortcuts are suppressed while an
      input/textarea/contenteditable is focused; modifier shortcuts still work.
-->
<script>
  import { currentPage } from '../../lib/stores.js';
  import {
    eventToCombo,
    getActionForCombo,
    isSequencePrefix,
    dispatchAction,
    overlayVisible,
    helpModalOpen,
  } from '../../lib/shortcutStore.js';

  // Map page names to shortcut contexts
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

  // Multi-key sequence state
  let pendingKey = $state(null);
  let pendingTimer = $state(null);

  function clearPending() {
    pendingKey = null;
    if (pendingTimer) {
      clearTimeout(pendingTimer);
      pendingTimer = null;
    }
  }

  // Check if the user is in an editable field
  function isEditableElement(el) {
    if (!el) return false;
    const tag = el.tagName;
    if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return true;
    if (el.isContentEditable) return true;
    // Check for rich text editors (tiptap, prosemirror, etc.)
    if (el.closest('.ProseMirror') || el.closest('.tiptap') || el.closest('[contenteditable]')) return true;
    return false;
  }

  // Check if the combo has a modifier key (Ctrl/Cmd, Alt)
  function hasModifier(combo) {
    return combo.includes('Ctrl+') || combo.includes('Alt+') || combo.includes('Meta+');
  }

  // ── Option/Alt key overlay tracking ──────────────────────────────
  let altPressedAt = $state(0);
  let altHoldTimer = $state(null);

  function handleKeydown(e) {
    // Track Alt/Option key for overlay
    if (e.key === 'Alt' || e.key === 'Option') {
      if (!altPressedAt) {
        altPressedAt = Date.now();
        altHoldTimer = setTimeout(() => {
          overlayVisible.set(true);
        }, 300);
      }
      return;
    }

    // If alt is held down with another key, don't trigger shortcuts
    // (the overlay should stay visible)
    if (e.altKey && e.key !== 'Alt') {
      // Let Alt+key browser defaults pass through
      return;
    }

    const context = pageToContext($currentPage);
    const editing = isEditableElement(e.target);
    const combo = eventToCombo(e);

    if (!combo) return;

    // ── Multi-key sequence handling ────────────────────────────────
    if (pendingKey) {
      const fullCombo = pendingKey + ' ' + combo.toLowerCase();
      clearPending();

      // Don't process sequences while editing (unless it's a modifier combo)
      if (editing && !hasModifier(fullCombo)) return;

      const actionId = getActionForCombo(fullCombo, context);
      if (actionId) {
        e.preventDefault();
        e.stopPropagation();
        dispatchAction(actionId);
        return;
      }
      // No match for the sequence — fall through and check as single key
    }

    // ── Check for sequence prefix ──────────────────────────────────
    if (!editing && combo.length === 1 && isSequencePrefix(combo, context)) {
      pendingKey = combo.toLowerCase();
      pendingTimer = setTimeout(() => {
        clearPending();
      }, 1000);
      e.preventDefault();
      return;
    }

    // ── Single key / modifier combo handling ───────────────────────
    // If editing, only process combos with modifiers
    if (editing && !hasModifier(combo)) return;

    const actionId = getActionForCombo(combo, context);
    if (actionId) {
      e.preventDefault();
      e.stopPropagation();
      dispatchAction(actionId);
    }
  }

  function handleKeyup(e) {
    if (e.key === 'Alt' || e.key === 'Option') {
      altPressedAt = 0;
      if (altHoldTimer) {
        clearTimeout(altHoldTimer);
        altHoldTimer = null;
      }
      overlayVisible.set(false);
    }
  }

  function handleWindowBlur() {
    // Reset state when the window loses focus
    clearPending();
    altPressedAt = 0;
    if (altHoldTimer) {
      clearTimeout(altHoldTimer);
      altHoldTimer = null;
    }
    overlayVisible.set(false);
  }
</script>

<svelte:window
  onkeydown={handleKeydown}
  onkeyup={handleKeyup}
  onblur={handleWindowBlur}
/>
