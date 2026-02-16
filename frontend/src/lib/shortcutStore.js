/**
 * Keyboard Shortcuts Store
 *
 * Central store that manages:
 *   - Default shortcuts merged with user overrides
 *   - Action handler registry (pages register/unregister handlers)
 *   - Key combo parsing and matching (including multi-key sequences)
 *   - API persistence of user customizations
 *   - Overlay visibility state
 *   - Help modal visibility state
 */

import { writable, derived, get } from 'svelte/store';
import { SHORTCUT_DEFAULTS, getDefaultsMap } from './shortcutDefaults.js';
import { api } from './api.js';

// ── User overrides store ───────────────────────────────────────────
// Map of actionId -> custom key combo (sparse — only stores changes from defaults)
export const userOverrides = writable({});

// Whether overrides have been loaded from the server
export const overridesLoaded = writable(false);

// ── Active shortcuts (defaults merged with overrides) ──────────────
export const activeShortcuts = derived(userOverrides, ($overrides) => {
  const defaults = getDefaultsMap();
  const result = {};
  for (const s of SHORTCUT_DEFAULTS) {
    result[s.id] = {
      ...s,
      key: $overrides[s.id] || s.key,
      isCustom: !!$overrides[s.id],
      defaultKey: s.key,
    };
  }
  return result;
});

// ── Shortcuts grouped by context ───────────────────────────────────
export const shortcutsByContext = derived(activeShortcuts, ($shortcuts) => {
  const grouped = {};
  for (const s of Object.values($shortcuts)) {
    if (!grouped[s.context]) {
      grouped[s.context] = [];
    }
    grouped[s.context].push(s);
  }
  return grouped;
});

// ── Shortcuts grouped by category ──────────────────────────────────
export const shortcutsByCategory = derived(activeShortcuts, ($shortcuts) => {
  const grouped = {};
  for (const s of Object.values($shortcuts)) {
    if (!grouped[s.category]) {
      grouped[s.category] = [];
    }
    grouped[s.category].push(s);
  }
  return grouped;
});

// ── Action handler registry ────────────────────────────────────────
// Map of actionId -> handler function
const actionHandlers = {};

/**
 * Register action handlers for the current page/component.
 * Call in onMount; returns a cleanup function to call on destroy.
 *
 * @param {Object} handlers - Map of actionId -> function
 * @returns {Function} cleanup function
 */
export function registerActions(handlers) {
  for (const [actionId, fn] of Object.entries(handlers)) {
    actionHandlers[actionId] = fn;
  }
  return () => unregisterActions(Object.keys(handlers));
}

/**
 * Unregister action handlers by their ids.
 * @param {string[]} actionIds
 */
export function unregisterActions(actionIds) {
  for (const id of actionIds) {
    delete actionHandlers[id];
  }
}

/**
 * Dispatch an action by id. Returns true if handled.
 * @param {string} actionId
 * @returns {boolean}
 */
export function dispatchAction(actionId) {
  const handler = actionHandlers[actionId];
  if (handler) {
    handler();
    return true;
  }
  return false;
}

/**
 * Check if an action handler is currently registered.
 * @param {string} actionId
 * @returns {boolean}
 */
export function hasHandler(actionId) {
  return !!actionHandlers[actionId];
}

// ── Key combo parsing ──────────────────────────────────────────────

const IS_MAC = typeof navigator !== 'undefined' && /Mac|iPhone|iPad/.test(navigator.userAgent);

/**
 * Normalize a key combo string for comparison.
 * Sorts modifiers alphabetically, lowercases the main key.
 *
 * @param {string} combo - e.g. "Ctrl+Shift+k", "g f", "Escape"
 * @returns {string} normalized combo
 */
export function normalizeCombo(combo) {
  if (!combo) return '';

  // Multi-key sequence (contains space but not a modifier combo)
  if (combo.includes(' ') && !combo.includes('+')) {
    return combo.split(' ').map(k => k.toLowerCase()).join(' ');
  }

  const parts = combo.split('+');
  if (parts.length === 1) {
    // Single key
    const key = parts[0].trim();
    if (key === 'Space') return ' ';
    return key.length === 1 ? key : key;
  }

  // Modifier combo
  const modifiers = [];
  let mainKey = '';
  for (const p of parts) {
    const trimmed = p.trim();
    const lower = trimmed.toLowerCase();
    if (lower === 'ctrl' || lower === 'control') {
      modifiers.push('Ctrl');
    } else if (lower === 'shift') {
      modifiers.push('Shift');
    } else if (lower === 'alt' || lower === 'option') {
      modifiers.push('Alt');
    } else if (lower === 'meta' || lower === 'cmd' || lower === 'command') {
      modifiers.push('Meta');
    } else {
      mainKey = trimmed;
    }
  }

  modifiers.sort();
  return [...modifiers, mainKey].join('+');
}

/**
 * Convert a KeyboardEvent to a normalized combo string.
 *
 * @param {KeyboardEvent} e
 * @returns {string} normalized combo
 */
export function eventToCombo(e) {
  const modifiers = [];
  // Map Ctrl on Mac to Ctrl (we use "Ctrl" universally — on Mac it means Cmd)
  if (IS_MAC ? e.metaKey : e.ctrlKey) modifiers.push('Ctrl');
  if (e.shiftKey) modifiers.push('Shift');
  if (e.altKey) modifiers.push('Alt');

  let key = e.key;

  // Normalize common keys
  if (key === ' ') key = 'Space';
  if (key === 'Esc') key = 'Escape';

  // Don't include bare modifier keys as the main key
  if (['Control', 'Shift', 'Alt', 'Meta', 'OS'].includes(key)) {
    return '';
  }

  if (modifiers.length === 0) {
    return key;
  }

  modifiers.sort();
  return [...modifiers, key].join('+');
}

