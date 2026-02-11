import { writable } from 'svelte/store';

function createThemeStore() {
  const stored = typeof localStorage !== 'undefined' ? localStorage.getItem('theme') : null;
  let initial = 'light';

  if (stored) {
    initial = stored;
  } else if (typeof window !== 'undefined' && window.matchMedia('(prefers-color-scheme: dark)').matches) {
    initial = 'dark';
  }

  const { subscribe, set, update } = writable(initial);

  function apply(theme) {
    if (typeof document !== 'undefined') {
      document.documentElement.classList.toggle('dark', theme === 'dark');
      localStorage.setItem('theme', theme);
    }
  }

  // Apply on creation
  apply(initial);

  return {
    subscribe,
    toggle: () => {
      update((current) => {
        const next = current === 'dark' ? 'light' : 'dark';
        apply(next);
        return next;
      });
    },
    set: (value) => {
      apply(value);
      set(value);
    },
  };
}

export const theme = createThemeStore();
