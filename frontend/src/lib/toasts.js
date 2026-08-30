import { writable } from 'svelte/store';

/**
 * Small toast queue with injectable timers so expiry behavior is deterministic
 * in tests. Toast callbacks stay in memory; durable mail-action state remains
 * server-owned and can be rehydrated independently.
 */
export function createToastController({
  schedule = globalThis.setTimeout,
  cancel = globalThis.clearTimeout,
  limit = 4,
} = {}) {
  const queue = writable([]);
  const timers = new Map();
  let nextId = 1;

  function dismiss(id) {
    const timer = timers.get(id);
    if (timer !== undefined) {
      cancel(timer);
      timers.delete(id);
    }
    queue.update(items => items.filter(item => item.id !== id));
  }

  function show(message, type = 'info', duration = 3000, options = {}) {
    if (duration && typeof duration === 'object') {
      options = duration;
      duration = options.duration ?? 3000;
    }

    const id = nextId++;
    const toast = {
      id,
      message,
      type,
      duration,
      actionLabel: options.actionLabel || null,
      onAction: options.onAction || null,
      dismissLabel: options.dismissLabel || 'Dismiss notification',
    };

    let evicted = [];
    queue.update(items => {
      const next = [...items, toast];
      evicted = next.length > limit ? next.slice(0, next.length - limit) : [];
      return next.slice(-limit);
    });
    for (const item of evicted) {
      const timer = timers.get(item.id);
      if (timer !== undefined) cancel(timer);
      timers.delete(item.id);
    }

    if (Number.isFinite(duration) && duration > 0) {
      timers.set(id, schedule(() => dismiss(id), duration));
    }
    return id;
  }

  function clear() {
    for (const timer of timers.values()) cancel(timer);
    timers.clear();
    queue.set([]);
  }

  return {
    subscribe: queue.subscribe,
    show,
    dismiss,
    clear,
  };
}

const toastController = createToastController();

export const toastMessages = { subscribe: toastController.subscribe };
export const showToast = (...args) => toastController.show(...args);
export const dismissToast = (id) => toastController.dismiss(id);
export const clearToasts = () => toastController.clear();