/**
 * Format a key combo for display to the user.
 *
 * @param {string} combo - normalized combo string
 * @returns {string} display string
 */
export function formatComboForDisplay(combo) {
  if (!combo) return '';

  // Multi-key sequence
  if (combo.includes(' ') && !combo.includes('+')) {
    return combo.split(' ').map(k => formatSingleKey(k)).join(' then ');
  }

  const parts = combo.split('+');
  return parts.map(p => formatSingleKey(p)).join(IS_MAC ? '' : '+');
}

function formatSingleKey(key) {
  if (IS_MAC) {
    const macSymbols = {
      'Ctrl': '⌘',
      'Shift': '⇧',
      'Alt': '⌥',
      'Meta': '⌘',
      'Enter': '↩',
      'Escape': '⎋',
      'Backspace': '⌫',
      'Delete': '⌦',
      'Space': '␣',
      'ArrowUp': '↑',
      'ArrowDown': '↓',
      'ArrowLeft': '←',
      'ArrowRight': '→',
      'Tab': '⇥',
    };
    if (macSymbols[key]) return macSymbols[key];
  } else {
    const winSymbols = {
      'Ctrl': 'Ctrl',
      'Shift': 'Shift',
      'Alt': 'Alt',
      'Meta': 'Win',
      'Escape': 'Esc',
      'Space': 'Space',
      'Enter': 'Enter',
    };
    if (winSymbols[key]) return winSymbols[key];
  }

  // Single character keys -- uppercase for display
  if (key.length === 1) return key.toUpperCase();

  return key;
}

/**
 * Look up which action matches a given key combo in the current context.
 *
 * Checks context-specific shortcuts first, then global shortcuts.
 *
 * @param {string} combo - normalized key combo
 * @param {string} context - current page context
 * @returns {string|null} action id or null
 */
export function getActionForCombo(combo, context) {
  const shortcuts = get(activeShortcuts);

  // First check context-specific shortcuts
  for (const s of Object.values(shortcuts)) {
    if (s.context === context && normalizeCombo(s.key) === combo) {
      return s.id;
    }
  }

  // Then check global shortcuts
  for (const s of Object.values(shortcuts)) {
    if (s.context === 'global' && normalizeCombo(s.key) === combo) {
      return s.id;
    }
  }

  return null;
}

/**
 * Check if any shortcut starts with this key (for multi-key sequence detection).
 *
 * @param {string} firstKey - the first key pressed
 * @param {string} context - current page context
 * @returns {boolean}
 */
export function isSequencePrefix(firstKey, context) {
  const shortcuts = get(activeShortcuts);
  const prefix = firstKey.toLowerCase();

  for (const s of Object.values(shortcuts)) {
    if (s.context !== context && s.context !== 'global') continue;
    const key = s.key;
    if (key.includes(' ') && !key.includes('+')) {
      const parts = key.split(' ');
      if (parts[0].toLowerCase() === prefix) return true;
    }
  }
  return false;
}

/**
 * Check if a combo conflicts with another shortcut in the same context.
 *
 * @param {string} actionId - the action being re-bound
 * @param {string} newCombo - the proposed new combo
 * @returns {{ conflictsWith: string, label: string } | null}
 */
export function checkConflict(actionId, newCombo) {
  const shortcuts = get(activeShortcuts);
  const targetShortcut = shortcuts[actionId];
  if (!targetShortcut) return null;

  const normalizedNew = normalizeCombo(newCombo);

  for (const s of Object.values(shortcuts)) {
    if (s.id === actionId) continue;
    // Conflict if same context or either is global
    if (s.context !== targetShortcut.context && s.context !== 'global' && targetShortcut.context !== 'global') continue;
    if (normalizeCombo(s.key) === normalizedNew) {
      return { conflictsWith: s.id, label: s.label };
    }
  }
  return null;
}

// ── API integration ────────────────────────────────────────────────

/**
 * Load user shortcut overrides from the API.
 */
export async function loadUserShortcuts() {
  try {
    const resp = await api.getKeyboardShortcuts();
    userOverrides.set(resp.shortcuts || {});
    overridesLoaded.set(true);
  } catch {
    // Silently fall back to defaults
    overridesLoaded.set(true);
  }
}

/**
 * Update a single shortcut override and persist to server.
 *
 * @param {string} actionId
 * @param {string} newKey - new key combo (empty string to reset to default)
 */
export async function updateShortcut(actionId, newKey) {
  const current = get(userOverrides);
  const updated = { ...current };

  if (newKey === '' || newKey === getDefaultsMap()[actionId]?.key) {
    delete updated[actionId];
  } else {
    updated[actionId] = newKey;
  }

  userOverrides.set(updated);

  try {
    await api.updateKeyboardShortcuts(updated);
  } catch {
    // Revert on error
    userOverrides.set(current);
  }
}

/**
 * Reset a single shortcut to its default.
 * @param {string} actionId
 */
export async function resetShortcut(actionId) {
  await updateShortcut(actionId, '');
}

/**
 * Reset all shortcuts to defaults.
 */
export async function resetAllShortcuts() {
  const previous = get(userOverrides);
  userOverrides.set({});
  try {
    await api.updateKeyboardShortcuts({});
  } catch {
    userOverrides.set(previous);
  }
}

// ── UI state ───────────────────────────────────────────────────────

/** Whether the shortcut overlay is visible (Option/Alt held) */
export const overlayVisible = writable(false);

/** Whether the help modal is showing */
export const helpModalOpen = writable(false);
