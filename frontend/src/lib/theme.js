import { writable } from 'svelte/store';
import { applyThemeColors } from './themes.js';

// ── Color Scheme (light / dark / system) ─────────────────────────────

function getSystemPreference() {
  if (typeof window === 'undefined') return 'light';
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}

function resolveEffectiveMode(scheme) {
  if (scheme === 'system') return getSystemPreference();
  return scheme;
}

function applyMode(mode) {
  if (typeof document === 'undefined') return;
  document.documentElement.classList.toggle('dark', mode === 'dark');
}

function createThemeStore() {
  const stored = typeof localStorage !== 'undefined' ? localStorage.getItem('theme') : null;
  let initial = 'light';

  if (stored === 'system' || stored === 'light' || stored === 'dark') {
    initial = stored;
  } else if (stored) {
    // Legacy: stored was 'dark' or 'light' from old toggle
    initial = stored;
  } else if (typeof window !== 'undefined' && window.matchMedia('(prefers-color-scheme: dark)').matches) {
    initial = 'dark';
  }

  const { subscribe, set, update } = writable(initial);

  // Apply on creation
  applyMode(resolveEffectiveMode(initial));

  // Listen for system preference changes when in 'system' mode
  if (typeof window !== 'undefined') {
    window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => {
      let currentScheme = null;
      subscribe(v => { currentScheme = v; })();
      if (currentScheme === 'system') {
        applyMode(getSystemPreference());
      }
    });
  }

  return {
    subscribe,
    toggle: () => {
      update((current) => {
        let effective = resolveEffectiveMode(current);
        const next = effective === 'dark' ? 'light' : 'dark';
        applyMode(next);
        localStorage.setItem('theme', next);
        return next;
      });
    },
    set: (value) => {
      applyMode(resolveEffectiveMode(value));
      localStorage.setItem('theme', value);
      set(value);
    },
  };
}

export const theme = createThemeStore();

/**
 * Derived helper: returns the effective visual mode ('light' or 'dark')
 * even when theme is set to 'system'.
 */
export function getEffectiveMode(scheme) {
  return resolveEffectiveMode(scheme);
}


// ── Active Color Theme (amber, blue, rose, etc.) ─────────────────────

function createActiveThemeStore() {
  const stored = typeof localStorage !== 'undefined' ? localStorage.getItem('activeTheme') : null;
  const initial = stored || 'amber';

  const { subscribe, set } = writable(initial);

  // Apply on creation
  if (typeof document !== 'undefined') {
    applyThemeColors(initial);
  }

  return {
    subscribe,
    set: (value) => {
      if (typeof document !== 'undefined') {
        applyThemeColors(value);
      }
      if (typeof localStorage !== 'undefined') {
        localStorage.setItem('activeTheme', value);
      }
      set(value);
    },
  };
}

export const activeTheme = createActiveThemeStore();
